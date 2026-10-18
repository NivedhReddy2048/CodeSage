"""Split code identifiers into searchable words.

Postgres full-text search cannot match "function that looks up a user by id"
against `find_by_id` or `findUserById`, because those are single opaque tokens. The
fix is to index the words *as well as* the identifier, so a natural-language query
has something to hit.

The `simple` text search configuration is used rather than `english`:

- `english` stems, so `users` and `user` collapse but so do unrelated code tokens,
  and stemming an identifier fragment produces noise.
- `english` drops stopwords, and short code words like `id`, `by`, `to`, `is` and
  `a` are exactly the connective tissue of identifier names. Losing `id` from
  `find_by_id` throws away most of its meaning.

`simple` lowercases and splits on punctuation and nothing more, which is what code
wants.
"""

import re

# Boundaries inside an identifier: an underscore, hyphen, dot, or the transition
# from lowercase/digit to uppercase, plus the ACRONYMWord case.
_SEPARATORS = re.compile(r"[_\-./\\:]+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_ACRONYM_BOUNDARY = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")

# An identifier-ish run in a line of source.
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,80}")

# Words too short or too generic to help retrieval. Kept deliberately tiny: this is
# code search, where `id` and `db` carry real meaning, unlike in prose.
_NOISE = frozenset({"self", "cls", "the", "and", "for", "not", "def", "var", "let"})


def split_identifier(identifier):
    """`findUserById` -> ['find', 'user', 'by', 'id'].

    Handles snake_case, camelCase, PascalCase, kebab-case, dotted paths and
    SCREAMING_CASE, including acronym runs like `HTTPResponse` -> ['http', 'response'].
    """
    if not identifier:
        return []

    words = []
    for part in _SEPARATORS.split(identifier):
        if not part:
            continue
        part = _ACRONYM_BOUNDARY.sub(" ", part)
        part = _CAMEL_BOUNDARY.sub(" ", part)
        words.extend(piece.lower() for piece in part.split() if piece)

    return [w for w in words if w and w not in _NOISE]


def expand_identifiers(text, limit=400):
    """Every identifier in `text`, split into words, de-duplicated.

    Capped because a long file would otherwise produce a tsvector far larger than
    the content it describes, which costs storage on a 0.5 GB free plan and dilutes
    ranking.
    """
    seen = {}
    for match in _IDENTIFIER.finditer(text or ""):
        token = match.group(0)
        for word in split_identifier(token):
            if len(word) > 1 and word not in seen:
                seen[word] = None
                if len(seen) >= limit:
                    return list(seen)
    return list(seen)


def path_words(file_path):
    """`app/users.py` -> ['app', 'users', 'py'].

    A query naming a module ("the users module") should be able to reach it.
    """
    return split_identifier(file_path or "")


def build_search_text(file_path, symbol, content):
    """The text that gets turned into a tsvector.

    Deliberately includes the raw content *and* the derived words: exact-token
    matches still work, and the split forms add reach without losing precision.
    Path and symbol come first so they weigh in a `ts_rank` that favours early
    positions.
    """
    parts = []

    if file_path:
        parts.append(file_path)
        parts.extend(path_words(file_path))

    if symbol:
        parts.append(symbol)
        parts.extend(split_identifier(symbol))

    if content:
        parts.append(content)
        parts.extend(expand_identifiers(content))

    return " ".join(parts)
