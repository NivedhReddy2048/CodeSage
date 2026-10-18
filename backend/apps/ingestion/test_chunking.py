"""Chunking tests.

The single most important case here is the parse-failure fallback: a repository with
one unparseable file must still index completely. `codesage-testbed`'s own `test.py`
is written with leading indentation before `def`, so this is an observed failure mode
rather than a hypothetical one.
"""

import pytest

from apps.ingestion.chunking import Chunk, chunk_file

PYTHON_SOURCE = '''"""Module docstring."""

import os
from typing import Any

MAX_USERS = 100


def get_user(users, user_id):
    """Look up a user by id."""
    for user in users:
        if user["id"] == user_id:
            return user
    return None


async def fetch_user(session, user_id):
    response = await session.get(f"/users/{user_id}")
    return response.json()


class UserRepository:
    """Stores users."""

    def __init__(self, connection):
        self.connection = connection

    def find_by_id(self, user_id):
        row = self.connection.execute(
            "SELECT * FROM users WHERE id = %s", [user_id]
        )
        return row.fetchone()


if __name__ == "__main__":
    print(get_user([], 1))
'''

# Exactly the shape that broke: a def indented at module level.
INDENTED_PYTHON = """   def get_user(users, user_id):
       for i in range(len(users) + 1):
           if users[i]["id"] == user_id:
               return users[i]
"""

JAVASCRIPT_SOURCE = """import { api } from "./api";

export function getUser(users, userId) {
  return users.find((u) => u.id === userId);
}

export const fetchUser = async (userId) => {
  const response = await api.get(`/users/${userId}`);
  return response.json();
};

export class UserStore {
  constructor(items) {
    this.items = items;
  }
}
"""


def symbols(chunks):
    return [c.symbol for c in chunks]


# ------------------------------------------------------------------ python, by AST


def test_python_chunks_by_function_and_class():
    chunks = chunk_file("app/users.py", PYTHON_SOURCE)

    names = symbols(chunks)
    assert "get_user" in names
    assert "fetch_user" in names
    assert "UserRepository" in names


def test_python_methods_are_chunked_separately():
    """A big class embeds poorly as one blob, so methods are indexed too."""
    chunks = chunk_file("app/users.py", PYTHON_SOURCE)

    assert "UserRepository.find_by_id" in symbols(chunks)


def test_python_line_ranges_point_at_the_real_definition():
    """Citations are only worth anything if the line numbers are right."""
    chunks = chunk_file("app/users.py", PYTHON_SOURCE)
    lines = PYTHON_SOURCE.splitlines()

    chunk = next(c for c in chunks if c.symbol == "get_user")

    assert lines[chunk.line_start - 1].startswith("def get_user")
    assert "return None" in lines[chunk.line_end - 1]


def test_python_module_level_code_is_kept():
    """Imports and constants are context a reviewer needs."""
    chunks = chunk_file("app/users.py", PYTHON_SOURCE)
    module_chunks = [c for c in chunks if c.kind == "module"]

    assert module_chunks
    assert any("MAX_USERS" in c.content for c in module_chunks)


def test_decorators_are_included_in_the_chunk():
    source = """@app.route("/x")
@requires_auth
def handler():
    return 1
"""
    chunk = next(c for c in chunk_file("a.py", source) if c.symbol == "handler")

    assert chunk.line_start == 1
    assert "@app.route" in chunk.content


# ---------------------------------------------------- the parse-failure fallback


def test_unparseable_python_falls_back_instead_of_raising():
    """The real case from codesage-testbed: leading indentation before `def`."""
    import ast

    with pytest.raises(IndentationError):
        ast.parse(INDENTED_PYTHON)

    chunks = chunk_file("test.py", INDENTED_PYTHON)

    assert chunks, "a file that fails to parse must still produce chunks"
    assert "range(len(users) + 1)" in chunks[0].content
    assert chunks[0].language == "python"


def test_syntactically_broken_python_falls_back():
    broken = "def oops(:\n    this is not python at all\n    still not\n"

    chunks = chunk_file("broken.py", broken)

    assert chunks
    assert "oops" in chunks[0].content


def test_fallback_still_labels_the_declaration():
    chunks = chunk_file("test.py", INDENTED_PYTHON)

    assert chunks[0].symbol == "get_user"


# ------------------------------------------------------------- generic fallback


def test_javascript_declarations_are_detected():
    chunks = chunk_file("src/users.js", JAVASCRIPT_SOURCE)

    names = symbols(chunks)
    assert "getUser" in names or "fetchUser" in names or "UserStore" in names
    assert all(c.language == "javascript" for c in chunks)


def test_arrow_function_assignment_is_named():
    source = "export const fetchUser = async (userId) => {\n  return userId;\n};\n"

    chunks = chunk_file("a.ts", source)

    assert chunks[0].symbol == "fetchUser"


def test_markdown_headings_become_symbols():
    source = "# Overview\n\nSome prose that is long enough to survive the minimum.\n"

    chunks = chunk_file("README.md", source)

    assert chunks[0].symbol == "Overview"


# ------------------------------------------------------------------ edge cases


@pytest.mark.parametrize("text", ["", "   ", "\n\n\n"])
def test_empty_files_produce_nothing(text):
    assert chunk_file("empty.py", text) == []


def test_oversized_chunks_are_split_with_honest_line_numbers(settings):
    settings.INGESTION_MAX_CHUNK_CHARS = 200
    body = "\n".join(f"    x = {i}" for i in range(200))
    source = f"def big():\n{body}\n"

    chunks = chunk_file("big.py", source)

    assert len(chunks) > 1
    assert all(len(c.content) <= 400 for c in chunks)
    # Line numbers must stay contiguous and in order, or citations break.
    assert chunks[0].line_start == 1
    for earlier, later in zip(chunks, chunks[1:], strict=False):
        assert later.line_start == earlier.line_end + 1


def test_content_hash_includes_the_path():
    """Identical code in two files is two citations, not one cached embedding."""
    a = Chunk("a.py", "f", "function", "python", 1, 2, "def f(): pass")
    b = Chunk("b.py", "f", "function", "python", 1, 2, "def f(): pass")

    assert a.content_hash != b.content_hash


def test_content_hash_is_stable_for_identical_input():
    a = Chunk("a.py", "f", "function", "python", 1, 2, "def f(): pass")
    b = Chunk("a.py", "f", "function", "python", 1, 2, "def f(): pass")

    assert a.content_hash == b.content_hash


def test_unknown_extension_still_chunks():
    chunks = chunk_file("Makefile", "build:\n\techo hello world and some more text\n")

    assert chunks
    assert chunks[0].language == ""
