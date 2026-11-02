# Deploying CodeSage

How to stand up the production stack on free tiers, in order. Every step lists
environment variable **names** only; values live in the provider dashboards and
never in this repository. The local equivalents are in `backend/.env.example` and
`frontend/.env.local.example`.

| Piece | Service | Region |
|---|---|---|
| Postgres + pgvector | Neon, free plan | AWS us-west-2 (Oregon) |
| Redis | Render Key Value `carebridge-redis`, **shared** | Oregon |
| Frontend | Vercel, Hobby | functions in `pdx1` (Portland) |
| Backend: Daphne + Celery worker | Render free web service, Python | Oregon |
| Keep-warm ping | GitHub Actions schedule | n/a |

Everything sits on the US west coast, so the API, the database and Redis are a few
milliseconds apart. Choose names before you start: the Render service name fixes
its URL (`https://<render-service>.onrender.com`), which the Vercel and GitHub App
steps need before the service exists.

---

## 1. Neon (Postgres)

1. Create a project: Postgres 17, region **AWS US West 2 (Oregon)**.
2. Compute: leave scale-to-zero on (fixed at 5 minutes on the free plan). Set
   autoscaling to **0.25-0.5 CU**: compute-hours are CU x hours, and a small ceiling
   keeps a busy day inside the monthly allowance (see "Monthly limits to watch").
3. Connection details: switch **Connection pooling on** and copy the pooled string.
   The host contains `-pooler`, and the string ends in `sslmode=require`.
4. pgvector needs no manual step: the first migration runs `CREATE EXTENSION vector`,
   which the Neon owner role is allowed to do.

| Variable (Render) | Value |
|---|---|
| `DATABASE_URL` | the **pooled** connection string |

Production refuses to start if `DATABASE_URL` is missing or is not a `*.neon.tech`
host, so the build fails instead of the app quietly running on the wrong database.
**Never use Render Postgres:** its free databases are deleted 30 days after creation.
CareBridge went down for exactly that reason. There is no SQLite fallback.

What the settings do with it (`backend/core/settings.py`): connections last one
request or task (`CONN_MAX_AGE=0`), so nothing held open keeps the compute awake. On
the pooled host (PgBouncer in transaction mode), server-side cursors and psycopg's
automatic prepared statements are off.

---

## 2. Redis: share `carebridge-redis`

The account is allowed one free Key Value instance (Valkey 8, 25 MB, 50
connections), and CareBridge already has it. CodeSage shares it without colliding:

- **Its own logical database.** CareBridge uses database 0; CodeSage uses **1**.
  Production refuses to start if `REDIS_URL`, the Celery broker or the result
  backend selects database 0.
- **A key prefix on everything**: `codesage:` on the broker, results and cache, and
  `codesage:asgi` on Channels. The apps stay apart even if the index were lost.
- **At most 15 connections** of the 50, capped per process (table below).

Steps:

1. In the Render dashboard, open `carebridge-redis` and copy its **internal** URL
   (both services are in Oregon, so the private network reaches it, without TLS or
   an IP allowlist).
2. Append `/1`, so the URL ends in `:6379/1`.
3. Set **Maxmemory policy** to **`volatile-lru`** (Settings). See "Eviction policy" below.

| Variable (Render) | Value |
|---|---|
| `REDIS_URL` | internal Key Value URL + `/1` |

To confirm database 1 is usable before deploying, allow your IP under the Key
Value's access control, then run this from `backend/`:

```bash
.venv/Scripts/python -c "import redis,sys; r=redis.from_url(sys.argv[1]); print(r.ping(), r.info('keyspace'))" "<external URL>/1"
```

### Connection budget (15 of 50)

Two processes run in the container (`bin/start.sh`). The caps are per **process**:
Django keeps a cache client per thread, so the cache shares one pool per process
(`core/redis_pool.py`) instead of one pool per thread.

| Process | Client | Cap |
|---|---|---|
| Daphne (web) | Django cache, one shared blocking pool | 2 |
| | Channels layer, Daphne's event loop | 3 |
| | Celery producer (`broker_pool_limit` 1) | 1 |
| Celery worker | broker consumer: blocking pop + acks | 2 |
| | Celery producer (tasks queueing tasks) | 1 |
| | Django cache, one shared blocking pool | 2 |
| | Channels `group_send`, one event loop at a time | 3 |
| | remote control pub/sub | 0 (off in production) |
| | result backend | 0 (results are not stored) |
| **Worst case** | | **14** |

