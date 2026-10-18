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
| 5 | Full 6-agent pipeline | `phase-5a` retrieval, `5b` graph, `5c` wiring | **Done** |
| 6 | Realtime + polish | `phase-6a` realtime, `6b` analytics, `6c` UI shell | Next |
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
| **Pull Shark** | Base badge at 2 merged PRs (already earned before this project); next tier **bronze at 16** | **22 merged — bronze (16) reached** |
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

`find_by_id` moved from **rank 4 to rank 2**, and the docstring left the top 3.

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
- **Model tiering is forced by the limits.** Groq reports 8000 TPM and the bucket
  looks shared across models, so the 120b model is reserved for Security, the 20b
  handles classification, grounding and test coverage, and static analysis uses no
  model. A token budget skips lower-priority agents rather than 429-ing part way.
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
