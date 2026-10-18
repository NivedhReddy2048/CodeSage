"""End-to-end indexer tests against a fake repository archive.

GitHub and Gemini are both mocked. The cases that matter most are the content-hash
cache (what makes re-indexing affordable) and a single unparseable file not taking
the whole job down with it.
"""

import io
from unittest import mock

import pytest

from apps.accounts.services import get_or_create_user_from_github
from apps.ingestion import indexer
from apps.ingestion.embeddings import EmbeddingError
from apps.ingestion.models import CodeChunk, IngestionJob
from apps.ingestion.source import SourceFetchError
from apps.repos.models import AppInstallation, Repository

GOOD_PY = '''def get_user(users, user_id):
    """Look up a user by id."""
    for user in users:
        if user["id"] == user_id:
            return user
    return None
'''

# Leading indentation before `def`: raises IndentationError, must fall back.
BROKEN_PY = """   def get_user(users, user_id):
       for i in range(len(users) + 1):
           return users[i]
"""

JS = """export function getUser(users, userId) {
  return users.find((u) => u.id === userId);
}
"""


class FakeEmbeddingClient:
    """Deterministic vectors, and a count of how many texts were actually paid for."""

    def __init__(self, dimensions=1536):
        self.dimensions = dimensions
        self.api_calls = 0
        self.embedded_texts = []

    def embed_texts(self, texts):
        self.embedded_texts.extend(texts)
        if texts:
            self.api_calls += 1
        return [[0.01] * self.dimensions for _ in texts]


def fake_archive(files):
    """Yield (path, size, handle) the way source.iter_repository_files does."""

    def _iter(installation_id, full_name, ref):
        for path, content in files.items():
            data = content if isinstance(content, bytes) else content.encode()
            yield path, len(data), io.BytesIO(data)

    return _iter


@pytest.fixture
def repository(db):
    user, _ = get_or_create_user_from_github(
        {"id": 1, "login": "owner", "name": "", "email": "", "avatar_url": ""}
    )
    installation = AppInstallation.objects.create(installation_id=999, account_login="owner")
    return Repository.objects.create(
        organization=user.memberships.get().organization,
        installation=installation,
        github_id=1,
        full_name="owner/repo",
        owner="owner",
        name="repo",
        default_branch="main",
    )


def run_index(repository, files, client=None, gitignore=""):
    job = IngestionJob.objects.create(repository=repository)
    client = client or FakeEmbeddingClient()

    with (
        mock.patch(
            "apps.ingestion.indexer.source.iter_repository_files",
            side_effect=fake_archive(files),
        ),
        mock.patch("apps.ingestion.indexer.source.resolve_head_sha", return_value="abc1234"),
        mock.patch("apps.ingestion.indexer.source.read_gitignore", return_value=gitignore),
    ):
        result = indexer.index_repository(job, embedding_client=client)

    job.refresh_from_db()
    return job, result, client


# --------------------------------------------------------------------- happy path


def test_indexing_stores_chunks_with_embeddings(repository):
    job, _, client = run_index(repository, {"app/users.py": GOOD_PY, "src/u.js": JS})

    assert job.status == IngestionJob.Status.DONE
    assert job.commit_sha == "abc1234"

    chunks = CodeChunk.objects.filter(repository=repository)
    assert chunks.count() > 0
    assert all(c.embedding is not None for c in chunks)
    assert {c.file_path for c in chunks} == {"app/users.py", "src/u.js"}


def test_stored_vectors_have_the_configured_dimension(repository, settings):
    job, _, _ = run_index(repository, {"a.py": GOOD_PY})

    chunk = CodeChunk.objects.filter(repository=repository).first()
    assert len(list(chunk.embedding)) == settings.EMBEDDING_DIMENSIONS


def test_citations_are_recorded(repository):
    run_index(repository, {"app/users.py": GOOD_PY})

    chunk = CodeChunk.objects.get(repository=repository, symbol="get_user")
    path, (start, end) = chunk.citation
    assert path == "app/users.py"
    assert start == 1 and end >= start


def test_embedding_text_includes_path_and_symbol(repository):
    """So a query can match on naming and location, not only the body."""
    _, _, client = run_index(repository, {"app/users.py": GOOD_PY})

    assert any("app/users.py :: get_user" in text for text in client.embedded_texts)


# ------------------------------------------------------------- the content cache


def test_reindexing_unchanged_code_pays_nothing(repository):
    """The cache is what makes re-indexing on every push affordable."""
    _, _, first = run_index(repository, {"app/users.py": GOOD_PY})
    assert first.embedded_texts, "the first run must actually embed"

    job, _, second = run_index(repository, {"app/users.py": GOOD_PY})

    assert second.embedded_texts == [], "unchanged content must not be re-embedded"
    assert second.api_calls == 0
    assert job.chunks_reused == job.chunks_created
    assert CodeChunk.objects.filter(repository=repository, embedding__isnull=True).count() == 0


def test_only_changed_chunks_are_re_embedded(repository):
    run_index(repository, {"a.py": GOOD_PY, "b.py": GOOD_PY.replace("get_user", "get_item")})

    changed = GOOD_PY.replace("return None", "return {}")
    job, _, client = run_index(
        repository, {"a.py": changed, "b.py": GOOD_PY.replace("get_user", "get_item")}
    )

    # Something was re-embedded, but not everything.
    assert client.embedded_texts
    assert job.chunks_reused > 0
    assert len(client.embedded_texts) < job.chunks_created


