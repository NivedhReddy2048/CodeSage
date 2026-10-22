"""Hand labels for the reversed benchmark cases: category and a one-line note each."""

import json
import sys
from pathlib import Path

LABELS = {
    # DEV
    "bugsinpy-pysnooper-3": ("correctness", "Writes to output_path, a name that does not exist here (NameError); the parameter is output."),
    "bugsinpy-thefuck-21": ("error-handling", "Indexes split()[1] without checking the length: a one-word command raises IndexError."),
    "bugsinpy-thefuck-3": ("correctness", "Parses `fish --version` output by its last word, which is not the version on every fish build."),
    "bugsinpy-thefuck-5": ("correctness", "Matches any output containing 'set-upstream', so the rule fires on unrelated git errors."),
    "bugsinpy-thefuck-29": ("correctness", "update() lets kwargs override settings already set; it should only fill unset ones."),
    "bugsinpy-thefuck-32": ("correctness", "`'ls' in command.script` matches any command containing 'ls' (e.g. `false`)."),
    "bugsjs-express-2": ("correctness", "Calls the trust-proxy function without the hop index argument."),
    "bugsjs-express-9": ("correctness", "Sets mountpath from `path`, the wrong variable, instead of mount_path."),
    # TEST
    "bugsinpy-httpie-3": ("error-handling", "Removes the None check: an explicitly unset header (None) is then .decode()d and raises."),
    "bugsinpy-cookiecutter-3": ("correctness", "Drops show_choices=False, so the choices are printed twice in the prompt."),
    "bugsinpy-spacy-2": ("correctness", "Removes config.update(overrides): component overrides are silently ignored."),
    "bugsinpy-spacy-4": ("correctness", "Treats '_' as a real head index: int('_') fails, or the head is wrong, for empty heads."),
    "bugsinpy-black-19": ("correctness", "Removes the rule against blank lines between a comment and a decorator."),
    "bugsinpy-sanic-1": ("correctness", "Response middleware is appended instead of prepended, reversing its run order."),
    "bugsinpy-tornado-11": ("correctness", "Transfer-Encoding is compared case-sensitively, so 'Chunked' bodies are not decoded."),
    "bugsinpy-luigi-28": ("correctness", "Case-sensitive table lookup; Hive lowercases names, so existing tables are reported missing."),
    "bugsinpy-fastapi-5": ("correctness", "Reuses the original field objects instead of cloning them, so the response model leaks fields."),
    "bugsinpy-scrapy-18": ("error-handling", "Decodes Content-Disposition strictly: a non-UTF-8 header raises instead of being replaced."),
    "bugsjs-hexo-5": ("correctness", "is_current no longer normalises a leading slash, so relative paths never match."),
    "bugsjs-karma-1": ("correctness", "The URL pattern now requires http://host/, missing relative /base and /absolute paths."),
    "bugsjs-bower-3": ("correctness", "Replaces only the first '%' placeholder; the global regex was dropped."),
}

stage = Path(sys.argv[1])
done = 0
for case_file in sorted(stage.glob("*/*/case.json")):
    case = json.loads(case_file.read_text(encoding="utf-8"))
    if case["id"] not in LABELS:
        assert all(b["category"] != "TODO" for b in case["bugs"]), case["id"]
        continue
    category, note = LABELS[case["id"]]
    case["bugs"][0]["category"] = category
    case["bugs"][0]["note"] = note + " (Lines the upstream fix changed, re-introduced here.)"
    case_file.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
    done += 1
missing = set(LABELS) - {p.parent.name for p in stage.glob("*/*/case.json")}
assert not missing, missing
print("labelled", done)
