# CodeSage — AI Multi-Agent Code Review & Engineering Copilot
### Full project specification — Django + DRF + Next.js, $0 infrastructure cost

> Build this with Claude Code in VS Code, phase by phase. Feed one "Build Phase" section at a time as a prompt; each phase is scoped to be a working, demo-able increment.

---

## 1. What it is

A multi-tenant SaaS where a team connects a GitHub repo, and every pull request is automatically reviewed by a **6-agent LangGraph pipeline** — not with generic advice, but grounded in the repo's *own* code and docs via hybrid retrieval (dense + BM25), the same RAG technique from your Enterprise Document Intelligence project, applied to source code instead of PDFs.

**Why this project, specifically:**
- Fills the one gap across your six existing projects: no project currently proves you can ship multi-agent/RAG engineering *inside a production Django full-stack app*. EKIP and Enterprise Document Intelligence prove the AI engineering; Smart Placement/CareBridge/OpsHub prove the full-stack engineering. This one proves both together.
- Domain (dev tooling) is untouched by your other six projects and is the most directly relatable one to a reviewer hiring for a Software Developer role.
- It replaces OpsHub in your project lineup, which was your one non-AI project — this closes that gap too.

---

## 2. Tech stack (every piece chosen to be genuinely $0, verified Sept 2026)

