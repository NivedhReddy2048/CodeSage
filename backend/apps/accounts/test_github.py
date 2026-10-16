"""Unit tests for the GitHub OAuth client.

The rest of the suite stubs this module out wholesale, so the code that actually talks
to GitHub is only covered here. `requests` is mocked at the transport level rather than
the module being replaced, so the real parsing and error handling runs.
"""

from unittest import mock

import pytest
import requests
from django.core import signing

from apps.accounts import github
from apps.accounts.github import GitHubOAuthError


def fake_response(status_code=200, json_data=None, raise_on_json=False):
    response = mock.Mock()
    response.status_code = status_code
    if raise_on_json:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = json_data if json_data is not None else {}
    return response


# ------------------------------------------------------------------ state handling


def test_state_round_trips():
    state = github.build_state()
    github.verify_state(state)  # must not raise


def test_build_state_is_not_reused():
    assert github.build_state() != github.build_state()


def test_verify_state_rejects_missing_state():
    with pytest.raises(GitHubOAuthError, match="Missing"):
        github.verify_state("")


def test_verify_state_rejects_a_tampered_signature():
    state = github.build_state()

    with pytest.raises(GitHubOAuthError, match="invalid"):
        github.verify_state(state[:-1] + ("A" if state[-1] != "A" else "B"))


def test_verify_state_rejects_a_foreign_signature():
    """A value signed with a different salt must not pass."""
    foreign = signing.dumps("nonce", salt="some.other.purpose")

    with pytest.raises(GitHubOAuthError, match="invalid"):
        github.verify_state(foreign)


def test_verify_state_rejects_an_expired_state(monkeypatch):
    state = github.build_state()
    # A negative max age makes any token, however fresh, already expired.
    monkeypatch.setattr(github, "STATE_MAX_AGE_SECONDS", -1)

    with pytest.raises(GitHubOAuthError, match="expired"):
        github.verify_state(state)


# ------------------------------------------------------------------ authorize URL


def test_authorize_url_contains_the_state_and_no_repo_scope(settings):
    settings.GITHUB_CLIENT_ID = "cid"
    state = github.build_state()

    url = github.build_authorize_url(state)

    assert "client_id=cid" in url
    # Repository access belongs to the GitHub App, so the login scope must stay narrow.
    assert "repo" not in url.split("scope=")[1].split("&")[0]


# ----------------------------------------------------------------- token exchange


def test_exchange_returns_the_access_token(settings):
    settings.GITHUB_CLIENT_ID = "cid"
    settings.GITHUB_CLIENT_SECRET = "secret"

    with mock.patch.object(
        github.requests,
        "post",
        return_value=fake_response(200, {"access_token": "gho_real"}),
    ) as post:
        assert github.exchange_code_for_token("code123") == "gho_real"

    sent = post.call_args.kwargs["data"]
    assert sent["code"] == "code123"
    assert sent["client_secret"] == "secret"


def test_exchange_treats_a_200_with_an_error_key_as_failure():
    """The one genuinely surprising part of GitHub's OAuth API.

    A bad or reused code comes back as HTTP 200 with an `error` field, so checking the
    status code alone would hand a missing token to the caller.
    """
    payload = {
        "error": "bad_verification_code",
        "error_description": "The code passed is incorrect or expired.",
    }

    with mock.patch.object(github.requests, "post", return_value=fake_response(200, payload)):
        with pytest.raises(GitHubOAuthError, match="incorrect or expired"):
            github.exchange_code_for_token("stale")


def test_exchange_falls_back_to_the_error_code_without_a_description():
    with mock.patch.object(
        github.requests,
        "post",
        return_value=fake_response(200, {"error": "redirect_uri_mismatch"}),
    ):
        with pytest.raises(GitHubOAuthError, match="redirect_uri_mismatch"):
            github.exchange_code_for_token("code")


def test_exchange_rejects_a_non_200():
    with mock.patch.object(github.requests, "post", return_value=fake_response(500, {})):
        with pytest.raises(GitHubOAuthError, match="rejected"):
            github.exchange_code_for_token("code")


