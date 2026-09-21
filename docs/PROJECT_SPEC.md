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
| Auth | GitHub OAuth App + Simple JWT | Free; also solves "how do we get repo access" in one step |
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
| `repos` | Connect/disconnect repos, webhook registration | `Repository`, `WebhookEvent` |
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
6. **Synthesis agent** — merges all findings, deduplicates, prioritizes (blocking vs. nit), and posts one structured review comment back to the PR via the GitHub API.

**Reliability layer (reuse your EKIP experience directly):**
- Multi-LLM failover: Groq → Gemini, with circuit breakers and latency tracking (you've already built this once).
- **Demo-mode fallback**: if both providers are rate-limited (real risk on free tiers), fall back to a cached/canned review response so your live demo never visibly breaks during an interview. This is a legitimate resilience pattern, not a hack — frame it as "graceful degradation," which is an enterprise concept interviewers like hearing about.

---

## 6. RAG / grounding design

- **Chunking**: parse by function/class (AST-aware, not naive line-splitting) so each chunk is a coherent unit — this is a meaningfully more sophisticated chunking story than "split every 500 tokens."
- **Embeddings**: Gemini's free embedding endpoint, stored as a `vector` column in Postgres via `pgvector`.
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
POST   /api/repos/connect/                 connect a GitHub repo, register webhook
POST   /api/webhooks/github/               GitHub webhook receiver (PR opened/synced)
GET    /api/reviews/{id}/                  review detail + findings
GET    /api/reviews/{id}/status/           poll fallback for Channels
WS     /ws/reviews/{id}/                   live status stream
GET    /api/repos/{id}/findings/analytics/ trend data for dashboard charts
GET    /api/audit-log/                     org audit trail
```
Document these with drf-spectacular (you already use this) for a live Swagger page — reuse that OpsHub strength directly.

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
5. **GitHub OAuth App**: Settings → Developer settings → OAuth Apps → new app, set callback URL to your Render backend URL.
6. **Render**: new free Web Service from your GitHub repo, start command from §7, add all env vars.
7. **Vercel**: import the `frontend/` folder as a new project, set `NEXT_PUBLIC_API_URL` to your Render URL.
8. **GitHub Actions**: reuse your EKIP pytest workflow as a starting point for CI on this repo.

`.env.example` to include: `DATABASE_URL`, `REDIS_URL`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_WEBHOOK_SECRET`, `DJANGO_SECRET_KEY`, `JWT_SIGNING_KEY`.

---

## 11. Suggested build order (feed these to Claude Code one at a time)

1. **Phase 0 — Scaffold**: Django project + DRF + Channels skeleton, Next.js app, monorepo layout (`backend/`, `frontend/`), Docker Compose for local dev only (Postgres+pgvector, Redis locally — no need to hit Neon/Upstash until deploy).
2. **Phase 1 — Auth**: GitHub OAuth flow end-to-end, JWT issuance, `Organization`/`Membership` models, org switcher UI.
3. **Phase 2 — Repo connection**: connect a repo, register webhook, list connected repos in UI.
4. **Phase 3 — Ingestion**: clone repo, AST-aware chunking, embed via Gemini, store in pgvector; build the `IngestionJob` status UI.
5. **Phase 4 — Agent pipeline v1**: get a single-agent (synthesis-only) review working end-to-end on a real PR, posted back to GitHub — prove the full loop before adding sophistication.
6. **Phase 5 — Full 6-agent pipeline**: add the remaining agents, hybrid retrieval, citations, multi-LLM failover.
7. **Phase 6 — Realtime + polish**: Channels live status, PR review UI (diff + findings pane), dashboard analytics, audit log, command palette.
8. **Phase 7 — Deploy + CI**: Render/Vercel/Neon/Upstash wiring, GitHub Actions, README with architecture diagram and the free-tier-tradeoff explanation from §7.

---

## 12. Resume bullets this project earns you

- "Architected a Django full-stack SaaS running a 6-agent LangGraph review pipeline on every GitHub PR, combining dense (pgvector) and keyword retrieval to ground suggestions in the repo's own code with file/line citations."
- "Designed a multi-LLM failover system (Groq → Gemini) with circuit breakers and a graceful-degradation fallback path, achieving zero-downtime demo reliability on free-tier API quotas."
- "Built async ingestion pipelines (Celery/Redis) for AST-aware code chunking and embedding, and a real-time review status stream via Django Channels."
- "Shipped a multi-tenant, RBAC-secured platform (org → repo → PR hierarchy) with a live audit log and OpenAPI-documented REST API."

---

### Sources for the free-tier claims above
- [Render — Deploy for Free](https://render.com/docs/free)
- [Render Pricing Guide — Kuberns](https://kuberns.com/blogs/render-pricing/)
- [Neon Pricing](https://neon.com/pricing)
- [Upstash Redis Pricing](https://upstash.com/pricing/redis)
- [Groq API Free Tier Limits 2026 — TokenMix](https://tokenmix.ai/blog/groq-free-tier-limits-2026)
- [Vercel Hobby Plan](https://vercel.com/docs/plans/hobby)
