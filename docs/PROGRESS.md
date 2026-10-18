# CodeSage — Build Progress

Single source of truth for where the build stands. Each phase ships as 2-3 focused
pull requests, each closing its own issue. Architecture lives in
[PROJECT_SPEC.md](PROJECT_SPEC.md); the per-phase prompts live in
[BUILD_PROMPTS.md](BUILD_PROMPTS.md).

## Phase checklist

| # | Phase | Branches | Status |
|---|---|---|---|
| 0 | Scaffold | `phase-0-scaffold` (squashed) | **Done** |
| 1 | Auth | `phase-1a` backend, `1b` frontend, `1c` tests | **Done** |
| 2 | Repo connection (GitHub App) | `phase-2a` app auth, `2b` webhook, `2c` UI | **Done** |
| 3 | Ingestion | `phase-3a` chunk+embed, `3b` status UI | Next |
| 4 | Agent pipeline v1 | `phase-4a` models, `4b` pipeline, `4c` PR comment | Not started |
| 5 | Full 6-agent pipeline | `phase-5a` agents, `5b` RAG, `5c` synthesis | Not started |
| 6 | Realtime + polish | `phase-6a` realtime, `6b` analytics, `6c` UI shell | Not started |
| 7 | Deploy + CI | `phase-7a` config, `7b` CI+keep-warm, `7c` README | Not started |
| 8 | Evaluation | `phase-8a` fixtures, `8b` run_eval, `8c` results | Not started |

Phase 8 depends only on Phase 5, so it can be built before or after Phase 7.

---

## Version control workflow

Phase 0 (the project spec, the build prompts and the whole scaffold) was squashed
into a single commit on `main` to keep the repository's contributor history clean.
The phase-branch history from the original build was discarded along with it.

From Phase 1 onward every change lands through a **pull request**, not a local merge:

1. `gh issue create` describing the work.
2. Branch off latest `main` as `phase-N<letter>-<slug>` (e.g. `phase-1a-auth-backend`).
3. Build and **fully verify** the work on the branch — tests, lint, manual check.
4. `gh pr create` with `Closes #<issue number>` in the body.
5. `gh pr merge --merge --delete-branch` — a real merge commit, never a squash, so each
   PR stays visible in `git log --graph`.
6. `git checkout main && git pull`.

Three standing rules, spelled out in full in [BUILD_PROMPTS.md](BUILD_PROMPTS.md):

- **No AI attribution.** No `Co-Authored-By` trailers in commits, no "generated with"
  lines in issues or PRs. This repository reads as solo work.
- **2-3 PRs per phase**, each with its own issue and real tested changes — never an
  empty PR raised to inflate a count.
- **Fast merges.** Verify before opening, then open and merge within a couple of minutes.
- **LF line endings**, enforced by `.gitattributes` (`* text=auto eol=lf`). Windows
  tooling here writes CRLF, which made git report whole-file rewrites for one-line
  changes; normalising removes that noise and matches the Linux deploy target.

---

## GitHub achievements

Tracked as a side effect of the PR workflow above, not as a reason to create busywork —
every PR must still be real, tested work.

| Achievement | Requirement | Status |
|---|---|---|
| **Pull Shark** | Base badge at 2 merged PRs (already earned before this project); next tier **bronze at 16** | **10 / 16 toward bronze** |
| **YOLO** | Merge a PR without a review | Earned by this workflow — PRs are self-merged |
| **Quickdraw** | Close an issue or PR within 5 minutes of opening | Targeted by the fast-merge rule |
| **Pair Extraordinaire** | Co-authored commits with a real collaborator | **Needs a real human collaborator — optional** |
| **Starstruck** | 16 stars on a repository | After launch |

**Pair Extraordinaire note.** This one needs `Co-Authored-By` trailers naming a *real*
collaborator, so it is optional rather than part of the plan. An AI co-author trailer must
not be used to earn it: that contradicts the no-AI-attribution rule and, when it was tried
once, listed "claude" as a repository contributor.

**Update the merged-PR count in this table in each phase's last PR.**

---

## Phase 2 — Repo connection (GitHub App)

**Status:** Done — 2a, 2b and 2c merged.