def test_exchange_rejects_a_missing_access_token():
    with mock.patch.object(
        github.requests, "post", return_value=fake_response(200, {"scope": "read:user"})
    ):
        with pytest.raises(GitHubOAuthError, match="no access token"):
            github.exchange_code_for_token("code")


def test_exchange_wraps_network_errors():
    """Callers catch GitHubOAuthError; a raw requests exception would 500."""
    with mock.patch.object(github.requests, "post", side_effect=requests.ConnectionError("dns")):
        with pytest.raises(GitHubOAuthError, match="Could not reach GitHub"):
            github.exchange_code_for_token("code")


# ------------------------------------------------------------------ profile fetch


def test_profile_is_returned_when_the_email_is_public():
    profile = {"id": 1, "login": "octocat", "email": "public@example.com"}

    with mock.patch.object(github.requests, "get", return_value=fake_response(200, profile)) as get:
        result = github.fetch_user_profile("gho_x")

    assert result["email"] == "public@example.com"
    # No need to ask for the email list when the profile already has one.
    assert get.call_count == 1


def test_profile_falls_back_to_the_primary_verified_email():
    profile = {"id": 1, "login": "octocat", "email": None}
    emails = [
        {"email": "old@example.com", "primary": False, "verified": True},
        {"email": "unverified@example.com", "primary": True, "verified": False},
        {"email": "primary@example.com", "primary": True, "verified": True},
    ]

    with mock.patch.object(
        github.requests,
        "get",
        side_effect=[fake_response(200, profile), fake_response(200, emails)],
    ):
        result = github.fetch_user_profile("gho_x")

    assert result["email"] == "primary@example.com"


def test_profile_ignores_an_unverified_primary_email():
    profile = {"id": 1, "login": "octocat", "email": None}
    emails = [{"email": "unverified@example.com", "primary": True, "verified": False}]

    with mock.patch.object(
        github.requests,
        "get",
        side_effect=[fake_response(200, profile), fake_response(200, emails)],
    ):
        result = github.fetch_user_profile("gho_x")

    assert result["email"] == ""


def test_profile_tolerates_the_email_endpoint_failing():
    """A missing email must not block login."""
    profile = {"id": 1, "login": "octocat", "email": None}

    with mock.patch.object(
        github.requests,
        "get",
        side_effect=[fake_response(200, profile), fake_response(403, {})],
    ):
        result = github.fetch_user_profile("gho_x")

    assert result["email"] == ""


def test_profile_tolerates_a_non_list_email_payload():
    profile = {"id": 1, "login": "octocat", "email": None}

    with mock.patch.object(
        github.requests,
        "get",
        side_effect=[fake_response(200, profile), fake_response(200, {"message": "no"})],
    ):
        assert github.fetch_user_profile("gho_x")["email"] == ""


def test_profile_without_an_id_is_rejected():
    """github_id is the identity everything else keys on, so it cannot be absent."""
    with mock.patch.object(
        github.requests, "get", return_value=fake_response(200, {"login": "octocat"})
    ):
        with pytest.raises(GitHubOAuthError, match="missing an id"):
            github.fetch_user_profile("gho_x")


def test_profile_rejects_a_non_200():
    with mock.patch.object(github.requests, "get", return_value=fake_response(401, {})):
        with pytest.raises(GitHubOAuthError, match="returned 401"):
            github.fetch_user_profile("expired-token")


def test_profile_wraps_network_errors():
    with mock.patch.object(github.requests, "get", side_effect=requests.Timeout("slow")):
        with pytest.raises(GitHubOAuthError, match="Could not reach the GitHub API"):
            github.fetch_user_profile("gho_x")


def test_profile_sends_the_bearer_token_and_api_version():
    with mock.patch.object(
        github.requests,
        "get",
        return_value=fake_response(200, {"id": 1, "email": "a@b.co"}),
    ) as get:
        github.fetch_user_profile("gho_secret")

    headers = get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer gho_secret"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"
