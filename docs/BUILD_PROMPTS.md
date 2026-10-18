# CodeSage — Phase-by-Phase Build Prompts for Claude Code

How to use this file: each "Phase N Prompt" section is meant to be **copy-pasted as-is**
into Claude Code in VS Code, one at a time, in order. Claude Code in VS Code starts fresh
each session with no memory of this conversation — that's why every prompt tells it to read
the spec and progress files from the repo first, instead of relying on anything being
remembered.

---

## 0. One-time setup (already done)

1. GitHub repo created at `NivedhReddy2048/CodeSage`.
2. `docs/PROJECT_SPEC.md` committed — the single source of truth for architecture, so no
   phase prompt has to re-explain it.
3. Phase 0 scaffold landed as one squashed commit on `main` (see
   [PROGRESS.md](PROGRESS.md) for why).
4. `gh` CLI installed and authenticated — every phase below depends on it.

---

## Standard workflow every phase prompt follows

**This replaces the older "merge to main with `--no-ff`" instruction everywhere.** Each
prompt below already includes these steps, but here's the pattern so you know what to
expect.

### Per PR

1. **Create an issue** describing the work:
   `gh issue create --title "Phase 1a: backend auth models + OAuth endpoints" --body "..."`
2. **Branch** off latest `main`: `git checkout main && git pull && git checkout -b phase-1a-auth-backend`
3. **Build** that PR's scope only — not ahead, not behind.
4. **Verify it actually works** — tests pass, lint clean, plus whatever manual check the
   prompt describes. Do this *before* opening the PR, not after.
5. **Commit** with a conventional commit message (`feat(phase1a): ...`).
6. **Push and open the PR**, with the issue reference in the body:
   `gh pr create --title "..." --body "...\n\nCloses #<issue number>"`
7. **Wait for CI**: `gh pr checks <number> --watch`
8. **Merge once every check has passed**, with a real merge commit so each PR stays
   visible in `git log --graph`: `gh pr merge --merge --delete-branch`
9. **Sync**: `git checkout main && git pull`

### Rules that apply to every phase

**A. No AI attribution anywhere.** No `Co-Authored-By` trailers in commits. No "Generated
with Claude Code" or similar line in PR or issue descriptions. Every commit, issue and PR
must read as my own solo work.

**B. Split each phase into 2-3 focused PRs**, not one big one. Each PR gets **its own
issue**, and its body closes that issue with `Closes #N`. Branch names are
`phase-N<letter>-<slug>` (e.g. `phase-1a-auth-backend`). Every PR must contain real,
working, tested changes — never an empty or trivial PR just to raise the count. Each phase
prompt below suggests a split.

**C. Verify, then merge — never merge red.** Finish and verify all the work on the
branch *before* opening the PR. Then open it, wait for CI with
`gh pr checks <number> --watch`, and merge only once every check has passed.

`main` is protected: the **Backend (ruff + pytest)** and **Frontend (eslint + build)**
checks are required, and enforcement applies to admins, so a red PR cannot be merged
even deliberately.

This replaces the earlier "merge within a couple of minutes" rule. Quickdraw is
already earned, and speed bought nothing: three Phase 2 PRs were merged on green local
runs while CI was red the whole time, because nobody looked. Correctness now matters
more than the clock.

**D. Update `docs/PROGRESS.md`** in the phase's last PR: mark the phase done, note any
deviation from the spec, and bump the merged-PR count in the "GitHub achievements" section.

If a phase turns out too big for one sitting, that's fine — commit working increments on
the branch, and only open the PR once that PR's scope is genuinely done.

---

## Phase 1 — Auth

