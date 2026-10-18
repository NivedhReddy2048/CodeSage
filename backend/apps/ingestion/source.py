"""Fetch a repository's source through the GitHub App installation token.

Deliberately not `git clone`. Render's free tier gives an ephemeral filesystem and no
guarantee the app process can shell out to git, so cloning is a thing that works on a
laptop and fails in production. The tarball endpoint needs only `contents: read`,
which the App already has, and arrives as a single stream we can read without ever
writing it to disk.
"""

import io
import logging
import tarfile

import requests
from django.conf import settings

from apps.repos.github_app import API_HEADERS, GitHubAppError, get_installation_token

logger = logging.getLogger(__name__)

API_ROOT = "https://api.github.com"
TIMEOUT = 120


class SourceFetchError(Exception):
    """The repository archive could not be fetched or read."""


def resolve_head_sha(installation_id, full_name, ref):
    """The commit the index will describe, recorded on the IngestionJob."""
    token = get_installation_token(installation_id)
    try:
        response = requests.get(
            f"{API_ROOT}/repos/{full_name}/commits/{ref}",
            headers={**API_HEADERS, "Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise SourceFetchError(f"Could not reach GitHub: {exc}") from exc

    if response.status_code != 200:
        raise SourceFetchError(f"Could not resolve {full_name}@{ref}: HTTP {response.status_code}")
    return response.json().get("sha", "")


def iter_repository_files(installation_id, full_name, ref):
    """Yield `(relative_path, bytes)` for every file in the repository archive.

    Streams the tarball into memory rather than to disk: a free dyno has no
    persistent storage, and repositories within the archive cap are small enough that
    memory is the simpler and faster choice.
    """
    token = get_installation_token(installation_id)
    url = f"{API_ROOT}/repos/{full_name}/tarball/{ref}"

    try:
        response = requests.get(
            url,
            headers={**API_HEADERS, "Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
            stream=True,
        )
    except requests.RequestException as exc:
        raise SourceFetchError(f"Could not download the archive: {exc}") from exc

    if response.status_code != 200:
        raise SourceFetchError(f"Archive download failed: HTTP {response.status_code}")

    payload = _read_capped(response)

    try:
        archive = tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz")
    except tarfile.TarError as exc:
        raise SourceFetchError(f"Archive is not a readable tarball: {exc}") from exc

    with archive:
        for member in archive:
            if not member.isfile():
                continue

            # GitHub wraps everything in a "<owner>-<repo>-<sha>/" directory; strip it
            # so stored paths match what a reviewer sees on GitHub.
            relative = member.name.split("/", 1)[-1] if "/" in member.name else member.name
            if not relative:
                continue

            try:
                handle = archive.extractfile(member)
            except tarfile.TarError:
                continue
            if handle is None:
                continue

            yield relative, member.size, handle


def _read_capped(response):
    """Read the response body, refusing anything over the archive cap.

    Without this a single enormous repository could exhaust the dyno's memory; the
    job should fail with a clear message instead of being killed by the platform.
    """
    cap = settings.INGESTION_MAX_ARCHIVE_BYTES
    buffer = io.BytesIO()
    total = 0

    for block in response.iter_content(chunk_size=64 * 1024):
        total += len(block)
        if total > cap:
            raise SourceFetchError(
                f"Repository archive exceeds the {cap // (1024 * 1024)} MB limit."
            )
        buffer.write(block)

    return buffer.getvalue()


def read_gitignore(installation_id, full_name, ref):
    """Fetch the repository's .gitignore, or '' when it has none."""
    token = get_installation_token(installation_id)
    try:
        response = requests.get(
            f"{API_ROOT}/repos/{full_name}/contents/.gitignore",
            headers={
                **API_HEADERS,
                "Authorization": f"Bearer {token}",
                # raw avoids a base64 round trip for what is a small text file.
                "Accept": "application/vnd.github.raw+json",
            },
            params={"ref": ref},
            timeout=TIMEOUT,
        )
    except (requests.RequestException, GitHubAppError):
        return ""

    if response.status_code != 200:
        return ""
    return response.text
