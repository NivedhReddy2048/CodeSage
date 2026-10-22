# Evaluation (Phase 8)

How well does CodeSage review code, compared with a single LLM prompt? This document
gives the method, the dataset and, once the runs are done, the results. Spec section 16
describes the original plan; this is what was actually built.

## Method

**Two arms**, run on the same stored diffs, in-process, with no GitHub and no
webhooks (`manage.py run_eval`):

- **Pipeline:** the full multi-agent review. Diff/intent, security and test coverage
  run on `gpt-oss-20b` and `gpt-oss-120b`; grounding retrieves from the indexed testbed
  for testbed cases; static analysis lints the real files.
- **Baseline:** one prompt to `gpt-oss-120b`, with the same numbered diff, anchoring
  and severity post-processing, and no agents, retrieval or linters. Most pipeline
  agents use the smaller `gpt-oss-20b`, so the baseline is not handicapped on model
  size.

**Matching** (`backend/apps/evaluation/matching.py`):

- **Headline:** same file, within ±2 lines of the bug, a finding category accepted by
  the frozen `eval/categories.json` for the bug's category, and anchored to a line.
- **Lenient:** ±3 lines, any category, any placement.

**Counts, not percentages.** Every rate is k/n with a 95% Wilson interval. A bug
counts as caught when more than half of its valid runs catch it.

**No fallback.** The Gemini LLM fallback is off. A run where any model-backed agent
failed at the provider or fell back is invalid: retried, then excluded and counted.

**DEV and TEST.** DEV (20 cases) may be used to tune prompts. TEST (30 cases) was
sealed before any DEV result existed, and runs once, at an `eval-freeze-*` tag.

### Seal and its amendment

- **Seal:** TEST sealed at `e4d42b9` (PR #112; TEST content `6a0726c`).
- **Amendment** (issue #113, before any run):
  - removed answer-revealing docstrings and comments from the indexed testbed (testbed
    `a6ddd12`, re-indexed), moving the recorded index commit of the 16 retrieval cases
    from `8934446` to `a6ddd12`;
  - gave every non-testbed case the neutral title `Update <path>` with no body, and
    named upstream repositories instead of the BugsJS forks.
- **What changed:** only those case fields. No diff, snapshot or ground truth changed.
- **No results existed** at either point.

Full detail: [eval/tools/README.md](../eval/tools/README.md#seal-amendment-before-any-run).

## Dataset

See [eval/README.md](../eval/README.md) and
[eval/cases/test/README.md](../eval/cases/test/README.md). DEV: 20 cases (8 clean).
TEST: 30 cases (9 clean, 25 bugs).

## Results

Pending: DEV runs first, then TEST once at the freeze tag.
