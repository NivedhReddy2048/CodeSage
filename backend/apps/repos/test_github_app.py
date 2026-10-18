"""Tests for the GitHub App token chain.

GitHub is mocked at the transport level. A throwaway RSA key is generated per test
run, so no real credential is needed and CI makes no network calls.
"""

import time
from unittest import mock

import jwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.cache import cache

from apps.repos import github_app
from apps.repos.github_app import GitHubAppError


@pytest.fixture(scope="module")
def rsa_keypair():
    """A real 2048-bit key, so RS256 signing and verification genuinely run."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


@pytest.fixture
def app_settings(settings, rsa_keypair):
    private_pem, _ = rsa_keypair
    settings.GITHUB_APP_ID = "5366297"
    settings.GITHUB_APP_CLIENT_ID = ""
    settings.GITHUB_APP_PRIVATE_KEY = private_pem
    settings.GITHUB_APP_PRIVATE_KEY_PATH = ""
    return settings


@pytest.fixture(autouse=True)
def clear_cache():
    """Installation tokens are cached; leaking one between tests would hide bugs."""
    cache.clear()
    yield
    cache.clear()


def api_response(status_code=200, json_data=None, text=""):
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = json_data if json_data is not None else {}
    response.text = text
    return response


# ------------------------------------------------------------------------ JWT shape


def test_jwt_claims_match_githubs_requirements(app_settings, rsa_keypair):
    _, public_pem = rsa_keypair
    before = int(time.time())

    token = github_app.build_app_jwt()

    claims = jwt.decode(token, public_pem, algorithms=["RS256"], options={"verify_aud": False})
    assert claims["iss"] == "5366297"
    # Backdated to absorb clock drift, as GitHub advises.
    assert claims["iat"] <= before - 59
    # GitHub rejects anything more than 10 minutes out.
    assert claims["exp"] - claims["iat"] <= 600
    assert jwt.get_unverified_header(token)["alg"] == "RS256"


def test_jwt_prefers_the_client_id_as_issuer(app_settings, rsa_keypair):
    """GitHub's docs recommend the client ID over the numeric App ID."""
    _, public_pem = rsa_keypair
    app_settings.GITHUB_APP_CLIENT_ID = "Iv23liAbCdEfGhIjKlMn"

    claims = jwt.decode(github_app.build_app_jwt(), public_pem, algorithms=["RS256"])

    assert claims["iss"] == "Iv23liAbCdEfGhIjKlMn"


def test_jwt_falls_back_to_the_app_id(app_settings, rsa_keypair):
    """Must keep working when only the App ID is configured."""
    _, public_pem = rsa_keypair
    app_settings.GITHUB_APP_CLIENT_ID = ""

    claims = jwt.decode(github_app.build_app_jwt(), public_pem, algorithms=["RS256"])

    assert claims["iss"] == "5366297"


def test_jwt_without_any_identity_is_an_error(app_settings):
    app_settings.GITHUB_APP_ID = ""
    app_settings.GITHUB_APP_CLIENT_ID = ""

    with pytest.raises(GitHubAppError, match="No GitHub App identity"):
        github_app.build_app_jwt()


# ------------------------------------------------------------------- key loading


def test_key_is_read_from_a_file_path(app_settings, rsa_keypair, tmp_path, settings):
    """The local-development path: a gitignored .pem on disk."""
    private_pem, public_pem = rsa_keypair
    key_file = tmp_path / "app.pem"
    key_file.write_text(private_pem)

    app_settings.GITHUB_APP_PRIVATE_KEY = ""
    app_settings.GITHUB_APP_PRIVATE_KEY_PATH = "app.pem"
    settings.BASE_DIR = tmp_path

    claims = jwt.decode(github_app.build_app_jwt(), public_pem, algorithms=["RS256"])

    assert claims["iss"] == "5366297"


def test_escaped_newlines_in_the_env_var_are_unescaped(app_settings, rsa_keypair):
    """Env vars cannot hold real newlines reliably, so production escapes them."""
    private_pem, public_pem = rsa_keypair
    app_settings.GITHUB_APP_PRIVATE_KEY = private_pem.replace("\n", "\\n")

    claims = jwt.decode(github_app.build_app_jwt(), public_pem, algorithms=["RS256"])

    assert claims["iss"] == "5366297"