```
Read docs/PROJECT_SPEC.md (especially §4 accounts app, §8 API surface, §10 env vars) and docs/PROGRESS.md for current status before starting. Follow the "Standard workflow" section of docs/BUILD_PROMPTS.md — issue per PR, branch, verify, PR that closes its issue, gh pr merge --merge --delete-branch. No AI attribution in any commit, issue or PR.

Phase 1: Auth. Split into three PRs:
  - phase-1a-auth-backend  — accounts models + OAuth callback + JWT
  - phase-1b-auth-frontend — login page, callback handler, authenticated shell
  - phase-1c-auth-tests    — test suite + CI postgres service

Build:
1. accounts app models: User (extend Django's), Organization, Membership (role: owner/admin/member) — per spec §4.
2. GitHub OAuth App flow: backend endpoint(s) to start the OAuth redirect and handle the callback (POST /api/auth/github/callback/ per spec §8), exchanging the code for a GitHub access token, creating/matching the User, and issuing our own JWT (Simple JWT — access + refresh, matching the pattern from my other Django projects).
3. Org creation on first login (a user's first login creates a personal Organization with them as owner) and GET /api/orgs/ to list orgs the user belongs to.
4. Frontend: a login page that kicks off the GitHub OAuth redirect, a callback handler that stores the JWT, and a bare-bones authenticated shell page (just proves the token works — no real dashboard yet).
5. Add GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, JWT_SIGNING_KEY to .env.example (per spec §10) and README instructions for creating the GitHub OAuth App locally.
6. Write tests: at minimum, the OAuth callback creates a user + org, and JWT auth is enforced on a protected endpoint. Make these pass in CI — this is the phase where CI needs a postgres service container, since the first real models land here.
7. Update docs/PROGRESS.md.

This phase is the OAuth App only — user login. The GitHub App for the PR loop is Phase 2 (spec §13). Do not build repo connection or any pipeline logic yet.
```

---

## Phase 2 — Repo connection via GitHub App

```
Read docs/PROJECT_SPEC.md (§4 repos app, §8 API surface, and §13 "GitHub App — the PR loop" in full) and docs/PROGRESS.md before starting. Follow the "Standard workflow" section of docs/BUILD_PROMPTS.md. No AI attribution in any commit, issue or PR.

Phase 2: Repo connection. Split into three PRs:
  - phase-2a-github-app    — App auth (JWT -> installation token), AppInstallation model
  - phase-2b-webhook       — signed webhook receiver, 202 fast path, ack comment
  - phase-2c-repos-ui      — connect-a-repo page + connected repos list

Important: this phase uses a GITHUB APP, not the user's OAuth token, for everything that touches a repo. The OAuth App from Phase 1 stays as-is for user login. Read spec §13 before writing code — it specifies the two identities, the permissions, the token chain and the 10-second rule.

Build:
1. repos app models: AppInstallation (installation_id, account_login), Repository, WebhookEvent (per spec §4).
2. GitHub App authentication: sign an RS256 JWT from GITHUB_APP_ID + GITHUB_APP_PRIVATE_KEY (10 min max lifetime), exchange it for an installation access token (1 hr), and cache that token until shortly before expiry rather than minting one per call. Add GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY and GITHUB_WEBHOOK_SECRET to .env.example. The private key is a multi-line PEM — store it escaped in the env var and unescape on read.
3. POST /api/repos/connect/ — connect a repo the App installation can see, storing the Repository scoped to the user's Organization. Webhooks come from the App subscription (pull_request events), so there is no per-repo webhook registration call to make.
4. POST /api/webhooks/github/ — the receiver, with a hard 10-second budget. It must: verify the X-Hub-Signature-256 HMAC against GITHUB_WEBHOOK_SECRET using a constant-time compare (401 on mismatch); store a WebhookEvent row including the raw payload; enqueue a Celery task keyed on the delivery id so redelivery is idempotent; and return 202 immediately. Never run review work inline in this handler.
5. On a verified pull_request opened/synchronize event, the enqueued task posts an acknowledgement comment on the PR as codesage[bot]: "CodeSage is reviewing this PR...". Store the returned comment id on the record so Phase 5 can edit that same comment into the final review instead of adding a second one. Post this from the task, not the request handler.
6. Frontend: a "Connect a repo" page listing repos visible to the App installation, let the user pick one to connect, and show connected repos in a simple list/table. If the App is not yet installed, show the install link instead.
7. Tests: webhook signature verification (valid + tampered payload), the handler returns 202 without running pipeline work, redelivery of the same delivery id does not double-enqueue, and repo connect creates the right records scoped to the right org. Mock the GitHub API — don't hit it in CI.
8. Update docs/PROGRESS.md.

No review pipeline yet — that's Phase 4. This phase ends with: open a PR on a repo where the App is installed, and an acknowledgement comment from codesage[bot] appears on it.
```

