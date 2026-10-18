"""Split source files into coherent, citable chunks.

Spec section 6 asks for AST-aware chunking by function and class rather than fixed-size
splitting, so each chunk is a unit a reviewer would recognise and a finding can cite
by name and line range.

Python gets a real parse through the stdlib `ast` module. Everything else gets a
structural fallback that finds declarations by pattern and splits on blank lines.

**A parse failure is never fatal.** Real repositories contain files that do not
parse - syntax from a newer version, templating markers, or simply broken code mid-PR
- and `codesage-testbed`'s own `test.py` has leading indentation before `def` that
raises IndentationError. Every entry point here falls back to plain chunking rather
than letting one bad file fail an entire indexing run.

tree-sitter was considered for JS/TS and rejected: it would add a compiled dependency
and per-language grammars to a 512 MB free dyno, to improve chunk boundaries in a
retrieval system whose results are already scored by embedding similarity. The
fallback below finds the declaration a chunk belongs to, which is what citations need.
"""

import ast
import hashlib
import re
from dataclasses import dataclass

from django.conf import settings

from apps.ingestion.selection import language_for

# Floor for module-level leftovers. A single import line embeds into noise, but a
# file's imports plus its constants are genuine review context and must survive.
# Started at 80, which silently dropped a realistic import-and-constants block of 73
# characters; 40 keeps those while still discarding one-line scraps.
MIN_CHUNK_CHARS = 40


@dataclass
class Chunk:
    """A candidate chunk, before it becomes a CodeChunk row."""

    file_path: str
    symbol: str
    kind: str
    language: str
    line_start: int
    line_end: int
    content: str

    @property
    def content_hash(self):
        # Hashed with the path included: identical code in two files is still two
        # citations, and must not collapse into one cached embedding.
        payload = f"{self.file_path}\n{self.content}".encode()
        return hashlib.sha256(payload).hexdigest()


# Declarations worth naming in the fallback chunker. Deliberately loose: the aim is a
# useful label for a citation, not a parser.
DECLARATION_PATTERNS = (
    (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)"), "class"),
    (
        re.compile(
            r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*"
            r"([A-Za-z_$][\w$]*)"
        ),
        "function",
    ),
    (
        re.compile(
            r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
            r"(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
        ),
        "function",
    ),
    (re.compile(r"^\s*(?:public|private|protected)?\s*func\s+([A-Za-z_$][\w$]*)"), "function"),
    (re.compile(r"^\s*def\s+([A-Za-z_][\w]*)"), "function"),
    (re.compile(r"^\s*(?:type|interface)\s+([A-Za-z_$][\w$]*)"), "class"),
    (re.compile(r"^#{1,3}\s+(.+)$"), "module"),  # markdown headings
)


def chunk_file(file_path, text):
    """Chunk one file. Always returns a list; never raises for malformed input."""
    if not text or not text.strip():
        return []

    language = language_for(file_path)

    if language == "python":
        try:
            return _chunk_python(file_path, text, language)
        except (SyntaxError, ValueError, RecursionError):
            # Unparseable Python still has review value, so fall through to the
            # generic chunker rather than dropping the file.
            pass

    return _chunk_generic(file_path, text, language)


# ------------------------------------------------------------------ python, by AST


def _chunk_python(file_path, text, language):
    tree = ast.parse(text)
    lines = text.splitlines()
    chunks = []
    covered = set()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start, end = _node_span(node, len(lines))
            covered.update(range(start, end + 1))

            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            chunks.extend(_emit(file_path, node.name, kind, language, start, end, lines))

            if isinstance(node, ast.ClassDef):
                chunks.extend(_chunk_class_methods(file_path, node, language, lines))

    # Everything not inside a definition: imports, constants, main guards. Grouped
    # into one module chunk so module-level context is retrievable too.
    remainder = [i for i in range(1, len(lines) + 1) if i not in covered]
    if remainder:
        chunks.extend(_emit_module_remainder(file_path, language, remainder, lines))

    return [c for c in chunks if c.content.strip()]


def _chunk_class_methods(file_path, class_node, language, lines):
    """Emit each method separately as well as the class.

    A large class embeds poorly as one blob - the signal of any single method is
    diluted - so methods are indexed in their own right. The duplication is
    deliberate and bounded by the chunk cap.
    """
    chunks = []
    for node in class_node.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start, end = _node_span(node, len(lines))
        if end - start < 2:
            # One-line methods add nothing over the class chunk.
            continue
        chunks.extend(
            _emit(
                file_path,
                f"{class_node.name}.{node.name}",
                "method",
                language,
                start,
                end,
                lines,
            )
        )
    return chunks


