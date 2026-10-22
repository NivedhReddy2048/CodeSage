"""Select and stage reversed BugsJS cases: same rules as build_bugsinpy.py.

Candidates: Bug-N-original -> Bug-N-fix changing exactly one non-test .js file by at
most 20 lines. Selection: seeded shuffle per project ("8-<project>"), then the first
that build as one hunk within the size limits. Usage: python build_bugsjs.py <stage>
"""

import json
import random
import subprocess
import time
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from build_bugsinpy import MAX_DIFF, MAX_FILE, hunks, reversed_diff  # noqa: E402

TOKEN = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PLAN = {"dev": {"express": 2}, "test": {"hexo": 1, "karma": 1, "bower": 1}}


def get(url):
    for attempt in range(6):
        try:
            return requests.get(url, headers=AUTH, timeout=60)
        except requests.RequestException:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GitHub unreachable: {url}")


def candidates(project):
    """Bug numbers from the repository's Bug-N-fix tags, then one compare per bug."""
    tags = subprocess.run(
        ["gh", "api", "--paginate", f"repos/BugsJS/{project}/tags", "--jq", ".[].name"],
        capture_output=True,
        text=True,
    ).stdout.split()
    numbers = sorted({int(t.split("-")[1]) for t in tags if t.startswith("Bug-") and t.endswith("-fix")})
    out = []
    for n in numbers:
        r = get(f"https://api.github.com/repos/BugsJS/{project}/compare/Bug-{n}-original...Bug-{n}-fix")
        if r.status_code != 200:
            continue
        files = r.json().get("files", [])
        src = [f for f in files if f["filename"].endswith(".js") and "test" not in f["filename"].lower()]
        if len(files) == 1 and len(src) == 1 and src[0]["changes"] <= 20:
            out.append({"bug": n, "file": src[0]["filename"]})
    print(f"  {project}: {len(numbers)} bugs, {len(out)} candidates")
    return out


DELETION_CAP = 0.30
REVERSED = {"dev": 8, "test": 13}  # BugsInPy + BugsJS cases per suite


def staged_deletions(stage, suite):
    count = 0
    for case_file in (Path(stage) / suite).glob("*/case.json"):
        case = json.loads(case_file.read_text(encoding="utf-8"))
        count += any(bug.get("kind") == "deletion" for bug in case["bugs"])
    return count


def tag_commit(project, tag):
    """A tag's commit SHA. Raw URLs by tag NAME serve the same file for both tags of a
    bug (verified on bower Bug-2), so files are fetched by SHA, which is unambiguous."""
    ref = get(f"https://api.github.com/repos/BugsJS/{project}/git/ref/tags/{tag}").json()["object"]
    if ref["type"] == "tag":
        ref = get(ref["url"]).json()["object"]
    return ref["sha"]


def fetch_at(project, sha, path):
    r = get(f"https://raw.githubusercontent.com/BugsJS/{project}/{sha}/{path}")
    return r.text if r.status_code == 200 else None


def main(stage):
    for suite, quota in PLAN.items():
        chosen = []
        for project, wanted in quota.items():
            pool = candidates(project)
            random.Random(f"8-{project}").shuffle(pool)
            taken = 0
            for c in pool:
                if taken == wanted:
                    break
                # The tags have diverged from a common ancestor, and GitHub's compare is
                # three-dot: the fix applies to the MERGE BASE, which holds the buggy
                # code. (At bower Bug-2 the file is byte-identical at -original and
                # -fix, so diffing the two tags finds nothing.)
                compare = get(
                    f"https://api.github.com/repos/BugsJS/{project}/compare/"
                    f"Bug-{c['bug']}-original...Bug-{c['bug']}-fix"
                ).json()
                buggy_sha = compare["merge_base_commit"]["sha"]
                fixed_sha = tag_commit(project, f"Bug-{c['bug']}-fix")
                buggy = fetch_at(project, buggy_sha, c["file"])
                fixed = fetch_at(project, fixed_sha, c["file"])
                if buggy is None or fixed is None or len(buggy.encode()) > MAX_FILE:
                    print(f"  skip {project}-{c['bug']}: not fetchable or too big")
                    continue
                diff = reversed_diff(c["file"], fixed, buggy)
                parts = hunks(diff)
                if len(diff.encode()) > MAX_DIFF or len(parts) != 1:
                    print(f"  skip {project}-{c['bug']}: {len(parts)} hunks")
                    continue
                part = parts[0]
                kind = "added" if part["added"] else "deletion"
                # The 30% deletion-only cap covers every reversed case in the suite,
                # BugsInPy's included (already staged), not each dataset separately.
                if kind == "deletion" and staged_deletions(stage, suite) + 1 > DELETION_CAP * REVERSED[suite]:
                    print(f"  skip {project}-{c['bug']}: deletion-only cap reached")
                    continue
                if kind == "added":
                    lines = [min(part["added"]), max(part["added"])]
                else:
                    point = part["deleted_at"][0]
                    lines = [point, point] if point in part["context"] else [point - 1, point - 1]
                cid = f"bugsjs-{project}-{c['bug']}"
                case_dir = Path(stage) / suite / cid
                (case_dir / "files" / Path(c["file"]).parent).mkdir(parents=True, exist_ok=True)
                (case_dir / "files" / c["file"]).write_text(buggy, encoding="utf-8", newline="")
                (case_dir / "diff.patch").write_text(diff, encoding="utf-8", newline="\n")
                case = {
                    "id": cid,
                    "suite": suite,
                    "language": "javascript",
                    "clean": False,
                    "source": {
                        "kind": "bugsjs",
                        "project": project,
                        "bug": c["bug"],
                        "url": f"https://github.com/BugsJS/{project}",
                        "license": "MIT",
                        "buggy_tag": f"Bug-{c['bug']}-original",
                        "fixed_tag": f"Bug-{c['bug']}-fix",
                        "buggy_commit": buggy_sha,  # merge base of -original and -fix
                        "fixed_commit": fixed_sha,
                        "dataset": "https://bugsjs.github.io/",
                    },
                    "context": {
                        "full_name": f"BugsJS/{project}",
                        "pr_number": 0,
                        "title": f"Reversed BugsJS {project} bug {c['bug']}",
                        "base_branch": "master",
                        "head_sha": buggy_sha,
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
                chosen.append(cid + ("*" if kind == "deletion" else ""))
                taken += 1
            if taken < wanted:
                print(f"  {project}: only {taken}/{wanted}")
        print(suite, chosen)


main(sys.argv[1])
