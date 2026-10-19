"""Citation enforcement (spec section 6).

A model asked to cite sources will produce citations whether or not it used them.
Posted on a PR, an invented citation looks authoritative and is wrong — worse than
no citation at all. So the rule is checked, not requested.
"""

from apps.agents.citations import find_supporting_chunk, format_citation, validate
from apps.agents.types import Category, Finding, RetrievedChunk, Severity


def chunk(path="app/users.py", start=15, end=20, symbol="UserRepository.find_by_id"):
    return RetrievedChunk(
        file_path=path,
        symbol=symbol,
        line_start=start,
        line_end=end,
        content="def find_by_id(self, user_id): ...",
        score=0.9,
    )


def finding(path="app/users.py", line=16):
    return Finding(
        file=path,
        line=line,
        severity=Severity.NIT,
        category=Category.OTHER,
        message="This duplicates existing logic.",
    )


def test_a_chunk_covers_lines_inside_its_range():
    entry = chunk(start=15, end=20)

    assert entry.covers("app/users.py", 15)
    assert entry.covers("app/users.py", 20)
    assert entry.covers("app/users.py", 17)


def test_a_chunk_does_not_cover_lines_outside_its_range():
    entry = chunk(start=15, end=20)

    assert not entry.covers("app/users.py", 14)
    assert not entry.covers("app/users.py", 21)


def test_a_chunk_does_not_cover_a_different_file():
    assert not chunk().covers("app/other.py", 16)


def test_a_grounded_citation_is_kept():
    retrieved = [chunk()]

    kept, dropped = validate([(finding(), "app/users.py", 16)], retrieved)

    assert len(kept) == 1
    assert dropped == []
    _, citation = kept[0]
    assert citation == "app/users.py:15-20"


def test_an_invented_file_is_dropped():
    """The model cites a plausible path it was never shown."""
    retrieved = [chunk()]

    kept, dropped = validate([(finding(path="app/invented.py"), "app/invented.py", 16)], retrieved)

    assert kept == []
    assert len(dropped) == 1


def test_a_line_outside_the_retrieved_range_is_dropped():
    """Right file, wrong place: still not evidence of anything."""
    retrieved = [chunk(start=15, end=20)]

    kept, dropped = validate([(finding(line=400), "app/users.py", 400)], retrieved)

    assert kept == []
    assert len(dropped) == 1


def test_a_missing_citation_is_dropped():
    retrieved = [chunk()]

    kept, dropped = validate([(finding(), "", 0)], retrieved)

    assert kept == []
    assert len(dropped) == 1


def test_validation_against_an_empty_retrieval_set_drops_everything():
    """If retrieval found nothing, nothing can be grounded in it."""
    kept, dropped = validate([(finding(), "app/users.py", 16)], [])

    assert kept == []
    assert len(dropped) == 1


def test_the_right_chunk_is_chosen_from_several():
    retrieved = [
        chunk(path="app/a.py", start=1, end=5),
        chunk(path="app/users.py", start=15, end=20),
        chunk(path="app/b.py", start=1, end=5),
    ]

    found = find_supporting_chunk(retrieved, "app/users.py", 18)

    assert found is not None
    assert found.file_path == "app/users.py"


def test_mixed_findings_are_split_correctly():
    retrieved = [chunk()]
    findings = [
        (finding(line=16), "app/users.py", 16),
        (finding(path="nope.py"), "nope.py", 1),
        (finding(line=19), "app/users.py", 19),
    ]

    kept, dropped = validate(findings, retrieved)

    assert len(kept) == 2
    assert len(dropped) == 1


def test_the_citation_format_is_clickable():
    assert format_citation(chunk(start=15, end=20)) == "app/users.py:15-20"


# ===================================== the cited chunk must support the claim


def py_chunk():
    return RetrievedChunk(
        file_path="app/users.py",
        symbol="UserRepository.find_by_id",
        line_start=15,
        line_end=20,
        content=(
            "    def find_by_id(self, user_id):\n        return self.db.query(User).get(user_id)\n"
        ),
    )


def js_lookalike():
    """What hybrid retrieval really ranks first for "look up a user by id"."""
    return RetrievedChunk(
        file_path="web/users.js",
        symbol="findUserById",
        line_start=3,
        line_end=5,
        content="export function findUserById(id) {\n  return users.find(u => u.id === id);\n}\n",
    )


def grounded(message, path="app/accounts.py", line=8, severity=Severity.BLOCKING):
    return Finding(
        file=path,
        line=line,
        severity=severity,
        category=Category.CORRECTNESS,
        message=message,
        agent="grounding",
    )


def test_a_js_lookalike_cited_for_a_python_function_is_dropped():
    """The case from the testbed: a Python change, a JS chunk that merely looks alike.

    The location is real - it was retrieved - so the old check passed it. It is
    still not evidence about Python code.
    """
    finding = grounded("`get_user` reimplements the existing `findUserById` lookup.")

    kept, dropped = validate([(finding, "web/users.js", 4)], [js_lookalike(), py_chunk()])

    assert kept == []
    assert dropped == [finding]


def test_a_js_lookalike_is_dropped_even_when_it_contains_the_named_symbol():
    """Same name, wrong language: still not precedent."""
    finding = grounded("This duplicates `findUserById`.")

    kept, _ = validate([(finding, "web/users.js", 4)], [js_lookalike()])

    assert kept == []


def test_a_same_language_chunk_that_contains_the_named_function_is_kept():
    finding = grounded("`get_user` reimplements `UserRepository.find_by_id`.")

    kept, dropped = validate([(finding, "app/users.py", 16)], [py_chunk()])

    assert dropped == []
    kept_finding, citation = kept[0]
    assert citation == "app/users.py:15-20"
    assert kept_finding.severity == Severity.BLOCKING


def test_a_same_language_chunk_without_the_named_symbol_is_dropped():
    """Right language, real location, but the chunk is about something else."""
    finding = grounded("This duplicates the existing `paginate_users` helper.")

    kept, dropped = validate([(finding, "app/users.py", 16)], [py_chunk()])

    assert kept == []
    assert dropped == [finding]


def test_a_finding_that_names_no_symbol_is_downgraded_not_trusted():
    finding = grounded("This duplicates logic that already exists elsewhere.")

    kept, dropped = validate([(finding, "app/users.py", 16)], [py_chunk()])

    assert dropped == []
    assert kept[0][0].severity == Severity.NIT


def test_typescript_and_javascript_are_one_language_family():
    finding = grounded("Duplicates `findUserById`.", path="web/profile.ts")

    kept, _ = validate([(finding, "web/users.js", 4)], [js_lookalike()])

    assert len(kept) == 1


def test_symbols_are_read_from_backticks_calls_and_code_shaped_words():
    from apps.agents.citations import referenced_symbols

    assert referenced_symbols("`UserRepository.find_by_id` and fetchUser() vs get_user") == {
        "UserRepository",
        "find_by_id",
        "fetchUser",
        "get_user",
    }
    assert referenced_symbols("This duplicates existing logic.") == set()
    assert referenced_symbols("`self` returns `None`") == set()


def test_a_symbol_must_match_whole_not_as_a_substring():
    """`find` must not be satisfied by `find_by_id`."""
    from apps.agents.citations import chunk_mentions

    assert chunk_mentions(py_chunk(), "find_by_id")
    assert not chunk_mentions(py_chunk(), "find_by")