**Measured** in `python:3.14.2-slim`, running `bin/start.sh` with production-shaped
settings: **2 connections idle; 7 at peak** with 20 concurrent signed webhooks, 10
open WebSockets, and 20 reviews running through the worker. Before the
shared-pool fix the same run peaked at 25. `tests/test_redis_budget.py` counts live
connections by client name and fails if the cache pool's cap stops holding.

CodeSage's cache and Channels connections show up in `CLIENT LIST` as
`codesage-cache` and `codesage-channels`. Celery's appear unnamed.

### Eviction policy: `volatile-lru`

What each app keeps in the shared instance (CareBridge read from its repository at
`master`):

| App | Keys | TTL |
|---|---|---|
| CareBridge (db 0) | Celery broker queue `celery`, `_kombu.binding.*`, `unacked*` | **none** |
| | Celery results `celery-task-meta-*` (only if a worker runs) | 1 day |
| | Channels (`asgi*`) for notifications and telemedicine | yes (60 s / 1 day) |
| | Django cache and DRF throttles | not in Redis (`CACHES` is unset, so local memory) |
| CodeSage (db 1) | Celery queue, unacked hash, bindings | **none** |
| | cache (installation tokens, catch-up state) | yes, always |
| | Channels | yes |

Under `allkeys-lru`, memory pressure can evict any key, including either app's
**Celery queue**, which silently loses queued reviews or EHR tasks. Under
`volatile-lru`, only keys with a TTL are evicted: caches and Channels messages,
which both apps rebuild. Queues are never touched. The trade-off: if keys without a
TTL ever filled 25 MB, writes would fail with an OOM error instead of evicting.
That is loud, not silent, and unlikely, because CodeSage's TTL-less keys are a
handful of small queue messages.

One thing to watch on CareBridge's side: it runs as a web service only, with no
Celery worker, so every `process_ehr_document.delay()` adds a message to its
`celery` list that nothing consumes, and those messages have no TTL. Check
`LLEN celery` on database 0 now and then.

---

## 3. Vercel (frontend)

1. Import the repository; **Root Directory** `frontend`, framework Next.js.
2. Functions run in **`pdx1`** (Portland, next to Oregon). This is set in
   `frontend/vercel.json`, so there is nothing to choose in the dashboard.
3. Environment variables (Production):

| Variable (Vercel) | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://<render-service>.onrender.com` (no trailing slash) |
| `NEXT_PUBLIC_DEMO_REVIEWS_PER_WORKSPACE` | the backend's `DEMO_REVIEWS_PER_WORKSPACE_PER_DAY` (5) |

**`NEXT_PUBLIC_DEMO_REVIEWS_PER_WORKSPACE` must match the backend's
`DEMO_REVIEWS_PER_WORKSPACE_PER_DAY` on Render.** The landing page shows this number
before anyone signs in, when the backend may still be asleep, so it cannot ask the
API. Nothing keeps the two in sync: change both together, and redeploy Vercel after
changing it, because `NEXT_PUBLIC_` values are baked in at build time. Signed-in
pages read the real cap from `GET /api/demo/`, so only the landing page can drift.

The WebSocket URL is derived from `NEXT_PUBLIC_API_URL` (`https` becomes `wss`).
Note the deployment's domain (`https://<vercel-app>.vercel.app`): the next three
steps need it.

---

## 4. Production OAuth App (sign-in)

GitHub, Settings, Developer settings, **OAuth Apps**, New:

- Homepage URL: `https://<vercel-app>.vercel.app`
- Authorization callback URL: `https://<vercel-app>.vercel.app/auth/callback` (a
  frontend route; the SPA posts the code to the API, so tokens never sit in a URL)

| Variable (Render) | Value |
|---|---|
| `GITHUB_CLIENT_ID` | the OAuth App's client ID |
| `GITHUB_CLIENT_SECRET` | a generated client secret |
| `GITHUB_OAUTH_REDIRECT_URI` | the callback URL above, exactly |

---

## 5. Production GitHub App (the PR loop)

GitHub, Settings, Developer settings, **GitHub Apps**, New. This is a separate
identity from the OAuth App: it receives webhooks and comments as `<slug>[bot]`.

