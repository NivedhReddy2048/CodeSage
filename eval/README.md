# Evaluation fixtures and results (Phase 8)

Method, dataset and results: [docs/EVALUATION.md](../docs/EVALUATION.md).

```
eval/
  categories.json            frozen category-equivalence map used by the matcher
  cases/dev/<case-id>/        DEV set: may be used to tune prompts
  cases/test/<case-id>/       TEST set: sealed before any DEV result, run once at an
                              eval-freeze-* tag
    case.json                 metadata and ground truth (format: backend/apps/evaluation/cases.py)
    diff.patch                the change under review
    files/<repo path>         head version of each modified file (static analysis lints it)
  results/<suite>/<arm>/<case-id>/run-<n>.json   one cached result per run
  results/ledger.jsonl        every attempt, valid or not, by UTC day (the quota cap)
```

```bash
cd backend
python manage.py run_eval --check                         # validate fixtures, no LLM call
python manage.py run_eval --suite dev --runs 1 --dry-run  # what would run, and its quota
python manage.py run_eval --suite dev --runs 1            # run; resumes from the cache
python manage.py run_eval --suite dev --report            # score cached results
```

Rules the harness enforces:

- **No fallback.** The Gemini LLM fallback is off. A run where a model-backed agent
  failed at the provider or fell back is invalid: retried with backoff, then stored
  invalid and excluded from every metric (counted in the report).
- **Quota.** At most 35 multi-agent runs per UTC day (Groq limits are per organisation;
  the rest is headroom for the dev stack), and at least 60 s between runs.
- **Cache.** A result is reused while its case hash and pipeline version (a hash of
  `backend/apps/agents` and the model ids) match.
- **Sealed TEST.** `--suite test` runs only at a commit tagged `eval-freeze-*` with no
  local change to the pipeline, the cases or the category map.