def test_missing_key_configuration_is_an_error(app_settings):
    app_settings.GITHUB_APP_PRIVATE_KEY = ""
    app_settings.GITHUB_APP_PRIVATE_KEY_PATH = ""

    with pytest.raises(GitHubAppError, match="No GitHub App private key"):
        github_app.build_app_jwt()


def test_unreadable_key_file_is_an_error(app_settings, settings, tmp_path):
    app_settings.GITHUB_APP_PRIVATE_KEY = ""
    app_settings.GITHUB_APP_PRIVATE_KEY_PATH = "does-not-exist.pem"
    settings.BASE_DIR = tmp_path

    with pytest.raises(GitHubAppError, match="Could not read the private key"):
        github_app.build_app_jwt()


def test_a_malformed_key_is_an_error(app_settings):
    app_settings.GITHUB_APP_PRIVATE_KEY = "-----BEGIN RSA PRIVATE KEY-----\nnope\n"

    with pytest.raises(GitHubAppError, match="Could not sign"):
        github_app.build_app_jwt()


# ------------------------------------------------------------ installation tokens


def test_installation_token_is_fetched_and_returned(app_settings):
    payload = {"token": "ghs_installation", "expires_at": "2099-01-01T00:00:00Z"}

    with mock.patch.object(
        github_app.requests, "request", return_value=api_response(201, payload)
    ) as request:
        assert github_app.get_installation_token(172631969) == "ghs_installation"

    args = request.call_args.args
    assert args[0] == "POST"
    assert "/app/installations/172631969/access_tokens" in args[1]


def test_installation_token_is_cached_and_not_refetched(app_settings):
    payload = {"token": "ghs_cached", "expires_at": "2099-01-01T00:00:00Z"}

    with mock.patch.object(
        github_app.requests, "request", return_value=api_response(201, payload)
    ) as request:
        github_app.get_installation_token(1)
        github_app.get_installation_token(1)
        github_app.get_installation_token(1)

    # One network call for three logical uses: the point of the cache.
    assert request.call_count == 1


def test_tokens_are_cached_per_installation(app_settings):
    """Two installations must never share a token: they have different scopes."""
    responses = [
        api_response(201, {"token": "ghs_one", "expires_at": "2099-01-01T00:00:00Z"}),
        api_response(201, {"token": "ghs_two", "expires_at": "2099-01-01T00:00:00Z"}),
    ]

    with mock.patch.object(github_app.requests, "request", side_effect=responses):
        assert github_app.get_installation_token(111) == "ghs_one"
        assert github_app.get_installation_token(222) == "ghs_two"


def test_invalidating_a_token_forces_a_refetch(app_settings):
    responses = [
        api_response(201, {"token": "ghs_first", "expires_at": "2099-01-01T00:00:00Z"}),
        api_response(201, {"token": "ghs_second", "expires_at": "2099-01-01T00:00:00Z"}),
    ]

    with mock.patch.object(github_app.requests, "request", side_effect=responses):
        assert github_app.get_installation_token(1) == "ghs_first"
        github_app.invalidate_installation_token(1)
        assert github_app.get_installation_token(1) == "ghs_second"


