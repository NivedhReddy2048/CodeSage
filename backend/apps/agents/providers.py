"""LLM providers behind one interface, with timeouts, retries and backoff.

Groq is OpenAI-compatible; Gemini is not, so each gets a thin adapter and the router
above them never needs to know which is which.
"""

import logging
import random
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field

import requests

from apps.agents.schema import RESPONSE_SCHEMA, to_gemini_schema

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

# 429 is the free tier doing its job; 5xx is the provider having a moment. Both are
# worth waiting out. Anything else is our fault and retrying only burns quota.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class ProviderError(Exception):
    """A provider could not produce a response."""


class DailyLimitReached(ProviderError):
    """The provider's per-day token or request quota is spent: waiting cannot help.

    Live, the caller fails over at once. The evaluation harness stops for the day
    instead, because its runs must not be served by the fallback.
    """


# Groq names the exhausted limit in the 429 body: "... on tokens per day (TPD):
# Limit 200000, Used ..." or "requests per day (RPD)".
DAILY_LIMIT = re.compile(r"\b(?:tokens|requests) per day\b|\((?:TPD|RPD)\)", re.IGNORECASE)
DAILY_LIMIT_MESSAGE = "daily limit reached"


# Groq's free tier: 8,000 tokens per minute per model, and one review's three parallel
# 20b agents spend about 4.4k. A 429 is usually that bucket, which refills within a
# minute - so it is waited out rather than failed over. A wait longer than this means a
# daily limit, where failing over at once is the right call.
MAX_RATE_LIMIT_WAIT = 30.0
# Added to each wait so agents that were rejected together do not retry together.
RATE_LIMIT_JITTER = 1.5

RATE_LIMIT_HEADERS = (
    "x-ratelimit-limit-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-requests",
    "x-ratelimit-reset-tokens",
)

_DURATION = re.compile(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?$")


def parse_duration(value):
    """Seconds from Groq's "7.66s", "2m59.56s", "1h2m3s", or a bare number; None."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    if text.endswith("ms"):
        try:
            return float(text[:-2]) / 1000
        except ValueError:
            return None
    match = _DURATION.match(text)
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds = (float(part) if part else 0.0 for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _headers(response):
    headers = getattr(response, "headers", None)
    return headers if isinstance(headers, Mapping) else {}


def retry_after(response):
    """How long the provider asked us to wait, in seconds, or None if it did not say."""
    headers = _headers(response)
    for name in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        seconds = parse_duration(headers.get(name))
        if seconds is not None:
            return seconds
    return None


def rate_limit_snapshot(response):
    """The x-ratelimit-* headers of a response, for the record."""
    headers = _headers(response)
    return {name: str(headers[name]) for name in RATE_LIMIT_HEADERS if name in headers}


@dataclass
class ProviderResponse:
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    # The model that served this response, as named by the provider that served it.
    # Callers record this rather than the model they asked for, which after a
    # failover is a different provider's model entirely.
    model: str = ""
    # What the provider itself reported: its model field and version fingerprint (Groq's
    # `system_fingerprint`), and its rate-limit headers. Telemetry, never used for
    # pricing or routing.
    provider_model: str = ""
    system_fingerprint: str = ""
    rate_limits: dict = field(default_factory=dict)


class Provider:
    name = "provider"

    def __init__(self, api_key, model, timeout=90, max_retries=3, backoff=2.0):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff

    @property
    def configured(self):
        return bool(self.api_key)

    def complete(self, system_prompt, messages, schema=None):
        """Return a ProviderResponse. `schema` is the JSON Schema the reply must match."""
        raise NotImplementedError

    def _post_with_retries(self, url, **kwargs):
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            asked = None
            try:
                response = requests.post(url, timeout=self.timeout, **kwargs)
            except requests.Timeout:
                last_error = f"timed out after {self.timeout}s"
            except requests.RequestException as exc:
                last_error = f"network error: {exc}"
            else:
                if response.status_code == 200:
                    return response
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                if response.status_code not in RETRYABLE_STATUS:
                    raise ProviderError(f"{self.name}: {last_error}")
                if response.status_code == 429:
                    if DAILY_LIMIT.search(response.text or ""):
                        raise DailyLimitReached(
                            f"{self.name}: {DAILY_LIMIT_MESSAGE} ({last_error})"
                        )
                    asked = retry_after(response)
                    if asked is not None and asked > MAX_RATE_LIMIT_WAIT:
                        # A daily limit, not the per-minute bucket: nothing to wait for.
                        raise ProviderError(
                            f"{self.name}: rate limited for {asked:.0f}s ({last_error})"
                        )

            if attempt < self.max_retries:
                delay = self.backoff * (2 ** (attempt - 1))
                if asked is not None:
                    # Wait as long as the provider asked, not a fixed guess that is
                    # usually too short for a per-minute window.
                    delay = max(delay, asked) + random.uniform(0, RATE_LIMIT_JITTER)
                logger.warning(
                    "%s attempt %s/%s failed (%s); retrying in %.1fs",
                    self.name,
                    attempt,
                    self.max_retries,
                    last_error,
                    delay,
                )
                time.sleep(delay)

        raise ProviderError(f"{self.name}: failed after {self.max_retries} attempts ({last_error})")


class GroqProvider(Provider):
    name = "groq"

    def complete(self, system_prompt, messages, schema=None):
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "temperature": 0,
            "max_tokens": 4096,
            # Verified against the live API: the production gpt-oss models honour
            # this and return parseable JSON, where the preview qwen model did not
            # without it.
            "response_format": {"type": "json_object"},
        }

        response = self._post_with_retries(
            GROQ_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        data = response.json()

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"{self.name}: unexpected response shape") from exc

        usage = data.get("usage") or {}
        return ProviderResponse(
            content=content,
            input_tokens=usage.get("prompt_tokens") or 0,
            output_tokens=usage.get("completion_tokens") or 0,
            model=self.model,
            provider_model=str(data.get("model") or ""),
            system_fingerprint=str(data.get("system_fingerprint") or ""),
            rate_limits=rate_limit_snapshot(response),
        )


class GeminiProvider(Provider):
    name = "gemini"

    def complete(self, system_prompt, messages, schema=None):
        # Gemini has no system role; it takes a separate systemInstruction, which
        # preserves the same separation between rules and untrusted content.
        contents = [
            {"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
            for m in messages
        ]
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 4096,
                # Native structured output: the response is constrained to this
                # schema rather than asked nicely to follow it. The schema must be
                # the calling agent's own - forcing the findings shape on the
                # intent classifier or the grounding agent produced valid JSON
                # that answered the wrong question.
                "responseMimeType": "application/json",
                "responseSchema": to_gemini_schema(schema or RESPONSE_SCHEMA),
            },
        }

        response = self._post_with_retries(
            f"{GEMINI_ROOT}/{self.model}:generateContent",
            params={"key": self.api_key},
            json=payload,
        )
        data = response.json()

        try:
            parts = data["candidates"][0]["content"]["parts"]
            content = "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"{self.name}: unexpected response shape") from exc

        usage = data.get("usageMetadata") or {}
        return ProviderResponse(
            content=content,
            input_tokens=usage.get("promptTokenCount") or 0,
            output_tokens=usage.get("candidatesTokenCount") or 0,
            model=self.model,
        )
