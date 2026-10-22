# DEV run 1 report

- **Run:** 2026-10-22, 15:16:25–15:56:10 UTC. 40 runs: 20 cases × 1 run × 2 arms (pipeline, baseline).
- **Code:** harness commit `e7cb665` (main), pipeline version `2b0a0fd217778a48`.
- **Models:** pipeline uses `openai/gpt-oss-20b` for intent, grounding and test coverage, and `openai/gpt-oss-120b` for security. The baseline makes one call to `openai/gpt-oss-120b`.
- **Provider:** every call was served by Groq. Groq reported 51 distinct `system_fingerprint` values across 88 calls; all are recorded per agent in the result JSON.
- **Status:** no tuning, prompt change or code change has been made since the run. DEV round 2 and TEST have not started.

## 0. Pre-run items

DEV run 1 started at **2026-10-22T15:16:25Z**.

| Item | PR | Merged (UTC) | Before the run? |
|---|---|---|---|
| a) Testbed answer leaks stripped, re-indexed, `index_commit` updated, amendment documented | #114 (`b6516dc`) | 14:59:08 | yes |
| b) Neutral titles and upstream repo names | #114 (same amendment) | 14:59:08 | yes |
| c) Daily-limit handling, live and eval, with tests | #116 (`1a69370`) | 15:10:40 | yes |
| d) LICENSE copyright line | #114 (commit `95118fe`) | 14:59:08 | yes |
| Baseline arm (needed for the run) | #118 (`e7cb665`) | 15:15:50 | yes (35 s before) |

Every result records `harness_commit = e7cb665`. No DEV result predates any item, so nothing needs re-running.

### a) What was removed from the testbed

The change is testbed `8934446` → `a6ddd12`. It touched docstrings, comments and README text only; no behaviour changed.

- **`app/orders.py`, `search_by_status`:** removed the docstring paragraph *"BUG (SQL injection): status is interpolated into the statement instead of being bound as a parameter, unlike every other query in this class."*
- **`app/orders.py`, `open_connection`:** the docstring *"BUG (resource leak): the connection is never closed on the error path."* became *"Check that the database at `path` responds."*
- **`app/users.py`, `get_user_display_name`:** removed the paragraph *"BUG (missing null check): find_by_id returns None for an unknown id, and this dereferences it straight away…"*
- **`app/users.py`, `paginate_users`:** removed the paragraph *"BUG (off-by-one): the end index adds per_page to the page number rather than to the start offset…"*
- **`web/users.js`, `loadUserSummary`:** removed the two-line comment *"// BUG (missing await): fetchUser returns a promise, so `user` is a Promise…"*
- **`README.md`:** *"A deliberately small service used to exercise CodeSage's indexing and review pipeline. Not production code."* and *"Indexed by CodeSage."* became *"A small order and user service."*

The testbed was re-indexed at `a6ddd12`. `retrieval.index_commit` moved to `a6ddd12` in 16 cases: 9 testbed (8 DEV, 1 TEST) and 7 planted (TEST). The harness refuses a retrieval case whose index commit does not match.