- Homepage URL: the Vercel URL.
- Webhook: **active**. URL `https://<render-service>.onrender.com/api/webhooks/github/`.
  Secret: generate one with `python -c "import secrets; print(secrets.token_hex(32))"`.
- Setup URL (optional): `https://<vercel-app>.vercel.app/repos`, so installing
  returns the user to the repositories page.
- **Where can this GitHub App be installed: Any account.** The free-demo
  guardrails assume this (public repositories only, 3 per workspace, 5 reviews a
  day per workspace, 35 a day overall).

Repository permissions, the minimum the code uses:

| Permission | Access | Used for |
|---|---|---|
| Contents | Read-only | the diff, file contents, the branch head, the archive for indexing, push events |
| Pull requests | Read and write | the review comment, inline comments, resolving outdated threads (GraphQL) |
| Metadata | Read-only | mandatory |

Nothing else: no Issues, Checks or Actions, and no account permissions.

Subscribe to events: **Pull request** and **Push**. `installation` and
`installation_repositories` have no checkbox: GitHub sends them to every App.

Then generate a **private key** (a `.pem` download).

| Variable (Render) | Value |
|---|---|
| `GITHUB_APP_ID` | the numeric App ID |
| `GITHUB_APP_CLIENT_ID` | the App's client ID (`Iv23...`) |
| `GITHUB_APP_SLUG` | the URL slug (optional; fetched once from `GET /app` if unset) |
| `GITHUB_APP_PRIVATE_KEY` | the PEM itself, the PEM with `\n` escapes, or base64 of the PEM |
| `GITHUB_WEBHOOK_SECRET` | the webhook secret |

Base64 is the safest way to paste the key into any editor:
`base64 -w0 key.pem` (Linux) or
`[Convert]::ToBase64String([IO.File]::ReadAllBytes("key.pem"))` (PowerShell).

---

## 6. Render web service (the backend)

New, **Web Service**, from the GitHub repository:

| Setting | Value |
|---|---|
| Name | `<render-service>` (fixes the URL used above) |
| Region | Oregon |
| Instance type | Free |
| Runtime | Python 3 (no `render.yaml`) |
| Root Directory | `backend` |
| Build Command | `bash bin/build.sh` |
| Start Command | `bash bin/start.sh` |
| Health Check Path | `/api/health/` |
| Auto-Deploy | **After CI Checks Pass** |

**Root Directory `backend`** also means Render only auto-deploys commits that change
something under `backend/`. Frontend, docs and evaluation-result commits cost no
build minutes.

`bin/build.sh` installs requirements, runs `collectstatic`, `migrate` and
`flushexpiredtokens`, and prints how long each step took. `bin/start.sh` runs Daphne
and one lean Celery worker (solo pool, no gossip, mingle or heartbeat) side by side.
If either exits, the other is stopped and Render restarts the container, and
Render's SIGTERM reaches both.

Environment variables. Required:

