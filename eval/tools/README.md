# Building the evaluation fixtures

These scripts produced every case under `eval/cases/`. They read GitHub only (the API
through `gh auth token`, raw files from raw.githubusercontent.com), make no LLM call,
and are deterministic: re-running them reproduces the same selection.

```bash
python scan_bugsinpy.py candidates.json thefuck PySnooper httpie cookiecutter \
    youtube-dl black sanic tornado luigi fastapi scrapy spacy
python build_bugsinpy.py candidates.json stage    # reversed BugsInPy cases
python build_bugsjs.py stage                      # reversed BugsJS cases
python build_clean.py stage                       # clean upstream refactors
python build_testbed.py stage                     # testbed PRs + new TEST cases
python label.py stage                             # hand-assigned bug categories
# then: move stage/dev and stage/test under <root>/cases/, copy categories.json, and
python manage.py run_eval --check --root <root>
```

**Selection rules** (also in each script's docstring):

- **Reversed fixes.** The "PR" re-introduces an upstream bug: base = the fixed file,
  head = the buggy file; the fix's lines are the ground truth. Candidates change one
  non-test source file by at most 20 lines, rebuild as a single hunk, and fit the
  limits (256 KB file, 24 KB diff). Deletion-only cases (a reversed fix that removes
  a check) are capped at 30% of a suite's reversed cases.
- **Order.** A seeded shuffle per project (`"8-<project>"`), then the first candidates
  that pass. Recorded deviations:
  - youtube-dl's files are no longer fetchable at the recorded commits, so its two
    TEST slots went to spaCy;
  - spaCy bug 10 was excluded by hand: its fix only adds an error-message constant,
    so the diff shows no observable defect.
- **BugsJS.** `Bug-N-original` and `Bug-N-fix` diverge from a common ancestor, and the
  fix applies to that merge base, so the merge base is the buggy version. At bower
  Bug-2 the file is byte-identical at the two tags.
- **Clean cases.** Upstream commits whose message reads as a refactor or cleanup and
  never mentions a fix, bug, issue, revert, regression, crash, "broken" or "error",
  changing exactly one source file by 3-30 lines. "Clean" means no KNOWN bug. Tests
  and docs in the same commit are not part of the reviewed diff.
- **Licenses.** Only permissive licenses (MIT, BSD-3-Clause, Apache-2.0); GPL
  projects (e.g. ansible) are excluded. See THIRD_PARTY_NOTICES.md.

## Seal amendment (before any run)

The TEST set was sealed at `e4d42b9` (PR #112; TEST content `6a0726c`). Before any
evaluation run, a review of what the pipeline would see found answer leaks, and they
were removed in one amendment (issue #113):

1. **The testbed index.** Testbed `main` carried four `BUG (...)` docstrings
   (`app/orders.py` x2, `app/users.py` x2), one `// BUG (missing await)` comment
   (`web/users.js`) and a README saying the service exists to exercise CodeSage's
   review. Grounding could retrieve any of them. They were removed or neutralised
   (docstring, comment and README text only; no behaviour change) in testbed commit
   `a6ddd12`, and the testbed was re-indexed at it. Every retrieval case's
   `retrieval.index_commit` moved from `8934446` to `a6ddd12` (16 cases: 9 testbed,
   7 planted).
2. **Titles and repository names.** The baseline prompt includes the PR title, which
   said "Reversed BugsInPy <project> bug <n>" for every benchmark case and repeated
   the commit message for clean ones. BugsJS cases also named `BugsJS/<project>` as
   the repository, which the intent agent sees. Every non-testbed case now has the
   title `Update <path>` (41 cases, buggy and clean alike) and no body; the five
   BugsJS cases name their upstream repository. Testbed PRs keep their real titles,
   none of which reveals a bug.

Only `context.title`, `context.full_name` and `retrieval.index_commit` changed. No
diff, file snapshot or ground truth changed. No evaluation result existed at the
original seal or at the amendment; `eval/results/` was empty and no commit had ever
touched it. The builders here produce the amended cases (verified byte for byte for
the testbed and planted cases).
