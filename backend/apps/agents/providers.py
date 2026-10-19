"""LLM providers behind one interface, with timeouts, retries and backoff.

Groq is OpenAI-compatible; Gemini is not, so each gets a thin adapter and the router
above them never needs to know which is which.
"""

import logging
import time
from dataclasses import dataclass

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


@dataclass
class ProviderResponse:
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    # The model that served this response, as named by the provider that served it.
    # Callers record this rather than the model they asked for, which after a
    # failover is a different provider's model entirely.
    model: str = ""


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

            if attempt < self.max_retries:
                delay = self.backoff * (2 ** (attempt - 1))
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
