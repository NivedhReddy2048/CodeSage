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
| 6 | Realtime + enterprise UI | `phase-6a` realtime + data, `6b` shell + design system, `6c` review experience, `6d` dashboard + notifications + audit | **Done** |
| 7 | Deploy + CI | `phase-7a` config, `7b` CI+keep-warm, `7c` README | Next |
| 8 | Evaluation | `phase-8a` fixtures, `8b` run_eval, `8c` results | Not started |
| R | Frontend redesign ("Abyssal Navy & Sage Mint") | `redesign-1` tokens and primitives, `2` shell, `3` landing, `4` dashboard, `5` reviews, `6` repos/audit/settings | **Done** |

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
| **Pull Shark** | Base badge at 2 merged PRs (already earned before this project); next tier **bronze at 16** | **48 merged — bronze (16) reached** |
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

## Follow-ups: superseded comments, token blacklisting, severity gaps

**Status:** In progress.

### Refresh-token blacklisting and auth audit events (#101)

- `rest_framework_simplejwt.token_blacklist` is installed with
  `BLACKLIST_AFTER_ROTATION=True`. A rotated refresh token is refused (401). Before
  this, a replayed one got 200 against the live backend.
- `POST /api/auth/logout/` blacklists the refresh token. The frontend's sign-out calls
  it, fire and forget, then clears the session exactly as #65/#66 did.
- Two tabs share one refresh token. When both refresh at once, the loser's old token is
  blacklisted, so the client checks whether another tab already stored a new pair
  before treating that 401 as a sign-out. The single-flight refresh from #98 is the
  only caller of `/token/refresh/` in a tab: the proactive refresh, the 401 fallback
  and the socket's `ensureFreshToken`.
- The audit log records `auth.signed_in`, `auth.signed_out` and `auth.sign_in_failed`
  (an OAuth failure, or replay of a revoked refresh token) with actor, time, IP (first
  X-Forwarded-For hop) and user agent. Each event is filed under every organisation the
  user belongs to. A failed sign-in GitHub never identified has no organisation and is
  visible in the Django admin only. The Action filter has an "Auth" group.

**Phase 7 prerequisite: run `python manage.py flushexpiredtokens` in the build command.**
Every issued refresh token now leaves an `OutstandingToken` row and every rotation a
`BlacklistedToken` row. Nothing prunes them otherwise, and the table grows with every
sign-in and refresh.

---

## Review quality and UI fixes from the testbed run

**Status:** Done. Seven PRs, each closing its own issue: #86, #88, #90, #92, #94, #96 and
this one. They came from testing the full flow on codesage-testbed (PRs #5, #6, #7 and
a re-run).

**What the investigation found.** Raw agent findings were never stored, so they were
reconstructed for the investigation. Two problems surfaced:

- Every "(also flagged by static_analysis)" was a false lint warning, caused by
  linting a file rebuilt from the diff's hunks: F821 "undefined sqlite3", F841 "conn
  never used". Synthesis had merged it into an unrelated finding by proximity alone.
- Lines like :4 and :15 came from LLM agents counting lines in a raw diff and landing
  on blank context lines, which the diff check accepted.

**Fixed, in order:**

1. **#86, static analysis on the real file.** Modified files are fetched at the head
   SHA. If the fetch fails, the linter runs on the hunks with context-dependent rules
   off. Tool findings are kept only on added lines.
2. **#88, evidence-based anchoring.** Agents see numbered `+`/context lines and must
   quote the line they mean. Each finding is anchored where the quote actually is:
   an added line goes inline, an unchanged line goes under "existing code", and
   anything else becomes "general". Inline comments only ever land on added lines.
3. **#90, severity policy, before merging.** Test coverage is never blocking. Lint
   rules are nits; only bandit medium/high may block. Blocking needs evidence on an
   added line and definite wording. Agents stay in their own scope.
4. **#92, synthesis.** Findings merge only on the same line and the same issue, and no
   distinct finding is lost. Every raw finding is persisted (`ReviewRawFinding`) as
   kept, merged or dropped, with the reason. Grounding no longer cites the PR's own
   change.
5. **#94, UI.** Counts read in words ("2 blocking · 1 nit"). Review rows show the
   head SHA and a "Re-run" tag (`Review.trigger`, backfilled from the audit log).
   Notification titles lead with the PR number. Costs show 2 decimals with the exact
   figure in a tooltip, and model names wrap.
