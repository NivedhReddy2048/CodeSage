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
| 3 | Ingestion | `phase-3a` engine, `3b` Celery+API, `3c` UI | **Done** |
| 4 | Agent pipeline v1 | `phase-4a` agents pkg, `4b` reviews app, `4c` push+page | **Done** |
| 5 | Full 6-agent pipeline | `phase-5a` retrieval, `5b` graph, `5c` wiring; hardening `5d` honest output, `5e` grounding + inline | **Done** |
| 6 | Realtime + enterprise UI | `phase-6a` realtime + data, `6b` shell + design system, `6c` review experience, `6d` dashboard + notifications + audit | **In progress** (6a, 6b done) |
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
| **Pull Shark** | Base badge at 2 merged PRs (already earned before this project); next tier **bronze at 16** | **29 merged — bronze (16) reached** |
| **YOLO** | Merge a PR without a review | Earned by this workflow — PRs are self-merged |
| **Quickdraw** | Close an issue or PR within 5 minutes of opening | Targeted by the fast-merge rule |
| **Pair Extraordinaire** | Co-authored commits with a real collaborator | **Needs a real human collaborator — optional** |
| **Starstruck** | 16 stars on a repository | After launch |

**Pair Extraordinaire note.** This one needs `Co-Authored-By` trailers naming a *real*
collaborator, so it is optional rather than part of the plan. An AI co-author trailer must
not be used to earn it: that contradicts the no-AI-attribution rule and, when it was tried
once, listed "claude" as a repository contributor.

**Update the merged-PR count in this table in each phase's last PR.** The figure
counts merged PRs *including* the one making the edit, so it is correct the moment that
PR lands rather than one behind forever.

---

## Phase 6 — Realtime and enterprise UI

**Status:** In progress. Four PRs: 6a backend realtime and data (done), 6b app shell
and design system (done), 6c review experience, 6d dashboard, notifications and audit pages.

### 6b — app shell, design system, frontend tests

**Shell.** Every signed-in page sits in an `(app)` route group whose layout renders
the shell, which also owns the auth guard the pages used to repeat. It has:

- a persistent sidebar (Dashboard, Repositories, Reviews, Audit log, Settings), which
  collapses to icons on desktop and becomes a sheet on a phone;
- an organisation switcher, which sends `X-Organization-Id` and remounts the page on
  a switch so its data reloads;
- a user menu, a light/dark/system theme toggle (next-themes, system by default, no
  flash), and a Ctrl/Cmd+K command palette for pages, repositories, recent reviews and
  actions.

Settings has member role management (owner only) and appearance. Reviews and Audit log
pages exist in basic form; 6c and 6d build them out.

**Design system** on shadcn/ui (Base UI flavour):
- status badges for blocking, nit, degraded, fallback, ok, running, pending, failed
  and skipped. Each has an icon and a word, so status never rests on colour alone;
- `PageHeader`, and `EmptyState`, `ErrorState` (with retry) and labelled skeletons,
  used on every page;
- a `useResource` hook so loading, error and retry behave identically everywhere.

**Accessibility, measured rather than assumed:**
- **Contrast.** Badge colours were picked with an OKLCH-to-WCAG contrast script; every
  badge's text is at least 5.5:1 against both its badge and the card, in both themes.
- **Focus.** The default focus ring grey was ~2.3:1 on white, under the 3:1 WCAG asks
  of a focus indicator, so focus uses its own token: 6.1:1 light, 9.9:1 dark.
- **Navigation.** A skip link, `aria-current` on the active page, a labelled palette
  dialog, and a spinner that respects reduced motion.

**Tests.** Vitest + Testing Library on jsdom, added to the existing CI frontend job so
the required check covers them: 49 tests across badges, states, navigation, the org
switcher, the palette, settings roles, the audit 403 state, indexing errors, the API
client and `useResource`. `@vitejs/plugin-react` was left out: its Babel 8 peer
conflicts with the Babel 7 Next pins, and Vite's own JSX transform is enough.
`@types/node` moved to `^24` to match the Node 24 runtime, which Vitest 5 requires.

