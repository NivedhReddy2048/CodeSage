"""Select and stage clean refactor commits (no known bug), for false-alarm measurement.

From each project's recent history (first 300 commits on the default branch):
message matches refactor/simplify/cleanup/tidy/rename and NOT fix/bug/issue/revert/#N;
exactly one non-test .py/.js file changes, by 3-30 lines; the file fits the snapshot
limit and the diff the review limit. Seeded shuffle per project ("8-clean-<project>").
"Clean" means no known bug - a limitation stated in the report.

Usage: python build_clean.py <stage>
"""

import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from build_bugsinpy import MAX_DIFF, MAX_FILE, reversed_diff  # noqa: E402

TOKEN = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PLAN = {
    "dev": {"nvbn/thefuck": 2, "cool-RR/PySnooper": 1, "expressjs/express": 1},
    "test": {
        "httpie/cli": 1,
        "cookiecutter/cookiecutter": 1,
        "psf/black": 1,
        "sanic-org/sanic": 1,
        "tornadoweb/tornado": 1,
        "spotify/luigi": 1,
        "fastapi/fastapi": 1,
        "scrapy/scrapy": 1,
        "karma-runner/karma": 1,
    },
}
LICENSES = {
    "nvbn/thefuck": "MIT", "cool-RR/PySnooper": "MIT", "expressjs/express": "MIT",
    "httpie/cli": "BSD-3-Clause", "cookiecutter/cookiecutter": "BSD-3-Clause",
    "psf/black": "MIT", "sanic-org/sanic": "MIT", "tornadoweb/tornado": "Apache-2.0",
    "spotify/luigi": "Apache-2.0", "fastapi/fastapi": "MIT", "scrapy/scrapy": "BSD-3-Clause",
    "karma-runner/karma": "MIT",
}
WANT = re.compile(
    r"\b(refactor\w*|simplif\w*|clean\s?-?up|tidy|tidies|rename\w*|extract\w*|move[sd]?|"
    r"reorgani[sz]\w*|restructur\w*|consolidat\w*|dedup\w*|moderni[sz]\w*|"
    r"type (?:hint|annotation)s?|annotat\w*|improve (?:code|readability|structure))\b",
    re.I,
)
# "(#1234)" is a squash-merged PR number, not an issue, so it is not excluded.
AVOID = re.compile(r"\b(fix\w*|bug\w*|issue\w*|revert\w*|regression|crash\w*|broken|error)\b", re.I)


def get(url, **kw):
    for attempt in range(6):
        try:
            r = requests.get(url, headers=AUTH, timeout=60, **kw)
            if r.status_code in (403, 429):
                time.sleep(5 * (attempt + 1))
                continue
            return r
        except requests.RequestException:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GitHub unreachable: {url}")


def raw(repo, sha, path):
    r = get(f"https://raw.githubusercontent.com/{repo}/{sha}/{path}")
    return r.text if r.status_code == 200 else None


def candidates(repo):
    commits = []
    for page in range(1, 11):
        batch = get(f"https://api.github.com/repos/{repo}/commits", params={"per_page": 100, "page": page}).json()
        if not isinstance(batch, list) or not batch:
            break
        commits += batch
    return [
        c for c in commits
        if len(c.get("parents", [])) == 1
        and WANT.search(c["commit"]["message"].splitlines()[0])
        and not AVOID.search(c["commit"]["message"])
    ]


def main(stage):
    for suite, quota in PLAN.items():
        chosen = []
        for repo, wanted in quota.items():
            pool = candidates(repo)
            random.Random(f"8-clean-{repo}").shuffle(pool)
            taken = 0
            for c in pool:
                if taken == wanted:
                    break
                detail = get(f"https://api.github.com/repos/{repo}/commits/{c['sha']}").json()
                files = detail.get("files", [])
                src = [
                    f for f in files
                    if f["filename"].endswith((".py", ".js"))
                    and not re.search(r"test|spec|docs?/|examples?/", f["filename"], re.I)
                ]
                # Exactly one source file; tests and docs alongside it are allowed, but
                # only the source file's diff is reviewed (stated in the case notes).
                if len(src) != 1 or not 3 <= src[0]["changes"] <= 30:
                    continue
                path, parent = src[0]["filename"], c["parents"][0]["sha"]
                before, after = raw(repo, parent, path), raw(repo, c["sha"], path)
                if before is None or after is None or len(after.encode()) > MAX_FILE:
                    continue
                # Not reversed: the refactor as it was committed, parent -> commit.
                diff = reversed_diff(path, before, after)
                if not diff or len(diff.encode()) > MAX_DIFF:
                    continue
                project = repo.split("/")[1].lower()
                cid = f"clean-{project}-{c['sha'][:7]}"
                case_dir = Path(stage) / suite / cid
                (case_dir / "files" / Path(path).parent).mkdir(parents=True, exist_ok=True)
                (case_dir / "files" / path).write_text(after, encoding="utf-8", newline="")
                (case_dir / "diff.patch").write_text(diff, encoding="utf-8", newline="\n")
                title = c["commit"]["message"].splitlines()[0][:200]
                case = {
                    "id": cid,
                    "suite": suite,
                    "language": "javascript" if path.endswith(".js") else "python",
                    "clean": True,
                    "source": {
                        "kind": "refactor",
                        "project": repo,
                        "url": f"https://github.com/{repo}/commit/{c['sha']}",
                        "license": LICENSES[repo],
                        "commit": c["sha"],
                        "parent": parent,
                        "message": title,
                    },
                    "context": {
                        "full_name": repo,
                        "pr_number": 0,
                        "title": title,
                        "base_branch": "main",
                        "head_sha": c["sha"],
                    },
                    "retrieval": None,
                    "bugs": [],
                    "notes": "An upstream refactor commit with no known bug. Clean means no "
                    "KNOWN bug; any blocking finding counts as a false alarm. Only the "
                    f"source file's diff is reviewed; the commit changed {len(files)} file(s).",
                }
                (case_dir / "case.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
                chosen.append(f"{cid}: {title[:60]}")
                taken += 1
            if taken < wanted:
                print(f"  {repo}: only {taken}/{wanted}")
        print(suite)
        for line in chosen:
            print("   ", line)


main(sys.argv[1])