6. **#96, dashboard and repositories.** The indexed commit stays visible while a
   re-index runs. "Avg findings per PR" uses one scope (each PR's latest review)
   for both its headline and its breakdown.
7. **This PR, console.** `data-scroll-behavior` on `<html>`. Page loads no longer
   log 401s from `/api/auth/me/`: the cause was an expired 30-minute access token
   sent twice under Strict Mode. The access token is now refreshed before it's sent,
   through the existing single-flight refresh.

**Re-run after #86–#92** (`rerun_review`, reviews 43 and 44):

- PR #5: 1 nit at :9.
- PR #7: 2 nits at :3 and :17.

Every finding was anchored by quoted evidence onto an added line. Every model
"blocking" was downgraded with a recorded reason. No lint artefacts, no blank-line
anchors.

### Known limitations

- **Run-to-run variance** (which findings a model reports, and how it words them) is
  deferred to the Phase 8 evaluation harness. The testbed PRs are regression fixtures,
  not tuning targets.
- **Two planted bugs are still missed:** testbed PR #4's unclosed DB connection and its
  missing not-found check. That's for Phase 8 to measure.
- **Stale inline comments stay.** Inline comments from earlier runs are never removed,
  so a re-run leaves an outdated "Blocking" comment next to the corrected one. The
  summary comment is always current.
- **Near-duplicates on adjacent lines.** One agent reporting a single issue twice, on
  adjacent lines with identical text, is not merged, by the same-line rule.
- **JS/TS pattern scan.** Its `eval()` and `innerHTML` rules are nits now that only
  bandit may make a tool finding blocking.
- **Refresh tokens are rotated but not blacklisted,** so a used refresh token stays
  valid until it expires.

---

## Tooling — a Windows-safe dev runner replaces honcho

**Status:** Done. One PR, closes #83.

**Why.** On Windows, `honcho start -f Procfile.dev` cannot stop its children. On
Ctrl+C it loops "sending SIGKILL to backend.1 ..." without effect, then crashes with
`InterruptedError`, leaving the backend, worker, frontend and smee relay running.
Those orphans were the root cause of the incident below: six stale workers on one
queue, and a runserver holding :8000.

**What.** `python scripts/dev.py` starts the four processes, and
`python scripts/dev.py stop` is the emergency cleanup. Its only dependency is
psutil, which replaces honcho in `requirements-dev.txt`. `Procfile.dev` is gone.

- Each child gets its own process group (Windows) or session (Unix). Node tools run
  as `node <script>`, never through `npm`/`npx`: those are batch files on Windows,
  and cmd.exe answers Ctrl+Break with "Terminate batch job (Y/N)?" instead of exiting.
- Stopping is graceful first (CTRL_BREAK_EVENT, or SIGTERM). After 8 s each tree is
  force-killed (`taskkill /T /F`, or SIGKILL), plus every descendant seen before
  shutdown: a tree kill cannot reach a grandchild whose parent already exited. The
  runner names whatever needed force.
- The runner joins a kill-on-close Windows job object, so a crashed or hard-killed
  runner still takes everything down with it.
- Preflight refuses to start if :8000 or :3000 is busy, if a Celery worker answers a
  ping on the broker, or if leftover dev processes exist. It says what to run instead.

**Found by verifying it, not by the tests.**

- Each venv `python.exe` on Windows is a launcher that starts the real interpreter as
  its child. runserver with its autoreloader is four processes deep, which is why the
  runner snapshots whole trees rather than tracking pids.
- Windows children inherit "Ctrl+C disabled" from whatever started them (an IDE task
  runner, an agent's shell), even across a new console. Started that way, the first
  version ignored Ctrl+C entirely. The runner now re-enables Ctrl+C for itself.

**Verified on Windows**, two full cycles of start → all four ready → Ctrl+C:
everything ready in about 8 s, a graceful stop in 0.3 s, no process from the run
left, ports 8000 and 3000 free. Separately: hard-killing only the runner left 0 of
its 11 processes alive after 3 s (the job object), and killing the worker stopped the
other three with exit code 1. The Unix paths (SIGTERM, then SIGKILL of the group) are
covered by the shutdown tests that CI runs on Linux.

---

## Fix — reviews that no worker picked up were invisible

**Status:** Done. Two PRs: #80 (backend, closes #79) and this one (UI, closes #81).

**What happened.** Testbed PR #4 got its acknowledgement comment, then nothing: no row
on /reviews, and the comment said "reviewing..." indefinitely. Seven Celery workers
were consuming the one queue, six of them left over from earlier dev sessions, and a
three-day-old runserver held port 8000. The worker that took the task predated
migration `reviews.0005` and crashed in `Review.objects.create`
(`null value in column "progress"`). The insert rolled back, so nothing recorded that
a review had been requested.

**What changed.**

- The webhook handler creates the `Review` as **pending** before queueing it and passes
  its id to the task, which is how the UI re-run already worked. A failed enqueue marks
  the row failed.
- A review still pending or running after `STALE_AFTER` (15 minutes, the threshold
  re-run already used) is **stalled**. The API flags it; /reviews and the review page
  show a "Stalled" badge with a hint that the worker may be down, instead of a
  "Queued" pulse that never ends.

**Operational lesson.** Celery workers never reload code, and every dev worker here
shares one nodename and one queue. The orphans came from honcho, which cannot stop
its children on Windows; `scripts/dev.py` (below) replaced it and refuses to start
while another worker answers on the broker.

---

## Frontend redesign — "Abyssal Navy & Sage Mint"

**Status:** Done. Six frontend-only PRs (#68, #70, #72, #74, #76, #78), each with
its own issue; no backend or API changes. Every route, API call, socket stream and
sign-in step stays as it was, `/login` stays at `/login`, and `/` stays protected.

### What the redesign amounts to

- **One token system**, light and dark, in `globals.css`. The shadcn variables
  point at it. Every text, icon, control-border, focus and chart pair that the UI
  draws is checked against WCAG AA by a test in CI: 163 pairs in both themes, all
  passing (`npm run contrast` prints them). Spec values that failed got their own
  tokens rather than a quiet exception:
  - control borders;
  - placeholders;
  - the unread pill's text;
  - dark chart marks (validated with the dataviz validator).
- **An app shell built for keyboard and phone:**
  - a 248/64 px sidebar and a phone drawer;
  - a floating organisation switcher and a glass top bar;
  - a Ctrl+K palette;
  - one `main` landmark and a skip link.
- **A landing page at `/login`** whose every technical claim matches the code, an
  example review drawn by the real components from static data (tested to make no
  network request), and Lighthouse mobile 93-96 / desktop 100, Accessibility 100.
- **Pages that read well at any size of data:**
  - charts with empty slots and an average line for sparse months;
  - KPI breakdowns that match the API's definitions;
  - a review page with live agent progress, sticky diff headers and a trace matrix;
  - repository cards with index health;
  - an append-only audit log;
  - a role permissions table taken from the backend's checks.
- **One dependency added**, sonner, for toasts: no dependencies of its own, and
  mounted only in the signed-in shell.
- **Tests: 121 → 327.** Every pre-existing test still passes. Where markup
  legitimately changed (the landing page's headline and its several sign-in
  buttons), queries were scoped to the right region rather than accessible names
  being renamed.

### redesign-6 — repositories, audit log, settings, system states

**/repos.**
- **Connected repositories as cards:**
  - a repository icon, then `owner/` in secondary text with the name in mono;
  - visibility and default-branch pills;
  - Disconnect;
  - an index health block. It has a state badge (Indexed, Indexing n/m files,
    Queued, Indexing failed, Not indexed yet), mono chunk, file and commit
    figures, a files-indexed meter while a job runs, and after a run a reuse
    meter: "Last run reused 80 of 120 chunk embeddings; 3 embedding calls".
  - `chunks_created` counts every chunk stored, and `chunks_reused` the ones
    whose embedding was not paid for again, so the meter is exactly
    reused ÷ created.
- **A lone repository spans the row** rather than half of it.
- **"How indexing works"**: four steps, each checked against
  `backend/apps/ingestion`:
  - the default branch, skipping generated, vendored, binary, oversized and
    `.gitignore`d files;
  - Python split by its AST into functions, classes and their methods; other
    languages split at declarations found by pattern;
  - `gemini-embedding-001` at 1536 dimensions into pgvector, with a Postgres
    full-text vector (filled by a trigger) alongside;
  - reuse when a chunk's path-and-content hash is unchanged.

  A test checks it never mentions tree-sitter.

**/audit.**
- **A scope strip** saying what the filters cover ("All activity in this
  organisation", or each active filter in words) with the entry count, and an
  "Append-only: entries cannot be edited or deleted" notice.
- **Rows:**
  - actor badges in mono;
  - action pills coloured by kind (connected green, disconnected rose, re-index and
    re-run blue, role change amber), each with an icon and its label;
  - target chips;
  - mono timestamps;
  - pagination with chevrons.

**/settings.**
- **Members:** rows with a mono name, a "you" pill, the role underneath, and the
  role select for owners. The cards align to the top, so one member does not
  leave a stretched, empty card.
- **Role permissions:** a table of what each role may do, taken from the backend's
  checks (`REPO_MANAGEMENT_ROLES` for connect, disconnect, re-index, re-run, the
  audit log and raw errors; owner-only role changes; the last owner cannot be
  demoted). It carries "Allowed" / "Not allowed" for screen readers.
- **Appearance:** three preview cards, each a miniature of the app in that theme
  (System split down the middle). They are the same native radios, named Light,
  Dark and System.

**System states, everywhere.**
- Empty states carry a small layered-card illustration (decorative, hidden from
  assistive tech).
- Error cards share the callout layout, with a retry where one makes sense.
- KPI and table skeletons keep the page from jumping.
- Success toasts for connecting, disconnecting, starting a re-index, starting a
  re-run and changing a role. Errors stay inline, where they do not vanish on a
  timer.

**Tests:** a new `workspace-pages.test.tsx` covers:
- repository cards and index health;
- the indexing explainer;
- the connect toast;
- running-job progress;
- the audit scope, the append-only notice and action pills;
- the permissions table;
- the "you" pill;
- the empty-state illustration being hidden from assistive tech.

Checked in Edge with one repository and one member, light and dark, at 1366 px and
375 px: no horizontal page scroll.


### redesign-5 — reviews list and review detail

**/reviews.**
- One toolbar on the table card: a "Filters" label with an active-filter count,
  the Repository, Status and Severity selects, Clear filters, and the result count.
- A set filter is outlined in brand. Each select's label stays for assistive
  tech; its first option ("All repositories", "Any status") names it on screen.
- Pagination has mono, tabular page and review counts.
- The filters still live in the URL.

**/reviews/[id].**
- **Header:** the repository and PR as a mono badge, the commit reviewed, the
  slug as the heading, and the PR title beneath it. The status pill, Fallback,
  Re-run and the GitHub link sit on the right.
- **While running:**
  - the live pill gets a soft pulse (still under reduced motion);
  - a five-segment bar shows each agent's state, in graph order (Diff/Intent,
    then the four that fan out);
  - the bar works from the stored progress until the socket or poll updates it;
  - each segment has the agent's name and state in words, for screen readers on
    every width and on screen from `sm` up, so it never relies on colour.
- **Callouts:** one `Callout` (icon, title, body, tone) for each thing a reader
  must know before trusting the page:
  - degraded (`role="alert"`, "nothing here is an approval");
  - failed (`role="alert"`);
  - answered by the fallback (informational, no alert);
  - not every line reviewed.
- **Summary strip:** findings, time, est. cost at paid-tier rates, tokens and
  models, in mono figures, with dashes while running.
- **Diff:**
  - File headers stick under the top bar. The file card moved from
    `overflow: hidden` to `clip`, which does not make a scroll container, so
    sticky works.
  - Added and removed lines take the success and blocking fills, with a coloured
    sign and the existing screen-reader word.
  - The line-number gutter is tabular.
- **Findings panel:** severity-edged cards with an agent chip and a count per
  group.
- **Agents table, now a trace matrix:** model and provider as mono chips;
  right-aligned tokens; and latency with a bar scaled to the slowest agent, so
  the critical path shows at a glance.

**Contrast:** 32 new pairs. Body and secondary text on every tinted fill (added
and removed diff lines on a card, callouts on the canvas), in both themes; all
pass.

**Tests:**
- the active-filter count and Clear filters;
- the fallback callout raises no alert;
- agent progress order and words;
- latency bars scaled to the slowest agent.

Checked in Edge, light and dark, at 1366 px and 375 px, on the list, a finished
review with a fallback, and a running review (2/5 agents, polling): no horizontal
page scroll. On a phone the diff and the agents table scroll inside their own
containers, and inline findings stay at the visible width.

### redesign-4 — dashboard

Everything below is computed from what `GET /api/analytics/overview/` and
`GET /api/reviews/` already return; no backend change.

**Header.** Title and subtitle on the left. The period segmented control and the
repository select sit on the right, in the page header above everything they
scope. Their labels stay for assistive tech, and the filters still live in the
URL.

**KPI cards.** A brand-tinted icon badge, the value in mono tabular figures, one
line of context, and a small summary mark. The marks are decorative (the numbers
are in text), so they are hidden from assistive tech:
- **PRs reviewed:** a proportional bar of done, degraded, failed and in progress.
  These are disjoint in the API: a degraded review is stored as failed with the
  degraded flag, and `failed_reviews` excludes it. The remainder is still running.
- **Avg findings per PR:** blocking vs nits.
- **Avg review time** and **est. cost per review:** sparklines from the daily
  series (`avg_latency_ms`, and `est_cost_inr / reviews`).
  - A day with no value breaks the line rather than dropping to zero.
  - A sparkline appears only when at least half the days have a value: three
    review days in thirty drew stray stubs that suggested a trend that is not
    there.
- The cost tile keeps "At paid-tier rates · ... total; actual spend ₹0".

**Charts.**
- **Reviews per day.**
  - A zero day gets a faint full-height empty slot, so a sparse month reads as a
    calendar with a few marks rather than a broken chart.
  - A dashed line marks the daily average, labelled in a gutter right of the plot
    so it never sits on a column.
  - Date labels thin out with the plot's width, so a phone gets fewer labels, not
    overlapping ones.
- **Show table** is kept on all three charts; the table view has mono, right-aligned
  numbers.

**Palette, validated with the dataviz validator, not eyeballed.**
- Light passes every check against `#ffffff` (blocking/nit CVD ΔE 9.4).
- In dark, the spec's emerald, sky, rose and amber sit above the lightness band
  for marks on a near-black card (OKLCH L 0.48-0.67) and glare. The dark marks are
  one step deeper:
  - primary/secondary `#0d9e6d` / `#1f9bd6`: pass every check, CVD ΔE 15.3;
  - blocking/nit `#e11d48` / `#c47f0b`: pass, with CVD ΔE 7.8. That is the floor
    band, legal because every two-series chart also has a legend, 2 px gaps, a
    per-row readout and a table.
- All chart marks clear 3:1 on the card, in the contrast test.

**Recent reviews table** (shared with `/reviews`):
- mono `owner/repo#PR` slugs;
- status pills;
- a blocking-count pill with an icon, its count, and "blocking" for screen
  readers;
- mono, right-aligned findings, time and cost;
- mono relative timestamps.

**Tests:**
- the review-count breakdown (done, degraded, failed; in-progress hidden at zero);
- zero days, and only zero days, get an empty slot;
- the average line and its label, and no average for one day or an empty period;
- the breakdown bar's proportions and text key;
- sparkline gaps, and no sparkline without a trend.

Checked in Edge with sparse (4 of 30 days) and dense (every day) data, light and
dark, at 1366 px and 375 px: no horizontal page scroll; the reviews table scrolls
inside its card on a phone.

### redesign-3 — landing page at /login, callback restyle

`/login` is still the sign-in page, at the same path, with the same redirect when
already signed in. It is now also the page that explains the product.

**Sections:**
- A sticky glass header: logo, jump links (How it works, Architecture, Example
  review), View on GitHub, a theme switch and a compact "Continue with GitHub".
- A split hero: the "Multi-agent PR review" eyebrow, a display headline, the
  one-line pitch, the three feature cards, and the sign-in card with a mint glow.
  On a phone the sign-in card comes before the feature cards, so signing in is one
  screen down.
- "How it works": the pipeline as an SVG at desktop width, with data pulses that
  are hidden under reduced motion. Below that width, and for screen readers at
  every width, it is an ordered list.
- "Architecture": six tiles, one per real component.
- An example review, a closing call to action, and a footer.

**The diagram follows the code, not the brief.**
- The brief said "5 parallel agents". `graph.py` runs Diff/Intent first and alone,
  then the other four in parallel, so the diagram shows that.
- The brief put the citation check in synthesis. It lives in the grounding agent
  (`citations.validate`), so it is on that node.
- A test pins the order and checks that the page never mentions tree-sitter or
  ESLint, neither of which the code uses.

**Example review.**
- Drawn by the real `DiffViewer` and `StatusBadge` from fixed sample data, badged
  "Example".
- One blocking off-by-one (`range(len(users) + 1)`), shaped like a real grounding
  finding: it names `export_rows`, and its citation uses the checker's
  `path:start-end` form.
- Per-agent timings, and "est. ₹0.07 at paid-tier rates · actual spend ₹0".
- A test stubs `fetch`, `WebSocket` and `XMLHttpRequest` and asserts none is
  called, and that it renders no image, script or other fetched resource.
- No testimonials, logos, user counts or invented metrics; a test checks for the
  usual phrases.

**Inline findings, on the review page too.** A severity-coloured left edge, an
agent chip, and the citation as a brand chip. On a phone the finding card takes
the diff scroller's visible width (a size container, `100cqw`), so it reads
without scrolling sideways while long code lines still scroll under it.

**/auth/callback.** The loading and error states sit in a card with the logo.
Only JSX changed: the effect, state, timing and routing lines are untouched, and
all 10 callback tests pass unchanged.

**Lighthouse, production build (`next build && next start`), Edge headless.**

| | Performance | Accessibility | Best practices | SEO |
|---|---|---|---|---|
| Mobile, final build, 3 runs | 93, 94, 94 | 100 | 100 | 100 |
| Mobile, previous build, 5 runs | 96 (all five) | 100 | 100 | 100 |
| Desktop | 100 | 100 | 100 | 100 |

The two builds differ only in the header's jump-link breakpoint; the spread is
machine load.

**Getting mobile from 81 to the 90s, measured one step at a time:**
- **The example review renders on the server.** `DiffViewer` holds no state and
  only memoises, so it lost `"use client"`. The landing page ships no diff code
  and has nothing of it to hydrate; the review page, a client component, still
  bundles it.
- **The landing islands carry no component library.** The sign-in button is a
  plain `<button>` whose classes the server page computes with `buttonVariants`.
  The header uses a three-radio theme switch rather than the menu.
  `TooltipProvider` moved from the root layout into the app shell, its only user.
  Together: 81 → 87-90.
- **Below-the-fold sections sit in a Suspense boundary**, so React hydrates them
  as a separate unit instead of in the same long task.
- **The ₹ sign is set in the system UI font on this page.** Geist has ₹ only in
  its latin-ext subset, so one ₹ fetched two more font files (31 KB) at very high
  priority, competing with first paint. The same build without them went from
  87-93 to 95-96. `<Inr />` keeps the glyph and drops the fetch.

**Tests:** 275 pass. New tests cover:
- the section links;
- a failure reported next to the button that was pressed, once;
- the pipeline order and its copy;
- no social proof;
- the cost wording;
- the example's badge, finding and citation;
- the example making no network requests.

Checked in Edge, light and dark, at 1366, 1024, 768 and 375 px: no horizontal page
scroll, no console errors, and no API request from the landing page.

### redesign-2 — app shell

**Sidebar.**
- 248 px wide, collapsing to a 64 px icon rail (Ctrl/Cmd+B or the toggle) over
  220 ms on the out-expo curve. On a phone it is a drawer.
- The header carries the logo, linked home.
- The workspace badge is the organisation's initial on the brand tint, replacing
  the generic blue square.
- The active page is a surface-2 pill with a brand icon and a 2 px brand bar, so it
  is marked by more than colour; `aria-current` is unchanged.

**Organisation switcher.** It used to open as a panel the same colour as the
sidebar, laid over "Dashboard", so it read as part of the nav. It is now a floating
layer: surface-3, the popover shadow, wider than the sidebar so it visibly sits
above it, and a stronger edge in dark (`border-strong`; `border-default` all but
vanished on the near-black page). From the icon rail it opens beside the rail.
Each organisation shows its badge and role.

**Top bar.**
- Sticky glass (`bg-glass`, 12 px blur) at z-20; menus and dialogs portal out above
  it at z-50.
- A "Search or jump to..." trigger with a mono `Ctrl K` keycap.
- The bell's unread count is a solid rose pill with its own text token
  (`--on-blocking`, in the contrast test: 6.3:1 light, 7.3:1 dark). It stays out of
  the accessible name, which already says "Notifications, N unread".
- On a phone, the logo sits beside the drawer toggle.

**Notification popover and command palette.** Both are on surface-3.
- The popover shows an unread count, brand unread dots (the "(unread)" text for
  screen readers stays) and mono timestamps.
- The palette has a flush search row, whose focus indicator is its bottom edge
  turning brand, and mono `owner/repo#PR` slugs.
- The selected row in the palette gets a surface lift and a brand edge, and a footer
  lists the keys (arrows, Enter, Esc).

**Page container:** max width 1380 px, padding 16 / 24 / 32 px.

**Found while building:** the page had two `main` landmarks. shadcn's
`SidebarInset` renders a `<main>`, and the shell put its own `<main id="content">`
inside it. The inset is now a `div`, and a test pins exactly one `main`.

**Found in the browser:** in the icon rail, the switcher's and account menu's
names and chevrons still took space, which squashed the workspace badge and the
avatar to a sliver. They now hide in the rail.

**Tests:** the logo's alt text, switching organisation from the keyboard, sign-out
from the account menu, one `main` with a skip link to it, opening the palette from
the search button and from Ctrl+K, and the bell's capped "9+" count. Verified in
Edge, light and dark, at 1366 px and 375 px:
- the switcher opened by keyboard, expanded and from the rail;
- the bell, the palette and the skip link;
- the phone drawer.

No horizontal page scroll and no console errors.

### redesign-1 — tokens, theme, favicon, core primitives

**Tokens.** One set per theme in `globals.css`: canvas and three surface levels, a
glass layer for the top bar, three border steps, three text steps, brand
(emerald fills, teal accents and focus), four status families plus a neutral, chart
colours, card and popover elevation, radii, a type scale and motion timings. The
shadcn variables point at these tokens, so the generated components pick up the
palette without being rewritten. Dark is the hero theme. Primary buttons there use
dark text on emerald, because white on `#10b981` is only 2.5:1.

**Contrast is a test, not a note.** `src/app/theme-contrast.test.ts` parses
`globals.css`, composites translucent fills over the surface beneath them, and
checks every pair the UI draws against WCAG AA in both themes. That is 125 pairs:
text on each surface, button text on its fill, badge text on its badge, and the
focus ring, control borders and chart marks at 3:1. It runs in CI with the rest of
the suite, and `npm run contrast` prints every ratio. Two spec values failed and
got their own tokens:
- **Control borders.** `border-strong` is 2.6:1 on white and 1.9:1 on the dark
  card, under the 3:1 a control boundary needs. Inputs, selects and the segmented
  control use `--control-border`: 3.2-3.5:1 light, 3.1-3.6:1 dark.
- **Placeholders.** Light `text-muted` is 4.3:1 on the surface-2 input fill. It is
  kept for the canvas and cards, where it passes, and placeholders get their own
  step (5.0:1).

Card edges, table dividers and badge outlines are decorative. WCAG 1.4.11 does not
cover them, so they are not checked.

**Primitives.**
- Buttons, cards, inputs, selects, badges, tooltips, skeletons, menus and dialogs
  all use the tokens. Focus is one 2 px ring with a 2 px offset everywhere,
  replacing shadcn's soft ring.
- A `NativeSelect` for the Repository, Status, Severity, Role and Action filters.
  It is still a real `<select>`, so roles, labels and the mobile picker are
  unchanged.
- A `SegmentedControl` built from real radio inputs, now used for the dashboard
  period.
- The "Est. cost" header's dotted underline sat on the baseline and cut through the
  text. It now sits 0.3 em below.
- Toasts did not exist. sonner is added (no dependencies; mounted only in the
  signed-in shell, so `/login` does not load it) and first confirms a role change.
  Errors stay inline, where they do not vanish on a timer.
- Reduced motion turns every transition and animation into an instant change.

**Favicon.** The default Next.js favicon is replaced by the CodeSage logo:
`favicon.ico` (16/32/48), `icon.png` and `apple-icon.png`, generated from
`docs/assets/codesage-logo.png`. The five unused Next.js starter SVGs are removed.

**Found by a test:** the class merger (`cn`) read the new `text-control` size as a
text colour, so `text-control text-fg` silently dropped the size. `cn` is now
configured with the design system's type scale and shadows, and the shadcn
components import it from `@/lib/utils` rather than from the package directly.

**Found in the browser:** cards moved from `overflow: hidden` to `overflow: clip`,
so sticky headers inside them can stick to the page later. That stopped them being
scroll containers, so as grid items they grew to fit a wide chart, and the
dashboard was 315 px too wide on a phone. `min-w-0` on the card fixed it.

Checked in Edge in light and dark, at 1366 px and 375 px, on the dashboard,
reviews, audit log, settings, repositories and login: no horizontal page scroll and
no console errors.

---

## Phase 6 — Realtime and enterprise UI

**Status:** Done. Four PRs: 6a backend realtime and data, 6b app shell and design
system, 6c review experience, 6d dashboard, notifications and audit pages.

### Fixed after Phase 6: sign-in hung on "Completing sign-in..."

**Symptom.** After signing out and choosing "Continue with GitHub" again, the callback
page never left "Completing sign-in...". Reported as affecting only the second
sign-in, the one where GitHub skips the consent screen.

**Reproduced** in Edge, with GitHub's authorize step and the code exchange simulated.
It hung on every dev-mode sign-in, the first included. The exchange ran once and
returned 200 with valid tokens; nothing happened afterwards.

**Cause, confirmed by logging the effect:** the callback effect had two guards.
- A `started` ref, so the single-use code was exchanged once.
- An `active` flag, cleared in cleanup, to ignore late results.

Strict Mode runs an effect, cleans it up, and runs it again. Run 1 started the only
exchange, cleanup cleared `active`, and run 2 returned early because of the ref. The
exchange resolved into a closure nobody was listening to: no redirect, and, because
the `.catch` checked the same flag, no error either. Each guard is reasonable alone;
together they drop the only result. Production does not double-run effects, which is
why it looked intermittent.

How the other suspects came out:
- **The code exchanged twice:** no; the ref prevented that.
- **State removed before the second run:** no; the second run never read it.
- **A stale workspace header or token:** no; sign-out already cleared them.
- **The OAuth `state` in sessionStorage:** not the cause, but sign-out did leave it
  behind.

**Fix.**
- **Exactly one exchange.** It now lives outside React (`lib/oauth.ts`): one promise
  per callback URL, shared by however many times the effect runs or the page
  remounts. Every run subscribes, and the live one acts on the result, so it is
  exchanged exactly once and always heard.
- **A timeout.** Any failure, or 20 s without an answer, shows a short reason and a
  "Try again" link back to `/login`. GitHub's raw detail never reaches the page.
- **Sign-out clears everything.** `clearSession()` removes both tokens, the chosen
  workspace and any pending OAuth state. A successful sign-in clears the same before
  storing new tokens, so one account never inherits another's workspace.

**Tests.** Regression tests under `StrictMode` cover:
- the double effect run;
- a remount mid-exchange;
- a second sign-in after sign-out;
- a stale workspace;
- a failed exchange, an unreachable backend, a cancelled sign-in, a state from
  another tab, the timeout, and what sign-out clears.

Against the old callback page all eight page tests fail, error paths included. Live:
three sign-in and sign-out rounds in a row each reached the dashboard with exactly one
exchange; a 400 showed the short error after 1.9 s, and a backend that never
answered timed out at 20 s.

**Login page.** It is the first page a demo visitor sees, so it now has:
- the logo and a one-line value proposition;
- three feature points: multi-agent review, grounded in your codebase, and inline PR
  comments;
- a "View on GitHub" link and a theme toggle.

Checked in light, dark and at 390 px.

### 6d — dashboard, notifications, audit log

**Dashboard.** One filter row above everything it scopes: period presets for the last
7, 30 or 90 days, and a repository. The filters live in the URL. Below it:
- a KPI row: PRs reviewed, average findings per PR, average review time (completed
  reviews only), and est. cost per review, which carries "at paid-tier rates · actual
  spend ₹0";
- three charts: reviews per day (one series, so a single colour and no legend
  box), findings by category (single-colour bars; a darkening ramp on unordered
  categories is a listed anti-pattern), and agent contribution, split blocking/nit;
- recent reviews.

The charts are hand-built SVG and HTML rather than a library, so the marks follow
the dataviz spec: bars at most 24 px with 4 px rounded data ends, square at the
baseline, a 2 px surface gap between stacked segments, solid hairline grid, a label
on the peak only, and text in text colours, never the series colour. Every chart has:
- a table view;
- a tooltip on hover with the same readout on keyboard focus (arrow keys walk the
  days);
- a dimmed previous render, rather than a skeleton flash, when filters change.

**One palette, validated, not eyeballed.** The two series colours are slots 1 and 2 of
the dataviz reference palette, run through its validator against this app's actual
card surfaces. Light (`#ffffff`): CVD ΔE 24.7, normal-vision ΔE 33.6, contrast at
least 3:1. Dark (`#171717`), validated separately with its own steps: ΔE 26.8 / 31.8,
also at least 3:1.

**Notification bell.** The unread count is in the button's accessible name, not only
the badge. The latest notifications open in a menu: opening one marks it read and
follows its link, and "Mark all as read" clears the rest. It polls once a minute and
on open.

**Audit log.** Filters by action, actor, target text, and a from/to date range. They
are applied together, so typing does not refetch per keystroke, and kept in the URL.
The table is paginated with a page count and shows each entry's details.

**Found by a test:** a browser date input sends `2026-10-19`, and on Python 3.11+
Django's `parse_datetime` accepts a bare date as midnight, so `until=<today>`
excluded the whole day. A date is now widened to the start or end of that day.

Verified in Edge, in light, dark and at 390 px: no console errors, no page overflow,
filters update the URL, and the bell and audit filters work against live data (the
audit entry came from a real re-index through the API).

### 6c — the review experience

**Review page** (`/reviews/{id}`):
- the reviewed diff with each finding threaded under the line it points at, and that
  line outlined. Added and removed lines are labelled for screen readers as well as
  coloured;
- a sticky findings panel grouped by severity, where an anchored finding jumps to its
  line and moves focus there. A finding on a line the diff does not show is listed
  and says so;
- the per-agent table: the model that actually served each agent, what it asked for
  after a failover, provider, tokens, latency, status, and static analysis's
  `ran ruff, bandit`;
- a summary strip (findings, time, est. cost at paid-tier rates, tokens, models), the
  GitHub PR link, and a confirmed re-run for owners and admins.

**Reviews list** filters by repository, status (including degraded) and severity. The
filters live in the URL, so a filtered view can be bookmarked and Back works.

**The diff is the reviewed one.** `Review.diff` now stores the diff each review read.
A review from before that is filled once from GitHub's compare API at its own head
commit (`base...head_sha`, a three-dot compare, as a PR diff is), then cached. So the
findings line up with the code that was reviewed, not with whatever the PR looks like
now. A GitHub failure returns a short message, and the page still lists the findings.

**Live status pill.** It says "Reviewing... 3/5 agents" in an `aria-live` region, fed
by the 6a socket. If the socket cannot connect or drops, the page polls the status
endpoint every 3 s and says so. A 4401 close gets one token refresh and one
reconnect; a 4404 stops. When the review finishes, the page refetches the review and
its diff.

Verified live in Edge: a review run from another process moved the pill through
0/5 → 1/5 → 2/5 → 4/5 → 5/5 → Done. The page then showed the finding anchored at
`test.py:3`. Escape closes the re-run dialog and returns focus to its button.

**Found in the browser:** while a review ran, the page said "No findings — this review
produced no findings" with ₹0.0000 and 0/0 tokens. That reads like a finished clean
review of a change nobody had finished looking at. While in flight it now says
findings appear when the agents finish, with dashes for cost and tokens.

**Found by the build:** `next build` typechecks test files too, and caught mocks the
page tests added without declaring.

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

`python scripts/dev.py` runs all four processes — backend, Celery worker
(`--pool=solo`, required on Windows), smee relay and frontend. Forgetting the worker
is the usual cause of "the webhook arrived but no comment appeared". (This was
`honcho start -f Procfile.dev` until #83 replaced it; honcho cannot stop its
children on Windows.)

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