def test_identical_content_in_two_files_is_embedded_twice(repository):
    """Two files are two citations, so they must not share one cached vector."""
    _, _, client = run_index(repository, {"a.py": GOOD_PY, "b.py": GOOD_PY})

    paths = {c.file_path for c in CodeChunk.objects.filter(repository=repository)}
    assert paths == {"a.py", "b.py"}
    assert len(client.embedded_texts) >= 2


# ------------------------------------------------------- resilience and skipping


def test_an_unparseable_file_does_not_fail_the_job(repository):
    """The codesage-testbed case, exercised through the whole pipeline."""
    job, _, _ = run_index(repository, {"ok.py": GOOD_PY, "test.py": BROKEN_PY})

    assert job.status == IngestionJob.Status.DONE
    paths = {c.file_path for c in CodeChunk.objects.filter(repository=repository)}
    assert paths == {"ok.py", "test.py"}


def test_skipped_files_are_counted_not_indexed(repository):
    files = {
        "app/users.py": GOOD_PY,
        "package-lock.json": '{"lockfileVersion": 3}',
        "node_modules/x/index.js": JS,
        "logo.png": b"\x89PNG\x00\x00binary",
    }

    job, result, _ = run_index(repository, files)

    assert job.files_discovered == 4
    assert job.files_indexed == 1
    assert job.files_skipped == 3
    paths = {c.file_path for c in CodeChunk.objects.filter(repository=repository)}
    assert paths == {"app/users.py"}


def test_gitignored_files_are_skipped(repository):
    job, _, _ = run_index(
        repository,
        {"app/users.py": GOOD_PY, "debug.log": "noise " * 50},
        gitignore="*.log\n",
    )

    assert job.files_skipped == 1
    assert not CodeChunk.objects.filter(file_path="debug.log").exists()


def test_binary_content_without_a_known_extension_is_skipped(repository):
    job, _, _ = run_index(
        repository, {"app/users.py": GOOD_PY, "data.bin2": b"\x00\x01\x02\x03" * 100}
    )

    assert job.files_skipped == 1


def test_the_chunk_cap_is_enforced(repository, settings):
    """Neon's free plan is 0.5 GB; the cap is the main lever on storage."""
    settings.INGESTION_MAX_CHUNKS_PER_REPO = 3
    files = {f"mod{i}.py": GOOD_PY.replace("get_user", f"get_{i}") for i in range(10)}

    job, _, _ = run_index(repository, files)

    assert CodeChunk.objects.filter(repository=repository).count() <= 3


def test_oversized_files_are_skipped(repository, settings):
    settings.INGESTION_MAX_FILE_BYTES = 100

    job, _, _ = run_index(repository, {"big.py": GOOD_PY * 100, "small.py": "x = 1\n"})

    assert job.files_skipped >= 1
    assert not CodeChunk.objects.filter(file_path="big.py").exists()


# ----------------------------------------------------------------- failure paths


def test_a_fetch_failure_marks_the_job_failed(repository):
    job = IngestionJob.objects.create(repository=repository)

    with mock.patch(
        "apps.ingestion.indexer.source.resolve_head_sha",
        side_effect=SourceFetchError("archive gone"),
    ):
        indexer.index_repository(job, embedding_client=FakeEmbeddingClient())

    job.refresh_from_db()
    assert job.status == IngestionJob.Status.FAILED
    assert "archive gone" in job.error
    assert job.finished_at is not None


def test_an_embedding_failure_marks_the_job_failed(repository):
    class Failing(FakeEmbeddingClient):
        def embed_texts(self, texts):
            raise EmbeddingError("quota exhausted")

    job, _, _ = run_index(repository, {"a.py": GOOD_PY}, client=Failing())

    assert job.status == IngestionJob.Status.FAILED
    assert "quota exhausted" in job.error


def test_a_repository_without_an_installation_fails_cleanly(repository):
    repository.installation = None
    repository.save()
    job = IngestionJob.objects.create(repository=repository)

    indexer.index_repository(job, embedding_client=FakeEmbeddingClient())

    job.refresh_from_db()
    assert job.status == IngestionJob.Status.FAILED
    assert "installation" in job.error.lower()


def test_an_unexpected_error_is_captured_rather_than_raised(repository):
    job = IngestionJob.objects.create(repository=repository)

    with mock.patch(
        "apps.ingestion.indexer.source.resolve_head_sha",
        side_effect=RuntimeError("something odd"),
    ):
        indexer.index_repository(job, embedding_client=FakeEmbeddingClient())

    job.refresh_from_db()
    assert job.status == IngestionJob.Status.FAILED
    assert "RuntimeError" in job.error


def test_reindexing_replaces_rather_than_accumulates(repository):
    run_index(repository, {"a.py": GOOD_PY, "b.py": JS})
    first_count = CodeChunk.objects.filter(repository=repository).count()

    run_index(repository, {"a.py": GOOD_PY})

    paths = {c.file_path for c in CodeChunk.objects.filter(repository=repository)}
    assert paths == {"a.py"}
    assert CodeChunk.objects.filter(repository=repository).count() < first_count
