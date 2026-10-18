"""Tests for identifier splitting, hybrid retrieval and RRF fusion."""

import pytest

from apps.accounts.services import get_or_create_user_from_github
from apps.ingestion.identifiers import (
    build_search_text,
    expand_identifiers,
    path_words,
    split_identifier,
)
from apps.ingestion.models import CodeChunk
from apps.ingestion.retrieval import (
    RRF_K,
    hybrid_search,
    reciprocal_rank_fusion,
    text_search,
    vector_search,
)
from apps.repos.models import AppInstallation, Repository

DIM = 1536


@pytest.fixture
def repository(db):
    user, _ = get_or_create_user_from_github(
        {"id": 1, "login": "owner", "name": "", "email": "", "avatar_url": ""}
    )
    installation = AppInstallation.objects.create(installation_id=1, account_login="owner")
    return Repository.objects.create(
        organization=user.memberships.get().organization,
        installation=installation,
        github_id=1,
        full_name="owner/repo",
        owner="owner",
        name="repo",
    )


def make_chunk(repository, path, symbol, content, start=1, end=5, embedding=None):
    return CodeChunk.objects.create(
        repository=repository,
        file_path=path,
        symbol=symbol,
        kind="function",
        language="python",
        line_start=start,
        line_end=end,
        content=content,
        content_hash=f"{path}:{start}",
        search_text=build_search_text(path, symbol, content),
        embedding=embedding,
    )


# ================================================================== identifiers


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("find_by_id", ["find", "by", "id"]),
        ("findUserById", ["find", "user", "by", "id"]),
        ("FindUserById", ["find", "user", "by", "id"]),
        ("find-user-by-id", ["find", "user", "by", "id"]),
        ("MAX_RETRY_COUNT", ["max", "retry", "count"]),
        ("app/users.py", ["app", "users", "py"]),
        ("UserRepository.find_by_id", ["user", "repository", "find", "by", "id"]),
        ("getUserID", ["get", "user", "id"]),
    ],
)
def test_identifiers_split_into_words(identifier, expected):
    assert split_identifier(identifier) == expected


def test_acronym_runs_split_sensibly():
    """HTTPResponse must not become ['h','t','t','p','response']."""
    assert split_identifier("HTTPResponse") == ["http", "response"]
    assert split_identifier("parseJSONBody") == ["parse", "json", "body"]


def test_short_code_words_are_kept():
    """`id` and `by` are stopwords in english but carry the meaning here."""
    words = split_identifier("find_by_id")

    assert "id" in words
    assert "by" in words


def test_empty_input_is_handled():
    assert split_identifier("") == []
    assert split_identifier(None) == []
    assert path_words(None) == []


def test_identifiers_are_extracted_from_source():
    words = expand_identifiers("def findUserById(users, userId):\n    return None\n")

    assert "find" in words and "user" in words and "id" in words


def test_identifier_expansion_is_capped():
    source = "\n".join(f"variable_number_{i} = {i}" for i in range(500))

    assert len(expand_identifiers(source, limit=50)) <= 50


def test_search_text_includes_path_symbol_and_split_forms():
    text = build_search_text("app/users.py", "find_by_id", "def find_by_id(): pass")

    assert "app/users.py" in text
    assert "find_by_id" in text  # exact token still searchable
    assert "find by id" in text or ("find" in text and "by" in text and "id" in text)


# ========================================================= the tsvector trigger


@pytest.mark.django_db
def test_the_trigger_populates_the_vector_on_insert(repository):
    """bulk_create skips save(), so this must be the database's job."""
    chunk = make_chunk(repository, "app/users.py", "find_by_id", "def find_by_id(): ...")

    chunk.refresh_from_db()
    assert chunk.search_vector is not None


@pytest.mark.django_db
def test_the_trigger_fires_on_bulk_create(repository):
    CodeChunk.objects.bulk_create(
        [
            CodeChunk(
                repository=repository,
                file_path="a.py",
                symbol="find_by_id",
                line_start=1,
                line_end=2,
                content="def find_by_id(): ...",
                content_hash="h1",
                search_text=build_search_text("a.py", "find_by_id", "def find_by_id():"),
            )
        ]
    )

    assert CodeChunk.objects.filter(search_vector__isnull=False).count() == 1


@pytest.mark.django_db
def test_the_vector_updates_when_the_text_changes(repository):
    chunk = make_chunk(repository, "a.py", "old_name", "def old_name(): ...")

    chunk.search_text = build_search_text("a.py", "brand_new_symbol", "x")
    chunk.save()

    assert text_search(repository, "brand new symbol")


# ===================================================================== lexical


@pytest.mark.django_db
def test_lexical_search_matches_a_split_identifier(repository):
    """The whole point: a natural-language query reaching an opaque token."""
    make_chunk(repository, "app/users.py", "find_by_id", "def find_by_id(self, uid):")
    make_chunk(repository, "app/cart.py", "total", "def total(self): return 0", start=10, end=12)

    results = text_search(repository, "function that looks up a user by id")

    assert results
    assert results[0].file_path == "app/users.py"


