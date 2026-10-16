"""GitHub OAuth App client — user login only.

Everything that touches a repository (webhooks, PR comments, file reads) goes through
the GitHub *App* installation token instead, which arrives in Phase 2 (spec section 13).
This module is strictly about identifying the human signing in.

The OAuth redirect lands on the FRONTEND, which then POSTs the code here. That keeps
issued JWTs out of URLs, browser history and referrer headers entirely — the
alternative, redirecting to the backend and bouncing to the frontend with tokens in the
query string or fragment, leaks credentials into places that get logged and synced.
"""

import secrets

import requests
from django.conf import settings
from django.core import signing

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_API_URL = "https://api.github.com/user"
USER_EMAILS_API_URL = "https://api.github.com/user/emails"

# Enough to read the signing-in user's profile and verified email. No repo scope:
# repository access belongs to the GitHub App, not to the user's token.
SCOPES = "read:user user:email"

STATE_SALT = "accounts.github.oauth.state"
STATE_MAX_AGE_SECONDS = 600

TIMEOUT = 10


class GitHubOAuthError(Exception):
    """GitHub rejected the exchange, or returned something unusable."""


def build_state():
    """Return a signed, timestamped nonce for the OAuth `state` parameter.

    Signed rather than stored: there is no server-side session to hang it on, and a
    signature plus a 10 minute expiry gives the same replay protection without making
    login depend on Redis being up.
    """
    return signing.dumps(secrets.token_urlsafe(16), salt=STATE_SALT)


def verify_state(state):
    """Raise GitHubOAuthError unless `state` is one of ours and still fresh."""
    if not state:
        raise GitHubOAuthError("Missing OAuth state parameter.")
    try:
        signing.loads(state, salt=STATE_SALT, max_age=STATE_MAX_AGE_SECONDS)
    except signing.SignatureExpired as exc:
        raise GitHubOAuthError("OAuth state has expired. Start the login again.") from exc
    except signing.BadSignature as exc:
        raise GitHubOAuthError("OAuth state is invalid.") from exc


def build_authorize_url(state):
    """The URL to send the browser to, to begin the OAuth dance."""
    from urllib.parse import urlencode

    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_token(code):
    """Trade a single-use authorization code for a user access token."""
    try:
        response = requests.post(
            ACCESS_TOKEN_URL,
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
            },
            headers={"Accept": "application/json"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise GitHubOAuthError("Could not reach GitHub to exchange the code.") from exc

    if response.status_code != 200:
        raise GitHubOAuthError("GitHub rejected the code exchange.")

    payload = response.json()

    # GitHub signals failure with HTTP 200 and an `error` key, so the status code alone
    # is not enough to tell success from failure here.
    if "error" in payload:
        raise GitHubOAuthError(payload.get("error_description") or payload["error"])

    token = payload.get("access_token")
    if not token:
        raise GitHubOAuthError("GitHub returned no access token.")
    return token


def _api_get(url, token):
    try:
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise GitHubOAuthError("Could not reach the GitHub API.") from exc

    if response.status_code != 200:
        raise GitHubOAuthError(f"GitHub API returned {response.status_code}.")
    return response.json()


def fetch_user_profile(token):
    """Return the signing-in user's GitHub profile as a dict.

    Falls back to /user/emails when the profile's email is private, which is the
    default for a lot of accounts — without this, those users get a blank email.
    """
    profile = _api_get(USER_API_URL, token)

    if not profile.get("id"):
        raise GitHubOAuthError("GitHub profile is missing an id.")

    if not profile.get("email"):
        profile["email"] = _fetch_primary_email(token)

    return profile


def _fetch_primary_email(token):
    """Best-effort primary verified email. Returns "" rather than failing login."""
    try:
        emails = _api_get(USER_EMAILS_API_URL, token)
    except GitHubOAuthError:
        return ""

    if not isinstance(emails, list):
        return ""

    for entry in emails:
        if entry.get("primary") and entry.get("verified"):
            return entry.get("email") or ""
    return ""