def test_a_token_expiring_imminently_is_not_cached(app_settings):
    """Caching a token that dies in 10 seconds would hand out a dead credential."""
    from django.utils import timezone

    soon = (timezone.now() + timezone.timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    responses = [
        api_response(201, {"token": "ghs_a", "expires_at": soon}),
        api_response(201, {"token": "ghs_b", "expires_at": soon}),
    ]

    with mock.patch.object(github_app.requests, "request", side_effect=responses):
        assert github_app.get_installation_token(1) == "ghs_a"
        # Not served from cache, because the renewal margin exceeds the lifetime.
        assert github_app.get_installation_token(1) == "ghs_b"


def test_a_missing_expires_at_still_caches_conservatively(app_settings):
    with mock.patch.object(
        github_app.requests,
        "request",
        return_value=api_response(201, {"token": "ghs_no_expiry"}),
    ) as request:
        github_app.get_installation_token(1)
        github_app.get_installation_token(1)

    assert request.call_count == 1


def test_a_malformed_expires_at_still_caches_conservatively(app_settings):
    with mock.patch.object(
        github_app.requests,
        "request",
        return_value=api_response(201, {"token": "ghs_x", "expires_at": "not-a-date"}),
    ) as request:
        github_app.get_installation_token(1)
        github_app.get_installation_token(1)

    assert request.call_count == 1


def test_a_response_without_a_token_is_an_error(app_settings):
    with mock.patch.object(github_app.requests, "request", return_value=api_response(201, {})):
        with pytest.raises(GitHubAppError, match="no installation token"):
            github_app.get_installation_token(1)


# ----------------------------------------------------------------- error handling


def test_http_errors_are_wrapped(app_settings):
    with mock.patch.object(
        github_app.requests,
        "request",
        return_value=api_response(404, text="Not Found"),
    ):
        with pytest.raises(GitHubAppError, match="returned 404"):
            github_app.get_app_metadata()


def test_network_errors_are_wrapped(app_settings):
    """Callers catch GitHubAppError; a bare requests exception would 500."""
    with mock.patch.object(
        github_app.requests, "request", side_effect=requests.ConnectionError("dns")
    ):
        with pytest.raises(GitHubAppError, match="Could not reach the GitHub API"):
            github_app.get_app_metadata()


# -------------------------------------------------------------------- repo listing


def test_repository_listing_follows_pagination(app_settings):
    first = {"repositories": [{"full_name": f"o/r{i}"} for i in range(100)]}
    second = {"repositories": [{"full_name": "o/last"}]}

    responses = [
        api_response(201, {"token": "ghs_t", "expires_at": "2099-01-01T00:00:00Z"}),
        api_response(200, first),
        api_response(200, second),
    ]

    with mock.patch.object(github_app.requests, "request", side_effect=responses):
        repositories = github_app.list_installation_repositories(1)

    assert len(repositories) == 101
    assert repositories[-1]["full_name"] == "o/last"


def test_repository_listing_stops_on_a_short_page(app_settings):
    responses = [
        api_response(201, {"token": "ghs_t", "expires_at": "2099-01-01T00:00:00Z"}),
        api_response(200, {"repositories": [{"full_name": "o/only"}]}),
    ]

    with mock.patch.object(github_app.requests, "request", side_effect=responses) as request:
        repositories = github_app.list_installation_repositories(1)

    assert len(repositories) == 1
    # Token mint + one page; no speculative second page.
    assert request.call_count == 2


def test_app_metadata_uses_the_app_jwt_not_an_installation_token(app_settings):
    with mock.patch.object(
        github_app.requests, "request", return_value=api_response(200, {"slug": "codesage-nr"})
    ) as request:
        assert github_app.get_app_metadata()["slug"] == "codesage-nr"

    # /app only accepts the App JWT, so no token exchange should have happened.
    assert request.call_count == 1
    assert request.call_args.args[1] == "https://api.github.com/app"


def test_list_installations_uses_the_app_jwt(app_settings):
    payload = [{"id": 172631969, "account": {"login": "NivedhReddy2048"}}]

    with mock.patch.object(
        github_app.requests, "request", return_value=api_response(200, payload)
    ) as request:
        assert github_app.list_installations()[0]["id"] == 172631969

    assert request.call_args.args[1].endswith("/app/installations")


def test_get_installation_fetches_a_single_installation(app_settings):
    with mock.patch.object(
        github_app.requests,
        "request",
        return_value=api_response(200, {"id": 42, "repository_selection": "selected"}),
    ) as request:
        assert github_app.get_installation(42)["repository_selection"] == "selected"

    assert request.call_args.args[1].endswith("/app/installations/42")


def test_the_authorization_header_is_a_bearer_token(app_settings):
    with mock.patch.object(
        github_app.requests, "request", return_value=api_response(200, {})
    ) as request:
        github_app.get_app_metadata()

    headers = request.call_args.kwargs["headers"]
    assert headers["Authorization"].startswith("Bearer ")
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"
