"""Scan BugsInPy for small single-file source fixes; write candidate summaries.

Usage: python scan_bugsinpy.py <out.json> <project> [<project> ...]
Reads GitHub only (API via `gh auth token`, raw files via raw.githubusercontent.com).
"""

import json
import re
import subprocess
import sys
import time

import requests

TOKEN = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
API = "https://api.github.com/repos/soarsmu/BugsInPy/contents/projects"
H = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github.raw"}


def raw(url):
    for _ in range(3):
        r = requests.get(url, headers=H, timeout=30)
        if r.status_code == 200:
            return r.text
        time.sleep(1)
    return None


def info(text):
    return dict(re.findall(r'(\w+)="([^"]*)"', text or ""))


def files_in_patch(patch):
    return re.findall(r"^diff --git a/(\S+) b/", patch, re.M)


def changed_count(patch):
    return sum(
        1
        for line in patch.splitlines()
        if (line.startswith("+") or line.startswith("-")) and not line.startswith(("+++", "---"))
    )


out = []
for project in sys.argv[2:]:
    pinfo = info(raw(f"{API}/{project}/project.info"))
    repo = pinfo["github_url"].rstrip("/").removeprefix("https://github.com/")
    listing = requests.get(f"{API}/{project}/bugs", headers={"Authorization": f"Bearer {TOKEN}"}, timeout=30).json()
    for entry in sorted(listing, key=lambda e: int(e["name"])):
        n = entry["name"]
        binfo = info(raw(f"{API}/{project}/bugs/{n}/bug.info"))
        patch = raw(f"{API}/{project}/bugs/{n}/bug_patch.txt") or ""
        files = files_in_patch(patch)
        src = [f for f in files if f.endswith(".py") and "test" not in f.lower()]
        if len(files) != 1 or len(src) != 1:
            continue
        changes = changed_count(patch)
        if changes > 20:
            continue
        out.append(
            {
                "project": project,
                "repo": repo,
                "bug": int(n),
                "file": src[0],
                "buggy": binfo.get("buggy_commit_id"),
                "fixed": binfo.get("fixed_commit_id"),
                "changed_lines": changes,
                "patch": patch,
            }
        )
    print(project, sum(1 for o in out if o["project"] == project), "candidates", file=sys.stderr)

json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), indent=1)