def _node_span(node, total_lines):
    """Line span of a definition, including its decorators."""
    start = node.lineno
    for decorator in getattr(node, "decorator_list", []):
        start = min(start, decorator.lineno)
    end = getattr(node, "end_lineno", None) or node.lineno
    return start, min(end, total_lines)


def _emit_module_remainder(file_path, language, line_numbers, lines):
    """Group non-contiguous leftover lines into runs, and emit each run."""
    chunks = []
    run = [line_numbers[0]]

    for number in line_numbers[1:]:
        if number == run[-1] + 1:
            run.append(number)
        else:
            chunks.extend(_emit_run(file_path, language, run, lines))
            run = [number]
    chunks.extend(_emit_run(file_path, language, run, lines))
    return chunks


def _emit_run(file_path, language, run, lines):
    body = "\n".join(lines[run[0] - 1 : run[-1]])
    if len(body.strip()) < MIN_CHUNK_CHARS:
        return []
    return _emit(file_path, "", "module", language, run[0], run[-1], lines)


# -------------------------------------------------------------- generic fallback


def _chunk_generic(file_path, text, language):
    """Split on blank lines, then merge runs up to the size cap.

    Blank lines are a decent proxy for logical boundaries across most languages, and
    unlike a fixed token window they never cut a function in half at an arbitrary
    point.
    """
    lines = text.splitlines()
    blocks = _blank_line_blocks(lines)
    if not blocks:
        return []

    chunks = []
    current_start, current_end = blocks[0]

    for start, end in blocks[1:]:
        candidate = "\n".join(lines[current_start - 1 : end])
        fits = len(candidate) <= settings.INGESTION_MAX_CHUNK_CHARS

        # Break at a declaration even when the merged chunk would still fit.
        # Merging purely on size put every function of a small JS file into a single
        # chunk: individually unretrievable, with a citation spanning the whole file.
        # A declaration is a real boundary, so it outranks packing efficiency.
        if fits and not _starts_declaration(lines[start - 1 : end]):
            current_end = end
        else:
            chunks.extend(_emit_generic(file_path, language, current_start, current_end, lines))
            current_start, current_end = start, end

    chunks.extend(_emit_generic(file_path, language, current_start, current_end, lines))
    return [c for c in chunks if c.content.strip()]


def _blank_line_blocks(lines):
    """Contiguous runs of non-blank lines, as 1-indexed (start, end) pairs."""
    blocks = []
    start = None
    for index, line in enumerate(lines, start=1):
        if line.strip():
            if start is None:
                start = index
        elif start is not None:
            blocks.append((start, index - 1))
            start = None
    if start is not None:
        blocks.append((start, len(lines)))
    return blocks


def _emit_generic(file_path, language, start, end, lines):
    symbol, kind = _detect_declaration(lines[start - 1 : end])
    return _emit(file_path, symbol, kind, language, start, end, lines)


def _starts_declaration(block_lines):
    """Whether this block opens a new function, class or heading."""
    _, kind = _detect_declaration(block_lines[:2])
    return kind != "block"


def _detect_declaration(block_lines):
    """Best-effort name for a block, so citations read usefully."""
    for line in block_lines[:6]:
        for pattern, kind in DECLARATION_PATTERNS:
            match = pattern.match(line)
            if match:
                return match.group(1).strip()[:512], kind
    return "", "block"


# ----------------------------------------------------------------------- emitting


def _emit(file_path, symbol, kind, language, start, end, lines):
    """Build chunks for a line span, splitting anything over the character cap.

    The cap protects both the embedding request size and the Neon row size; a
    2000-line generated file that slipped through selection would otherwise become
    one enormous chunk.
    """
    body = "\n".join(lines[start - 1 : end])
    limit = settings.INGESTION_MAX_CHUNK_CHARS

    if len(body) <= limit:
        return [
            Chunk(
                file_path=file_path,
                symbol=symbol,
                kind=kind,
                language=language,
                line_start=start,
                line_end=end,
                content=body,
            )
        ]

    # Too large: split by line count, keeping line numbers honest so citations stay
    # accurate even for the split pieces.
    chunks = []
    span_lines = lines[start - 1 : end]
    approx_chars_per_line = max(1, len(body) // max(1, len(span_lines)))
    lines_per_part = max(1, limit // approx_chars_per_line)

    for offset in range(0, len(span_lines), lines_per_part):
        part = span_lines[offset : offset + lines_per_part]
        part_start = start + offset
        chunks.append(
            Chunk(
                file_path=file_path,
                symbol=symbol,
                kind=kind,
                language=language,
                line_start=part_start,
                line_end=part_start + len(part) - 1,
                content="\n".join(part),
            )
        )
    return chunks
