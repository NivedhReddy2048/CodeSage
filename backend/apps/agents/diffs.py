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

# A hunk header names the line the hunk starts at in the new file, and a pull request
# chooses that number. Reconstruction places lines at their real line numbers, so an
# absurd header asks for an absurd file: `@@ -0,0 +99999999,1 @@` is a one-line diff
# requesting a hundred million lines of memory. Lines past this are dropped. No real
# source file comes close, and this module's premise is that the diff is hostile.
MAX_RECONSTRUCTED_LINES = 20_000


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


def added_lines(section_text):
    """Line numbers in the NEW file that the PR added or modified ("+" lines only)."""
    numbers = set()
    line_number = None

    for raw in section_text.splitlines():
        hunk = HUNK_HEADER.match(raw)
        if hunk:
            line_number = int(hunk.group(1))
            continue
        if line_number is None or raw.startswith(("-", "\\")):
            continue
        if raw.startswith("+"):
            numbers.add(line_number)
        line_number += 1

    return numbers


def adds_whole_file(section_text):
    """Does this section add the file, so that its hunks are the whole of it?

    Worth knowing because a reconstruction of an added file is the complete source,
    and can be judged as source. A reconstruction of a few hunks out of a larger
    file cannot: hunks from inside a class body reconstruct as indented top-level
    code, and a linter will rightly call that a syntax error while saying nothing
    about the change.
    """
    for raw in section_text.splitlines():
        if raw.startswith("@@"):
            break
        if raw.startswith("new file mode"):
            return True
        if raw.startswith("--- ") and raw[4:].strip() == "/dev/null":
            return True
    return False


def reconstruct_new_file(section_text):
    """The post-change content of one diff section, at its real line numbers.

    Built from hunk bodies alone: everything before the first `@@` is skipped. That
    is the only reliable way to keep git's extended headers out of the source, since
    `new file mode 100644`, `rename from`, `similarity index` and the rest begin with
    none of the characters that mark a diff body line. A prefix blacklist misses
    whichever header it was not told about, and a leaked header is both invalid
    syntax and a one-line shift in every line number after it.

    Gaps between hunks are padded with blank lines, so a line's position in the
    result is its line number in the new file and a linter's output needs no
    translation. A translation that is quietly wrong is worse than no finding: it
    anchors a review comment to code the author never touched.
    """
    lines = []
    number = None

    for raw in section_text.splitlines():
        hunk = HUNK_HEADER.match(raw)
        if hunk:
            number = int(hunk.group(1))
            continue
        if number is None:
            continue  # still in the headers
        if raw.startswith(("-", "\\")):
            continue  # removed, or "\ No newline at end of file"
        if number > MAX_RECONSTRUCTED_LINES:
            break
        content = raw[1:] if raw[:1] in ("+", " ") else raw
        while len(lines) < number - 1:
            lines.append("")
        if len(lines) == number - 1:
            lines.append(content)
        else:
            lines[number - 1] = content
        number += 1

    return "\n".join(lines)


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
            DiffFile(
                path=path,
                changed_lines=changed_lines(section),
                added_lines=added_lines(section),
                text=section,
                is_new_file=adds_whole_file(section),
            )
        )

    prepared.text = "".join(kept)
    prepared.included_bytes = used
    return prepared