Open a PR on a repository the App is installed on and `codesage-nr[bot]` comments
within seconds. The `/repos` page shows what the installation can reach and lets an
owner or admin connect and disconnect.

The App is `CodeSage NR` (slug `codesage-nr`, App ID 5366297), installed on
`NivedhReddy2048/codesage-testbed` only. Comments will post as `codesage-nr[bot]` —
spec §13 writes `codesage[bot]`, but the plain name was unavailable, and the bot login
is derived from the App name. Cosmetic only.

### 2a — App authentication and repos models

`AppInstallation`, `Repository` and `WebhookEvent` models, plus
`apps/repos/github_app.py`: RS256 App JWT to installation token, with tokens cached in
Redis until a minute before expiry.

Verified live against real GitHub, not only against mocks: `GET /app` returns
`contents: read`, `metadata: read`, `pull_requests: write` and `['pull_request']` as the
only subscribed event; the installation token scopes to just the testbed; and the cache
turns an 843 ms mint into a 1 ms read.

### 2b — signed webhook receiver and acknowledgement comment

`POST /api/webhooks/github/` verifies `X-Hub-Signature-256`, stores a `WebhookEvent`,
queues the follow-up work and returns 202 — no GitHub call on the request path. A
`PullRequest` model holds the bot comment's id so phase 5 can edit that comment rather
than adding a second one.

Measured over `127.0.0.1`: **~60 ms** for verify + persist + enqueue, against GitHub's
10 second budget. (A first measurement showed ~2 s, which turned out to be a
client-side `localhost` IPv6 resolution delay on Windows, not server time — the same
request to `127.0.0.1` took 15 ms.)

### 2c — connect-a-repo API and UI

`GET /api/repos/`, `GET /api/repos/installable/`, `POST /api/repos/connect/` and
`DELETE /api/repos/{id}/`, plus a `/repos` page listing connected repositories and
those available to connect, with an install link when the App is absent.

Verified live against real GitHub: unauthenticated 401; installable listed the testbed
with `connected: false`; a repository id the installation cannot reach was rejected
400; connect returned 201 then 200 on repeat; both views then showed it connected;
disconnect returned 204.

### Decisions worth recording

- **Connect and disconnect require owner or admin.** This is the first real use of
  `Membership.role` from phase 1: a member can see what the organisation reviews but
  must not rewire it.
- **The posted repository id is resolved against GitHub, not trusted.** Connecting
  checks the id against `GET /installation/repositories` first, so a caller cannot
  attach a repository the App has no access to.
- **Another tenant's repository reads as 404, not 403.** A 403 would confirm the row
  exists, which is itself a leak across tenants.
- **`current_organization()` is a single helper.** Phase 1 gives every user exactly
  one personal organisation, so that is the answer today; phase 6's workspace switcher
  changes this function and nothing else.
- **Connecting pins the installation to the organisation.** From then on the webhook
  path uses that explicit link instead of falling back to GitHub-login matching, so
  the UI and the webhook can never disagree about which tenant a PR belongs to.
- **A GitHub outage degrades the page rather than 500ing it.** If listing
  installation repositories fails, connected repositories still render.
- **The App slug is cached for a day.** It is needed to build the install URL and
  never changes, so it is fetched once from `GET /app` rather than per request, or
  supplied directly via `GITHUB_APP_SLUG`.

### Fixed after the phase merged

Two defects got through all three Phase 2 PRs. In both cases the local suite was
green, so they are recorded here for the reason they were missed rather than for the
fix itself.