**Raw errors in the UI.** The indexing status printed `job.error` to everyone, and that
text can be a raw Gemini response. The ingestion API now sends `error_summary` to all
and `error` only to owners and admins, and the UI shows the details behind a toggle
for them only. The same rule applies to review errors.

**Found by the tests:** the generated command dialog renders without a cmdk root in
this shadcn version, so the palette crashed the moment it opened; and its title sat
outside the dialog popup, which left the dialog with no accessible name.

**Found only in a real browser** (Edge driven by playwright-core, screenshots in both
themes and at phone width):
- **Users were signed out on every other page load.** The new `X-Organization-Id`
  header is not CORS-safelisted, the backend did not allow it, and the failed
  preflight surfaced as a network error, which the auth provider treated as an
  expired session and cleared the tokens. Two fixes, each with a test: the header is
  in `CORS_ALLOW_HEADERS`, and only a 401 now ends a session. An unreachable API keeps
  the session and shows a retry.
- **Outline-style links rendered with no border.** `buttonVariants()` returned
  unmerged classes, in which `border-transparent` beat the variant's border colour.
  It now merges like `<Button>` does.
- **A wide table widened the whole page on a phone.** It was 73 px too wide, which
  pushed the theme toggle off-screen. `min-w-0` on the main column fixed it.

### 6a — realtime, notifications, analytics, audit, re-run

**Live progress socket, `/ws/reviews/{id}/`.** The pipeline gained an injected
`on_progress(agent, state, status)` callback (the agents package stays Django-free);
each of the five analysis agents reports `started` and `finished` with
`ok`/`failed`/`skipped`. The review service turns that into a `review.progress` event
on the Redis channel layer and writes the same state to `Review.progress`. The socket
sends a `review.snapshot` first, then progress events, then `review.finished`.
`GET /api/reviews/{id}/status/` returns the same snapshot as the poll fallback.

Verified live across processes: a review run from a separate process streamed to a
socket on the running server, with diff_intent running alone, the four analysis
agents fanning out, the count rising 1/5 → 5/5, then `review.finished`.

- **The JWT goes in the first message, not the URL.** A browser WebSocket cannot set
  `Authorization`, and a token in the query string ends up in access logs. Bad or
  expired token, or no auth within 10 s: close `4401`. A review outside every
  organisation the user belongs to: close `4404`, the same as a missing one, so the
  socket cannot probe for other tenants' ids. The socket joins the review's group only
  after both checks, so a user can never receive another organisation's events.
- **Origin is checked.** `AllowedHostsOriginValidator` refuses a handshake from a
  foreign origin (verified: `evil.example` refused, `localhost:3000` accepted). This is
  the cross-site WebSocket hijacking guard. It also refuses a handshake with no Origin,
  which is why a Node or CLI client must send one.
- **Counts five agents, not six.** Spec §9 writes "3/6 agents complete"; synthesis is
  the deterministic merge step after the five, not an agent that can be pending.

**Found live, not by the tests:** the finished event and the status endpoint reported
0/5 after every review. The service's final full `review.save()` wrote its stale
in-memory `progress` over the reporter's updates. The reporter now keeps that object in
step, and a regression test (confirmed to fail without the fix) covers it.

**Also fixed:** a review that crashed mid-run stayed `running` forever (seen in 5e).
`review_pull_request` now always ends the review `failed` with the error recorded, then
announces it and notifies.

**Workspace selection.** `X-Organization-Id`, read at authentication and honoured by
`current_organization()` only if the caller is a member, so every existing org-scoped
endpoint follows the switcher with no per-view changes. Naming another tenant's id
falls back to the caller's own organisation. Writing the tests exposed an ambiguity:
the fallback took "a personal organisation", and once a user joins someone else's
personal organisation there are two. It now takes the one the user owns.

**New endpoints**, all org-scoped and each covered by a cross-org test:

