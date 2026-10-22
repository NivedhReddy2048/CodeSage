"""Select and stage reversed BugsInPy cases. Deterministic: seed "8-<project>".

The "PR" under review is the fix reversed: base = the fixed file, head = the buggy one,
so the change re-introduces the bug and the fix's lines are the ground truth. The
diff is rebuilt with difflib from the two real file versions, so its line numbers are
exact. Categories are labelled by hand afterwards (left as "TODO" here).

Usage: python build_bugsinpy.py <candidates.json> <stage_dir>
"""

import difflib
import json
import random
import sys
from pathlib import Path

import requests

PLAN = {
    "dev": {"thefuck": 5, "PySnooper": 1},
    "test": {
        "httpie": 1,
        "cookiecutter": 1,
        "spacy": 2,  # youtube-dl files no longer fetchable at the recorded commits
        "black": 1,
        "sanic": 1,
        "tornado": 1,
        "luigi": 1,
        "fastapi": 1,
        "scrapy": 1,
    },
}
LICENSES = {
    "thefuck": "MIT", "PySnooper": "MIT", "httpie": "BSD-3-Clause", "cookiecutter": "BSD-3-Clause",
    "youtube-dl": "Unlicense", "black": "MIT", "sanic": "MIT", "tornado": "Apache-2.0",
    "luigi": "Apache-2.0", "fastapi": "MIT", "scrapy": "BSD-3-Clause", "spacy": "MIT",
}
# Excluded by hand, with the reason recorded. Kept to cases where no reviewer could
# see a defect in the changed file at all.
EXCLUDED = {
    ("spacy", 10): "the fix only adds an error-message constant to errors.py; the logic "
    "that uses it is not in the diff, so the change shows no observable defect",
}
MAX_FILE = 256 * 1024
MAX_DIFF = 24_000
DELETION_CAP = 0.30


def fetch(repo, sha, path):
    r = requests.get(f"https://raw.githubusercontent.com/{repo}/{sha}/{path}", timeout=30)
    return r.text if r.status_code == 200 else None


def reversed_diff(path, fixed, buggy):
    # difflib does not write git's "\ No newline at end of file": a last line without a
    # newline would run into the next diff line (seen on PySnooper's generate_authors).
    body = "".join(
        line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
        for line in difflib.unified_diff(
            fixed.splitlines(keepends=True),
            buggy.splitlines(keepends=True),
            f"a/{path}",
            f"b/{path}",
            n=3,
        )
    )
    return f"diff --git a/{path} b/{path}\n{body}" if body else ""


def hunks(diff):
    """[(added new-file lines, context new-file lines, deletion points)] per hunk."""
    out, number, current = [], None, None
    for line in diff.splitlines():
        if line.startswith("@@"):
            number = int(line.split("+")[1].split(",")[0].split(" ")[0])
            current = {"added": [], "context": [], "deleted_at": []}
            out.append(current)
            continue
        if current is None or line.startswith(("---", "+++")):
            continue
        if line.startswith("+"):
            current["added"].append(number)
            number += 1
        elif line.startswith("-"):
            current["deleted_at"].append(number)
        else:
            current["context"].append(number)
            number += 1
    return out


def main(candidates_path, stage):
    candidates = json.load(open(candidates_path, encoding="utf-8"))
    log = []
    for suite, quota in PLAN.items():
        chosen = []
        for project, wanted in quota.items():
            pool = [c for c in candidates if c["project"] == project]
            # Seeded per project, so swapping one project cannot shift another's picks.
            random.Random(f"8-{project}").shuffle(pool)
            taken = 0
            for c in pool:
                if taken == wanted:
                    break
                buggy = fetch(c["repo"], c["buggy"], c["file"])
                fixed = fetch(c["repo"], c["fixed"], c["file"])
                reason = EXCLUDED.get((project, c["bug"]), "")
                if reason:
                    reason = f"excluded by hand: {reason}"
                elif buggy is None or fixed is None:
                    reason = "file not fetchable at both commits"
                elif len(buggy.encode()) > MAX_FILE:
                    reason = "file over 256 KB"
                diff = reversed_diff(c["file"], fixed, buggy) if not reason else ""
                parts = hunks(diff) if diff else []
                if not reason and len(diff.encode()) > MAX_DIFF:
                    reason = "diff over 24 KB"
                if not reason and len(parts) != 1:
                    reason = f"{len(parts)} hunks (one bug must be one range)"
                if not reason:
                    kind = "added" if parts[0]["added"] else "deletion"
                    deletions = sum(1 for x in chosen if x["kind"] == "deletion")
                    if kind == "deletion" and (deletions + 1) > DELETION_CAP * sum(quota.values()):
                        reason = "deletion-only cap reached"
                log.append(f"{suite} {project}-{c['bug']}: {reason or 'TAKEN'}")
                if reason:
                    continue
                part = parts[0]
                if kind == "added":
                    lines = [min(part["added"]), max(part["added"])]
                else:
                    point = part["deleted_at"][0]
                    lines = [point, point] if point in part["context"] else [point - 1, point - 1]
                cid = f"bugsinpy-{project.lower()}-{c['bug']}"
                case_dir = Path(stage) / suite / cid
                (case_dir / "files" / Path(c["file"]).parent).mkdir(parents=True, exist_ok=True)
                (case_dir / "files" / c["file"]).write_text(buggy, encoding="utf-8", newline="")
                (case_dir / "diff.patch").write_text(diff, encoding="utf-8", newline="\n")
                case = {
                    "id": cid,
                    "suite": suite,
                    "language": "python",
                    "clean": False,
                    "source": {
                        "kind": "bugsinpy",
                        "project": project,
                        "bug": c["bug"],
                        "url": f"https://github.com/{c['repo']}",
                        "license": LICENSES[project],
                        "buggy_commit": c["buggy"],
                        "fixed_commit": c["fixed"],
                        "dataset": "https://github.com/soarsmu/BugsInPy",
                    },
                    "context": {
                        "full_name": c["repo"],
                        "pr_number": 0,
                        # Neutral, the same for buggy and clean cases: nothing in the
                        # title may hint at a bug (seal amendment, docs/EVALUATION.md).
                        "title": f"Update {c['file']}",
                        "base_branch": "main",
                        "head_sha": c["buggy"],
                    },
                    "retrieval": None,
                    "bugs": [
                        {
                            "id": "fix",
                            "file": c["file"],
                            "lines": lines,
                            "category": "TODO",
                            "kind": kind,
                            "note": "Lines the upstream fix changed (reversed: re-introduced here).",
                        }
                    ],
                    "notes": "Reversed upstream fix; grounding disabled (repository not indexed).",
                }
                (case_dir / "case.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
                chosen.append({"id": cid, "kind": kind})
                taken += 1
            if taken < wanted:
                log.append(f"{suite} {project}: only {taken}/{wanted} usable")
        print(suite, [c["id"] + ("*" if c["kind"] == "deletion" else "") for c in chosen])
    Path(stage, "selection.log").write_text("\n".join(log) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(*sys.argv[1:])
