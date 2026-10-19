"""Citation enforcement for the grounding agent (spec section 6).

A grounded finding is only worth more than an ungrounded one if the citation is
real. A model asked to cite its sources will produce citations whether or not it
used them: plausible file paths, plausible line numbers, occasionally a file it was
never shown. Posted on a PR those look authoritative and are wrong, which is worse
than no citation at all.

So the rule is checked rather than requested, in two steps:

1. **The location is real.** The cited line must fall inside a chunk that was
   actually in the retrieved set for that query.
2. **The chunk supports the claim.** A real location is not yet evidence. Retrieval
   returns lookalikes - `web/users.js findUserById` for a query about Python's
   `find_by_id` - and a model will happily cite the lookalike. So the cited chunk
   must be in the same language as the code under review, and must contain a
   symbol the message actually names. A message that names no symbol cannot be
   checked against the chunk, so it is kept but downgraded to a nit.
"""

import logging
import re
from dataclasses import replace

logger = logging.getLogger(__name__)

# Language families by extension. JS and TS share one: a TypeScript helper is a
# legitimate precedent for JavaScript code and the other way round.
LANGUAGES = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "javascript",
    ".tsx": "javascript",
}

_BACKTICKED = re.compile(r"`([^`]{1,200})`")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CALL = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
_WORD = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_CAMEL = re.compile(r"[a-z0-9][A-Z]")

# Code-shaped words that name nothing in particular.
_NOT_SYMBOLS = frozenset(
    {
        "self",
        "cls",
        "None",
        "True",
        "False",
        "null",
        "undefined",
        "def",
        "class",
        "return",
        "function",
        "const",
        "let",
        "var",
        "async",
        "await",
        "import",
        "from",
        "this",
        "new",
    }
)


def find_supporting_chunk(retrieved, file_path, line):
    """The retrieved chunk covering this location, or None."""
    if not file_path or not line:
        return None
    for chunk in retrieved:
        if chunk.covers(file_path, line):
            return chunk
    return None


def format_citation(chunk):
    """`app/users.py:15-20` - what a reader can click through to."""
    return f"{chunk.file_path}:{chunk.line_start}-{chunk.line_end}"


def language_of(path):
    """A language family for a path; unknown extensions are their own family."""
    name = (path or "").rsplit("/", 1)[-1]
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else name
    return LANGUAGES.get(suffix, suffix)


def referenced_symbols(message):
    """Identifiers a finding's message names.

    Taken from backticked spans, call forms (`name(`), and words shaped like code
    (snake_case or camelCase). Plain English words are not symbols, so "this
    duplicates existing logic" names none.
    """
    text = message or ""
    candidates = set()

    for span in _BACKTICKED.findall(text):
        candidates.update(_IDENTIFIER.findall(span))
    for call in _CALL.findall(text):
        candidates.update(part for part in call.split(".") if part)
    for word in _WORD.findall(text):
        if "_" in word.strip("_") or _CAMEL.search(word):
            candidates.add(word)

    return {name for name in candidates if len(name) >= 3 and name not in _NOT_SYMBOLS}


def chunk_mentions(chunk, symbol):
    """Does the chunk's code (or its recorded symbol) contain this identifier?"""
    if symbol in (chunk.symbol or "").split("."):
        return True
    pattern = rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])"
    return re.search(pattern, chunk.content or "") is not None


def check_support(finding, chunk):
    """Whether a real cited chunk actually supports the finding.

    Returns `(verdict, reason)`: verdict is "ok", "downgrade" or "drop".
    """
    under_review = language_of(finding.file)
    cited = language_of(chunk.file_path)
    if under_review != cited:
        return "drop", f"cites {cited} code for a {under_review} change"

    symbols = referenced_symbols(finding.message)
    if not symbols:
        return "downgrade", "message names no symbol to check against the chunk"

    if any(chunk_mentions(chunk, symbol) for symbol in symbols):
        return "ok", ""
    return "drop", f"none of {sorted(symbols)} appear in the cited chunk"


def validate(findings, retrieved):
    """Keep only findings whose citation is real AND supports the claim.

    Returns `(kept, dropped)` so the caller can report how many were discarded;
    silently dropping would hide a model that cites badly every time. A kept
    finding the citation cannot fully vouch for comes back downgraded to a nit.
    """
    from apps.agents.types import Severity

    kept = []
    dropped = []

    for finding, cited_file, cited_line in findings:
        chunk = find_supporting_chunk(retrieved, cited_file, cited_line)
        if chunk is None:
            logger.info(
                "Dropping ungrounded finding: cited %s:%s which was not retrieved",
                cited_file,
                cited_line,
            )
            dropped.append(finding)
            continue

        verdict, reason = check_support(finding, chunk)
        if verdict == "drop":
            logger.info(
                "Dropping finding at %s:%s: citation %s does not support it (%s)",
                finding.file,
                finding.line,
                format_citation(chunk),
                reason,
            )
            dropped.append(finding)
            continue
        if verdict == "downgrade" and finding.severity != Severity.NIT:
            finding = replace(finding, severity=Severity.NIT)

        kept.append((finding, format_citation(chunk)))

    return kept, dropped
