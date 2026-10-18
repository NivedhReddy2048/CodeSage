"""Embedding client tests. Gemini is mocked throughout: no network, no quota."""

from unittest import mock

import pytest
import requests

from apps.ingestion.embeddings import EmbeddingClient, EmbeddingError


@pytest.fixture(autouse=True)
def fast_backoff(settings):
    """Keep retry tests instant without weakening what they assert."""
    settings.EMBEDDING_BACKOFF_SECONDS = 0.0
    settings.GEMINI_API_KEY = "test-key"
    settings.EMBEDDING_DIMENSIONS = 4
    settings.EMBEDDING_BATCH_SIZE = 2
    return settings


def ok(count, dims=4):
    response = mock.Mock()
    response.status_code = 200
    response.json.return_value = {"embeddings": [{"values": [0.1] * dims} for _ in range(count)]}
    return response


def err(status, text="boom"):
    response = mock.Mock()
    response.status_code = status
    response.text = text
    return response


def test_no_texts_means_no_api_call():
    client = EmbeddingClient()

    with mock.patch("apps.ingestion.embeddings.requests.post") as post:
        assert client.embed_texts([]) == []

    post.assert_not_called()


def test_missing_api_key_is_an_error(settings):
    settings.GEMINI_API_KEY = ""

    with pytest.raises(EmbeddingError, match="GEMINI_API_KEY"):
        EmbeddingClient().embed_texts(["x"])


def test_vectors_are_returned_in_order():
    client = EmbeddingClient()

    with mock.patch("apps.ingestion.embeddings.requests.post", return_value=ok(2)):
        vectors = client.embed_texts(["a", "b"])

    assert len(vectors) == 2
    assert all(len(v) == 4 for v in vectors)


def test_inputs_are_batched(settings):
    """One request per chunk would be thousands of round trips."""
    settings.EMBEDDING_BATCH_SIZE = 2
    client = EmbeddingClient()

    with mock.patch(
        "apps.ingestion.embeddings.requests.post", side_effect=[ok(2), ok(2), ok(1)]
    ) as post:
        vectors = client.embed_texts(["a", "b", "c", "d", "e"])

    assert len(vectors) == 5
    assert post.call_count == 3


def test_requested_dimensionality_is_sent(settings):
    """The whole point: 1536 stays indexable, the 3072 default does not."""
    settings.EMBEDDING_DIMENSIONS = 1536
    client = EmbeddingClient()

    with mock.patch(
        "apps.ingestion.embeddings.requests.post", return_value=ok(1, dims=1536)
    ) as post:
        client.embed_texts(["a"])

    sent = post.call_args.kwargs["json"]["requests"][0]
    assert sent["outputDimensionality"] == 1536


def test_wrong_dimension_response_is_rejected_loudly():
    """Silently storing the wrong width fails much later, at the database."""
    client = EmbeddingClient()

    with mock.patch("apps.ingestion.embeddings.requests.post", return_value=ok(1, dims=99)):
        with pytest.raises(EmbeddingError, match="Expected 4 dimensions"):
            client.embed_texts(["a"])


def test_count_mismatch_is_rejected():
    client = EmbeddingClient()

    with mock.patch("apps.ingestion.embeddings.requests.post", return_value=ok(1)):
        with pytest.raises(EmbeddingError, match="returned 1 embeddings for 2"):
            client.embed_texts(["a", "b"])


def test_rate_limit_is_retried_then_succeeds():
    """429 is the expected free-tier response, and waiting is the correct answer."""
    client = EmbeddingClient()

    with mock.patch(
        "apps.ingestion.embeddings.requests.post",
        side_effect=[err(429), err(429), ok(1)],
    ) as post:
        vectors = client.embed_texts(["a"])

    assert len(vectors) == 1
    assert post.call_count == 3


def test_backoff_grows_exponentially(settings):
    settings.EMBEDDING_BACKOFF_SECONDS = 1.0
    client = EmbeddingClient()

    with (
        mock.patch(
            "apps.ingestion.embeddings.requests.post",
            side_effect=[err(429), err(429), ok(1)],
        ),
        mock.patch("apps.ingestion.embeddings.time.sleep") as sleep,
    ):
        client.embed_texts(["a"])

    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 2.0]


def test_server_errors_are_retried():
    client = EmbeddingClient()

    with mock.patch(
        "apps.ingestion.embeddings.requests.post", side_effect=[err(503), ok(1)]
    ) as post:
        client.embed_texts(["a"])

    assert post.call_count == 2


def test_a_bad_request_is_not_retried():
    """Retrying a 400 cannot help; it just wastes the quota budget."""
    client = EmbeddingClient()

    with mock.patch(
        "apps.ingestion.embeddings.requests.post", side_effect=[err(400, "bad model")]
    ) as post:
        with pytest.raises(EmbeddingError, match="400"):
            client.embed_texts(["a"])

    assert post.call_count == 1


def test_retries_are_bounded(settings):
    settings.EMBEDDING_MAX_RETRIES = 3
    client = EmbeddingClient()

    with mock.patch("apps.ingestion.embeddings.requests.post", side_effect=[err(429)] * 3) as post:
        with pytest.raises(EmbeddingError, match="after 3 attempts"):
            client.embed_texts(["a"])

    assert post.call_count == 3


def test_network_errors_are_retried_then_wrapped(settings):
    settings.EMBEDDING_MAX_RETRIES = 2
    client = EmbeddingClient()

    with mock.patch(
        "apps.ingestion.embeddings.requests.post",
        side_effect=requests.ConnectionError("dns"),
    ):
        with pytest.raises(EmbeddingError, match="network error"):
            client.embed_texts(["a"])


def test_api_calls_are_counted_for_the_job_report():
    client = EmbeddingClient()

    with mock.patch(
        "apps.ingestion.embeddings.requests.post", side_effect=[err(429), ok(1), ok(1)]
    ):
        client.embed_texts(["a"])
        client.embed_texts(["b"])

    # Two successes plus one retried failure: the retry really did cost a call.
    assert client.api_calls == 3


def test_empty_values_in_a_response_are_rejected():
    response = mock.Mock()
    response.status_code = 200
    response.json.return_value = {"embeddings": [{"values": []}]}
    client = EmbeddingClient()

    with mock.patch("apps.ingestion.embeddings.requests.post", return_value=response):
        with pytest.raises(EmbeddingError, match="no values"):
            client.embed_texts(["a"])
