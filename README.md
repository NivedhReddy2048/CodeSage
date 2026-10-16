# CodeSage

Multi-agent code review for GitHub pull requests. Every PR is reviewed by a
six-agent LangGraph pipeline grounded in the repository's own code through hybrid
retrieval (pgvector dense + Postgres full-text), so findings carry real file and
line citations rather than generic advice.

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

## Checks

```bash
cd backend  && ruff check . && python manage.py check && pytest
cd frontend && npm run lint && npm run build
```
