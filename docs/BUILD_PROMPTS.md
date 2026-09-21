# CodeSage — Phase-by-Phase Build Prompts for Claude Code

How to use this file: each "Phase N Prompt" section is meant to be **copy-pasted as-is** into Claude Code in VS Code, one at a time, in order. Claude Code in VS Code starts fresh each session with no memory of this conversation — that's why every prompt tells it to read the spec and progress files from the repo first, instead of relying on anything being remembered.

---

## 0. One-time setup (do this yourself, before Phase 0)

1. Create an empty GitHub repo, e.g. `codesage` (no README/gitignore template needed — you'll generate those).
2. Clone it locally and open it in VS Code.
3. Save the spec document I gave you earlier into the repo at **`docs/PROJECT_SPEC.md`** (rename it from `CodeSage_Project_Spec.md`). Every phase prompt below points Claude Code at this file — it's the single source of truth, so you never have to re-explain the architecture in a prompt again.
4. Commit that alone directly to `main`:
   ```
   git add docs/PROJECT_SPEC.md
   git commit -m "docs: add project specification"
   git push -u origin main
   ```

Everything after this uses feature branches, as you asked.

---

## Standard workflow every phase prompt follows

Each prompt below already includes these steps, but here's the pattern so you know what to expect:

1. Branch off latest `main`: `git checkout main && git pull && git checkout -b phase-N-<slug>`
2. Build the phase's scope only — not ahead, not behind.
3. Run/verify it actually works (tests, or a manual check described in the prompt).
4. Update `docs/PROGRESS.md` (created in Phase 0) marking the phase done, with a short note on any deviation from the spec.
5. Commit with a conventional commit message (`feat(phaseN): ...`).
6. Merge to `main` with `--no-ff` (keeps phase history visible in `git log --graph`, which itself is a nice thing to show in an interview) and push.

If a phase turns out too big for one sitting, that's fine — Claude Code should still commit working increments on the branch, and only merge to `main` once the phase's definition of done is met.

---

## Phase 0 — Scaffold

```
Read docs/PROJECT_SPEC.md in full before doing anything else — it defines the entire architecture for this project (CodeSage, a Django + DRF + Next.js multi-agent code review SaaS).

We are starting Phase 0: Scaffold. Do this:

1. Create branch: git checkout -b phase-0-scaffold (from main)
2. Set up a monorepo layout:
   - backend/  — Django project, DRF, Django Channels configured (ASGI via Daphne), the 8 apps listed in spec §4 as empty Django apps with just app configs (accounts, repos, ingestion, reviews, agents, notifications, analytics, audit) — no models yet, just the skeleton.
   - frontend/ — Next.js (TypeScript) app, Tailwind configured, shadcn/ui initialized.
   - docker-compose.yml for LOCAL DEV ONLY — Postgres with the pgvector extension enabled, and Redis. (We deploy to Neon/Upstash later, per spec §10 — local dev doesn't need those accounts.)
3. Add a root .gitignore covering Python, Node, and editor artifacts.
4. Add a minimal GitHub Actions workflow (.github/workflows/ci.yml) that runs on every PR: backend lint (ruff) + a placeholder test job, frontend lint (eslint) + build. It's fine if there are no real tests yet — the job should still pass on an empty test suite.
5. Create docs/PROGRESS.md with a checklist of all 8 phases (0-7, named per spec §11), mark Phase 0 in progress.
6. Verify: `docker compose up` brings up Postgres+Redis cleanly, Django's `manage.py check` passes, Next.js `npm run dev` serves the default page.
7. Update docs/PROGRESS.md: mark Phase 0 done with one sentence on what's in place.
8. Commit (conventional commit message), merge to main with --no-ff, push.

Do not build auth, models, or any business logic yet — this phase is scaffolding only.
```

---

## Phase 1 — Auth

```
Read docs/PROJECT_SPEC.md (especially §4 accounts app, §8 API surface, §10 env vars) and docs/PROGRESS.md for current status before starting.

Phase 1: Auth. Branch: phase-1-auth (from latest main).

Build:
1. accounts app models: User (extend Django's), Organization, Membership (role: owner/admin/member) — per spec §4.
2. GitHub OAuth App flow: backend endpoint(s) to start the OAuth redirect and handle the callback (POST /api/auth/github/callback/ per spec §8), exchanging the code for a GitHub access token, creating/matching the User, and issuing our own JWT (Simple JWT — access + refresh, matching the pattern from my other Django projects).
3. Org creation on first login (a user's first login creates a personal Organization with them as owner) and GET /api/orgs/ to list orgs the user belongs to.
4. Frontend: a login page that kicks off the GitHub OAuth redirect, a callback handler that stores the JWT, and a bare-bones authenticated shell page (just proves the token works — no real dashboard yet).
5. Add GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, JWT_SIGNING_KEY to .env.example (per spec §10) and README instructions for creating the GitHub OAuth App locally.
6. Write tests: at minimum, the OAuth callback creates a user + org, and JWT auth is enforced on a protected endpoint. Make these pass in CI.
7. Update docs/PROGRESS.md.
8. Commit, merge to main with --no-ff, push.

Do not build repo connection or any pipeline logic yet.
```

---

## Phase 2 — Repo connection

```
Read docs/PROJECT_SPEC.md (§4 repos app, §8 API surface) and docs/PROGRESS.md before starting.

Phase 2: Repo connection. Branch: phase-2-repos (from latest main).

Build:
1. repos app models: Repository, WebhookEvent (per spec §4).
2. POST /api/repos/connect/ — given a GitHub repo the authenticated user has access to, register a webhook on it (PR opened/synchronize events) and store the Repository record scoped to the user's Organization.
3. POST /api/webhooks/github/ — receiver that verifies the GitHub webhook signature (use GITHUB_WEBHOOK_SECRET, add to .env.example) and stores a WebhookEvent row. For this phase, just store and log the event — no pipeline trigger yet (that's Phase 4+).
4. GET endpoint to list connected repos for the current org.
5. Frontend: a "Connect a repo" page — list the user's GitHub repos (via GitHub API using their OAuth token from Phase 1), let them pick one to connect, show connected repos in a simple list/table.
6. Tests: webhook signature verification (valid + tampered payload), repo connect flow creates the right records scoped to the right org.
7. Update docs/PROGRESS.md.
8. Commit, merge to main with --no-ff, push.
```

---

## Phase 3 — Ingestion

```
Read docs/PROJECT_SPEC.md (§4 ingestion app, §6 RAG/grounding design, §10 embeddings choice) and docs/PROGRESS.md before starting.

Phase 3: Ingestion. Branch: phase-3-ingestion (from latest main).

Build:
1. ingestion app models: CodeChunk (file_path, symbol, content, embedding vector column via pgvector, repo FK), IngestionJob (status: pending/running/done/failed).
2. A Celery task that, given a connected Repository: clones/fetches its default branch, walks the source files, chunks them AST-aware by function/class (per spec §6 — not naive fixed-size splitting), calls the Gemini free embedding endpoint for each chunk, and bulk-stores CodeChunk rows with their vectors.
3. Trigger ingestion automatically right after a repo is connected (Phase 2's connect endpoint enqueues this task), with an IngestionJob record whose status the frontend can poll.
4. GET endpoint for ingestion job status; frontend shows "Indexing repo... X/Y files" (polling is fine here — Channels live updates come in Phase 6).
5. For local dev, run Celery via the co-located approach from spec §7 (document the exact start command in README) so it matches how it'll run on Render later — don't build a separate worker process assumption now that we'll have to undo.
6. Add GEMINI_API_KEY to .env.example.
7. Tests: chunking produces sensible boundaries on a small fixture file; embedding + storage round-trips correctly (mock the Gemini call in tests — don't burn real API quota in CI).
8. Update docs/PROGRESS.md.
9. Commit, merge to main with --no-ff, push.
```

---

## Phase 4 — Agent pipeline v1 (single agent, prove the full loop)

```
Read docs/PROJECT_SPEC.md (§4 reviews/agents apps, §5 agent pipeline, §7 in-process module boundary decision) and docs/PROGRESS.md before starting.

Phase 4: Agent pipeline v1. Branch: phase-4-agent-v1 (from latest main).

Important architecture note from spec §7 (already decided, don't relitigate it): the agent pipeline runs IN-PROCESS inside Django, but lives in its own `agents/` Python package with a narrow interface — no Django ORM imports inside that package. The `reviews` app calls into it and handles all persistence itself.

Build:
1. reviews app models: PullRequest, Review, ReviewFinding (agent, severity, file, line, message, citation) — per spec §4.
2. A minimal `agents/` package exposing one function, e.g. `run_review_pipeline(pr_diff: str, repo_context: RepoContext) -> ReviewResult` — for THIS phase, implement only a single synthesis-style agent (skip the other 5 from spec §5 for now): it takes the PR diff, calls Groq (primary) with Gemini as fallback, and returns findings as structured data. Build the multi-LLM failover (Groq -> Gemini, per spec §5 reliability layer) now, since it's needed from the start, not bolted on later.
3. Wire the webhook receiver from Phase 2 to enqueue a Celery task on PR opened/synchronize events, which runs the pipeline and stores a Review + its findings.
4. Post the review back to the actual GitHub PR as a comment via the GitHub API (using the connecting user's OAuth token or a bot token — pick whichever is simpler and document the choice).
5. GET /api/reviews/{id}/ endpoint; a bare-bones frontend page showing a review's findings list (no fancy diff UI yet — that's Phase 6).
6. Tests: pipeline runs against a fixture diff and returns findings; failover path triggers correctly when the primary provider errors (mock both providers in tests).
7. Update docs/PROGRESS.md — note explicitly that only 1 of 6 planned agents exists at this point, full pipeline is Phase 5.
8. Commit, merge to main with --no-ff, push.

Goal of this phase: prove PR opened -> pipeline runs -> comment appears on the real PR, end to end, before adding the other 5 agents.
```

---

## Phase 5 — Full 6-agent pipeline + RAG grounding

```
Read docs/PROJECT_SPEC.md (§5 full agent pipeline, §6 RAG/grounding design) and docs/PROGRESS.md before starting.

Phase 5: Full pipeline. Branch: phase-5-full-pipeline (from latest main).

Build, inside the existing agents/ package from Phase 4:
1. Rebuild the pipeline as a LangGraph graph with all 6 agents from spec §5: Diff/Intent, Static analysis (actually invoke ruff/eslint/bandit as tool calls, not LLM guesses), Security, Codebase-grounding (the RAG one), Test-coverage, Synthesis.
2. Codebase-grounding agent: hybrid retrieval per spec §6 — pgvector cosine similarity (dense) combined with Postgres full-text ts_rank (sparse), querying the CodeChunk table from Phase 3. Every finding this agent produces must carry a (file_path, line_range) citation pulled from the retrieved chunk metadata — enforce this in code, don't just prompt for it.
3. Synthesis agent merges and deduplicates findings from all agents, assigns severity (blocking vs. nit), before posting to GitHub.
4. Demo-mode fallback per spec §5: if both LLM providers are rate-limited/erroring, fall back to a cached/canned review so the pipeline never hard-fails visibly. Log clearly when this fallback fires (needed for Phase 6's status UI and for being honest about it in interviews).
5. Update ReviewFinding usage to store the citation and agent name per finding.
6. Tests: each agent function tested independently with fixtures; the graph runs end-to-end against a fixture PR and produces findings from multiple agents with citations; the demo-mode fallback path is tested explicitly.
7. Update docs/PROGRESS.md.
8. Commit, merge to main with --no-ff, push.
```

---

## Phase 6 — Realtime + enterprise UI polish

```
Read docs/PROJECT_SPEC.md (§9 frontend enterprise UI plan, §8 WebSocket endpoint) and docs/PROGRESS.md before starting.

Phase 6: Realtime + UI. Branch: phase-6-realtime-ui (from latest main).

Backend:
1. Django Channels consumer at /ws/reviews/{id}/ streaming pipeline progress ("reviewing... 3/6 agents complete") as each agent in Phase 5's graph finishes.
2. notifications app: Notification model + in-app notification center data (per spec §4).
3. analytics app: aggregation endpoints for the dashboard (PRs reviewed, avg findings/PR, avg review latency, findings-over-time trend) per spec §9.
4. audit app: AuditLogEntry model + GET /api/audit-log/, and hook it into the key actions from earlier phases (repo connected, role changed, finding dismissed) — retrofit logging calls into those existing endpoints.

Frontend (per spec §9 — load the dataviz skill/guidance before building the charts so they read as one coherent system, not default chart-library styling):
5. Persistent sidebar nav + org/workspace switcher.
6. Command palette (Cmd+K) for jumping to repos/PRs.
7. PR review view: diff pane + threaded findings pane per file/line, live status pill driven by the WebSocket from step 1.
8. Dashboard home: KPI row + trend chart from the analytics endpoints.
9. Audit log page: filterable table.
10. Dark mode.

Tests: Channels consumer sends expected progress events (can be a lightweight integration test); analytics endpoints return correct aggregates against fixture data.

Update docs/PROGRESS.md. Commit, merge to main with --no-ff, push.
```

---

## Phase 7 — Deploy + CI

```
Read docs/PROJECT_SPEC.md (§10 deployment checklist, §7 free-tier worker workaround) and docs/PROGRESS.md before starting.

Phase 7: Deploy + CI. Branch: phase-7-deploy (from latest main).

Do the account setup yourself first (Neon project with pgvector enabled, Upstash Redis claimed into your account, Groq key, Gemini key, GitHub OAuth App with production callback URL) per spec §10 — Claude Code can't create these accounts for you, but can help you get the connection strings wired in correctly.

Then have Claude Code:
1. Add production settings split (backend/core/settings/production.py or django-environ based config) reading all env vars from spec §10's .env.example list.
2. Write the Render start command implementing the co-located Celery+Daphne workaround from spec §7 exactly, and a render.yaml (or documented manual setup steps) for the Web Service.
3. Configure the Next.js app for Vercel deploy (NEXT_PUBLIC_API_URL env var pointing at the Render backend URL, CORS configured on the Django side to allow the Vercel domain).
4. Expand .github/workflows/ci.yml from Phase 0 into a real CI/CD pipeline: run the full backend + frontend test suites on every PR (reusing the pytest pattern from my EKIP project as a reference point), block merge on failure.
5. Write/finish the README: architecture diagram (reuse spec §3), setup instructions, and an explicit "Engineering tradeoffs" section documenting the free-tier worker co-location decision from spec §7 and the demo-mode fallback from spec §5 — these are talking points, so they should be visible in the repo, not just known to you.
6. Do a full deploy and smoke-test the real flow: connect a real repo, open a real PR, confirm a review comment appears.
7. Update docs/PROGRESS.md marking all phases complete, with the live URLs.
8. Commit, merge to main with --no-ff, push.
```

---

## After Phase 7

Once this is live, come back and I'll help you turn it into the resume bullets from spec §12, tuned to whatever actually shipped (some details always shift during a real build).