| Layer | Choice | Why / free-tier reality |
|---|---|---|
| Backend framework | Django + Django REST Framework | Matches your existing stack |
| Realtime | Django Channels (ASGI, via Daphne) | Live "reviewing PR #42..." status, same pattern as CareBridge |
| Frontend | Next.js 15/16 + TypeScript + Tailwind + shadcn/ui | Matches your existing stack; shadcn/ui is what gives the "enterprise" look (data tables, command palette, sidebar nav) for free |
| User login | GitHub OAuth App + Simple JWT | Free; identifies the human signing in to the dashboard |
| Repo integration | **GitHub App** (`codesage[bot]`) | Free. Owns webhooks, repo reads and PR comments, so reviews are posted by a bot identity rather than by my personal account — see §13 |
| Keep-warm | Scheduled GitHub Actions ping | Free. Works around Render's ~50s cold start against GitHub's 10s webhook timeout — see §15 |
| Database | **Neon** (serverless Postgres) with `pgvector` | Free tier is *permanent* (not a trial): 0.5GB storage, 100 compute-hrs/month, pgvector included on the free plan. This avoids Render's own free Postgres, which now **expires after 30 days** — a dealbreaker for a project you want live for interviews. [Neon pricing](https://neon.com/pricing) |
| Vector store | pgvector inside the same Neon Postgres | No separate vector DB service to host = one less paid thing. Keeps the "why Postgres over a dedicated vector DB" story simple in interviews too |
| Cache / Celery broker | **Upstash Redis** (claim the free DB into your account, not the anonymous instant one) | 256MB, 500K commands/month, persists once claimed. [Upstash pricing](https://upstash.com/pricing/redis) |
| Background jobs | Celery, worker **co-located in the same web dyno** (see §7) | Render's free tier only offers a free **Web Service** — Background Workers require a paid plan ($7/mo+). We work around this, not around $0. [Render free tier](https://render.com/docs/free) |
| LLM (primary) | **Groq** (Llama 3.3 70B) | Free tier: 30 RPM / 6,000 TPM / 1,000 requests per day — plenty for a demo project. [Groq free tier limits](https://tokenmix.ai/blog/groq-free-tier-limits-2026) |
| LLM (fallback) | Gemini free tier (already used in your other projects) | Reuses your multi-LLM failover pattern from EKIP |
| Embeddings | Gemini's free embedding endpoint | Avoids self-hosting a transformer model on a 512MB free dyno — keeps the web service light enough to actually run |
| Backend hosting | Render free Web Service | 750 free instance-hrs/month, spins down after 15 min idle (~50s cold start on next request — same tradeoff your other Render-deployed projects already have) |
| Frontend hosting | Vercel Hobby plan | Free, but restricted to non-commercial/personal use — fine for a portfolio project. Generous limits: 100GB data transfer, 1M edge requests/month. [Vercel Hobby plan](https://vercel.com/docs/plans/hobby) |
| CI/CD | GitHub Actions | Free for public repos; reuse the pytest CI pattern from EKIP |

**Total monthly cost: $0.** Every limit above is generous enough for a live portfolio demo; none of it is a "free trial" that expires.

---

## 3. Architecture

```
                    ┌─────────────────────┐
   Browser  ───────▶│  Next.js (Vercel)   │
                    │  dashboard, PR view  │
                    └──────────┬───────────┘
                               │ REST + WebSocket (JWT)
                               ▼
                 ┌───────────────────────────────┐
                 │   Django + DRF + Channels      │
                 │   (Render free Web Service,    │
                 │    single dyno, Daphne/ASGI)   │
                 │                                │
                 │  accounts · repos · reviews ·  │
                 │  ingestion · agents · analytics│
                 │                                │
                 │  ┌──────────────────────────┐  │
                 │  │ Celery worker             │  │  <- co-located process,
                 │  │ (same container, §7)      │  │     see workaround below
                 │  └──────────────────────────┘  │
                 └───────┬───────────┬─────────────┘
                         │           │
          GitHub Webhook │           │ broker/cache
                         ▼           ▼
                 ┌──────────┐  ┌──────────────┐
                 │ GitHub   │  │ Upstash Redis │
                 │ API      │  └──────────────┘
                 └──────────┘
                         │
                         ▼
                 ┌──────────────────────────┐
                 │ Neon Postgres + pgvector  │
                 │ (relational data + code   │
                 │  embeddings, hybrid       │
                 │  dense+BM25 retrieval)    │
                 └──────────────────────────┘
                         │
                         ▼
              ┌────────────────────────┐
              │ Groq (primary LLM)      │
              │ Gemini (fallback LLM)   │
              │ Gemini embeddings       │
              └────────────────────────┘
```

---

## 4. Django app breakdown

| App | Responsibility | Key models |
|---|---|---|
| `accounts` | GitHub OAuth login, org membership, RBAC | `User`, `Organization`, `Membership(role: owner/admin/member)` |
| `repos` | Connect/disconnect repos, GitHub App installation state | `AppInstallation(installation_id, account_login)`, `Repository`, `WebhookEvent` |
| `ingestion` | Clone/fetch repo content, chunk, embed, store in pgvector | `CodeChunk(file_path, symbol, content, embedding, repo_fk)`, `IngestionJob(status)` |
| `reviews` | PR webhook intake → trigger pipeline → store results | `PullRequest`, `Review`, `ReviewFinding(agent, severity, file, line, message, citation)` |
| `agents` | The LangGraph orchestration layer itself (not much "Django" here — mostly a Python package the `reviews` app calls into) | — |
| `notifications` | Live status over Channels, in-app notification center | `Notification` |
| `analytics` | Review quality trends, most-flagged files, agent agreement rate | (mostly aggregation queries over `Review`/`ReviewFinding`) |
| `audit` | Enterprise-feel audit log: who connected what repo, who changed a role, who dismissed a finding | `AuditLogEntry` |

This is 8 apps — comparable scope to OpsHub (8 modules), so it reads as a peer project, not a toy.

---

## 5. The agent pipeline (this is the centerpiece — spend your polish here)

Built with LangGraph, same orchestration tool as EKIP. A `Review` triggers this graph:

1. **Diff/Intent agent** — parses the PR diff, classifies what changed and why (feature/fix/refactor/docs), scopes which files matter.
2. **Static analysis agent** — runs real tools (ruff/eslint/bandit depending on language) as a *tool call*, not an LLM guess; feeds structured findings into context.
3. **Security agent** — LLM pass focused only on secrets, injection risk, unsafe deserialization, checked against the static findings.
4. **Codebase-grounding agent** — the RAG core: hybrid retrieval (pgvector cosine + Postgres full-text/BM25-style ranking) over the repo's own embedded code+docs, so a suggestion like "this duplicates logic in `utils/validators.py`" is actually true, with a citation (file + line).
5. **Test-coverage agent** — flags changed logic with no corresponding test change; suggests specific test cases.
6. **Correctness agent** *(added in Phase 8, issue #126)* — LLM pass that owns logic defects in the added lines: wrong conditions, the wrong variable, off-by-one, missing arguments, unhandled None/empty/index cases, broken behaviour changes. Never security or missing tests. Phase 8's DEV run 1 showed that without it most correctness bugs were noticed only as "untested".
7. **Synthesis** — merges all findings, deduplicates, prioritizes (blocking vs. nit), and posts one structured review comment back to the PR as `codesage[bot]` through the GitHub App (§13). The comment ends with a cost/latency footer (§14). As built it is a deterministic step, not a model call, so the pipeline counts six agents plus synthesis.

**Reliability layer (reuse your EKIP experience directly):**
- Multi-LLM failover: Groq → Gemini, with circuit breakers and latency tracking (you've already built this once).
- **Demo-mode fallback**: if both providers are rate-limited (real risk on free tiers), fall back to a cached/canned review response so your live demo never visibly breaks during an interview. This is a legitimate resilience pattern, not a hack — frame it as "graceful degradation," which is an enterprise concept interviewers like hearing about.

---

## 6. RAG / grounding design

- **Chunking**: parse by function/class (AST-aware, not naive line-splitting) so each chunk is a coherent unit — this is a meaningfully more sophisticated chunking story than "split every 500 tokens."
- **Embeddings**: `gemini-embedding-001` with **`outputDimensionality=1536`**, stored as a `vector(1536)` column via `pgvector`, searched by **cosine distance** over an **HNSW** index. The model name and dimension live in settings, not scattered through the code.

  **Why 1536 and not the default.** `gemini-embedding-001` returns **3072** dimensions
  unless told otherwise, and pgvector's `hnsw` and `ivfflat` indexes both cap at
  **2000 dimensions**. A 3072-dim column is storable but *not indexable*, so every
  similarity search silently degrades to a sequential scan — which defeats the whole
  point of the retrieval design below. The model supports Matryoshka truncation via
  `outputDimensionality`; 1536 stays indexable while keeping more signal than 768.
  Verified against the live API on 2026-10-18: 768 and 1536 come back indexable, 3072
  does not.
- **Hybrid retrieval**: pgvector cosine similarity (dense) combined with Postgres `ts_rank` full-text search (sparse/keyword) — same "hybrid dense + BM25" concept from your resume, implemented natively in Postgres instead of a separate BM25 library, which is a good "why Postgres can do this without extra infra" talking point.
- **Citation enforcement**: every grounding-agent claim must carry a `(file_path, line_range)` tuple pulled from the retrieved chunk's metadata — same citation-enforcement pattern as your Enterprise Document Intelligence project.

---

## 7. Free-tier worker workaround (be upfront about this in interviews — it's a legitimate tradeoff, not a hidden hack)

Render's free tier has no Background Worker service type. Options, in order of recommendation:

1. **Co-located process (recommended)**: a single start command that launches both the Celery worker and Daphne in the same container:
   ```bash
   celery -A core worker --loglevel=info --concurrency=2 & daphne core.asgi:application --port $PORT --bind 0.0.0.0
   ```
   This runs both inside your 750 free instance-hours, no second paid service. Document this explicitly in your README as a deliberate cost-tradeoff, with "in production this would split into a dedicated worker service" — that sentence itself is a good interview answer.
2. If concurrency/RAM becomes a problem on the free dyno, fall back to Celery's `task_always_eager=True` for lightweight jobs (runs synchronously in the request/worker process, no broker round-trip) and reserve the real async queue only for the heavier ingestion jobs.

---

## 8. API surface (representative, not exhaustive)

```
POST   /api/auth/github/callback/          GitHub OAuth exchange → JWT
GET    /api/orgs/                          list orgs user belongs to
POST   /api/repos/connect/                 connect a repo the GitHub App is installed on
GET    /api/repos/installable/             repos visible to the App installation
POST   /api/webhooks/github/               GitHub App webhook receiver -> 202 in <10s
GET    /api/reviews/{id}/                  review detail + findings + cost/latency
GET    /api/reviews/{id}/status/           poll fallback for Channels
WS     /ws/reviews/{id}/                   live status stream
GET    /api/repos/{id}/findings/analytics/ trend data for dashboard charts
GET    /api/audit-log/                     org audit trail
```
Document these with drf-spectacular (you already use this) for a live Swagger page — reuse that OpsHub strength directly.

`POST /api/webhooks/github/` is the one endpoint with a hard latency budget: it verifies
the signature, stores the event, enqueues the job and returns **202** — never running the
pipeline inline. See §13 for why 10 seconds is the ceiling.

---

## 9. Frontend — making the UI actually read "enterprise"

This is where a lot of "standout" perception comes from, and it's cheap to do well:

- **Component base**: shadcn/ui + Tailwind (free, unstyled-by-default, looks enterprise out of the box — this is what Linear/Vercel/Stripe-style dashboards are built from).
- **Shell**: persistent sidebar nav + org/workspace switcher (top-left dropdown) + command palette (`Cmd+K`) for jumping to repos/PRs — command palettes are a strong "this person thinks about developer experience" signal.
- **PR review view**: split pane — diff on one side, agent findings threaded per-file/per-line on the other, with a live status pill ("Reviewing... 3/6 agents complete") driven by the WebSocket.
- **Dashboard home**: KPI row (PRs reviewed, avg. findings/PR, avg. review latency) + a trend chart (findings over time) — load the `dataviz` design guidance when you build this so the charts look like one coherent system rather than default chart-library styling.
- **Audit log page**: table with filters — this single page does a lot of "enterprise" signaling for very little build effort.
- **Dark mode**: trivial with Tailwind + shadcn, expected at this point for a credible dev-tool UI.

---

## 10. Deployment checklist (all free)

1. **Neon**: create project → enable `pgvector` extension → copy connection string.
2. **Upstash**: create Redis DB, **claim it into your account** (don't use the anonymous instant-create flow, those auto-delete in 3 days) → copy `REDIS_URL`.
3. **Groq**: create API key (console.groq.com) — free, no card.
4. **Gemini**: create API key in Google AI Studio — free tier, no card.
5. **GitHub OAuth App** (user login only): Settings → Developer settings → OAuth Apps → new app, set callback URL to your Render backend URL.
5b. **GitHub App** (the PR loop): Settings → Developer settings → GitHub Apps → new app. Permissions: pull requests read & write, contents read, metadata read. Subscribe to `pull_request` events. Set the webhook URL to `<render-url>/api/webhooks/github/` and a webhook secret. Generate a private key and install the App on the repos (or the fork) you want reviewed. See §13.
6. **Render**: new free Web Service from your GitHub repo, start command from §7, add all env vars.
7. **Vercel**: import the `frontend/` folder as a new project, set `NEXT_PUBLIC_API_URL` to your Render URL.
8. **GitHub Actions**: reuse your EKIP pytest workflow as a starting point for CI on this repo.

`.env.example` to include: `DATABASE_URL`, `REDIS_URL`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`, `DJANGO_SECRET_KEY`, `JWT_SIGNING_KEY`.

`GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` belong to the OAuth App (user login). `GITHUB_APP_ID` / `GITHUB_APP_PRIVATE_KEY` / `GITHUB_WEBHOOK_SECRET` belong to the GitHub App (the PR loop). The private key is a multi-line PEM — store it with escaped newlines in the env var and unescape it on read.

---

## 11. Suggested build order (feed these to Claude Code one at a time)

1. **Phase 0 — Scaffold**: Django project + DRF + Channels skeleton, Next.js app, monorepo layout (`backend/`, `frontend/`), Docker Compose for local dev only (Postgres+pgvector, Redis locally — no need to hit Neon/Upstash until deploy).
2. **Phase 1 — Auth**: GitHub OAuth flow end-to-end, JWT issuance, `Organization`/`Membership` models, org switcher UI.
3. **Phase 2 — Repo connection**: connect a repo, register webhook, list connected repos in UI.
4. **Phase 3 — Ingestion**: clone repo, AST-aware chunking, embed via Gemini, store in pgvector; build the `IngestionJob` status UI.
5. **Phase 4 — Agent pipeline v1**: get a single-agent (synthesis-only) review working end-to-end on a real PR, posted back to GitHub — prove the full loop before adding sophistication.
6. **Phase 5 — Full 6-agent pipeline**: add the remaining agents, hybrid retrieval, citations, multi-LLM failover.
7. **Phase 6 — Realtime + polish**: Channels live status, PR review UI (diff + findings pane), dashboard analytics, audit log, command palette.
8. **Phase 7 — Deploy + CI**: Render/Vercel/Neon/Upstash wiring, GitHub Actions, keep-warm ping (§15), README with architecture diagram and the free-tier-tradeoff explanation from §7. Smoke-tested on a **fork** of a real open-source repo (§17).
9. **Phase 8 — Evaluation**: fixture repos with planted bugs, a ground-truth set, and a `run_eval` harness measuring CodeSage against a no-RAG baseline (§16). Can be run any time after Phase 5.

---

## 12. Resume bullets this project earns you

- "Architected a Django full-stack SaaS running a 6-agent LangGraph review pipeline on every GitHub PR, combining dense (pgvector) and keyword retrieval to ground suggestions in the repo's own code with file/line citations."
- "Designed a multi-LLM failover system (Groq → Gemini) with circuit breakers and a graceful-degradation fallback path, achieving zero-downtime demo reliability on free-tier API quotas."
- "Built async ingestion pipelines (Celery/Redis) for AST-aware code chunking and embedding, and a real-time review status stream via Django Channels."
- "Shipped a multi-tenant, RBAC-secured platform (org → repo → PR hierarchy) with a live audit log and OpenAPI-documented REST API."

---

---

## 13. GitHub App — the PR loop (Phase 2)

The project uses **two separate GitHub identities**, and conflating them is the most
likely source of confusion later:

| | OAuth App | GitHub App |
|---|---|---|
| Purpose | A human signs in to the dashboard | CodeSage reads repos and posts reviews |
| Phase | 1 | 2 |
| Acts as | The signed-in user | `codesage[bot]` |
| Credentials | `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | `GITHUB_APP_ID` / `GITHUB_APP_PRIVATE_KEY` |

**Why a GitHub App rather than the user's OAuth token** (a good interview answer):
review comments appear as `codesage[bot]` instead of as my own account, so the demo
looks like a product rather than a script; installation tokens are scoped to only the
repos the App is installed on and expire in an hour, so a leak is contained; and the
App keeps working when the installing user's OAuth token is revoked.

**App configuration.** Permissions: **pull requests read & write** (post the review),
**contents read** (fetch files for ingestion), **metadata read** (mandatory baseline).
Subscribed events: **`pull_request`** only — `opened` and `synchronize` are the two
actions that trigger a review.

**Token chain.** App ID + private key → sign a short-lived **RS256 JWT** (10 minute
maximum lifetime) → exchange it for an **installation access token** (valid 1 hour,
scoped to one installation) → use that token for every REST call. Cache installation
tokens until a minute before expiry rather than minting one per call.

### The 10-second rule

GitHub expects an HTTP response to a webhook within **10 seconds** and does not retry
automatically on timeout — a timed-out delivery has to be redelivered by hand from the
App's Advanced tab. The review pipeline takes far longer than 10 seconds, so the
webhook handler must never run it inline. The handler does exactly four things:

1. Verify the `X-Hub-Signature-256` HMAC against `GITHUB_WEBHOOK_SECRET` using a
   constant-time comparison. Reject with 401 on mismatch.
2. Persist a `WebhookEvent` row (raw payload included, for replay and debugging).
3. Enqueue the review as a Celery task, keyed on the delivery id so a redelivery is
   idempotent rather than producing a second review.
4. Return **202 Accepted** immediately.

The **acknowledgement comment** ("CodeSage is reviewing this PR...") is posted by the
enqueued task, not by the request handler — posting it inline would spend part of the
10 second budget on a GitHub API round-trip. The task stores the returned comment id on
the `Review`, so Phase 5's synthesis agent **edits that same comment** into the final
review instead of leaving two comments on the PR.

---

## 14. Cost and latency accounting (Phases 4-6)

Every LLM call is recorded, so "what does a review actually cost and how long does it
take" has a real answer rather than a guess.

**Recorded per call** (one row per call, foreign-keyed to the `Review`): agent name,
provider, model id, input tokens, output tokens, latency in milliseconds, and whether
the call was a primary, a failover, or a demo-mode response. Totals are denormalised
onto `Review` (`total_input_tokens`, `total_output_tokens`, `duration_ms`,
`estimated_cost_usd`, `estimated_cost_inr`) so the dashboard aggregates without
touching the per-call rows.

**Pricing lives in a table in settings**, not inline in the agents, so a price change
is a one-line edit:

```python
# USD per 1,000,000 tokens, at each provider's PAID tier.
# Gemini: https://ai.google.dev/gemini-api/docs/pricing - checked 2026-10-16.
# Groq: figure widely reported for llama-3.3-70b-versatile; Groq's own pricing page is
# JavaScript-rendered and could not be machine-verified, so RE-VERIFY at
# console.groq.com before trusting the output.
LLM_PRICING = {
    "llama-3.3-70b-versatile":  {"input": 0.59, "output": 0.79},
    # Replaces gemini-2.5-flash, which this account can no longer call. See the
    # "Gemini model availability" note below before changing this.
    "gemini-flash-lite-latest": {"input": 0.10, "output": 0.40},
    "gemini-embedding-001":     {"input": 0.20, "output": 0.00},
}

# Fixed, not fetched at runtime: a review's cost must not change when FX moves,
# and a currency API is one more thing that can fail in a demo.
# Source: ECB reference rate via api.frankfurter.dev - 1 USD = 95.06 INR on 2026-10-15.
USD_TO_INR = 95.06
USD_TO_INR_AS_OF = "2026-10-15"
```

**Always labelled an estimate at paid rates.** The project runs entirely on free tiers,
so actual spend is zero — the number is a projection of what the same review would cost
on a paid plan, and presenting it as a bill would be dishonest. Every surface says so:

```
Reviewed in 38 s · est. ₹2.10 at paid-tier rates
```

Shown in the PR comment footer (Phase 5), on the review detail view, and aggregated on
the dashboard as average cost and latency per review (Phase 6).

### Gemini model availability, verified 2026-10-18

Checked against a live key before building phase 3, because the plan above named
models that turned out not to be callable.

**`gemini-2.5-flash` and `gemini-2.5-flash-lite` return 404** — "no longer available
to new users. Please update your code to use models/gemini-3.8-flash". Both were named
in the price table above; both are now gone.

**The replacement thinking models are unusable in a review path.** Latency for the
prompt `"say ok"` on this key:

| Model | Latency | Thinking tokens |
|---|---|---|
| `gemini-3.8-flash` | **96 s** | 72 |
| `gemini-flash-latest` | **143 s** | 65 |
| `gemini-flash-lite-latest` | **2 s** | none |

Ninety-six seconds to emit one token would dominate the review latency the footer
reports. **The failover target is therefore `gemini-flash-lite-latest`, and thinking
models are never used in the review path.** Groq remains primary, so this only applies
when Groq is rate-limited.

---

## 15. Render cold start vs. GitHub's webhook timeout (Phase 7)

These two free-tier facts collide:

- A Render free web service **sleeps after 15 minutes idle** and takes roughly
  **50 seconds** to wake.
- GitHub **abandons a webhook after 10 seconds** and does not retry automatically.

So the first PR opened after a quiet period would lose its webhook entirely — the worst
possible failure for a live interview demo, because it looks like the product is broken.

**Fix: a keep-warm ping.** A scheduled GitHub Actions workflow curls `/api/health/`
every 10 minutes, keeping the service awake so webhooks land on a running process.

```yaml
on:
  schedule:
    - cron: "*/10 * * * *"
```

**Free-hours arithmetic** (document this in the README, it is the honest tradeoff):
keeping the service continuously awake costs about **744 instance-hours in a 31-day
month** (24 x 31) against Render's **750 free hours**. It fits, with roughly 6 hours of
headroom — but it consumes essentially the entire free allowance, so this account cannot
also run a second free web service. That is the deliberate trade: one always-warm
service instead of two cold ones.

**Known limits of this approach**, worth stating rather than hiding: GitHub's scheduled
workflows are best-effort and can be delayed under platform load, so an occasional ping
is late and one webhook may still hit a cold start; and GitHub disables scheduled
workflows on repositories with no activity for 60 days. Recovery for a missed delivery
is manual redelivery from the App's Advanced tab.

---

## 16. Phase 8 — Evaluation harness

The claim "a 6-agent RAG pipeline reviews better than one LLM prompt" is worth nothing
unless it is measured. Phase 8 measures it. It depends only on Phase 5, so it can run
any time after the full pipeline exists.

**Fixtures** — 3-5 small repositories under `eval/fixtures/`, a mix of Python and
JavaScript, each with a set of PRs:

- Most PRs plant **1-2 known bugs** drawn from: off-by-one, missing null check, SQL
  injection, missing `await`, wrong permission check, resource leak.
- **At least 30% are clean PRs** containing no planted bug at all. Without these the
  harness measures only recall and would reward a reviewer that flags everything.

**Ground truth** — one file per PR recording each planted bug as `(file, line_range,
category)`.

**The harness** — `python manage.py run_eval` runs every fixture PR through two arms:

- **(a) CodeSage** — the full 6-agent pipeline with hybrid retrieval.
- **(b) Baseline** — a single LLM prompt with the raw diff, no RAG and no agents. Same
  model as the pipeline's primary, so the comparison isolates the architecture rather
  than the model.

**Matching rule** — a finding counts as catching a planted bug when it is in the **same
file**, within **±3 lines** of the ground-truth range, and of a **matching category**.
The ±3 tolerance is deliberately generous (a reviewer that points at the right logic one
line off is correct), and it is a stated limitation, not a hidden thumb on the scale.

**Reported for both arms** — detection rate (bugs caught / bugs planted), false alarms
per PR, precision, average wall-clock time per review, average estimated cost per
review. Written to `eval/results.md`, with the summary table copied into the README.

**Quota discipline** — Groq's free tier allows 1,000 requests/day, and two arms over
several PRs multiply quickly. Results are **cached on disk**, keyed by fixture PR, arm
and pipeline version, so a rerun re-reads cached results instead of spending quota;
only changed fixtures re-run. Budget the first full run before launching it.

**Limitations** — stated plainly in `eval/results.md` and the README, because
overclaiming a 5-repo benchmark is worse than reporting a small one honestly:

- Small sample: a handful of repos and a few dozen PRs, so differences of a few
  percentage points are noise.
- Self-planted bugs, written by the same person who built the reviewer — not an
  independent benchmark, and likely easier than real production bugs.
- Free-tier model (Llama 3.3 70B), not a frontier model; absolute numbers would differ.
- The ±3 line matching tolerance and category matching are judgement calls.
- Single run per PR, so run-to-run LLM variance is unmeasured.

---

## 17. Demo and launch

**Smoke-test on a fork, never upstream.** Phase 7's end-to-end test runs against a
**fork** of a real open-source repository, with test PRs opened on the fork. Never open
test PRs against the upstream project: `codesage[bot]` comments would reach real
maintainers as spam. A fork gives genuinely realistic code to review with no one else
affected.

**After Phase 8 — my checklist** (not Claude Code's):

- [ ] Record a **2-minute demo video**: connect a repo, open a PR on the fork, review
      comment appears, with the live status pill visible.
- [ ] Put the **live link**, the **video** and the **evaluation results table** at the
      very top of the README, above the architecture section — a reviewer who reads only
      the first screen should see that it is deployed, working, and measured.

---

### Sources for the free-tier claims above
- [Render — Deploy for Free](https://render.com/docs/free)
- [Render Pricing Guide — Kuberns](https://kuberns.com/blogs/render-pricing/)
- [Neon Pricing](https://neon.com/pricing)
- [Upstash Redis Pricing](https://upstash.com/pricing/redis)
- [Groq API Free Tier Limits 2026 — TokenMix](https://tokenmix.ai/blog/groq-free-tier-limits-2026)
- [Vercel Hobby Plan](https://vercel.com/docs/plans/hobby)