The amendment is documented in [eval/tools/README.md](../../tools/README.md#seal-amendment-before-any-run) and in the method section of [docs/EVALUATION.md](../../../docs/EVALUATION.md).

### b) Titles

- **Benchmark cases:** all 41 BugsInPy/BugsJS cases, buggy and clean, now have the title `Update <path>` and an empty body. Before, they said "Reversed BugsInPy <project> bug <n>" or repeated the upstream commit message.
- **Repository names:** the five BugsJS cases now name the upstream repository (for example `expressjs/express`) instead of `BugsJS/<project>`.
- **Testbed PR titles:** none were changed. None of them reveals a bug.

### c) Daily-limit tests

All tests in both files pass (58 tests in `tests/test_rate_limits.py` + `apps/evaluation/test_evaluation.py`).

| Behaviour | Test |
|---|---|
| Live: a daily limit named in the 429 body fails over to Gemini at once, with no sleep | `test_live_a_daily_limit_fails_over_to_gemini_immediately` |
| A daily limit fails at once, even when Groq sends a short `retry-after` (TPD and RPD bodies) | `test_a_daily_limit_named_in_the_body_fails_at_once_even_with_a_short_retry_after` |
| `retry-after` over 30 s fails over at once instead of waiting | `test_a_daily_limit_fails_over_at_once_instead_of_waiting`, `test_a_daily_limit_on_the_provider_is_a_provider_error` |
| A per-minute limit is still waited out on Groq | `test_a_per_minute_limit_is_still_waited_out`, `test_a_per_minute_429_is_waited_out_and_never_fails_over` |
| Eval: a daily limit stops the day with no run marked invalid, and the next day resumes from the cache | `test_a_daily_limit_stops_the_day_cleanly_and_tomorrow_resumes` |

## A. Metrics

The scorer is `run_eval --suite dev --report`. There are 13 ground-truth bugs in 12 buggy cases, plus 8 clean cases. Every case has one run, so the majority vote is just that run, and the unstable-case count is not yet measurable.

| Metric | Pipeline | Baseline |
|---|---|---|
| **Recall, headline** (±2 lines + category, anchored) | **6/13 (23–71%)** | **10/13 (50–92%)** |
| Recall, lenient (±3 lines, any category) | 13/13 (77–100%) | 12/13 (67–99%) |
| Recall, headline, benchmark bugs only (BugsInPy + BugsJS) | 1/8 (2–47%) | 6/8 (41–93%) |
| Recall, headline, testbed bugs only | 5/5 (57–100%) | 4/5 (38–96%) |
| Recall at blocking severity *(extra, computed by hand)* | 3/13 (8–50%) | 8/13 (36–82%) |
| Blocking precision, raw | 2/2 (34–100%) | 7/11 (35–85%) |
| Blocking precision, after manual review | 2/2: both real (ruff syntax errors) | 8/11 (43–90%): 7 matched, 1 real but not planted, 3 false |
| False alarms on the 8 clean cases (any blocking finding) | 0/8 (0–32%) | 2/8 (7–59%) |
| Anchoring accuracy (headline hits inline on the exact bug lines) | 5/6 (44–97%) | 9/10 (60–98%) |
| Latency p50 / p95 | 3017 / 5539 ms | 1866 / 2830 ms |
| Estimated cost per review | US$0.000847 (₹0.0806) | US$0.000438 (₹0.0417) |
| Retries / invalid runs / fallbacks / daily-limit stops | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |

Manual review of the 4 baseline blocking findings that matched no bug:

| Case | Finding | Verdict |
|---|---|---|
| clean-express-511d9df `lib/utils.js:73` | `types.map` fails on array-like input, which the old index loop accepted | **Real but not planted**: a true behaviour change. It is harmless only if every caller passes an Array, and the diff does not show the callers. |
| testbed-pr3 `app/lookup.py:9` | `users` might be None or not iterable | **False**: speculation against the documented contract ("a list of users"). |
| testbed-pr8-584b17d `app/money.py:10` | `Decimal(str(value))` loses precision for a Decimal | **False**: `str()` of a Decimal round-trips exactly. |
| testbed-pr8-f701890 `app/money.py:17` | A negative total breaks the split | **False**: `divmod` floors, and the parts still sum to the total and differ by at most one cent. |

**Caveat 1: the testbed-pr1 numbers are inflated in both arms.** Both arms catch both pr1 bugs only through the ±2 window: one finding is credited for two bugs one line apart. Credited by meaning, headline recall is pipeline **5/13 (18–64%)** and baseline **9/13 (42–87%)**, and the anchoring misses in both arms are those cross-credits (see F2).

**Caveat 2: the pipeline's precision and false-alarm figures are not evidence of discrimination.** It produced only 2 blocking findings in 20 runs (see F1).

### A′. The same results under the measurement amendments H1–H3

These were approved after this report and applied to both arms before any TEST run (issue #124):
- **H1:** a finding credits at most one bug.
- **H2:** per-agent credit comes only from findings that survived.
- **H3:** recall at blocking severity is reported.

The table above is kept as originally reported. This table is `run_eval --suite dev --report` on the same 40 results under the amended scorer.

| Metric | Pipeline | Baseline |
|---|---|---|
| Recall, headline (±2 + category, one-to-one) | **5/13 (18–64%)** | **9/13 (42–87%)** |
| Recall, lenient (±3, one-to-one) | 13/13 (77–100%) | 11/13 (58–96%) |
| **Recall, blocking severity (H3)** | **2/13 (4–42%)** | **7/13 (29–77%)** |
| Blocking precision, raw (unchanged by H1) | 2/2 (34–100%) | 7/11 (35–85%) |
| False alarms on clean cases (unchanged) | 0/8 (0–32%) | 2/8 (7–59%) |
| Anchoring accuracy | 5/5 (57–100%) | 9/9 (70–100%) |

- **Per agent, pipeline (H2):**
  - static_analysis: 3 (pysnooper-3, pr1 syntax, pr8 syntax), all unique.
  - grounding: 2 (testbed-pr2, testbed-pr3), both unique.
  - Grounding was previously also credited with both pr1 bugs, through a finding the citation check dropped.
- **Per case:** the only verdict H1 changes is testbed-pr1.
  - Pipeline: the syntax bug is caught, the off-by-one is not.
  - Baseline: the off-by-one is caught, the syntax bug is not.
  - This is the "by meaning" reading given in caveat 1 above.

## B. Per-case results

Notation: severity:line, B = blocking, N = nit. "Lenient only" means a finding within ±3 lines exists but fails the headline rule.

| Case | Source | Ground truth | Pipeline | Baseline | Notes |
|---|---|---|---|---|---|
| bugsinpy-pysnooper-3 | BugsInPy | `:26` correctness: writes to undefined `output_path` (NameError) | **HIT** N:26 (ruff F821) | **HIT** B:26 | Pipeline found it with ruff, but every non-syntax lint finding is a nit. Test coverage also said "output_path is undefined". |
| bugsinpy-thefuck-21 | BugsInPy | `:8–9` error-handling: `split()[1]` raises IndexError on one word | miss (lenient only: test-coverage N:8 "testing") | **HIT** B:8 | The test-coverage message describes the IndexError exactly, but it is filed as "untested". |
| bugsinpy-thefuck-29 | BugsInPy | `:26–28` correctness: kwargs override settings already set | miss (lenient only: test-coverage N:28) | **HIT** B:27 | Test coverage half-described it: "now overrides existing keys". |
| bugsinpy-thefuck-3 | BugsInPy | `:108–110` correctness: version parsed from the last word of `fish --version` | miss (lenient only: ruff S607 N:108) | miss (lenient only: resource-leak N:110) | Neither arm saw the bug. Both lenient hits are unrelated findings that happen to be nearby. |
| bugsinpy-thefuck-32 | BugsInPy | `:2` correctness: `'ls' in script` matches too much | miss (lenient only: test-coverage N:2) | **HIT** N:2 | Test coverage described it ("matches any command containing 'ls'"). |
| bugsinpy-thefuck-5 | BugsInPy | `:9` correctness: any 'set-upstream' output matches | miss (lenient only: test-coverage N:9) | **HIT** B:9 | Test coverage: "broader condition… no test". |
| bugsjs-express-2 | BugsJS | `:361` correctness: trust-proxy fn called without the hop index | miss (lenient only: security N:361) | **HIT** N:361 | The security agent described it, but as a security finding, and downgraded it for speculative wording. |
| bugsjs-express-9 | BugsJS | `:171` correctness: wrong variable `path` | miss (lenient only: test-coverage N:171) | **HIT** B:171 | Test coverage said "ReferenceError". JS gets a pattern scan rather than ESLint (by design), so no linter catches an undefined variable. |
| testbed-pr1 | testbed | `:1` syntax (whole file indented); `:3` off-by-one | syntax **HIT** B:1 (ruff); off-by-one **HIT** only via that same B:1 | both **HIT** via one B:3 (off-by-one); syntax credited by ±2 | Cross-credit in both arms. Grounding found the off-by-one, but the finding was dropped for having no citation. |
| testbed-pr2 | testbed | `:8–9` concurrency: missing await | **HIT** N:8 (grounding) | **HIT** B:8 | Pipeline's 7 findings include 2 speculative security nits and 4 test nits. |
| testbed-pr3 | testbed | `:4–12` other: reimplements `UserRepository.find_by_id` | **HIT** N:4 (grounding) | miss (lenient only: B:9, a false None claim) | Only grounding can see this; the baseline has no repository context. |
| testbed-pr8-f701890 | testbed | `:1` syntax (whole file indented) | **HIT** B:1 (ruff) | miss; B:17 is false | The baseline did not notice the file cannot parse. |
| clean-express-511d9df | clean (upstream) | none | 0 findings | **false alarm** B:73, N:74 | B:73 is a real behaviour change for array-likes (see A). |
| clean-pysnooper-2b4b64b | clean (upstream) | none | 0 | 0 | |
| clean-thefuck-9e8b4f5 | clean (upstream) | none | 4 N (1 speculative security, 3 test) | 2 N (existing code) | |
| clean-thefuck-e288343 | clean (upstream) | none | 1 N (test, general) | 0 | |
| testbed-pr5 | clean (testbed) | none | 2 N | 0 | **Grounding advised against the fix.** It said "existing queries use f-strings; this change uses a parameterized query" (see F5). |
| testbed-pr6 | clean (testbed) | none | 2 N (hardcoded key in unchanged code, "existing") | 0 | |
| testbed-pr7 | clean (testbed) | none | 3 N (test) | 1 N (security) | |
| testbed-pr8-584b17d | clean (testbed) | none | 1 N (test) | **false alarm** B:10 (false) | |

## C. Per-agent contribution (pipeline)

| Agent | Model | Calls | Headline hits (harness) | Headline hits from findings that survived | Bugs only it caught | Bugs its message described correctly (manual, any category) |
|---|---|---|---|---|---|---|
| static_analysis (ruff, bandit; JS pattern scan) | none | 20 | 4 | 3 (+1 pr1 cross-credit) | pysnooper-3, testbed-pr8-f701890 syntax (and pr1 syntax) | pysnooper-3, pr1 syntax, pr8 syntax |
| grounding | 20b | 8 (testbed only) | 4 | **2** | testbed-pr2, testbed-pr3 | pr2, pr3, and pr1 off-by-one (dropped) |
| test_coverage | 20b | 20 | 0 (category is always "testing") | 0 | none | **7**: pysnooper-3, thefuck-21, thefuck-32, express-9, testbed-pr2 clearly; thefuck-29 and thefuck-5 in part |
| security | 120b | 20 | 0 | 0 | none | express-2 (as security, speculative) |
| diff_intent | 20b | 20 | not applicable | | | |

- The harness's per-agent figure counts raw findings even when anchoring dropped them, which is why grounding is credited with both pr1 bugs (see F3).
- Baseline: 10 headline hits, all from its single agent.

**In substance, the pipeline noticed more bugs than the baseline.** It showed a finding describing 11 of 13 bugs, counting the two partial descriptions; the baseline described 9 of 13. But 7 of those 11 were filed as "testing" or "security" nits by agents that do not own correctness, so they neither count nor block.

## D. Rate limits and schedule

### Measured headers

These are from the first calls; both models report the same limits.

| Header | gpt-oss-20b | gpt-oss-120b |
|---|---|---|
| `x-ratelimit-limit-requests` (per day) | 1000 | 1000 |
| `x-ratelimit-limit-tokens` (**per minute**) | 8000 | 8000 |
| `x-ratelimit-remaining-requests`, first call | 999 | 998 |
| `x-ratelimit-reset-requests`, first call | 1m26.4s | 2m52.8s |
| Lowest `remaining-tokens` seen in the run | 1447 | 6016 |
| `remaining-requests` at the last call | 972 | 961 |

- **Daily tokens:** the headers carry no daily token limit. The ~200K tokens/day figure is your account's stated limit, which I have not measured. Groq names it only in the body of a 429.
- **Request limit:** 1000 per day matches what you told me.
- **Tokens per minute:** the 8000-token limit is the per-minute ceiling to plan around.
  - On testbed cases the pipeline used up to **7,377 gpt-oss-20b tokens in about 5 s**, 92% of a minute's budget.
  - There were no 429s at 60 s spacing. TEST has more retrieval cases, though, so a large one may hit the minute limit; that shows up as a wait of up to 30 s, not an invalid run.
- **Other Groq use:** the first call showed 999/998 requests remaining, so nothing else had used Groq in the preceding window.

### Tokens used today (all from this run)

| Model | Input | Output | Total | Requests | ≈ Share of ~200K/day |
|---|---|---|---|---|---|
| gpt-oss-20b | 36,410 | 30,632 | 67,042 | 48 | 34% |
| gpt-oss-120b | 32,811 | 14,791 | 47,602 | 40 | 24% |

### Measured tokens per run

| Arm | Agent | Model | Tokens per call | Notes |
|---|---|---|---|---|
| Pipeline | diff_intent | 20b | 625 | |
| Pipeline | test_coverage | 20b | 1,660 | |
| Pipeline | grounding | 20b | 2,666 | retrieval cases only |
| Pipeline | security | 120b | 1,011 | |
| Baseline | baseline | 120b | 1,369 | 1,526 on testbed cases |

Per pipeline run, gpt-oss-20b uses about **2,057 tokens without retrieval** and **5,294 with retrieval** (7,377 at most). That is lower than the dry-run estimate (4,400). The gpt-oss-120b figures match it.

### Recomputed schedule

The schedule assumes the current pipeline and ~200K tokens/day per model. Requests are not a constraint: under 110 per model per day.

| Block | Runs | Day split | gpt-oss-20b per day | gpt-oss-120b per day | Dev-stack headroom per day |
|---|---|---|---|---|---|
| DEV round 2, 1 run (as in run 1) | 20 pipeline + 20 baseline | 1 day, ~45 min | ~67K | ~48K | ~133K 20b, ~152K 120b (~25 live reviews) |
| DEV round 2, 3 runs (*recommended*, so stability is measured before the freeze) | 60 pipeline + 60 baseline | 2 days: 35p+30b, 25p+30b | ≤118K | ≤77K | ≥82K 20b (~15 live reviews) |
| Freeze tag | 0 | same day as approval | none | none | none |
| TEST, 3 runs × 30 cases × 2 arms | 90 pipeline + 90 baseline | **3 days: 35p+30b, 35p+30b, 20p+30b** | ≤133K (TEST averages ~3.8K per run: 16 of 30 cases use retrieval) | ≤78K | ≥67K 20b (~12 live reviews), ≥120K 120b |

Each eval day takes about 70 minutes of wall-clock time at ≥60 s spacing.

**If proposal P1 is approved, the budget changes.**
- On gpt-oss-120b, P1 adds about 1.4K tokens per pipeline run: TEST reaches ~127K 120b per day, which still fits.
- On gpt-oss-20b it would add ~1.7K per run, pushing gpt-oss-20b to ~190K per day at 35 runs. The cap would then have to fall to ~25 pipeline runs a day, and TEST pipeline would take 4 days.
- That budget is one more reason to put P1 on gpt-oss-120b.

## E. Tuning proposals (none applied)

### P1. Add a correctness reviewer: one agent owns logic, error-handling and concurrency defects in changed lines

- **Rule:** every defect class the review reports needs an owning agent. Today nothing owns correctness, so the only agents that notice it file it as "untested" or "security".
- **Motivated by:**
  - thefuck-21, thefuck-29, thefuck-32, thefuck-5 and express-9: noticed only by test coverage.
  - express-2: noticed only by security, as speculative.
  - thefuck-3: noticed by nobody.
  - Together these are 7 of the 8 benchmark bugs the pipeline missed.
- **Might hurt:**
  - clean-express-511d9df and testbed-pr8-584b17d: a generalist prompt false-alarmed on both in the baseline arm.
  - testbed-pr3 and testbed-pr8-f701890: the baseline produced false blocking findings there.
  - Blocking precision in general.
  - Latency: about +1–1.5 s if it runs alongside the other agents.
  - Cost: about +1.4K gpt-oss-120b tokens per run.
- **Changes:**
  - `apps/agents/agent_prompts.py`: a new `CORRECTNESS_SYSTEM_PROMPT` that reuses the shared injection, line and JSON rules and excludes security.
  - `apps/agents/nodes.py` and `graph.py`: one more parallel node.
  - The budget estimate in `run_eval`.
- **Recommended model:** gpt-oss-120b, for the budget reasons in D.
- **This changes the architecture under test, not just a prompt.** Afterwards TEST would measure "specialists plus a generalist versus a generalist alone". I think that is the honest design, given DEV run 1, but it is your call.

### P2. Alternative to P1, no extra call: the test-coverage agent reports a defect it notices as a defect

- **Rule:** a finding's category describes the defect, not the agent that found it. The test-coverage contract gets a second finding kind, a defect in the changed line, filed as correctness and subject to the normal severity policy. "Missing test" findings stay testing-only and never block.
- **Motivated by:** pysnooper-3, thefuck-21, thefuck-29, thefuck-32, thefuck-5 and express-9, where the test-coverage messages already described the bug.
- **Might hurt:**
  - clean-thefuck-e288343: its test nit ("may cause commands to fail") would become a correctness finding. The speculative-wording downgrade should keep it a nit.
  - The 20b model would be judging defects that a 120b model judges in the baseline.
- **Changes:** `TEST_SYSTEM_PROMPT` in `agent_prompts.py`, and the `policy.py` rule "test coverage is never blocking", which would apply to the testing category only.
- **Recommendation:** P1 over P2. P2 makes one agent do two jobs on the smaller model.

### P3. An undefined name in a complete file is blocking

- **Rule:** ruff F821/F822/F823 reported when the linter had the whole file, not a reconstruction from hunks, is a certain runtime error. It should be blocking like a syntax error. It is already suppressed on partial files.
- **Motivated by:** pysnooper-3, which was found but left as a nit. This improves blocking recall, not headline recall.
- **Might hurt:** nothing observed. Ruff raised no F821 on any DEV clean case. The risk is names injected at runtime (for example builtins added by a framework).
- **Changes:** `apps/agents/static_analysis.py`, the severity mapping (currently `"blocking" if syntax else "nit"`, line 346).

### P4. Grounding: existing code is precedent only when it is not itself a defect

- **Rule:** never report a change as inconsistent with an existing pattern when the change is safer than that pattern: parameterised queries, input validation, closing resources, error handling.
- **Motivated by:** testbed-pr5. Grounding treated the injectable f-string SQL still in the index as the "established pattern" and flagged the fix.
- **Might hurt:** none seen in DEV. It may suppress some valid consistency nits. No headline effect is expected, since it was a nit; this fixes harmful advice.
- **Changes:** `GROUNDING_SYSTEM_PROMPT` in `agent_prompts.py`.

### Not proposed

- The speculative-wording downgrade: it correctly demoted 5 of 6 security findings, which were noise.
- The category map: it is frozen.
- Anything per case.

### Harness proposals (measurement only, both arms)

These change measurement rules that were frozen in 8a. If you approve them, they should be recorded as an amendment before DEV round 2.

- **H1. One-to-one matching.** A finding credits at most one bug (maximum bipartite matching).
  - Motivated by: testbed-pr1 in both arms.
  - DEV effect: pipeline 6 → 5, baseline 10 → 9.
- **H2. Per-agent contribution counts only findings that survived** (outcome `kept`).
  - Motivated by: testbed-pr1, where grounding is credited for a dropped finding.
- **H3. Report recall at blocking severity** next to recall at any severity, since blocking is what a merge-gating reviewer acts on.
  - Motivated by: the pipeline's hits are mostly nits.

## F. Unexpected

1. **The pipeline almost never blocks.**
   - In 20 runs it produced 2 blocking findings, both ruff syntax errors.
   - No LLM finding reached blocking:
     - test coverage is never blocking, by policy;
     - 5 of 6 security findings were downgraded for speculative wording, and the sixth was about unchanged code;
     - grounding emits nits.
   - So its 0/8 false-alarm rate and 2/2 precision come from silence, not judgement.
2. **±2 cross-credit (testbed-pr1).** Two bugs one line apart are both credited from one finding in each arm. Both anchoring "misses" are these cross-credits. See H1.
3. **Per-agent contribution counts dropped findings.** Grounding's pr1 credits come from a finding the citation check dropped. See H2.
4. **Lenient recall is proximity only.**
   - 13/13 for the pipeline includes "untested" nits and unrelated findings, such as ruff S607 on thefuck-3.
   - Judged by meaning, the pipeline described 11/13 and the baseline 9/13.
5. **Grounding recommended making a fix less safe** (testbed-pr5, at nit severity). See P4.
6. **The baseline missed a whole-file syntax error** (testbed-pr8-f701890) and raised 3 false blocking findings on the testbed. Linters complement the LLM where it fails.
7. **Groq rotates backends.** There were 51 distinct `system_fingerprint` values across 88 calls. With 1 run per case, run-to-run stability is unknown; this is why I recommend a 3-run DEV round 2.
8. **The per-minute limit is tight on retrieval cases** (7.4K of 8K gpt-oss-20b tokens in one run). Nothing failed, but watch TEST's larger planted cases.
9. **The baseline cache key covers all of `apps/agents`.** Any pipeline change therefore re-runs the baseline too (20–60 runs in DEV round 2). This is acceptable and is why the budget above includes the baseline.
10. **thefuck-3 is probably beyond a diff-only reviewer.** It needs knowledge of `fish --version` output. It stays in DEV as labelled; DEV is sealed only by choice, so I am noting it, not relabelling it.
11. **The harness ran cleanly.** 40/40 runs were valid, with 0 retries, 0 fallbacks, 0 invalid runs and no daily-limit stops. The ledger has 40 lines, one per run.
