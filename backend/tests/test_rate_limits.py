"""Groq 429s are waited out, not failed over.

Groq's free tier gives each model 8,000 tokens per minute; one review's three
parallel gpt-oss-20b agents spend about 4.4k. On a 429 the provider retried after
2 s and 4 s - far shorter than the minute the bucket takes to refill - then failed
over to Gemini, and three such failures opened the breaker for five minutes. The
Groq dashboard shows those 429s on Oct 19 and Oct 22.
"""

from unittest import mock

import pytest

from apps.agents import breaker as breaker_module
from apps.agents.graph import Runtime
from apps.agents.providers import GroqProvider, ProviderError, parse_duration, retry_after
from apps.agents.types import ReviewConfig


@pytest.fixture(autouse=True)
def clean_breakers():
    breaker_module.reset_all()
    yield
    breaker_module.reset_all()


def groq_ok(content='{"findings": []}', headers=None, fingerprint="fp_abc123"):
    response = mock.Mock(status_code=200, headers=headers or {})
    response.json.return_value = {
        "model": "openai/gpt-oss-20b",
        "system_fingerprint": fingerprint,
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 900, "completion_tokens": 300},
    }
    return response


def limited(headers):
    return mock.Mock(status_code=429, headers=headers, text="Rate limit reached ... TPM")


def gemini_ok():
    response = mock.Mock(status_code=200, headers={})
    response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '{"findings": []}'}]}}],
        "usageMetadata": {"promptTokenCount": 400, "candidatesTokenCount": 40},
    }
    return response


def runtime():
    return Runtime(
        ReviewConfig(groq_api_key="g", gemini_api_key="m", max_retries=3, backoff_seconds=2.0)
    )


def call(responses):
    with (
        mock.patch("apps.agents.providers.requests.post", side_effect=responses) as post,
        mock.patch("apps.agents.providers.time.sleep") as sleep,
    ):
        result = runtime().complete("openai/gpt-oss-20b", "system", "user")
    return result, post, sleep


# ----------------------------------------------------------------- the fix


def test_a_per_minute_429_is_waited_out_and_never_fails_over():
    """A fake clock: Groq keeps refusing until its bucket refills 7 s from now.

    The old 2 s + 4 s backoff gave up at 6 s and failed over to Gemini.
    """
    clock = {"now": 0.0}
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        if "groq" in url and clock["now"] < 7:
            return limited({"retry-after": f"{7 - clock['now']:.2f}"})
        return groq_ok() if "groq" in url else gemini_ok()

    def sleep(seconds):
        clock["now"] += seconds

    with (
        mock.patch("apps.agents.providers.requests.post", side_effect=post),
        mock.patch("apps.agents.providers.time.sleep", side_effect=sleep),
    ):
        _, provider, used_fallback = runtime().complete("openai/gpt-oss-20b", "system", "user")

    assert (provider, used_fallback) == ("groq", False)
    assert len(calls) == 2
    assert 7 <= clock["now"] <= 7 + 1.5  # what Groq asked, plus jitter


def test_groqs_token_reset_header_is_used_when_there_is_no_retry_after():
    _, _, sleep = call([limited({"x-ratelimit-reset-tokens": "12.5s"}), groq_ok()])

    assert 12.5 <= sleep.call_args.args[0] <= 14.0


def test_a_daily_limit_fails_over_at_once_instead_of_waiting():
    (_, provider, used_fallback), post, sleep = call(
        [limited({"retry-after": "3600"}), gemini_ok()]
    )

    assert (provider, used_fallback) == ("gemini", True)
    sleep.assert_not_called()
    assert post.call_count == 2  # one refused Groq call, then Gemini


def test_a_429_without_headers_keeps_the_exponential_backoff():
    _, _, sleep = call([limited({}), groq_ok()])

    assert sleep.call_args.args[0] == 2.0


def test_three_agents_waiting_out_one_429_each_leave_the_breaker_closed():
    """One review's three parallel 20b agents, all rejected by the same minute."""
    for _ in range(3):
        (_, provider, _), _, _ = call([limited({"retry-after": "4"}), groq_ok()])
        assert provider == "groq"

    assert breaker_module.get_breaker("groq").allows()


def test_a_daily_limit_on_the_provider_is_a_provider_error():
    provider = GroqProvider(api_key="g", model="m", max_retries=3)
    with (
        mock.patch(
            "apps.agents.providers.requests.post",
            return_value=limited({"retry-after": "86400"}),
        ),
        mock.patch("apps.agents.providers.time.sleep") as sleep,
        pytest.raises(ProviderError, match="rate limited for 86400s"),
    ):
        provider.complete("s", [{"role": "user", "content": "u"}])
    sleep.assert_not_called()


# -------------------------------------------------------------- the record


def test_the_providers_model_fingerprint_and_limits_reach_the_agent_run():
    from apps.agents.nodes import _call_model

    headers = {
        "x-ratelimit-limit-tokens": "8000",
        "x-ratelimit-remaining-tokens": "6512",
        "x-ratelimit-reset-tokens": "11.16s",
        "x-ratelimit-limit-requests": "1000",
        "x-ratelimit-remaining-requests": "996",
        "content-type": "application/json",
    }
    rt = runtime()
    with mock.patch("apps.agents.providers.requests.post", return_value=groq_ok(headers=headers)):
        _, run = _call_model(rt, "security", "openai/gpt-oss-120b", "s", "u", 100)

    assert run.provider_model == "openai/gpt-oss-20b"
    assert run.system_fingerprint == "fp_abc123"
    assert run.rate_limits == {k: v for k, v in headers.items() if k.startswith("x-ratelimit")}


@pytest.mark.parametrize(
    ("value", "seconds"),
    [
        ("7.66s", 7.66),
        ("2m59.56s", 179.56),
        ("1h2m3s", 3723.0),
        ("1m", 60.0),
        ("250ms", 0.25),
        ("12", 12.0),
        ("", None),
        ("soon", None),
    ],
)
def test_groq_durations_parse(value, seconds):
    assert parse_duration(value) == seconds


def test_a_mock_without_real_headers_means_no_retry_after():
    assert retry_after(mock.Mock()) is None
