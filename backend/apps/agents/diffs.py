"""Unified-diff parsing, filtering and truncation.

Two jobs that both protect the review:

1. **Keep the prompt inside the token budget.** Groq's live rate-limit headers report
   8000 tokens per minute, so an unbounded diff would be rejected outright or starve
   the next review. Lock files and generated output are also pure noise to a
   reviewer, so dropping them improves the result as well as the cost.

2. **Know which lines are real.** A model will cheerfully cite a line that is not in
   the diff. Recording the changed line numbers per file lets the caller drop those
   findings rather than posting a comment anchored to the wrong place.
"""

import re

from apps.agents.types import DiffFile, PreparedDiff

FILE_HEADER = re.compile(r"^\+\+\+ b/(.+)$")
OLD_FILE_HEADER = re.compile(r"^--- a/(.+)$")
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

# Mirrors the ingestion skip rules, kept separate because this package must not
# import Django and the two lists serve different stages.
SKIP_DIRECTORIES = (
    "node_modules/",
    "vendor/",
    "dist/",
    "build/",
    ".next/",
    "__pycache__/",
    "site-packages/",
    "migrations/",
)

SKIP_FILENAMES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "Pipfile.lock",
        "uv.lock",
        "Cargo.lock",
        "composer.lock",
        "Gemfile.lock",
        "go.sum",
    }
)

SKIP_SUFFIXES = (
    ".min.js",
    ".min.css",
    ".map",
    ".lock",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".pdf",
    ".zip",
    ".gz",
    ".woff",
    ".woff2",
    ".ttf",
    ".snap",
    "_pb2.py",
)

BINARY_MARKER = "Binary files"


def should_skip(path):
    name = path.rsplit("/", 1)[-1]
    if name in SKIP_FILENAMES:
        return True
    if any(segment in path for segment in SKIP_DIRECTORIES):
        return True
    return any(path.endswith(suffix) for suffix in SKIP_SUFFIXES)


def split_file_sections(diff_text):
    """Split a unified diff into `(path, section_text)` pairs.

    Splits on `diff --git` when present, and falls back to `--- a/` headers so a
    bare diff (the shape most test fixtures and `git diff` pipes produce) still
    parses.
    """
    if not diff_text:
        return []

    lines = diff_text.splitlines(keepends=True)
    sections = []
    current = []

    for line in lines:
        starts_file = line.startswith("diff --git ") or (line.startswith("--- ") and not current)
        if starts_file and current:
            sections.append(current)
            current = [line]
        elif line.startswith("diff --git ") and current:
            sections.append(current)
            current = [line]
        else:
            current.append(line)

    if current:
        sections.append(current)

    result = []
    for section in sections:
        text = "".join(section)
        path = _path_for(section)
        if path:
            result.append((path, text))
    return result


def _path_for(section_lines):
    for line in section_lines:
        stripped = line.rstrip("\n")

        match = FILE_HEADER.match(stripped)
        if match:
            return match.group(1).strip()

        # A deletion is "+++ /dev/null", which FILE_HEADER's "b/" prefix does not
        # match. Returning here rather than falling through is what stops the
        # "--- a/<path>" fallback below resurrecting a file that no longer exists:
        # it would be sent to the model with no citable lines, spending tokens on a
        # change nobody can act on.
        if stripped.startswith("+++ ") and stripped[4:].strip() == "/dev/null":
            return None

    # No "+++" header at all: a bare diff fragment. Fall back to the old path so
    # fixtures and piped `git diff` output still parse.
    for line in section_lines:
        match = OLD_FILE_HEADER.match(line.rstrip("\n"))
        if match and match.group(1).strip() != "/dev/null":
            return match.group(1).strip()
    return None


def changed_lines(section_text):
    """Line numbers in the NEW file touched by this section.

    Context lines are included as well as additions: a finding may legitimately
    point at an unchanged line inside a hunk, and GitHub will anchor a comment there.
    """
    numbers = set()
    line_number = None

    for raw in section_text.splitlines():
        hunk = HUNK_HEADER.match(raw)
        if hunk:
            line_number = int(hunk.group(1))
            continue
        if line_number is None:
            continue
        if raw.startswith("+"):
            numbers.add(line_number)
            line_number += 1
        elif raw.startswith("-"):
            continue  # removed lines do not exist in the new file
        elif raw.startswith("\\"):
            continue  # "\ No newline at end of file"
        else:
            numbers.add(line_number)
            line_number += 1

    return numbers


def prepare(diff_text, max_bytes):
    """Filter and truncate a diff, recording what was left out.

    Files are added whole: half a file is worse than none, because a model reviewing
    a truncated function invents context. Whatever does not fit is reported as
    skipped so the PR comment can say so honestly.
    """
    prepared = PreparedDiff(text="", original_bytes=len((diff_text or "").encode("utf-8")))
    if not diff_text:
        return prepared

    kept = []
    used = 0

    for path, section in split_file_sections(diff_text):
        if should_skip(path) or BINARY_MARKER in section:
            prepared.skipped_files.append(path)
            continue

        size = len(section.encode("utf-8"))
        if used + size > max_bytes:
            prepared.skipped_files.append(path)
            prepared.truncated = True
            continue

        kept.append(section)
        used += size
        prepared.files.append(
            DiffFile(path=path, changed_lines=changed_lines(section), text=section)
        )

    prepared.text = "".join(kept)
    prepared.included_bytes = used
    return prepared