---

## Phase 3 — Ingestion

```
Read docs/PROJECT_SPEC.md (§4 ingestion app, §6 RAG/grounding design, §10 embeddings choice) and docs/PROGRESS.md before starting. Follow the "Standard workflow" section of docs/BUILD_PROMPTS.md. No AI attribution in any commit, issue or PR.

Phase 3: Ingestion. Split into two PRs:
  - phase-3a-chunk-embed   — models, AST chunking, Gemini embeddings, Celery task
  - phase-3b-ingest-status — job status endpoint + indexing UI

Build:
1. ingestion app models: CodeChunk (file_path, symbol, content, embedding vector column via pgvector, repo FK), IngestionJob (status: pending/running/done/failed).
2. A Celery task that, given a connected Repository: fetches its default branch using the GitHub App installation token from Phase 2, walks the source files, chunks them AST-aware by function/class (per spec §6 — not naive fixed-size splitting), calls the Gemini free embedding endpoint for each chunk, and bulk-stores CodeChunk rows with their vectors.
3. Trigger ingestion automatically right after a repo is connected (Phase 2's connect endpoint enqueues this task), with an IngestionJob record whose status the frontend can poll.
4. GET endpoint for ingestion job status; frontend shows "Indexing repo... X/Y files" (polling is fine here — Channels live updates come in Phase 6).
5. For local dev, run Celery via the co-located approach from spec §7 (document the exact start command in README) so it matches how it'll run on Render later — don't build a separate worker process assumption now that we'll have to undo.
6. Add GEMINI_API_KEY to .env.example.
7. Tests: chunking produces sensible boundaries on a small fixture file; embedding + storage round-trips correctly (mock the Gemini call in tests — don't burn real API quota in CI).
8. Update docs/PROGRESS.md.
```

---

## Phase 4 — Agent pipeline v1 (single agent, prove the full loop)

```
Read docs/PROJECT_SPEC.md (§4 reviews/agents apps, §5 agent pipeline, §13 GitHub App, §14 cost and latency accounting) and docs/PROGRESS.md before starting. Follow the "Standard workflow" section of docs/BUILD_PROMPTS.md. No AI attribution in any commit, issue or PR.

Phase 4: Agent pipeline v1. Split into three PRs:
  - phase-4a-reviews-models  — reviews models incl. per-call cost/latency records
  - phase-4b-pipeline-v1     — agents package, single agent, Groq->Gemini failover
  - phase-4c-pr-comment      — webhook -> pipeline wiring, edit ack comment, review API + page

Important architecture note (already decided, don't relitigate it): the agent pipeline runs IN-PROCESS inside Django, but lives in its own `agents/` Python package with a narrow interface — no Django ORM imports inside that package. The `reviews` app calls into it and handles all persistence itself.

Build:
1. reviews app models: PullRequest, Review, ReviewFinding (agent, severity, file, line, message, citation) — per spec §4. Plus the cost/latency records from spec §14: one row per LLM call (agent, provider, model, input tokens, output tokens, latency ms, and whether it was primary / failover / demo-mode), with totals denormalised onto Review (total_input_tokens, total_output_tokens, duration_ms, estimated_cost_usd, estimated_cost_inr).
2. Add the LLM_PRICING table, USD_TO_INR and USD_TO_INR_AS_OF to settings exactly as spec §14 specifies, keeping the source-and-date comments. Note the spec's warning that the Groq figure needs re-verifying at console.groq.com — do that and correct the table if it differs.
3. A minimal `agents/` package exposing one function, e.g. `run_review_pipeline(pr_diff: str, repo_context: RepoContext) -> ReviewResult` — for THIS phase, implement only a single synthesis-style agent (skip the other 5 from spec §5 for now): it takes the PR diff, calls Groq (primary) with Gemini as fallback, and returns findings as structured data plus the per-call token/latency telemetry. Build the multi-LLM failover (Groq -> Gemini, per spec §5 reliability layer) now, since it's needed from the start, not bolted on later.
4. Wire the Phase 2 webhook task to run the pipeline and store a Review + its findings + its cost/latency rows.
5. Post the review back to the real GitHub PR as codesage[bot] via the GitHub App — by EDITING the acknowledgement comment from Phase 2, not adding a second comment. Include the spec §14 footer, labelled as an estimate at paid rates: "Reviewed in 38 s · est. ₹2.10 at paid-tier rates".
6. GET /api/reviews/{id}/ endpoint returning findings plus cost/latency; a bare-bones frontend page showing a review's findings list (no fancy diff UI yet — that's Phase 6).
7. Tests: pipeline runs against a fixture diff and returns findings; failover path triggers correctly when the primary provider errors (mock both providers); cost computation produces the expected INR figure for a known token count.
8. Update docs/PROGRESS.md — note explicitly that only 1 of 6 planned agents exists at this point, full pipeline is Phase 5.

Goal of this phase: prove PR opened -> pipeline runs -> the bot's acknowledgement comment becomes a real review with a cost/time footer, end to end, before adding the other 5 agents.
```

