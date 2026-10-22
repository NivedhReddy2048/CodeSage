# TEST set (held out)

Sealed: committed and merged before the first DEV run, so no TEST case could have been
shaped by a DEV result. It runs **once**, after prompt tuning on DEV is finished, at a
commit tagged `eval-freeze-*` with no local change to the pipeline, the cases or the
category map; `run_eval --suite test` refuses otherwise.

30 cases, 9 clean (30%), 25 bugs:

- `testbed-pr4`: the five planted bugs, including the two known misses (unclosed
  connection, missing not-found check). It was reviewed live during development,
  so it is the one TEST case that is not unseen.
- `planted-*` (7): written for TEST against the testbed index at `8934446`. Four
  need the codebase (grounding):
  - refund-dollars: dollars subtracted from `total_cents`;
  - signup-email: reimplements `is_valid_email`;
  - change-email: skips `register`'s validation;
  - admin-renamed: calls a nonexistent `get_by_id`.
  Three are planted bugs in spec categories DEV lacks: order-permission (wrong
  permission check), profile-null (missing null check, JS), export-leak (resource
  leak, JS).
- `bugsinpy-*` (10) and `bugsjs-*` (3): upstream fixes reversed, from projects
  that do not appear in DEV. Three are deletion-only (30%).
- `clean-*` (9): upstream refactor commits with no known bug.

Selection and labelling: [eval/tools/README.md](../../tools/README.md).
