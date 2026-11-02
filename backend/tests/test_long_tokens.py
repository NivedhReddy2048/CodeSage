"""GitHub installation tokens of any length pass through untouched.

GitHub is moving installation tokens to a new format (`ghs_...`, up to about 520
characters). Nothing in CodeSage stores one in a model field, keys a cache entry by
one, validates one with a pattern, or logs one, so nothing may truncate or reject a
long one. These tests pin that with a 600-character token: minted, cached in the
real Redis, and sent whole in every Authorization header CodeSage builds.
"""

from unittest import mock

import pytest
from django.core.cache import cache

from apps.repos import github_app
from apps.repos.github_app import GitHubAppError

# 600 characters, with the underscores and mixed case the new format uses.
LONG_TOKEN = "ghs_" + ("Ab3_xY9z" * 75)[:596]
INSTALLATION = 4242


def response(status, payload=None, text=""):
    fake = mock.Mock(status_code=status, text=text or str(payload), headers={})
    fake.json.return_value = payload if payload is not None else {}
    return fake


@pytest.fixture(autouse=True)
def minted():
    """A token minted through the real chain (the App JWT aside) and cached in Redis."""
    assert len(LONG_TOKEN) == 600
    cache.clear()
    with (
        mock.patch.object(github_app, "build_app_jwt", return_value="app-jwt"),
        mock.patch.object(
            github_app.requests,
            "request",
            return_value=response(201, {"token": LONG_TOKEN, "expires_at": "2099-01-01T00:00:00Z"}),
        ),
    ):
        assert github_app.get_installation_token(INSTALLATION) == LONG_TOKEN
    yield
    cache.clear()


def bearer(call):
    return call.kwargs["headers"]["Authorization"]


def test_the_cached_token_comes_back_whole_without_minting_again():
    with mock.patch.object(github_app.requests, "request") as request:
        assert github_app.get_installation_token(INSTALLATION) == LONG_TOKEN

    request.assert_not_called()


def test_rest_and_graphql_calls_send_it_whole():
    with mock.patch.object(
        github_app.requests, "request", return_value=response(200, {"number": 1})
    ) as request:
        github_app.get_pull_request(INSTALLATION, "alice/app", 1)
    assert bearer(request.call_args) == f"Bearer {LONG_TOKEN}"

    data = {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}
    with mock.patch.object(github_app.requests, "request", return_value=response(200, data)) as gql:
        github_app.list_review_threads(INSTALLATION, "alice/app", 1)
    assert bearer(gql.call_args) == f"Bearer {LONG_TOKEN}"


def test_the_review_diff_fetch_sends_it_whole():
    from apps.reviews import services

    diff = response(200, text="diff")
    with mock.patch.object(services.requests, "get", return_value=diff) as get:
        services.fetch_diff(INSTALLATION, "alice/app", 1)

    assert bearer(get.call_args) == f"Bearer {LONG_TOKEN}"


def test_ingestion_sends_it_whole():
    from apps.ingestion import source

    with mock.patch.object(
        source.requests, "get", return_value=response(200, {"sha": "a" * 40})
    ) as get:
        source.resolve_head_sha(INSTALLATION, "alice/app", "main")
        source.read_gitignore(INSTALLATION, "alice/app", "main")

    assert [bearer(call) for call in get.call_args_list] == [f"Bearer {LONG_TOKEN}"] * 2


def test_a_rejected_call_never_carries_the_token_in_its_error():
    """Error messages are truncated and logged; the token must not be in them."""
    with (
        mock.patch.object(
            github_app.requests,
            "request",
            return_value=response(401, text='{"message": "Bad credentials"}'),
        ),
        pytest.raises(GitHubAppError) as raised,
    ):
        github_app.get_pull_request(INSTALLATION, "alice/app", 1)

    assert "401" in str(raised.value)
    assert LONG_TOKEN not in str(raised.value)
    assert LONG_TOKEN[:20] not in str(raised.value)
