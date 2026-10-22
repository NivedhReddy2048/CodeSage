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
