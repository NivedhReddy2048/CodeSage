# CodeSage

Multi-agent code review for GitHub pull requests. Every PR is reviewed by a
LangGraph pipeline of six agents (diff/intent, static analysis, security, correctness,
codebase grounding and test coverage) and a deterministic synthesis step, grounded in
the repository's own code through hybrid retrieval (pgvector dense + Postgres
full-text), so findings carry real file and line citations rather than generic advice.

Architecture, tech-stack rationale and free-tier constraints: [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md).
Build status: [docs/PROGRESS.md](docs/PROGRESS.md).

> Scaffold stage (phase 0). The full README — architecture diagram, deployment
> guide and engineering-tradeoffs section — is written in phase 7.

## Layout

```
backend/    Django + DRF + Channels (ASGI via Daphne), eight apps under backend/apps/
frontend/   Next.js + TypeScript + Tailwind + shadcn/ui
docker/     Local-dev container support files
docs/       Specification, build prompts, progress
```

## Local development

Requires Docker Desktop, Python 3.13+ and Node 20+.

**1. Start Postgres (with pgvector) and Redis:**

```bash
docker compose up -d
```

**2. Backend:**

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows; use source .venv/bin/activate elsewhere
pip install -r requirements-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

Serves on http://localhost:8000 — health check at `/api/health/`, Swagger at `/api/docs/`.

**3. Frontend:**

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Serves on http://localhost:3000. `NEXT_PUBLIC_API_URL` in `.env.local` points at the
backend (`http://localhost:8000` locally, the Render URL in production).

Once signed in, `/repos` lists what the GitHub App can reach and lets an owner or
admin connect a repository.

Sign in at http://localhost:3000/login once the OAuth App below is configured.

## GitHub OAuth App (needed to sign in)

Login goes through a GitHub OAuth App. This is **not** the GitHub App that posts PR
reviews — that one is separate and arrives in phase 2 (spec §13).

1. GitHub → Settings → Developer settings → **OAuth Apps** → *New OAuth App*.
2. Fill in:
   - **Application name**: `CodeSage (local)`
   - **Homepage URL**: `http://localhost:3000`
   - **Authorization callback URL**: `http://localhost:3000/auth/callback`
3. Generate a client secret, then put both values in `backend/.env`:

   ```
   GITHUB_CLIENT_ID=Iv1....
   GITHUB_CLIENT_SECRET=....
   GITHUB_OAUTH_REDIRECT_URI=http://localhost:3000/auth/callback
   ```

The callback URL points at the **frontend**, not the backend. GitHub redirects the
browser there, the SPA reads the `code` from the query string and POSTs it to
`/api/auth/github/callback/`, and the backend returns the JWT pair in the response
body. Routing the redirect through the backend instead would mean handing the tokens
back through a URL, where they end up in browser history and server logs.

`GITHUB_OAUTH_REDIRECT_URI` must match the registered callback URL character for
character, or GitHub rejects the exchange with `redirect_uri_mismatch`.

## GitHub App (needed for repo connection and PR reviews)

A **second, separate** GitHub identity from the OAuth App above. The OAuth App
identifies the human signing in; the GitHub App reads repositories, receives webhooks
and posts review comments as `<app-slug>[bot]`. Mixing the two is the most common way
to get stuck here — spec §13 has the full rationale.

1. GitHub → Settings → Developer settings → **GitHub Apps** → *New GitHub App*.
2. Name it something globally unique (the bot login is derived from it). Homepage URL
   can be this repository.
3. Leave **Callback URL** blank and leave *Request user authorization (OAuth) during
   installation* **unchecked** — user login is the OAuth App's job.
4. **Webhook**: Active, URL = your smee channel (see below), Secret =
   `GITHUB_WEBHOOK_SECRET` from `backend/.env`.
5. **Repository permissions** — exactly these three, everything else "No access":

   | Permission | Access |
   |---|---|
   | Contents | Read-only |
   | Metadata | Read-only (mandatory) |
   | Pull requests | Read and write |

6. **Subscribe to events**: *Pull request* only.
7. **Where can this GitHub App be installed**: Only on this account.

After creating it:

- Copy the **App ID** and the **Client ID** into `GITHUB_APP_ID` and
  `GITHUB_APP_CLIENT_ID`.
