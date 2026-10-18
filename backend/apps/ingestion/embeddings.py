"""Gemini embedding client: batched, retried, and dimension-pinned.

Three things matter here, all of them about staying inside a free tier:

1. **Batching.** One request per chunk would be thousands of round trips for a
   modest repository. The batch endpoint takes many inputs at once.
2. **Backoff on 429.** The free tier rate-limits, and the correct response is to wait
   rather than to fail the job. Retries are exponential so a sustained limit does not
   turn into a tight loop.
3. **A pinned output dimension.** `gemini-embedding-001` returns 3072 dimensions by
   default, which pgvector cannot index (its hnsw/ivfflat ceiling is 2000). Requesting
   1536 is what keeps similarity search indexed instead of sequential - see spec
   section 6.
"""

import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
TIMEOUT = 120

# Transient: worth retrying. 429 is the rate limit; 5xx is Google having a moment.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class EmbeddingError(Exception):
    """Embeddings could not be produced."""


class EmbeddingClient:
    """Counts its own API calls, so an IngestionJob can report real usage."""

    def __init__(self, api_key=None, model=None, dimensions=None):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model = model or settings.EMBEDDING_MODEL
        self.dimensions = dimensions or settings.EMBEDDING_DIMENSIONS
        self.api_calls = 0

    def embed_texts(self, texts):
        """Embed a list of strings, returning one vector per input, in order."""
        if not texts:
            return []
        if not self.api_key:
            raise EmbeddingError("GEMINI_API_KEY is not set, so no embeddings can be produced.")

        vectors = []
        batch_size = settings.EMBEDDING_BATCH_SIZE
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            vectors.extend(self._embed_batch(batch))
        return vectors

    def _embed_batch(self, batch):
        payload = {
            "requests": [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": text}]},
                    "outputDimensionality": self.dimensions,
                }
                for text in batch
            ]
        }
        url = f"{API_ROOT}/models/{self.model}:batchEmbedContents"

        response = self._post_with_retries(url, payload)
        embeddings = response.get("embeddings") or []

        if len(embeddings) != len(batch):
            raise EmbeddingError(
                f"Gemini returned {len(embeddings)} embeddings for {len(batch)} inputs."
            )

        vectors = []
        for item in embeddings:
            values = item.get("values")
            if not values:
                raise EmbeddingError("Gemini returned an embedding with no values.")
            if len(values) != self.dimensions:
                # Loud rather than silent: a mismatch here would fail later at the
                # database with a far less obvious error.
                raise EmbeddingError(
                    f"Expected {self.dimensions} dimensions, got {len(values)}. "
                    "Check EMBEDDING_DIMENSIONS against the migration."
                )
            vectors.append(values)
        return vectors

    def _post_with_retries(self, url, payload):
        attempts = settings.EMBEDDING_MAX_RETRIES
        backoff = settings.EMBEDDING_BACKOFF_SECONDS
        last_error = None

        for attempt in range(1, attempts + 1):
            self.api_calls += 1
            try:
                response = requests.post(
                    url,
                    params={"key": self.api_key},
                    json=payload,
                    timeout=TIMEOUT,
                )
            except requests.RequestException as exc:
                last_error = f"network error: {exc}"
            else:
                if response.status_code == 200:
                    return response.json()

                last_error = f"HTTP {response.status_code}: {response.text[:200]}"

                if response.status_code not in RETRYABLE_STATUS:
                    # A 400 means the request itself is wrong; retrying cannot help.
                    raise EmbeddingError(last_error)

            if attempt < attempts:
                delay = backoff * (2 ** (attempt - 1))
                logger.warning(
                    "Embedding attempt %s/%s failed (%s); retrying in %.1fs",
                    attempt,
                    attempts,
                    last_error,
                    delay,
                )
                time.sleep(delay)

        raise EmbeddingError(f"Embedding failed after {attempts} attempts: {last_error}")