---

## Phase 5 — Full 6-agent pipeline + RAG grounding

```
Read docs/PROJECT_SPEC.md (§5 full agent pipeline, §6 RAG/grounding design, §14 cost and latency accounting) and docs/PROGRESS.md before starting. Follow the "Standard workflow" section of docs/BUILD_PROMPTS.md. No AI attribution in any commit, issue or PR.

Phase 5: Full pipeline. Split into three PRs:
  - phase-5a-langgraph-agents  — LangGraph graph, Diff/Intent, Static analysis, Security, Test-coverage
  - phase-5b-rag-grounding     — hybrid retrieval + enforced citations
  - phase-5c-synthesis-fallback — synthesis/dedup/severity, demo-mode fallback, PR comment footer

Build, inside the existing agents/ package from Phase 4:
1. Rebuild the pipeline as a LangGraph graph with all 6 agents from spec §5: Diff/Intent, Static analysis (actually invoke ruff/eslint/bandit as tool calls, not LLM guesses), Security, Codebase-grounding (the RAG one), Test-coverage, Synthesis.
2. Codebase-grounding agent: hybrid retrieval per spec §6 — pgvector cosine similarity (dense) combined with Postgres full-text ts_rank (sparse), querying the CodeChunk table from Phase 3. Every finding this agent produces must carry a (file_path, line_range) citation pulled from the retrieved chunk metadata — enforce this in code, don't just prompt for it.
3. Synthesis agent merges and deduplicates findings from all agents, assigns severity (blocking vs. nit), and posts the final review by editing the bot's existing PR comment. The comment footer carries the spec §14 cost/latency line, labelled as an estimate at paid rates.
4. Demo-mode fallback per spec §5: if both LLM providers are rate-limited/erroring, fall back to a cached/canned review so the pipeline never hard-fails visibly. Log clearly when this fallback fires, and record it on the per-call rows from §14 (needed for Phase 6's status UI and for being honest about it in interviews).
5. Update ReviewFinding usage to store the citation and agent name per finding. Keep recording per-agent token/latency/cost telemetry for every agent in the graph, not just the synthesis one.
6. Tests: each agent function tested independently with fixtures; the graph runs end-to-end against a fixture PR and produces findings from multiple agents with citations; the demo-mode fallback path is tested explicitly; per-agent cost telemetry is recorded for a full graph run.
7. Update docs/PROGRESS.md.

Once this phase is merged, Phase 8's evaluation harness can be built at any time — it only depends on the full pipeline existing.
```

---

## Phase 6 — Realtime + enterprise UI polish