**CI had no Redis service container** ([#18](https://github.com/NivedhReddy2048/CodeSage/pull/18)).
2a added a `CACHES` setting pointing at Redis for installation-token caching. CI had
a Postgres service from phase 1 but never gained a Redis one, so the backend job
failed with `Error 111 connecting to localhost:6379` while every local run passed,
because `docker compose` provides Redis here. Three PRs were merged without checking
the CI result. The fix adds the service container — Redis is a real production
dependency and the cache semantics are under test, so substituting an in-memory cache
would have stopped testing what ships. The autouse cache fixture was also narrowed:
it had been making pure JWT and key-loading tests depend on Redis.

**The webhook route only existed with a trailing slash** ([#20](https://github.com/NivedhReddy2048/CodeSage/pull/20)).
`smee-client` strips the trailing slash from its target, so it posted to
`/api/webhooks/github` while the route was registered only as
`/api/webhooks/github/`. `APPEND_SLASH` cannot redirect a POST without discarding the
body, so `CommonMiddleware` raised and the relay saw a 500 before any project code
ran — no delivery ever reached the handler. Every test passed because they all
`reverse()` the route by name, which always yields the slashed path; nothing
exercised the path a real client uses. Both paths are now registered, with a test
asserting the slash-less one still rejects a bad signature.

**The lesson, for later phases:** a green local suite and green unit tests are not a
verified system. Check CI before merging, and exercise the real client path — the
relay found in minutes what 161 passing tests did not.

### Open item for me

**Setup URL (optional).** The GitHub App has no Setup URL, so installing or
reconfiguring it leaves the browser on GitHub's own confirmation page. Setting it to
`http://localhost:3000/repos` (and the Vercel URL in phase 7) would return the user
straight to the repositories page. Not required for anything to work.

- **Background work uses a thread, not Celery, for now.** Celery and its worker
  arrive in phase 3 with ingestion; standing one up here for a single small job would
  be work phase 3 immediately redoes. `apps/repos/dispatch.py` is a narrow seam with
  the same call shape as a Celery task, so phase 3 replaces the body and no caller
  changes. `BACKGROUND_TASKS_EAGER` runs it inline, which is how tests avoid racing a
  thread and mirrors Celery's `task_always_eager` (spec §7).
- **Connection teardown belongs only to the threaded path.** A first version closed
  all database connections in a `finally` regardless; in eager mode that closed the
  *caller's* connection and broke the request around it. A test caught it.
- **An unset webhook secret rejects everything.** Failing closed matters here: the
  endpoint is public, so treating "no secret configured" as "trust every caller" would
  be the worst possible default.
- **Only `opened` and `synchronize` trigger work.** Those are the two actions that
  change the diff; `reopened`, `edited` and `labeled` must not spend a review.
- **`synchronize` edits the existing comment instead of adding one**, so a PR with
  five pushes still carries one bot comment.
- **A repository is auto-registered on first webhook.** Installing the App is itself
  the grant of access, so a PR gets a review without a second confirmation step in the
  UI. The tenant is resolved from an explicit connect-flow link when one exists, and
  otherwise from the personal organisation of the user whose GitHub login matches the
  installation account. This is also what makes 2b testable on its own, before the 2c
  UI exists.
- **The JWT issuer prefers the Client ID, falling back to the App ID.** GitHub's docs
  now say "Use of the client ID is recommended"; the App ID is still accepted and is
  not deprecated. Supporting both means the project follows current guidance without
  breaking when only the App ID is configured.
- **The private key has two sources by design.** Locally it is a gitignored file
  (`GITHUB_APP_PRIVATE_KEY_PATH`); in production there is no filesystem to put it on,
  so the PEM travels in `GITHUB_APP_PRIVATE_KEY` with escaped newlines. Neither path
  requires pasting a multi-line PEM into a `.env`.
- **Redis became a real cache backend here.** Installation tokens need somewhere
  durable and shared to live; Django has shipped a native Redis backend since 4.0, so
  this cost no new dependency. Previously the project used the default in-memory cache.
- **`pyjwt[crypto]` is now pinned explicitly.** RS256 needs `cryptography`, which was
  present only as a transitive dependency of Twisted/pyOpenSSL. Depending on that
  accidentally would have broken on any unrelated dependency change.
- **A token expiring within the renewal margin is not cached at all**, rather than
  cached briefly. Handing out a credential that dies mid-request is worse than paying
  for a fresh mint.
- **`Repository` uniqueness is per organisation, not global.** Two tenants may
  legitimately connect the same public repository.
- **`WebhookEvent.delivery_id` is unique**, which is what makes redelivery idempotent:
  GitHub reuses the id, so a replay collides instead of queueing a duplicate review.
- **Deleting an installation keeps its `Repository` rows** (`SET_NULL`). Uninstalling
  the App should not erase the record of what was connected.

### Fixed here: the serif font

`globals.css` declared `--font-sans: var(--font-sans)` — a self-referential custom
property, which CSS treats as invalid at computed-value time. So `html { @apply
font-sans }` resolved to nothing and every page fell back to the browser's default
serif, while `layout.tsx` published the real font as `--font-geist-sans`, which nothing
read. Two scaffolds (create-next-app and shadcn) disagreeing on a variable name.
One-line fix, confirmed in the compiled CSS: `html{font-family:var(--font-geist-sans)}`.

---

## Phase 1 — Auth

**Status:** Done — 1a, 1b and 1c merged.

GitHub OAuth login works end to end: sign in at `/login`, land on an authenticated
shell listing your organisations. 51 backend tests, 100% statement coverage of the
measured backend code.

### 1a — backend auth models + OAuth endpoints

`accounts` app with a custom `User` (GitHub-backed), `Organization` and `Membership`
(owner/admin/member). GitHub OAuth App login exchanges a code for a user token, reads
the profile, matches or creates the user, creates a personal organisation on first
login, and returns a Simple JWT access/refresh pair. `GET /api/orgs/` lists the
caller's organisations with their role. 17 tests, GitHub fully mocked.

Endpoints: `GET /api/auth/github/start/`, `POST /api/auth/github/callback/`,
`POST /api/auth/token/refresh/`, `GET /api/auth/me/`, `GET /api/orgs/`.

### 1b — frontend login, callback and authenticated shell

A typed API client over `fetch` with one-shot token refresh, token storage that
tolerates blocked storage, an auth context, and three routes: `/login`
("Continue with GitHub"), `/auth/callback` (verifies state, exchanges the code,
stores the JWT pair), and `/` (an authenticated shell listing the signed-in user and
their organisations, with sign-out). Sidebar, org switcher, command palette and dark
mode are all phase 6.

### 1c — test hardening and coverage

Unit tests for `apps/accounts/github.py`, which every other test had stubbed out
wholesale and so had no coverage of its own. `requests` is mocked at the transport
level instead, so the real parsing and error handling runs. Plus Membership/RBAC
model tests and a query-count regression test on the org listing.

Coverage reporting is wired into `pytest` via `addopts`, with `fail_under = 90`
(currently 100%) so a later phase cannot land untested code silently. Entrypoints
(`asgi.py`, `wsgi.py`, `manage.py`) and migrations are excluded — they are executed by
the server, not the suite.

### Known gap

**The frontend has no test runner.** It is covered by `npm run lint` (including the
React Compiler rules) and a type-checked `npm run build`, but there are no component
tests. Choosing and wiring one (vitest or jest, plus React Testing Library) is a
decision worth making deliberately rather than slipping into a phase-1 PR. The UI
that matters — the PR review view — arrives in phase 6, which is the natural place
for it.

### Decisions worth recording

- **The OAuth redirect lands on the frontend, not the backend.** GitHub sends the
  browser to `http://localhost:3000/auth/callback`; the SPA posts the code to the
  backend and gets the JWTs in the response body. Redirecting to the backend would
  mean returning tokens through a URL, where they persist in browser history and
  server logs. `GITHUB_OAUTH_REDIRECT_URI` makes this configurable per environment.
- **The user's GitHub OAuth token is not stored.** It is used once in the callback to
  read the profile, then discarded. Phase 2 reaches repositories through the GitHub
  App installation token (spec §13), so there is no reason to keep a long-lived user
  credential in the database.
- **Users are matched on `github_id`, never on login or email.** GitHub logins can be
  renamed and then claimed by someone else; the numeric id is stable. A test covers
  the rename case.
- **OAuth `state` is signed rather than stored.** `django.core.signing` with a 10
  minute expiry gives replay protection without making login depend on Redis.
- **CI gained its Postgres service here, not in 1c.** The suggested split put it with
  the tests, but the first real models land in 1a and its tests need a database, so
  the service container had to come with them to keep CI green.
- **The GitHub token exchange checks the payload, not just the status code.** A bad
  or reused OAuth code comes back as HTTP 200 with an `error` field, so a status-only
  check would hand a missing token to the caller. There is a test for exactly this.
- **A tampered `state` must prevent the exchange, not just fail after it.** The test
  asserts the exchange function is never called, since that is the actual CSRF
  guarantee.
- **The org listing has a query-count test.** The `Subquery` annotation exists to
  avoid N+1; the test proves one organisation and seven organisations cost the same
  two queries, so a later refactor cannot quietly regress it.
- **The dev `DJANGO_SECRET_KEY` placeholder was lengthened to 32+ characters.** PyJWT
  warns below that for HS256, and the phase-0 placeholder was 26. Fixed in
  `.env.example` and the settings fallback.
- **Concurrent 401s share one refresh.** The backend has
  `ROTATE_REFRESH_TOKENS` on, so two racing refreshes would invalidate each other.
  The API client keeps a single in-flight refresh promise that all callers await.
- **JWTs live in `localStorage`, not cookies.** The backend is on a different origin
  from the frontend (Render vs Vercel) and issues bearer tokens, so there is no
  same-site cookie to lean on. The tradeoff is real — any injected script can read
  them — and is mitigated by a 30 minute access token lifetime.
- **The OAuth code exchange is guarded against React Strict Mode.** Effects run twice
  in development and an OAuth code is single-use, so the second exchange would fail
  with a confusing error. A ref makes it run once.
- **State updates in effects happen in promise callbacks, never synchronously.** The
  React Compiler lint rules reject synchronous `setState` in an effect body; the
  validation and exchange logic moved into async functions so the callback page and
  auth provider comply rather than suppressing the rule.
- **`frontend/.gitignore` needed a negation for `.env.local.example`.** Its blanket
  `.env*` rule would have silently excluded the file that documents the required
  variables.
- **`AUTH_USER_MODEL` was changed after phase 0 had already migrated.** The local dev
  database was dropped and recreated; nothing was deployed and no real data existed.
  A fresh clone is unaffected.

---

## Phase 0 — Scaffold

**Status:** Done

Monorepo scaffold in place: a Django 6.1 + DRF + Channels backend with the eight
spec apps as empty skeletons, a Next.js 16 + Tailwind + shadcn/ui frontend, local
Postgres (pgvector) and Redis via Docker Compose, and CI linting and testing both halves.

### Verified

| Check | Result |
|---|---|
| `docker compose up -d` | Both containers healthy |
| pgvector extension | v0.8.6, cosine operator (`<=>`) functional |
| Redis | Responds to `PING` |
| Channels layer | `RedisChannelLayer` group send/receive round-trips |
| `manage.py check` | No issues |
| `manage.py migrate` | Applied against the container |
| `ruff check .` | Clean |
| `pytest` | 2 passed |
| `npm run lint` / `npm run build` | Clean; 2 routes built |
| `npm run dev` | Serves HTTP 200 |

### Pinned versions

Django 6.1.1, DRF 3.18.1, Channels 4.3.2, Daphne 4.2.3, psycopg 3.3.6 on Python 3.14;
Next.js 16.3.5, React 19.2.8, Tailwind 4 on Node 24.

### Notes and deviations from the spec

- **Settings as a single env-driven module, not a split package.** `backend/core/settings.py`
  reads every environment-specific value through `django-environ`. Spec section 10 /
  phase 7 explicitly allows this ("or django-environ based config") as the alternative
  to a `settings/production.py` split, so phase 7 can supply env vars rather than
  refactor settings.
- **`drf-spectacular` wired in phase 0 rather than later.** Spec section 8 requires it for
  the live Swagger page. Wiring it while the URL conf is empty costs three lines and
  means every endpoint added from phase 1 onward is documented automatically.
- **A DB-free placeholder test suite.** `backend/tests/test_smoke.py` asserts the health
  endpoint and the OpenAPI schema respond. Phase 0's CI has no Postgres service
  container, so the suite deliberately touches no database; phase 1 adds the service
  when the first models land.
- **`agents` exists as a Django app for now.** Spec section 4 lists it among the eight apps, so
  phase 0 creates it as one. Phase 4 states the pipeline itself must be a plain Python
  package with no Django ORM imports — that package will live inside this app.
- **Known doc inconsistency (no action needed).** The phase 4 prompt cites "spec section 7
  in-process module boundary decision", but spec section 7 covers the free-tier Celery/Daphne
  co-location workaround and says nothing about the agents package boundary. The phase 4
  prompt states that boundary rule directly, so it is followed as written from there.
