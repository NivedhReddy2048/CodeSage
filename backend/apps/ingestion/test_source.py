"""Tests for fetching repository source through the GitHub App.

Real in-memory tarballs, mocked HTTP. The path-stripping case matters most: GitHub
wraps every archive in an "<owner>-<repo>-<sha>/" directory, and if that survived
into stored paths, every citation would point at a path that does not exist on
GitHub.
"""

import io
import tarfile
from unittest import mock

import pytest
import requests

from apps.ingestion import source
from apps.ingestion.source import SourceFetchError


def build_tarball(files, prefix="owner-repo-abc1234"):
    """A gzipped tarball shaped like GitHub's, wrapper directory included."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        # The wrapper directory entry itself, which must be ignored.
        info = tarfile.TarInfo(name=prefix)
        info.type = tarfile.DIRTYPE
        archive.addfile(info)

        for path, content in files.items():
            data = content if isinstance(content, bytes) else content.encode()
            info = tarfile.TarInfo(name=f"{prefix}/{path}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def streaming_response(payload, status_code=200):
    response = mock.Mock()
    response.status_code = status_code
    response.iter_content = lambda chunk_size: [
        payload[i : i + chunk_size] for i in range(0, len(payload), chunk_size)
    ]
    return response


@pytest.fixture(autouse=True)
def token():
    with mock.patch("apps.ingestion.source.get_installation_token", return_value="ghs_fake"):
        yield


# ---------------------------------------------------------------- the tarball


def test_files_are_yielded_with_the_wrapper_directory_stripped():
    """Citations must match paths as they appear on GitHub."""
    payload = build_tarball({"app/users.py": "x = 1\n", "README.md": "# hi\n"})

    with mock.patch("apps.ingestion.source.requests.get", return_value=streaming_response(payload)):
        files = {
            path: handle.read()
            for path, _, handle in source.iter_repository_files(1, "owner/repo", "main")
        }

    assert set(files) == {"app/users.py", "README.md"}
    assert files["app/users.py"] == b"x = 1\n"


def test_sizes_are_reported_for_the_selection_pass():
    payload = build_tarball({"a.py": "0123456789"})

    with mock.patch("apps.ingestion.source.requests.get", return_value=streaming_response(payload)):
        entries = list(source.iter_repository_files(1, "owner/repo", "main"))

    assert entries[0][1] == 10


def test_directories_are_not_yielded():
    payload = build_tarball({"pkg/mod.py": "x = 1\n"})

    with mock.patch("apps.ingestion.source.requests.get", return_value=streaming_response(payload)):
        paths = [p for p, _, _ in source.iter_repository_files(1, "owner/repo", "main")]

    assert paths == ["pkg/mod.py"]


def test_the_installation_token_is_used():
    payload = build_tarball({"a.py": "x = 1\n"})

    with mock.patch(
        "apps.ingestion.source.requests.get", return_value=streaming_response(payload)
    ) as get:
        list(source.iter_repository_files(1, "owner/repo", "main"))

    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer ghs_fake"
    assert "tarball/main" in get.call_args.args[0]


# -------------------------------------------------------------------- failures


def test_a_non_200_archive_response_raises():
    with mock.patch(
        "apps.ingestion.source.requests.get",
        return_value=streaming_response(b"", status_code=404),
    ):
        with pytest.raises(SourceFetchError, match="HTTP 404"):
            list(source.iter_repository_files(1, "owner/repo", "main"))


def test_a_network_failure_raises_source_fetch_error():
    with mock.patch(
        "apps.ingestion.source.requests.get",
        side_effect=requests.ConnectionError("dns"),
    ):
        with pytest.raises(SourceFetchError, match="Could not download"):
            list(source.iter_repository_files(1, "owner/repo", "main"))


def test_a_corrupt_archive_raises_rather_than_crashing():
    with mock.patch(
        "apps.ingestion.source.requests.get",
        return_value=streaming_response(b"this is not a tarball"),
    ):
        with pytest.raises(SourceFetchError, match="not a readable tarball"):
            list(source.iter_repository_files(1, "owner/repo", "main"))


def test_an_oversized_archive_is_refused_before_it_exhausts_memory(settings):
    """A huge repo should fail with a clear message, not be killed by the platform."""
    settings.INGESTION_MAX_ARCHIVE_BYTES = 100

    with mock.patch(
        "apps.ingestion.source.requests.get",
        return_value=streaming_response(b"x" * 5000),
    ):
        with pytest.raises(SourceFetchError, match="exceeds"):
            list(source.iter_repository_files(1, "owner/repo", "main"))


# ------------------------------------------------------------------- head sha


def test_head_sha_is_resolved():
    response = mock.Mock(status_code=200)
    response.json.return_value = {"sha": "deadbeef"}

    with mock.patch("apps.ingestion.source.requests.get", return_value=response):
        assert source.resolve_head_sha(1, "owner/repo", "main") == "deadbeef"


def test_head_sha_failure_raises():
    with mock.patch("apps.ingestion.source.requests.get", return_value=mock.Mock(status_code=422)):
        with pytest.raises(SourceFetchError, match="Could not resolve"):
            source.resolve_head_sha(1, "owner/repo", "nope")


def test_head_sha_network_failure_raises():
    with mock.patch("apps.ingestion.source.requests.get", side_effect=requests.Timeout("slow")):
        with pytest.raises(SourceFetchError, match="Could not reach GitHub"):
            source.resolve_head_sha(1, "owner/repo", "main")


# ------------------------------------------------------------------ gitignore


def test_gitignore_is_fetched_as_raw_text():
    response = mock.Mock(status_code=200)
    response.text = "*.log\n"

    with mock.patch("apps.ingestion.source.requests.get", return_value=response) as get:
        assert source.read_gitignore(1, "owner/repo", "main") == "*.log\n"

    assert get.call_args.kwargs["headers"]["Accept"] == "application/vnd.github.raw+json"


def test_a_missing_gitignore_is_not_an_error():
    """Most repositories have one; a repository without one must still index."""
    with mock.patch("apps.ingestion.source.requests.get", return_value=mock.Mock(status_code=404)):
        assert source.read_gitignore(1, "owner/repo", "main") == ""


def test_a_gitignore_fetch_failure_degrades_quietly():
    with mock.patch(
        "apps.ingestion.source.requests.get", side_effect=requests.ConnectionError("x")
    ):
        assert source.read_gitignore(1, "owner/repo", "main") == ""
