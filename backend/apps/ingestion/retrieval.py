"""Hybrid retrieval: pgvector cosine + Postgres full-text, fused with RRF.

Spec section 6 asks for dense and sparse retrieval combined. Phase 3 shipped the dense
half and measured its weakness: for "function that looks up a user by id", vector
search returned `app/users.py`'s module docstring above `UserRepository.find_by_id`,
because the docstring restates the query in prose while the code does not.

Lexical search has the opposite failure - it cannot match a paraphrase - so the two
are complements rather than alternatives.

**Why Reciprocal Rank Fusion and not a weighted score blend.** Cosine similarity and
`ts_rank` are not on the same scale and are not even comparable between queries:
cosine clusters tightly around 0.6-0.8 for code, while ts_rank depends on document
length and term frequency and can be orders of magnitude apart. Normalising them
would need per-query calibration. RRF ignores the scores entirely and fuses on
*rank*, which sidesteps the whole problem:

    score(d) = sum over retrievers of 1 / (k + rank(d))

`k` damps the influence of the top positions so one retriever cannot dominate; 60 is
the value from the original Cormack et al. paper and is the usual default.
"""

import logging

from django.conf import settings
from django.db import connection
from pgvector.django import CosineDistance

from apps.ingestion.identifiers import split_identifier
from apps.ingestion.models import CodeChunk

logger = logging.getLogger(__name__)

RRF_K = 60
DEFAULT_LIMIT = 8
# Each retriever returns more than the final cut so fusion has something to work
# with; a document ranked 15th by one retriever and 2nd by the other should still
# surface.
CANDIDATE_DEPTH = 30


def vector_search(repository, query_embedding, limit=CANDIDATE_DEPTH):
    """Dense retrieval: nearest chunks by cosine distance."""
    if query_embedding is None:
        return []

    return list(
        CodeChunk.objects.filter(repository=repository, embedding__isnull=False)
        .annotate(distance=CosineDistance("embedding", query_embedding))
        .order_by("distance")[:limit]
    )


def text_search(repository, query, limit=CANDIDATE_DEPTH):
    """Lexical retrieval over the `simple`-config tsvector.

    Raw SQL rather than Django's SearchQuery because the query string is built from
    identifier-split words joined with OR, and websearch/plainto helpers would
    re-tokenise them under their own rules. The query is still parameterised - the
    terms never reach SQL as text.
    """
    terms = _query_terms(query)
    if not terms:
        return []

    tsquery = " | ".join(terms)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, ts_rank(search_vector, to_tsquery('simple', %s)) AS rank
            FROM ingestion_codechunk
            WHERE repository_id = %s
              AND search_vector @@ to_tsquery('simple', %s)
            ORDER BY rank DESC
            LIMIT %s
            """,
            [tsquery, repository.pk, tsquery, limit],
        )
        rows = cursor.fetchall()

    if not rows:
        return []

    # One query for the objects, then restore the rank order Postgres gave us.
    ids = [row[0] for row in rows]
    by_id = {chunk.pk: chunk for chunk in CodeChunk.objects.filter(pk__in=ids)}
    ordered = []
    for chunk_id, rank in rows:
        chunk = by_id.get(chunk_id)
        if chunk is not None:
            chunk.text_rank = rank
            ordered.append(chunk)
    return ordered


def _query_terms(query):
    """Turn a natural-language query into `simple`-config tsquery terms.

    The query is split the same way identifiers are at index time, so "find_by_id"
    typed in a question matches a chunk indexed as "find by id".
    """
    words = []
    seen = set()
    for raw in (query or "").replace("_", " ").split():
        for word in split_identifier(raw) or [raw.lower()]:
            cleaned = "".join(ch for ch in word if ch.isalnum())
            if len(cleaned) > 1 and cleaned not in seen:
                seen.add(cleaned)
                words.append(cleaned)
    return words


def reciprocal_rank_fusion(ranked_lists, k=RRF_K, limit=DEFAULT_LIMIT):
    """Fuse ranked lists of chunks by reciprocal rank.

    Takes lists already in rank order. Returns `(chunk, score)` pairs, best first.
    """
    scores = {}
    chunks = {}

    for ranked in ranked_lists:
        for position, chunk in enumerate(ranked, start=1):
            scores[chunk.pk] = scores.get(chunk.pk, 0.0) + 1.0 / (k + position)
            chunks.setdefault(chunk.pk, chunk)

    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [(chunks[chunk_id], score) for chunk_id, score in ordered[:limit]]


def hybrid_search(repository, query, query_embedding=None, limit=DEFAULT_LIMIT):
    """Dense + lexical, fused. The retrieval entry point for the grounding agent."""
    dense = vector_search(repository, query_embedding)
    lexical = text_search(repository, query)

    if not dense and not lexical:
        return []

    return reciprocal_rank_fusion([dense, lexical], limit=limit)


def embed_query(query):
    """Embed a query with the same model and dimension as the index.

    Isolated here so a failure degrades to lexical-only rather than taking the whole
    retrieval down: an embedding outage should cost relevance, not availability.
    """
    from apps.ingestion.embeddings import EmbeddingClient, EmbeddingError

    if not settings.GEMINI_API_KEY:
        return None
    try:
        return EmbeddingClient().embed_texts([query])[0]
    except EmbeddingError as exc:
        logger.warning("Query embedding failed, falling back to lexical only: %s", exc)
        return None


def search(repository, query, limit=DEFAULT_LIMIT):
    """Convenience wrapper: embed the query, then fuse."""
    return hybrid_search(repository, query, embed_query(query), limit=limit)
