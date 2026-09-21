# CodeSage — Build Progress

Single source of truth for where the build stands. Each phase is built on its own
branch and merged to `main` with `--no-ff`. Architecture lives in
[PROJECT_SPEC.md](PROJECT_SPEC.md); the per-phase prompts live in
[BUILD_PROMPTS.md](BUILD_PROMPTS.md).

## Phase checklist

| # | Phase | Branch | Status |
|---|---|---|---|
| 0 | Scaffold | `phase-0-scaffold` | **Done** |
| 1 | Auth | `phase-1-auth` | Next |
| 2 | Repo connection | `phase-2-repos` | Not started |
| 3 | Ingestion | `phase-3-ingestion` | Not started |
| 4 | Agent pipeline v1 | `phase-4-agent-v1` | Not started |
| 5 | Full 6-agent pipeline | `phase-5-full-pipeline` | Not started |
| 6 | Realtime + polish | `phase-6-realtime-ui` | Not started |
| 7 | Deploy + CI | `phase-7-deploy` | Not started |

---

## Version control workflow

Phase 0 (the project spec, the build prompts and the whole scaffold) was squashed
into a single commit on `main` to keep the repository's contributor history clean.
The phase-branch history from the original build was discarded along with it.

From Phase 1 onward the repository follows the standard workflow in
[BUILD_PROMPTS.md](BUILD_PROMPTS.md): branch off `main` as `phase-N-<slug>`, commit
the phase's work, then merge back with `git merge --no-ff` so each phase stays
visible as its own merge commit in `git log --graph`.

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