| Endpoint | Who | Notes |
|---|---|---|
| `GET /api/reviews/` | members | Paginated; filter `repository`, `status` (incl. `degraded`), `severity` |
| `GET /api/reviews/{id}/status/` | members | Poll fallback; same shape as the socket snapshot |
| `POST /api/reviews/{id}/rerun/` | owner/admin | 202 with the new pending review id; 409 while one runs (a run older than 15 min counts as dead); audit-logged |
| `GET /api/notifications/`, `POST .../{id}/read/`, `POST .../read-all/` | members | Per-recipient, per-organisation |
| `GET /api/analytics/overview/` | members | KPIs, zero-filled daily series, by category, by agent; `?days=`, `?repository=` |
| `GET /api/repos/{id}/findings/analytics/` | members | Spec §8 path: the same view narrowed to one repository |
| `GET /api/audit-log/` | owner/admin | Paginated; filter `action`, `actor`, `q`, `since`, `until` |
| `GET /api/orgs/members/`, `PATCH /api/orgs/members/{id}/` | members / owner | Role changes; the last owner cannot be demoted; audit-logged |

- **Raw errors only for owners and admins.** Review, call and agent-run payloads carry
  `error_summary` (the same short public reason the PR comment uses) for everyone;
  `error` is blank unless the caller is owner or admin.
- **Audit log is append-only in code**: `save()` refuses an existing row, `delete()`
  refuses, the queryset blocks bulk update and delete, and the admin is read-only.
  Retrofitted into connect, disconnect, re-index, re-run (API and
  `manage.py rerun_review`) and role changes. A failed audit write is logged and never
  fails the action.
- **Notifications** fan out per member, so read state is personal: review finished,
  review degraded, review failed, indexing failed.
- **Analytics definitions** live in one module: findings per PR use each PR's latest
  completed review, so re-runs do not double-count; latency is over completed reviews
  only, so a fast failure cannot look like speed; cost covers every review and carries
  a `cost_basis` label saying it is an estimate at paid-tier rates.

**After merging: restart the Celery worker.** The task gained an optional `review_id`
argument; a worker still running the old code fails on API-triggered re-runs.

---

## Phase 5 hardening — honest review output

**Status:** Done. Run before Phase 6, in two PRs (5d, 5e).

Several things the review comment said were not true. Each was found by reading a
real comment against the database, not by the tests, which all passed.

### 5d — what ran, what served it, and what the public sees