| Variable | Notes |
|---|---|
| `PYTHON_VERSION` | `3.14.2`, matching CI and `backend/.python-version` |
| `DJANGO_PRODUCTION` | `True` |
| `DJANGO_SECRET_KEY` | 50+ random characters |
| `JWT_SIGNING_KEY` | 50+ random characters, different from the above |
| `CORS_ALLOWED_ORIGINS` | `https://<vercel-app>.vercel.app` (CSRF and WebSocket origins default to it) |
| `DATABASE_URL` | step 1 |
| `REDIS_URL` | step 2 |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_OAUTH_REDIRECT_URI` | step 4 |
| `GITHUB_APP_ID`, `GITHUB_APP_CLIENT_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET` | step 5 |
| `GROQ_API_KEY` | console.groq.com |
| `GEMINI_API_KEY` | Google AI Studio (embeddings and the LLM fallback) |

Optional, with defaults that suit this deploy: `GITHUB_APP_SLUG`,
`DJANGO_ALLOWED_HOSTS` (Render's `RENDER_EXTERNAL_HOSTNAME` is added automatically),
`TRUSTED_PROXY_HOPS` (3, see below), `DEMO_REVIEWS_PER_WORKSPACE_PER_DAY` (5),
`DEMO_REVIEWS_PER_DAY` (35), `DEMO_MAX_REPOS_PER_WORKSPACE` (3),
`INGESTION_MAX_CHUNKS_PER_REPO` (2000), `CATCHUP_INTERVAL_SECONDS` (1800),
`DJANGO_LOG_LEVEL`. The full list, with what each one does, is at the end of
`backend/.env.example`.

### Build time against the 500-minute budget

`bin/build.sh` measured in `python:3.14.2-slim` with a cold pip cache: **46-81 s**
over three runs (pip install 41-48 s; collectstatic, migrate on an empty database
and flushexpiredtokens about 5 s together). Render adds cloning, Python setup and
uploading the build, so expect **about 2-4 minutes per deploy**. Record the real
figure from the first deploy's log (the time between "Cloning" and "Build
successful"), since Neon's migrate is slower than a local database.

Budget: 500 pipeline minutes a month, **shared with every service on the account**
(CareBridge builds a Docker image, which is slower). At about 3 minutes, CodeSage
could deploy around 40 times a month on 120 minutes. The Root Directory filter
above keeps non-backend merges from counting.

### Client IP behind Render: `TRUSTED_PROXY_HOPS=3`

Measured on the live service, not documented by Render. A request reaches the app as

```
client  ->  Cloudflare (172.64.0.0/13 and its other ranges)  ->  Render's internal proxy (10.x)  ->  app
```

and each proxy appends the address it saw to `X-Forwarded-For`, so the header
ends `..., <client>, <Cloudflare edge>, <Render proxy>`. Counting from the right:

| `TRUSTED_PROXY_HOPS` | Audit log showed |
|---|---|
| 1 | `10.196.x`: Render's internal proxy |
| 2 | `172.71.x`: a Cloudflare edge |
| **3** | **the real client** |

3 is now the production default. A wrong value is not silent any more: when the
address read is private or internal, inside Cloudflare's published ranges, or the
header is shorter than the hop count, the app logs a warning and the audit entry
carries an `ip warning` detail naming the likely fix. A count that is too HIGH reads
an entry the client wrote itself, which can look like any public address; the only
tell is a header shorter than the count, which is flagged too. So after any change
on Render's side, repeat the `ifconfig.me` comparison.

**`CF-Connecting-IP` and `True-Client-IP` are not trusted.** Both are just headers.
Cloudflare overwrites them on requests it handles, but the app cannot see which hop
set them. If Render ever routed traffic without Cloudflare in front, a client's own
`CF-Connecting-IP` would arrive untouched.

A proposal, not implemented: the request can be shown to have come through
Cloudflare. The entry Render's own proxy appended second from the right is the
address of whoever connected to Render. If that entry is inside Cloudflare's
published ranges, Cloudflare handled the request, and its `CF-Connecting-IP` is the
address Cloudflare saw. That address is the same `X-Forwarded-For` entry that
`TRUSTED_PROXY_HOPS=3` already reads, so trusting the header would add nothing.
The one use worth having is a cross-check: when the second-from-right entry is a
Cloudflare address and `CF-Connecting-IP` differs from the third, flag the entry.
Two caveats keep this a proposal: the ranges must stay current (the list is in
`apps/audit/services.py`, last changed by Cloudflare in 2023), and a request sent from
a Cloudflare Worker also comes through Cloudflare.

### After the first deploy

1. `curl https://<render-service>.onrender.com/api/health/` returns
   `{"status": "ok", ...}`.
2. **Check the client IP the audit log records.** Sign in through Vercel, open
   **Audit log**, and compare the sign-in's IP with what `https://ifconfig.me` reports
   for you. See "Client IP behind Render" below; the answer was 3.
