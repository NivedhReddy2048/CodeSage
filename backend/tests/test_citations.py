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