```
Read docs/PROJECT_SPEC.md (§9 frontend enterprise UI plan, §8 WebSocket endpoint, §14 cost and latency accounting) and docs/PROGRESS.md before starting. Follow the "Standard workflow" section of docs/BUILD_PROMPTS.md. No AI attribution in any commit, issue or PR.

Phase 6: Realtime + UI. Split into three PRs:
  - phase-6a-realtime      — Channels consumer, notifications app
  - phase-6b-analytics-audit — analytics aggregations + audit log, backend and pages
  - phase-6c-ui-shell      — sidebar/org switcher, command palette, PR review view, dark mode

Backend:
1. Django Channels consumer at /ws/reviews/{id}/ streaming pipeline progress ("reviewing... 3/6 agents complete") as each agent in Phase 5's graph finishes.
2. notifications app: Notification model + in-app notification center data (per spec §4).
3. analytics app: aggregation endpoints for the dashboard (PRs reviewed, avg findings/PR, avg review latency, and the avg estimated cost per review from spec §14, plus the findings-over-time trend) per spec §9.
4. audit app: AuditLogEntry model + GET /api/audit-log/, and hook it into the key actions from earlier phases (repo connected, role changed, finding dismissed) — retrofit logging calls into those existing endpoints.

Frontend (per spec §9 — load the dataviz skill/guidance before building the charts so they read as one coherent system, not default chart-library styling):
5. Persistent sidebar nav + org/workspace switcher.
6. Command palette (Cmd+K) for jumping to repos/PRs.
7. PR review view: diff pane + threaded findings pane per file/line, live status pill driven by the WebSocket from step 1, and the review's time + estimated cost displayed per spec §14 (always labelled as an estimate at paid rates).
8. Dashboard home: KPI row (including avg review time and avg estimated cost) + trend chart from the analytics endpoints.
9. Audit log page: filterable table.
10. Dark mode.

Tests: Channels consumer sends expected progress events (can be a lightweight integration test); analytics endpoints return correct aggregates against fixture data, including the cost and latency averages.

Update docs/PROGRESS.md.
```

---

## Phase 7 — Deploy + CI

```
Read docs/PROJECT_SPEC.md (§10 deployment checklist, §7 free-tier worker workaround, §15 Render cold start vs. GitHub's webhook timeout, §17 demo and launch) and docs/PROGRESS.md before starting. Follow the "Standard workflow" section of docs/BUILD_PROMPTS.md. No AI attribution in any commit, issue or PR.

Phase 7: Deploy + CI. Split into three PRs:
  - phase-7a-prod-config  — production settings, render.yaml, CORS, Vercel config
  - phase-7b-ci-keepwarm  — full CI pipeline + the scheduled keep-warm workflow
  - phase-7c-readme       — README with architecture diagram and engineering tradeoffs

Do the account setup yourself first (Neon project with pgvector enabled, Upstash Redis claimed into your account, Groq key, Gemini key, GitHub OAuth App with production callback URL, and the GitHub App from spec §13 with its production webhook URL) per spec §10 — Claude Code can't create these accounts for you, but can help you get the connection strings wired in correctly.

Then have Claude Code:
1. Add production configuration reading all env vars from spec §10's .env.example list (django-environ based, per the note in docs/PROGRESS.md — settings are already a single env-driven module, so this is configuration, not a refactor).
2. Write the Render start command implementing the co-located Celery+Daphne workaround from spec §7 exactly, and a render.yaml (or documented manual setup steps) for the Web Service.
3. Configure the Next.js app for Vercel deploy (NEXT_PUBLIC_API_URL env var pointing at the Render backend URL, CORS configured on the Django side to allow the Vercel domain).
4. Expand .github/workflows/ci.yml from Phase 0 into a real CI/CD pipeline: run the full backend + frontend test suites on every PR, block merge on failure.
5. Add the keep-warm workflow from spec §15: a scheduled GitHub Actions job curling /api/health/ every 10 minutes, so a webhook never arrives at a sleeping dyno. Document it in the README's "Engineering tradeoffs" section including the free-hours arithmetic (about 744 of Render's 750 monthly hours) and the known limits (GitHub's cron is best-effort; scheduled workflows are disabled on repos idle for 60 days).
6. Write/finish the README: architecture diagram (reuse spec §3), setup instructions, and an explicit "Engineering tradeoffs" section documenting the free-tier worker co-location decision from spec §7, the keep-warm ping from §15, the demo-mode fallback from §5, and the estimated-cost labelling from §14 — these are talking points, so they should be visible in the repo, not just known to you.
7. Smoke-test the real flow on a FORK of a real open-source repository, per spec §17: fork it, install the GitHub App on the fork, open a test PR on the fork, and confirm a codesage[bot] review comment appears with its cost/time footer. Never open test PRs against an upstream project — bot comments would reach real maintainers.
8. Update docs/PROGRESS.md marking phases 0-7 complete, with the live URLs.
```