3. Connect a public repository you own (a fork, never someone else's upstream),
   open a test PR, and watch the `<slug>[bot]` comment arrive and turn into the
   review.
4. Try connecting a private repository: it is refused with "CodeSage's free demo
   reviews public repositories only".

---

## 7. Keep-warm: the `HEALTH_URL` variable

The `Keep warm` workflow (`.github/workflows/keep-warm.yml`) pings the health
endpoint every 5 minutes from **08:00 to 23:55 IST**, and is silent until this
variable exists.

GitHub repository, Settings, Secrets and variables, Actions, **Variables** tab,
New repository variable:

| Variable (GitHub Actions) | Value |
|---|---|
| `HEALTH_URL` | `https://<render-service>.onrender.com/api/health/` |

Run it once by hand (Actions, Keep warm, Run workflow) to confirm it is green.

Cron is UTC; IST is UTC+5:30, so the window is 02:30-18:30 UTC:

```yaml
- cron: "30-55/5 2 * * *"   # 08:00-08:25 IST
- cron: "*/5 3-17 * * *"    # 08:30-23:25 IST
- cron: "0-25/5 18 * * *"   # 23:30-23:55 IST
```

`tests/test_keep_warm.py` expands these lines and fails unless they cover exactly
08:00-23:55 IST at 5-minute steps.

**Hours math.** Awake from the first ping (08:00) until about 15 minutes after the
last (23:55), so about **16 h 10 min a day**, which is **~501 instance-hours** in a
31-day month (~485 in a 30-day one). That leaves **~249 of the 750 shared free
hours** for CareBridge, opshub-backend and smart-placement-platform. Those spend
hours only while awake, and a night-time visitor waking CodeSage costs at least 15
minutes.

Overnight, webhooks are lost (GitHub gives a delivery 10 s and never retries). The
**catch-up** recovers them: on the worker's first start each morning, and at most
every 30 minutes while awake, it lists each connected repository's open PRs on
GitHub and reviews any head commit with no review (`apps/repos/catchup.py`).
GitHub's cron is best-effort; a ping that runs more than 15 minutes late lets the
service sleep, and the next ping wakes it. Scheduled workflows also stop after 60
days without repository activity.

---

## Monthly limits to watch

| Limit | Allowance | Where to check | When it runs out |
|---|---|---|---|
| **Neon compute-hours** | 100 CU-hours per project per month | Neon console, the project, **Usage** (or Billing) | Neon suspends the compute until the month resets. Every API call that touches the database fails, and webhooks fail to store, so GitHub sees errors and those deliveries are lost. The catch-up reviews the open PRs once the database is back. |
| **Render instance hours** | 750 per month, **shared** by all free services | Render dashboard, Workspace settings, **Billing**, free usage | Every free web service on the account is suspended until the next month: CodeSage, CareBridge, opshub-backend and smart-placement-platform all stop answering. |
| **Render build minutes** | 500 pipeline minutes per month, **shared** | Render dashboard, Workspace settings, **Billing**, pipeline minutes | New builds stop until the month resets. The running deploy keeps serving, but merges no longer reach production. |
| **Groq daily tokens** | per model, per day: ~200K tokens for `gpt-oss-20b` and `gpt-oss-120b`, plus 1,000 requests a day for `gpt-oss-120b` | console.groq.com, **Settings**, **Limits** and **Usage**; live headers in the worker log | Live reviews fail over to Gemini (`REVIEW_FALLBACK_MODEL`) and are marked as fallback or degraded; evaluation runs stop for the day. Resets daily. |

**What wakes Neon.** Any authenticated API request (JWT authentication loads the
user); the notification bell's poll, once a minute but only while the tab is
visible and someone has touched the mouse, keyboard or screen in the last 10
minutes; webhook deliveries; review and indexing runs; the catch-up, but only for
news (an unknown head SHA, the cached repository list expiring every 6 hours, the
daily index check per repository); `migrate` and `flushexpiredtokens` on each
deploy; and the Django admin. The keep-warm ping, the health endpoint, an idle
Celery worker (which waits on Redis) and Render's health checks never touch it.

**Rough compute-hours**, at the 0.25 CU minimum. Each wake keeps the compute up for
at least 5 minutes after the last query:

| Use | Awake | CU-hours a month |
|---|---|---|
| Idle: no visitors, no PRs | catch-up refreshes, ~4 short wakes a day | **~3** |
| Light demo: about 1 h a day in the app, a few reviews | ~1.5 h a day | **~12-15** |
| Heavy: someone active in the app 8 h a day, 35 reviews and re-indexing | ~9-10 h a day, sometimes above 0.25 CU | **~70-100** |
| A visible tab forgotten on a screen | 10 minutes, then the bell stops polling | adds nothing after that (it was ~186 a month before the idle stop) |

**Groq on evaluation days.** A TEST run spends about 35 x 3.4K `gpt-oss-20b` tokens
(~119K of 200K), which leaves room for roughly 15-20 live reviews. Lower
`DEMO_REVIEWS_PER_DAY` (and, if needed, `DEMO_REVIEWS_PER_WORKSPACE_PER_DAY`) on
Render for that day, then put them back.
