"""Evaluation cases on disk: one directory per case.

    eval/cases/<suite>/<case-id>/
        case.json      metadata and ground truth (format below)
        diff.patch     the change under review, a unified diff
        files/...      the head version of every MODIFIED file, at its repo path; what
                       static analysis lints instead of fetching it from GitHub.
                       Added files need none - the diff is the whole file.

case.json:
    {
      "id": "testbed-pr4", "suite": "test", "language": "python",
      "clean": false,
      "source": {"kind": "testbed|bugsinpy|bugsjs|planted|refactor", "url": "...", ...},
      "context": {"full_name": "owner/repo", "pr_number": 4, "title": "...",
                  "base_branch": "main", "head_sha": "..."},
      "retrieval": null | {"repository": "owner/repo", "index_commit": "<sha>"},
      "bugs": [{"id": "sqli", "file": "app/reports.py", "lines": [9, 9],
                "category": "security", "kind": "added|deletion", "note": "..."}],
      "notes": "..."
    }

`lines` are NEW-file line numbers. For "added" bugs every line in the range must be
one the diff adds. A "deletion" bug (a reversed fix that removes a check) has no added
line; its range is where the removed code was, and must sit inside a hunk.
"""

import hashlib
import json
from pathlib import Path

from apps.agents.diffs import diff_lines, prepare, split_file_sections

KINDS = frozenset({"testbed", "bugsinpy", "bugsjs", "planted", "refactor"})
SUITES = frozenset({"dev", "test"})


class CaseError(ValueError):
    """A fixture that cannot be scored honestly."""


def suite_dir(root, suite):
    return Path(root) / "cases" / suite


def load(case_dir):
    case_dir = Path(case_dir)
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    case["diff"] = (case_dir / "diff.patch").read_text(encoding="utf-8")
    case["dir"] = case_dir
    return case


def load_suite(root, suite):
    base = suite_dir(root, suite)
    if not base.exists():
        return []
    return [load(d) for d in sorted(base.iterdir()) if (d / "case.json").exists()]


def snapshot(case, path):
    """The head version of a modified file, or None (static analysis then lints hunks)."""
    target = (Path(case["dir"]) / "files" / path).resolve()
    if Path(case["dir"]).resolve() not in target.parents or not target.is_file():
        return None
    return target.read_text(encoding="utf-8")


def case_hash(case):
    """Changes whenever anything the pipeline sees or the scorer reads changes."""
    digest = hashlib.sha256()
    for name in ("case.json", "diff.patch"):
        digest.update((Path(case["dir"]) / name).read_bytes())
    files = Path(case["dir"]) / "files"
    if files.exists():
        for path in sorted(p for p in files.rglob("*") if p.is_file()):
            digest.update(str(path.relative_to(files)).replace("\\", "/").encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def validate(case, categories, max_diff_bytes=24_000):
    """Every reason this case cannot be scored honestly. Empty means it is sound."""
    problems = []
    cid = case.get("id", "?")
    if case.get("suite") not in SUITES:
        problems.append(f"{cid}: suite must be one of {sorted(SUITES)}")
    if Path(case["dir"]).name != cid:
        problems.append(f"{cid}: directory name must equal the case id")
    if (case.get("source") or {}).get("kind") not in KINDS:
        problems.append(f"{cid}: source.kind must be one of {sorted(KINDS)}")
    if bool(case.get("clean")) == bool(case.get("bugs")):
        problems.append(f"{cid}: a case is clean (no bugs) or has bugs, not both or neither")

    prepared = prepare(case["diff"], max_diff_bytes)
    if not prepared.files:
        problems.append(f"{cid}: diff.patch parses to no reviewable file")
    if prepared.truncated or prepared.skipped_files:
        problems.append(f"{cid}: diff exceeds the review budget or skips files")
    entries = {entry.path: entry for entry in prepared.files}

    for path, _ in split_file_sections(case["diff"]):
        entry = entries.get(path)
        if entry is not None and not entry.is_new_file and snapshot(case, path) is None:
            problems.append(f"{cid}: modified file {path} has no files/{path} snapshot")
        if entry is not None and not entry.is_new_file and snapshot(case, path) is not None:
            text = snapshot(case, path).splitlines()
            for line in diff_lines(entry.text):
                if line.number and (line.number > len(text) or text[line.number - 1] != line.text):
                    problems.append(
                        f"{cid}: files/{path} line {line.number} does not match the diff"
                    )
                    break

    seen = set()
    for bug in case.get("bugs", []):
        bid = bug.get("id")
        if bid in seen:
            problems.append(f"{cid}: duplicate bug id {bid}")
        seen.add(bid)
        if bug.get("category") not in categories:
            problems.append(f"{cid}/{bid}: category {bug.get('category')!r} is not in the map")
        entry = entries.get(bug.get("file"))
        if entry is None:
            problems.append(f"{cid}/{bid}: {bug.get('file')} is not in the diff")
            continue
        start, end = bug["lines"]
        span = set(range(start, end + 1))
        if start > end:
            problems.append(f"{cid}/{bid}: line range is backwards")
        elif bug.get("kind", "added") == "added":
            if not span <= entry.added_lines:
                problems.append(f"{cid}/{bid}: lines {start}-{end} are not all added lines")
        elif bug.get("kind") == "deletion":
            if not span <= entry.changed_lines:
                problems.append(f"{cid}/{bid}: deletion point {start}-{end} is outside the hunks")
        else:
            problems.append(f"{cid}/{bid}: kind must be 'added' or 'deletion'")

    retrieval = case.get("retrieval")
    if retrieval and not (retrieval.get("repository") and retrieval.get("index_commit")):
        problems.append(f"{cid}: retrieval needs repository and index_commit")
    return problems