---

## Phase 8 — Evaluation

```
Read docs/PROJECT_SPEC.md (§16 Phase 8 evaluation harness, §14 cost and latency accounting) and docs/PROGRESS.md before starting. Follow the "Standard workflow" section of docs/BUILD_PROMPTS.md. No AI attribution in any commit, issue or PR.

Phase 8: Evaluation. This only depends on Phase 5's full pipeline, so it can be built any time after that — it does not need Phase 7's deploy. Split into three PRs:
  - phase-8a-fixtures   — fixture repos, planted bugs, ground-truth files
  - phase-8b-run-eval   — the run_eval command, both arms, matching and caching
  - phase-8c-results    — eval/results.md, README results table, limitations

Build:
1. 3-5 small fixture repos under eval/fixtures/, a mix of Python and JavaScript, each with a set of PRs. Most PRs plant 1-2 known bugs drawn from: off-by-one, missing null check, SQL injection, missing await, wrong permission check, resource leak. AT LEAST 30% of PRs must be clean — no planted bug at all — so the harness measures false alarms and not just recall.
2. A ground-truth file per PR recording each planted bug as (file, line_range, category).
3. `python manage.py run_eval` running every fixture PR through two arms:
   (a) the full CodeSage pipeline, and
   (b) a baseline single-prompt LLM review with no RAG and no agents, using the same primary model as the pipeline so the comparison isolates the architecture rather than the model.
4. Matching rule: a finding counts as catching a planted bug when it is in the same file, within ±3 lines of the ground-truth range, and of a matching category. Implement this as one tested function — it is the number everything else depends on.
5. Report, for BOTH arms: detection rate (bugs caught / bugs planted), false alarms per PR, precision, average wall-clock time per review, and average estimated cost per review (reuse the spec §14 cost machinery, same "estimate at paid rates" labelling). Write eval/results.md and add the summary table to the README.
6. A "Limitations" section in eval/results.md and the README, stating plainly: small sample so small differences are noise; bugs are self-planted by the same person who built the reviewer, so not an independent benchmark; free-tier model rather than a frontier one; the ±3 line and category matching are judgement calls; single run per PR so LLM variance is unmeasured.
7. Quota discipline: Groq's free tier is 1,000 requests/day and two arms multiply fast. Cache results on disk keyed by fixture PR, arm and pipeline version, so reruns re-read the cache instead of spending quota, and only changed fixtures re-run. Estimate the total call count before the first full run and report it.
8. Tests: the matching function (hit, near-miss outside ±3, wrong category, clean PR); metric arithmetic against a hand-computed fixture; the cache prevents a second LLM call on rerun.
9. Update docs/PROGRESS.md marking Phase 8 complete.
```

---

## After Phase 8 — my checklist

Not Claude Code's work, mine:

- [ ] Record a **2-minute demo video**: connect a repo, open a PR on the fork, the review
      comment appears, live status pill visible.
- [ ] Put the **live link**, the **demo video** and the **evaluation results table** at the
      very top of the README, above the architecture section.
- [ ] Come back and turn this into the resume bullets from spec §12, tuned to whatever
      actually shipped (some details always shift during a real build) — now with real
      measured numbers from Phase 8 instead of adjectives.