- **Static analysis claimed tools that never ran** ([#50](https://github.com/NivedhReddy2048/CodeSage/issues/50)).
  bandit was installed nowhere and ruff only in `requirements-dev.txt`, which Render
  does not install, yet every comment said `ruff+bandit+pattern-scan`. Both are now
  runtime requirements, invoked as `python -m <tool>` from the running interpreter
  (a worker without its venv on `PATH` still finds them), and the agent reports what
  *actually* ran: `ran ruff, bandit`, or `skipped: bandit (not installed)`. A tool
  that times out or prints no parseable report counts as not having run. If nothing
  ran, the row says *skipped* with the reason rather than "ok, 0 findings". A test
  fails if a tool static analysis invokes is missing from `requirements.txt`, and
  another runs both linters for real with no mocks.
- **The Agents table named the model that was asked for, not the one that answered**
  ([#51](https://github.com/NivedhReddy2048/CodeSage/issues/51)). Providers now
  report the serving model; `AgentRun`/`AgentRunRecord` keep it in `model` (what cost
  and analytics use) and the original in a new `requested_model`. A row reads
  `` `gemini-flash-lite-latest` via gemini (fallback for `openai/gpt-oss-20b`) ``.
- **A failed agent rendered as ok.** Rows are now keyed on `succeeded`; anything not
  succeeded and not skipped is `failed`, with or without an error string.
- **Public comments carried raw provider errors** — HTTP bodies with quota figures
  and organisation ids. The comment now gets a short reason (`AI providers
  unavailable`, `The AI response was not in the expected format`, ...); the full
  error is logged and stored on the Review, which the review page shows.
- **The Gemini fallback was held to the wrong schema.** It already used native JSON
  mode, but with the *findings* schema for every agent, so the intent classifier
  could not return `{intent, summary}` (the "5 output tokens, failed" diff_intent in
  #51) and the grounding agent could not emit `cited_file`/`cited_line`, so every
  grounded finding failed its citation check. Each agent now passes its own schema;
  one generic converter produces Gemini's dialect.

**Fallback re-run, live** (testbed PR #1, Groq key deliberately invalid, nothing
posted). All five agents succeed on Gemini; before the fix diff_intent failed and
grounding could produce nothing:

```
| Diff/Intent        | ok | 0 findings · `gemini-flash-lite-latest` via gemini (fallback for `openai/gpt-oss-20b`) |
| Codebase grounding | ok | 1 finding · `gemini-flash-lite-latest` via gemini (fallback for `openai/gpt-oss-20b`) |
| Security           | ok | 1 finding · `gemini-flash-lite-latest` via gemini (fallback for `openai/gpt-oss-120b`) |
| Static analysis    | ok | 1 finding · ran ruff, bandit |
| Test coverage      | ok | 0 findings · `gemini-flash-lite-latest` via gemini (fallback for `openai/gpt-oss-20b`) |
```

diff_intent returned 32 output tokens and a valid intent, against 5 tokens and a
failure before.

### 5e — verified citations, inline comments, operator commands

- **A citation must support the claim, not just exist.** The old check only asked
  whether the cited line was inside a retrieved chunk. Retrieval returns lookalikes:
  for "function that looks up a user by id", hybrid rank 1 is `web/users.js
  findUserById`, and a model reviewing Python will cite it. Now the cited chunk must be
  in the same language family as the changed file (JS and TS count as one), and must
  contain a symbol the message names, as a whole identifier. Cross-language or
  symbol-absent citations are dropped; a message that names no symbol at all is kept
  but downgraded to a nit, since nothing can be checked. The grounding prompt now
  requires the existing symbol in backticks. Tested, including the JS-lookalike-cited-
  for-a-Python-function case. The verified citation is stored in
  `ReviewFinding.citation`, which was previously always blank.
- **Inline review comments on diff lines — new; they did not exist before.** Each
  finding is posted as one PR review (`event: COMMENT`, never approve or block) on its
  `path`/`line`, `side: RIGHT`, at the reviewed head SHA, capped at
  `REVIEW_MAX_INLINE_COMMENTS` (15), blocking first. If GitHub rejects the batch (422,
  usually a line outside the diff), comments are retried one at a time so the rest
  land. **Deduplicated:** each comment carries a hidden marker, and a finding is skipped
  when a live CodeSage comment already sits on the same file within ±2 lines — the
  same window synthesis uses to call two findings one defect. Exact-line dedupe was
  the first version and failed live: a rerun anchored the same PR #1 defect at line 1
  instead of 3 and posted a second comment. GitHub nulls `line` on an outdated
  comment, so a comment whose code has since changed does not block a fresh one.
  Inline posting never fails a review.
- **`manage.py rerun_review <repo> <pr_number>`** — refreshes the head from GitHub and
  runs the review synchronously, bypassing webhook delivery-id dedupe on purpose.
- **`manage.py retrieval_probe "<query>"`** — vector-only next to hybrid, with each
  hit's rank in both retrievers. Both are documented in the README.

**Testbed reruns, live** (`rerun_review`, all on Groq):

| PR | Findings | Inline comments |
|---|---|---|
| #1 | 1 blocking | `test.py:3` |
| #2 | 3 (2 blocking) | `web/orders.js:4`, `:7`, `:13` |
| #3 | 2 (1 blocking) | `app/lookup.py:17`, `app/lookup.py:4` (grounded in Python `app/users.py`, not the JS lookalike) |

Rerunning PR #1 three more times anchored its findings at lines 1, 4 and 1; each run
reported them as already on the diff and posted nothing. Static analysis reported
`ran ruff, bandit` on the Python PRs and `ran pattern-scan` on the JavaScript one.

### Groq quota math

Per review: **4 LLM calls** — `gpt-oss-120b` once (Security) and `gpt-oss-20b` three
times (Diff/Intent, Grounding, Test coverage; Grounding only when retrieval returns
something) — plus one Gemini embedding call for the retrieval query. Static analysis
and synthesis make none. A 429 or 5xx can add up to two provider retries per call.

Measured over six real reviews of testbed PRs #1-#3: **120b ≈ 890 tokens/review**
(616 in + 270 out), **20b ≈ 4,170 tokens/review** (2,423 in + 1,746 out, about 1,390
per call).

Limits: live `x-ratelimit-*` headers on this key report **1,000 requests/day and 8,000
tokens/minute for each model**. Groq's rate-limits table lists both models at **30
RPM, 1K RPD, 8K TPM, 200K TPD**; the extracted table does not say which plan it is
for, but the RPD and TPM figures match the live headers. TPD is not exposed in the
headers, so 200K is the documented figure, not a measured one. The headers also
showed the two models' remaining requests (990 vs 972) and tokens counting down
independently, so **the buckets are per model, not shared** — correcting the Phase 5
note below.

| Model | Binding limit | Reviews/day |
|---|---|---|
| `gpt-oss-20b` | 200K TPD / 4,170 | **~48** |
| `gpt-oss-20b` | 1,000 RPD / 3 | 333 |
| `gpt-oss-120b` | 200K TPD / 890 | 225 |
| `gpt-oss-120b` | 1,000 RPD / 1 | 1,000 |

**Estimated capacity: about 48 full reviews a day**, bounded by `gpt-oss-20b`'s daily
tokens. Per minute, 20b's 8K TPM allows one review at a time (two only if their calls
do not overlap), and RPM is never binding at 4 calls. Past 48, the breaker opens on
Groq's 429 and agents fail over to Gemini, so the review still runs, served and
labelled as Gemini. Moving one 20b agent onto 120b would roughly double headroom,
because 120b's daily budget is mostly unused. Eval runs (Phase 8) must budget against
the 48/day figure, not the 1,000 RPD figure.

### Known limitations

- **Citation checking is lexical.** A message naming a common identifier that
  happens to appear in the cited chunk (`user_id`) passes. It catches the lookalike
  and wrong-chunk cases, not every unsupported claim.
- **Inline dedupe is positional.** Two genuinely different defects within ±2 lines
  of each other get one inline comment. That is the same trade synthesis already makes.
- **Findings vary run to run.** Reruns of an unchanged commit reworded and re-anchored
  findings (PR #1: off-by-one at line 3, then untested `get_user` at line 1). Single
  runs, so variance is unmeasured until Phase 8.
- **A crash between creating a Review and storing results leaves it `running`.** Seen
  when migration 0004 had not yet been applied to the dev database; three rows were
  closed by hand. A sweeper, or creating the row in the same transaction, would fix it.
- **The running Celery worker does not reload code.** After this pass, restart it
  (or use `rerun_review`) before relying on webhook-triggered reviews.

---

## Phase 5 — Full pipeline and hybrid retrieval

**Status:** Done.

```
START -> diff_intent -> [ static_analysis | security | grounding | test_coverage ] -> synthesis -> END
```

### Retrieval, measured before and after

The phase 3 query *"function that looks up a user by id"*, against the real indexed
testbed:

| | Rank 1 | Rank 2 | Rank 3 |
|---|---|---|---|
| **Vector only** | `app/users.py` module docstring | `web/users.js findUserById` | `web/users.js fetchUser` |
| **Hybrid RRF** | `web/users.js findUserById` | **`app/users.py UserRepository.find_by_id`** | `tests/test_users.py` |

`find_by_id` moved from **rank 5 to rank 2** (re-measured with `manage.py
retrieval_probe`; vector rank 4 is `tests/test_users.py`), and the docstring left
the top 3. The earlier "rank 4" here was wrong.

### Decisions worth recording

- **`simple` text-search config, not `english`.** English stems identifier fragments
  into noise and drops short code words like `id` and `by` as stopwords — which is
  most of the meaning in `find_by_id`.
- **Identifiers indexed split as well as whole**, so a natural-language query can
  reach an opaque token at all.
- **The tsvector is maintained by a database trigger.** The indexer uses
  `bulk_create`, which skips `save()`; a Python hook would quietly produce rows with
  a NULL vector that match nothing.
- **RRF rather than a weighted blend.** Cosine and `ts_rank` are not on the same
  scale and are not comparable between queries, so normalising would need per-query
  calibration. RRF fuses on rank instead.
- **Model tiering is forced by the limits.** Groq reports 8000 TPM per model, so
  the 120b model is reserved for Security, the 20b handles classification,
  grounding and test coverage, and static analysis uses no model. A token budget
  skips lower-priority agents rather than 429-ing part way. (This originally said the
  bucket "looks shared across models"; the 5e quota check found per-model buckets.)
- **Synthesis is deterministic.** Dedupe, ranking and blocking-versus-nit all have
  correct answers; a model call would add latency, cost and hallucination risk.
  Severity resolves upward on disagreement.
- **Degraded mode is deliberately unlike a review.** When no model answers, the
  comment states the change has *not* been reviewed. A degraded result that reads
  like a clean review is worse than no comment, because it tells a reviewer the code
  was checked when it was not. Static analysis succeeding alone counts as degraded.
- **Retrieval is injected into the agents package**, not imported, so the Django-free
  boundary holds: the grounding agent receives a callable and plain dataclasses.

### Static analysis: real tools, zero repo execution

ESLint configs are executable JavaScript, `pyproject.toml` can point tools at repo
plugins, and `npm install` runs preinstall scripts — each is remote code execution on
a pull request. So: `ruff --isolated`, `bandit` with our own flags and never `--ini`,
no package manager, no repo scripts, config-shaped files excluded entirely, content
written to a temp directory with paths flattened, and subprocesses with a timeout and
no shell. Tests assert that a hostile `pyproject.toml` and an `eslint.config.js`
containing `execSync` are neither read nor run.

**Why no ESLint.** Render's docs list `node`, `npm`, `yarn`, `pnpm` and `bun` in every
native runtime at build and runtime, so ESLint *would* work in production. It is still
not used: it needs `npm install` into the backend image (~50 MB on a 512 MB dyno) for a
linter that — forbidden from loading the repo's config, plugins and `extends` — runs a
bare ruleset catching little the security agent does not, and every ESLint integration
point worth having is the one that executes repo-controlled JavaScript. JS/TS gets a
pattern pass that executes nothing.

### Found by the tests, before shipping

- **`synthesised` was never declared in the graph state schema**, so LangGraph
  discarded it and every review came back with zero findings.
- **Grounding validated citations against the finding's location in the diff** rather
  than the `cited_file`/`cited_line` the model supplied, silently dropping every
  grounded finding — a diff location is never inside a retrieved chunk.

### Tradeoff accepted

LangGraph pulls about **30 transitive dependencies** (langchain-core, pydantic, httpx,
langsmith). That is real weight on a 512 MB dyno, accepted because the graph is the
project's centrepiece and parallel fan-out is verified working (three 0.4s nodes in
0.42s).

### Local development

`honcho start -f Procfile.dev` runs all four processes — backend, Celery worker
(`--pool=solo`, required on Windows), smee relay and frontend. Forgetting the worker
is the usual cause of "the webhook arrived but no comment appeared".

---

## Phase 4 — Agent pipeline v1

**Status:** Done. One review agent over the PR diff; the six-agent LangGraph pipeline
and retrieval grounding are phase 5.

### The spec's primary model does not exist on this key

Spec §5 names `llama-3.3-70b-versatile`. **`GET /v1/models` does not list it**, even
though Groq's docs still show it as a production model with no deprecation notice.
Documentation and account entitlement disagree, and entitlement is what runs.

Every callable candidate was probed with a real review prompt before choosing:

| Model | Mode | Latency | Valid JSON | Tier |
|---|---|---|---|---|
| `openai/gpt-oss-120b` | json_object | 1569 ms | yes | production |
| `openai/gpt-oss-20b` | json_object | 1814 ms | yes | production |
| `qwen/qwen3.8-27b` | json_object | 970 ms | yes | preview |
| `qwen/qwen3.8-27b` | none | 916 ms | **no** | preview |

**Primary is `openai/gpt-oss-120b`.** `qwen` is fastest but Groq labels it preview
("should not be used in production environments") and it emits invalid JSON without
json_object mode. Fallback stays `gemini-flash-lite-latest` per §14.

Live rate-limit headers report **1000 requests/day and 8000 TPM**, which is what sets
`REVIEW_MAX_DIFF_BYTES`.

### Decisions worth recording

- **The agents package has no Django imports, and that is now enforced.**
  `apps.agents` was removed from `INSTALLED_APPS` and its empty Django boilerplate
  deleted, so the only Django import — the `AppConfig` that registration demanded —
  is gone. A test greps the package for `django` and for sibling-app imports, so the
  boundary cannot erode quietly.
- **Prompt injection is treated as a real threat.** A diff is attacker-controlled.
  Four layers: rules only in the system message, the diff delimited and labelled
  untrusted, the output contract restated *after* the data, and structural validation
  so even a subverted response cannot produce a shape the caller mishandles. Verified
  live — the model caught the real bug *and* reported the injected instruction as a
  security finding.
- **Findings citing a line absent from the diff are dropped.** A comment anchored to
  unrelated code is worse than silence: it looks authoritative and is wrong.
- **A circuit breaker per provider.** With a quota exhausted, every review would
  otherwise spend its full retry budget (~14 s of backoff) rediscovering the same 429
  before failing over. A schema failure deliberately does *not* count against the
  breaker — that is the model's fault, not the endpoint's.
- **One corrective retry on invalid output**, then graceful failure with the reason in
  the PR comment.
- **The head SHA is in the comment because GitHub no-ops identical PATCHes.** Phase 2
  established this; a constant body would make every re-review invisible.
- **Cost is always labelled an estimate at paid-tier rates**, and an unpriced model
  reports "cost unknown" rather than a confident `0.00`. Groq's figures come from
  `console.groq.com/docs/models` — `groq.com/pricing` is JavaScript-rendered and
  carries no numbers.
- **`reopened` now triggers a review.** Phase 2 treated it as a no-op since it does
  not alter the diff, but a reopened PR has had no review of this branch state.
- **Push re-indexes, narrowly.** Only the default branch of a connected repository;
  other branches, tags, deletions and unconnected repositories are ignored, because
  indexing is the one thing that spends Gemini quota.

### Found while building

- A deleted file (`+++ /dev/null`) fell through to the `--- a/` fallback and was sent
  to the model with no citable lines, spending tokens on a change nobody can act on.

---

## Phase 3 — Ingestion

**Status:** Done, and **verified live** against `NivedhReddy2048/codesage-testbed`.

```
files discovered    : 16
files indexed       : 15
files skipped       :  1   (empty app/__init__.py)
chunks created      : 58
chunks reused       : 40   (second run, from the content-hash cache)
embedding API calls :  1   (batched)
stored dimension    : 1536
duration            : 6.2s
```

A manual query for `"function that looks up a user by id"` returns
`app/users.py:1-5`, `web/users.js:3-5 findUserById` and `web/users.js:11-13
fetchUser`. A query for `"SQL query built with string interpolation"` returns the
planted injection bug, `app/orders.py:17-24 OrderRepository.search_by_status`, at
rank 1.

### Decisions worth recording

- **Source arrives as a tarball through the App installation token, not `git`.**
  Render's free tier has an ephemeral filesystem and no guarantee the app process can
  shell out, so cloning is a thing that works locally and fails in production. The
  archive is streamed with a size cap rather than written to disk.
- **1536-dimension embeddings, not the model's 3072 default.** pgvector's hnsw and
  ivfflat indexes cap at 2000 dimensions, so 3072 would be storable but unindexable
  and every similarity search would silently become a sequential scan.
- **The migration creates the pgvector extension itself.** docker-compose seeds the
  dev database, but pytest builds a fresh test database and CI's service container
  has no init script. Verified by migrating into a database with no extension.
- **Embeddings are cached by content hash, including the file path.** Re-indexing an
  unchanged file costs nothing, which is what makes frequent re-indexing affordable;
  including the path keeps identical code in two files as two citations.
- **A parse failure never fails the job.** `codesage-testbed`'s `test.py` has leading
  indentation before `def` and raises `IndentationError`, so the fallback path is
  exercised by a test rather than assumed.
- **tree-sitter was considered and rejected** for JS/TS: a compiled dependency plus
  per-language grammars on a 512 MB dyno, to improve boundaries in a system whose
  results are already scored by embedding similarity.
- **Celery runs co-located with the web process** (spec §7). A second job is refused
  while one is pending or running, because two concurrent runs would race on the
  indexer's delete-then-insert.
- **Re-indexing requires owner or admin**, because it spends Gemini quota.

### Found by running it, not by the tests

- **The generic chunker merged whole files into one chunk.** Packing blocks purely by
  size put every function of a small JS file together: individually unretrievable,
  with a citation spanning the whole file. A declaration now breaks the chunk even
  when the merged result would fit. `web/users.js` went from 1 chunk to 6, and the
  repository from 45 to 58.
- **An 80-character minimum silently dropped module context.** A realistic
  imports-and-constants block measured 73 characters. Lowered to 40.

### Known limitation

Pure vector search ranks `app/users.py`'s module docstring above
`UserRepository.find_by_id` for `"function that looks up a user by id"` — the prose
restates the query, the code does not. This is precisely what spec §6's hybrid
retrieval addresses: phase 5 adds Postgres `ts_rank` keyword matching alongside the
dense search, which would lift the literal symbol name.

### Not enabled: re-index on push

The GitHub App subscribes to `pull_request` only, so pushing to the default branch
does not re-index. Enabling it needs **Settings → Developer settings → GitHub Apps →
CodeSage NR → Permissions & events → Subscribe to events → tick "Push"**. The
content-hash cache makes frequent re-indexing cheap, so this is reasonable to turn on
whenever wanted; the handler for it is not built yet.

---

## Phase 2 — Repo connection (GitHub App)

**Status:** Done, and **verified live**.

`codesage-nr[bot]` posted its acknowledgement on
[codesage-testbed#1](https://github.com/NivedhReddy2048/codesage-testbed/pull/1)
within seconds of the PR opening. The `/repos` page shows what the installation can
reach and lets an owner or admin connect and disconnect.

### Edit-not-duplicate, verified on a real PR

A second commit was pushed to the same PR branch, producing a `pull_request`
`synchronize` delivery. Both deliveries were received and processed, each answered
**202** in under 0.1s:

| delivery | event | action | processed |
|---|---|---|---|
| `1ead4f90-...` | `pull_request` | `opened` | yes |
| `328241a0-...` | `pull_request` | `synchronize` | yes |

Afterwards the PR still carried **exactly one** bot comment, with the same
`ack_comment_id` (6248297170), while the stored `head_sha` advanced to the new commit.
That combination is the proof: had the create branch run, there would be two comments.

**`updated_at` did not change, and cannot be used as evidence here.** The
acknowledgement body is a constant, and GitHub no-ops a PATCH whose body is
byte-identical. Confirmed directly by PATCHing the comment with its own current body
and watching `updated_at` stay put. Putting the head SHA in the acknowledgement text
would make each `synchronize` a visible edit — worth doing when phase 4 gives the
comment real content to carry.

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
