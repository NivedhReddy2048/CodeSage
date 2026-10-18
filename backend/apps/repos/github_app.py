"""GitHub App authentication — the credential the PR loop runs on.

Distinct from `apps.accounts.github`, which handles the OAuth App used for human
login. This module never acts as a user: it acts as the App installation, so review
comments appear as the bot and access is scoped to the repositories the App was
installed on (spec section 13).

The token chain:

    App ID or Client ID + private key
        -> RS256 JWT (max 10 minutes, used only against /app endpoints)
        -> installation access token (1 hour, scoped to one installation)
        -> every other REST call

Installation tokens are cached until shortly before they expire. Minting one per call
would waste a round trip on every request and burn rate limit for no benefit.
"""

import time

import jwt
import requests
from django.conf import settings
from django.core.cache import cache

API_ROOT = "https://api.github.com"

API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

TIMEOUT = 15

# GitHub rejects an `exp` more than 10 minutes out; 9 leaves room for clock skew.
JWT_LIFETIME_SECONDS = 9 * 60
# GitHub's own advice: backdate `iat` to absorb drift between us and them.
JWT_BACKDATE_SECONDS = 60

# Renew this long before the token actually expires, so a request can never set off
# with a token that dies mid-flight.
TOKEN_RENEWAL_MARGIN_SECONDS = 60


class GitHubAppError(Exception):
    """The App could not authenticate, or GitHub returned something unusable."""


def _private_key():
    """Return the App's private key as PEM bytes.

    Two sources, because the deployment shapes differ: locally the key is a file that
    must never be committed, while on Render there is no filesystem to put it on, so
    the PEM travels as an environment variable. Env vars cannot hold real newlines
    reliably, hence the unescaping.
    """
    inline = (settings.GITHUB_APP_PRIVATE_KEY or "").strip()
    if inline:
        return inline.replace("\\n", "\n").encode("utf-8")

    path = settings.GITHUB_APP_PRIVATE_KEY_PATH
    if not path:
        raise GitHubAppError(
            "No GitHub App private key configured. Set GITHUB_APP_PRIVATE_KEY_PATH "
            "locally or GITHUB_APP_PRIVATE_KEY in production."
        )

    key_path = settings.BASE_DIR / path
    try:
        return key_path.read_bytes()
    except OSError as exc:
        raise GitHubAppError(f"Could not read the private key at {key_path}.") from exc


def _issuer():
    """The JWT `iss` claim.

    GitHub's docs state "Use of the client ID is recommended", with the numeric App ID
    still accepted and not deprecated. Prefer the client ID when it is configured so
    we follow the current recommendation, but keep working from the App ID alone.
    """
    issuer = settings.GITHUB_APP_CLIENT_ID or settings.GITHUB_APP_ID
    if not issuer:
        raise GitHubAppError(
            "No GitHub App identity configured. Set GITHUB_APP_CLIENT_ID "
            "(recommended) or GITHUB_APP_ID."
        )
    return str(issuer)


def build_app_jwt():
    """Sign a short-lived JWT identifying the App itself (not an installation)."""
    now = int(time.time())
    payload = {
        "iat": now - JWT_BACKDATE_SECONDS,
        "exp": now + JWT_LIFETIME_SECONDS,
        "iss": _issuer(),
    }
    try:
        return jwt.encode(payload, _private_key(), algorithm="RS256")
    except GitHubAppError:
        raise
    except Exception as exc:  # noqa: BLE001 - surfaces as one error type to callers
        raise GitHubAppError(f"Could not sign the App JWT: {exc}") from exc


def _request(method, path, token, **kwargs):
    """Call the GitHub API, normalising transport and status failures."""
    try:
        response = requests.request(
            method,
            f"{API_ROOT}{path}",
            headers={**API_HEADERS, "Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise GitHubAppError(f"Could not reach the GitHub API: {exc}") from exc

    if response.status_code >= 400:
        raise GitHubAppError(
            f"GitHub API {method} {path} returned {response.status_code}: {response.text[:200]}"
        )
    return response


def get_app_metadata():
    """`GET /app` — useful as a credential health check."""
    return _request("GET", "/app", build_app_jwt()).json()


def _token_cache_key(installation_id):
    return f"github:installation-token:{installation_id}"


def get_installation_token(installation_id):
    """Return a valid installation access token, minting one only when needed."""
    cache_key = _token_cache_key(installation_id)
    cached = cache.get(cache_key)
    if cached:
        return cached

    response = _request(
        "POST", f"/app/installations/{installation_id}/access_tokens", build_app_jwt()
    )
    payload = response.json()
    token = payload.get("token")
    if not token:
        raise GitHubAppError("GitHub returned no installation token.")

    cache.set(cache_key, token, timeout=_cache_seconds(payload.get("expires_at")))
    return token


def _cache_seconds(expires_at):
    """Seconds to cache a token for, stopping short of its actual expiry.

    Falls back to a conservative window when GitHub omits or malforms `expires_at`,
    rather than caching indefinitely and serving a dead token later.
    """
    default = 50 * 60  # Tokens last an hour; assume slightly less when unsure.
    if not expires_at:
        return default

    from django.utils.dateparse import parse_datetime

    parsed = parse_datetime(expires_at)
    if parsed is None:
        return default

    remaining = parsed.timestamp() - time.time() - TOKEN_RENEWAL_MARGIN_SECONDS
    # Never cache for a non-positive duration: Django treats timeout=0 as "do not
    # cache" and a negative value as immediate expiry, both of which are fine, but a
    # clamp keeps the intent explicit.
    return int(remaining) if remaining > 0 else 0


def invalidate_installation_token(installation_id):
    """Drop a cached token, so the next call mints a fresh one.

    Used when GitHub rejects a token we believed was valid — for instance after the
    installation's permissions change.
    """
    cache.delete(_token_cache_key(installation_id))


def list_installations():
    """Every installation of this App. Used to reconcile local state."""
    return _request("GET", "/app/installations", build_app_jwt()).json()


def get_installation(installation_id):
    return _request("GET", f"/app/installations/{installation_id}", build_app_jwt()).json()


def create_issue_comment(installation_id, repo_full_name, issue_number, body):
    """Comment on a PR as the App.

    PRs are issues as far as this endpoint is concerned, which is why the path says
    `issues`. Needs the `pull_requests: write` permission.
    """
    token = get_installation_token(installation_id)
    response = _request(
        "POST",
        f"/repos/{repo_full_name}/issues/{issue_number}/comments",
        token,
        json={"body": body},
    )
    return response.json()


def update_issue_comment(installation_id, repo_full_name, comment_id, body):
    """Edit a comment the App previously made.

    Phase 5 uses this to turn the acknowledgement into the finished review, so a PR
    carries one bot comment rather than a running commentary.
    """
    token = get_installation_token(installation_id)
    response = _request(
        "PATCH",
        f"/repos/{repo_full_name}/issues/comments/{comment_id}",
        token,
        json={"body": body},
    )
    return response.json()


def list_installation_repositories(installation_id):
    """Repositories an installation can reach, following pagination."""
    token = get_installation_token(installation_id)
    repositories = []
    page = 1

    while True:
        response = _request(
            "GET",
            f"/installation/repositories?per_page=100&page={page}",
            token,
        )
        batch = response.json().get("repositories", [])
        repositories.extend(batch)
        # GitHub omits a `next` link on the final page; checking the batch size works
        # the same way without parsing the Link header.
        if len(batch) < 100:
            break
        page += 1

    return repositories