- **Generate a private key**, then move the downloaded `.pem` to
  `backend/secrets/codesage.private-key.pem`. That directory is gitignored, and
  `*.pem` is ignored tree-wide, so the key cannot be committed by accident.
- **Install App** → your account → *Only select repositories* → pick a throwaway test
  repository. Do not install it on this repository: testing means opening junk PRs.

Verify the whole chain without a browser:

```bash
cd backend
.venv/Scripts/python.exe manage.py shell -c "from apps.repos import github_app; a=github_app.get_app_metadata(); print(a['slug'], a['permissions'])"
```

## Receiving webhooks locally

GitHub cannot reach `localhost`, so deliveries are relayed through
[smee.io](https://smee.io). Create a channel at https://smee.io/new, use it as the
App's webhook URL. The dev runner below starts the relay for you.

`smee-client` is pinned as a devDependency and the channel URL lives in the
`webhooks` script in `frontend/package.json`, which the dev runner reads too. It
sits in the frontend package only because that is where npm already is — it relays
to the *backend*. Change the channel there if you create a new one. To run the relay
on its own: `npm --prefix frontend run webhooks`.

## Running everything at once

Four processes are needed for a review to complete: the API receives the webhook,
the Celery worker runs the pipeline, the smee relay forwards GitHub's delivery to
localhost, and the frontend serves the UI. Forgetting the worker is the usual cause
of "the webhook arrived but no comment appeared".

Start Postgres and Redis, then the whole stack, from the repository root:

```bash
docker compose up -d
python scripts/dev.py          # Ctrl+C stops all four processes
```

Any Python 3 works for `python`: the script re-runs itself under
`backend/.venv` (it needs `psutil` from `requirements-dev.txt`), so no virtualenv
activation is needed. It starts the backend on :8000, the Celery worker
(`--pool=solo`), the frontend on :3000 and the smee relay. Each output line is
prefixed with its process name, and it says when all four are ready.

**It refuses to start** while anything could compete with it, and says what to do:

- port 8000 or 3000 is already in use;
- a Celery worker already answers on the broker. A second worker takes review tasks
  too, possibly running stale code (that is how testbed PR #4's review vanished, #79);
- CodeSage dev processes from an earlier run are still alive.

**Stopping.** Ctrl+C, or any one of the four exiting, stops all of them. First each
process gets a graceful stop (Ctrl+Break on Windows, SIGTERM elsewhere). Whatever is
still running after 8 seconds has its whole process tree force-killed, and the runner
prints which processes needed that. On Windows the runner also sits in a
kill-on-close job object, so even if it is killed outright, nothing it started
outlives it.

If something is left over anyway (a crashed terminal, an old honcho session):

```bash
python scripts/dev.py stop     # kills this checkout's dev processes and anything on :8000/:3000
```

This replaced honcho, which cannot stop its children on Windows: on Ctrl+C it loops
"sending SIGKILL" without effect, then crashes and leaves all four running.

## Operator commands

Two management commands for working on the review pipeline. Run them from `backend/`
with the virtualenv active.

```bash
# Re-review a pull request now, in this process, without the Celery worker.
python manage.py rerun_review NivedhReddy2048/codesage-testbed 3
```

`rerun_review <repo> <pr_number>` refreshes the PR's head commit from GitHub and runs
the same review the webhook triggers: the bot's summary comment is edited in place and
inline comments are deduplicated against the ones already on the diff. It
**deliberately bypasses webhook delivery-id dedupe** — it never creates a
`WebhookEvent` — which is the point: GitHub redeliveries are ignored by design, so this
is the way to re-review after quota returns, after changing pipeline code (the worker
does not reload), or while the worker is down. It prints the per-agent table (with the
model that actually served each agent), the comment link and the "Files changed" link.
It spends a full review's LLM quota every time it runs.

```bash
# Compare vector-only and hybrid retrieval for one query.
python manage.py retrieval_probe "function that looks up a user by id"
python manage.py retrieval_probe "SQL query built with string interpolation" --repo owner/name --limit 8
```

`retrieval_probe "<query>"` prints the vector-only (cosine) ranking next to the hybrid
(vector + full-text, fused with RRF) ranking, with each hybrid hit's rank in both
underlying retrievers. `--repo` is optional when only one repository is indexed. It
spends one Gemini embedding call.

## Checks

```bash
cd backend  && ruff check . ../scripts && python manage.py check && pytest
cd frontend && npm run lint && npm run build
```