@pytest.mark.django_db
def test_lexical_search_matches_camel_case(repository):
    make_chunk(repository, "web/users.js", "findUserById", "export function findUserById(")

    results = text_search(repository, "find user by id")

    assert results and results[0].symbol == "findUserById"


@pytest.mark.django_db
def test_lexical_search_returns_nothing_for_an_unrelated_query(repository):
    make_chunk(repository, "app/users.py", "find_by_id", "def find_by_id(): ...")

    assert text_search(repository, "kubernetes helm chart rollout") == []


@pytest.mark.django_db
def test_an_empty_query_returns_nothing(repository):
    make_chunk(repository, "a.py", "f", "def f(): ...")

    assert text_search(repository, "") == []
    assert text_search(repository, "   ") == []


@pytest.mark.django_db
def test_a_query_of_only_punctuation_is_safe(repository):
    """Must not build a malformed tsquery."""
    make_chunk(repository, "a.py", "f", "def f(): ...")

    assert text_search(repository, "!!! ??? &&&") == []


@pytest.mark.django_db
def test_search_is_scoped_to_the_repository(repository):
    other_user, _ = get_or_create_user_from_github(
        {"id": 2, "login": "other", "name": "", "email": "", "avatar_url": ""}
    )
    other = Repository.objects.create(
        organization=other_user.memberships.get().organization,
        github_id=2,
        full_name="other/repo",
        owner="other",
        name="repo",
    )
    make_chunk(other, "app/users.py", "find_by_id", "def find_by_id(): ...")

    assert text_search(repository, "find by id") == []


# ========================================================================= RRF


class FakeChunk:
    def __init__(self, pk):
        self.pk = pk

    def __repr__(self):
        return f"c{self.pk}"


def test_rrf_scores_by_reciprocal_rank():
    a, b = FakeChunk(1), FakeChunk(2)

    fused = reciprocal_rank_fusion([[a, b]], k=RRF_K)

    assert fused[0][0] is a
    assert fused[0][1] == pytest.approx(1 / (RRF_K + 1))
    assert fused[1][1] == pytest.approx(1 / (RRF_K + 2))


def test_rrf_rewards_agreement_between_retrievers():
    """A document both retrievers like should beat one only a single retriever tops."""
    agreed, dense_only, lexical_only = FakeChunk(1), FakeChunk(2), FakeChunk(3)

    fused = reciprocal_rank_fusion([[dense_only, agreed], [lexical_only, agreed]], k=RRF_K)

    assert fused[0][0] is agreed


def test_rrf_handles_one_empty_list():
    """Lexical can legitimately return nothing; fusion must still work."""
    a = FakeChunk(1)

    fused = reciprocal_rank_fusion([[a], []], k=RRF_K)

    assert [c for c, _ in fused] == [a]


def test_rrf_of_nothing_is_nothing():
    assert reciprocal_rank_fusion([[], []]) == []


def test_rrf_respects_the_limit():
    chunks = [FakeChunk(i) for i in range(20)]

    assert len(reciprocal_rank_fusion([chunks], limit=5)) == 5


def test_rrf_is_deterministic_on_ties():
    """Equal scores must not reorder between runs."""
    a, b = FakeChunk(2), FakeChunk(1)

    first = [c.pk for c, _ in reciprocal_rank_fusion([[a], [b]])]
    second = [c.pk for c, _ in reciprocal_rank_fusion([[a], [b]])]

    assert first == second


# ====================================================================== hybrid


@pytest.mark.django_db
def test_hybrid_fuses_both_retrievers(repository):
    lexical_match = make_chunk(
        repository, "app/users.py", "find_by_id", "def find_by_id(self, uid):"
    )
    vector_match = make_chunk(
        repository,
        "app/other.py",
        "lookup",
        "def lookup(): ...",
        start=10,
        end=12,
        embedding=[0.1] * DIM,
    )

    results = hybrid_search(repository, "find by id", query_embedding=[0.1] * DIM, limit=5)

    ids = {chunk.pk for chunk, _ in results}
    assert lexical_match.pk in ids
    assert vector_match.pk in ids


@pytest.mark.django_db
def test_hybrid_works_without_an_embedding(repository):
    """An embedding outage should cost relevance, not availability."""
    make_chunk(repository, "app/users.py", "find_by_id", "def find_by_id(): ...")

    results = hybrid_search(repository, "find by id", query_embedding=None)

    assert results


@pytest.mark.django_db
def test_hybrid_returns_nothing_for_an_empty_repository(repository):
    assert hybrid_search(repository, "anything", query_embedding=[0.1] * DIM) == []


@pytest.mark.django_db
def test_vector_search_ignores_chunks_without_embeddings(repository):
    make_chunk(repository, "a.py", "f", "def f(): ...")  # no embedding

    assert vector_search(repository, [0.1] * DIM) == []


@pytest.mark.django_db
def test_vector_search_without_an_embedding_returns_nothing(repository):
    make_chunk(repository, "a.py", "f", "x", embedding=[0.1] * DIM)

    assert vector_search(repository, None) == []
