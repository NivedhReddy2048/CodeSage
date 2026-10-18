"""Index a repository: fetch, select, chunk, embed, store.

Orchestration only. Each step lives in its own module so it can be tested without a
network, a database, or the others.
"""

import logging
from collections import Counter

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.ingestion import selection, source
from apps.ingestion.chunking import chunk_file
from apps.ingestion.embeddings import EmbeddingClient, EmbeddingError
from apps.ingestion.models import CodeChunk, IngestionJob
from apps.ingestion.source import SourceFetchError

logger = logging.getLogger(__name__)


class IndexResult:
    """What a run did, for the job row and for reporting."""

    def __init__(self):
        self.files_discovered = 0
        self.files_indexed = 0
        self.files_skipped = 0
        self.chunks_created = 0
        self.chunks_reused = 0
        self.embedding_api_calls = 0
        self.skip_reasons = Counter()
        self.commit_sha = ""


def index_repository(job, embedding_client=None):
    """Run one indexing job to completion, updating it as it goes."""
    repository = job.repository
    installation = repository.installation

    job.status = IngestionJob.Status.RUNNING
    job.started_at = timezone.now()
    job.error = ""
    job.save(update_fields=["status", "started_at", "error"])

    client = embedding_client or EmbeddingClient()
    result = IndexResult()

    try:
        if installation is None:
            raise SourceFetchError(
                "This repository has no GitHub App installation, so its source cannot be fetched."
            )

        _run(job, repository, installation.installation_id, client, result)

    except (SourceFetchError, EmbeddingError) as exc:
        # Expected failure modes: report them on the job rather than as a traceback.
        job.status = IngestionJob.Status.FAILED
        job.error = str(exc)[:2000]
        logger.warning("Ingestion failed for %s: %s", repository.full_name, exc)
    except Exception as exc:  # noqa: BLE001 - the job row is the only error channel
        job.status = IngestionJob.Status.FAILED
        job.error = f"{type(exc).__name__}: {exc}"[:2000]
        logger.exception("Unexpected ingestion failure for %s", repository.full_name)
    else:
        job.status = IngestionJob.Status.DONE

    job.finished_at = timezone.now()
    job.commit_sha = result.commit_sha or job.commit_sha
    job.files_discovered = result.files_discovered
    job.files_indexed = result.files_indexed
    job.files_skipped = result.files_skipped
    job.chunks_created = result.chunks_created
    job.chunks_reused = result.chunks_reused
    job.embedding_api_calls = client.api_calls
    job.save()

    if result.skip_reasons:
        logger.info(
            "Skipped files for %s: %s",
            repository.full_name,
            dict(result.skip_reasons),
        )
    return result


def _run(job, repository, installation_id, client, result):
    full_name = repository.full_name
    ref = repository.default_branch or "HEAD"

    result.commit_sha = source.resolve_head_sha(installation_id, full_name, ref)
    gitignore_spec = selection.build_gitignore_spec(
        source.read_gitignore(installation_id, full_name, ref)
    )

    chunks = _collect_chunks(installation_id, full_name, ref, gitignore_spec, result)

    # Reuse first, then pay only for what is genuinely new.
    cached = _load_cached_vectors(repository, {c.content_hash for c in chunks})
    to_embed = [c for c in chunks if c.content_hash not in cached]
    result.chunks_reused = len(chunks) - len(to_embed)

    _persist_progress(job, result)

    if to_embed:
        vectors = client.embed_texts([_embedding_text(c) for c in to_embed])
        for chunk, vector in zip(to_embed, vectors, strict=True):
            cached[chunk.content_hash] = vector

    _store(repository, chunks, cached, result)


def _collect_chunks(installation_id, full_name, ref, gitignore_spec, result):
    """Walk the archive and chunk everything that survives selection."""
    chunks = []
    cap = settings.INGESTION_MAX_CHUNKS_PER_REPO

    for path, size, handle in source.iter_repository_files(installation_id, full_name, ref):
        result.files_discovered += 1

        reason = selection.should_skip(path, size, gitignore_spec)
        if reason:
            result.files_skipped += 1
            result.skip_reasons[reason] += 1
            continue

        try:
            data = handle.read()
        except Exception:  # noqa: BLE001 - a corrupt member must not fail the run
            result.files_skipped += 1
            result.skip_reasons["unreadable"] += 1
            continue

        text = selection.decode(data)
        if text is None:
            result.files_skipped += 1
            result.skip_reasons[selection.SkipReason.BINARY_CONTENT] += 1
            continue

        file_chunks = chunk_file(path, text)
        if not file_chunks:
            result.files_skipped += 1
            result.skip_reasons[selection.SkipReason.EMPTY] += 1
            continue

        remaining = cap - len(chunks)
        if remaining <= 0:
            # Stop collecting, but keep counting so the job reports honestly that
            # the repository was larger than the cap.
            result.files_skipped += 1
            result.skip_reasons["chunk-cap-reached"] += 1
            continue

        chunks.extend(file_chunks[:remaining])
        result.files_indexed += 1

    result.chunks_created = len(chunks)
    return chunks


def _embedding_text(chunk):
    """What actually gets embedded.

    The path and symbol are prepended so a query like "function that looks up a user
    by id" can match on naming and location, not only on the body. Without this, two
    structurally similar functions in unrelated files are nearly indistinguishable.
    """
    header = f"{chunk.file_path}"
    if chunk.symbol:
        header += f" :: {chunk.symbol}"
    return f"{header}\n\n{chunk.content}"


def _load_cached_vectors(repository, hashes):
    """Reuse embeddings for chunks whose content hash we already have.

    This is what makes re-indexing cheap: an unchanged file costs nothing, so a
    repository can be re-indexed after every push without burning the free tier.
    """
    if not hashes:
        return {}

    existing = CodeChunk.objects.filter(
        repository=repository, content_hash__in=hashes, embedding__isnull=False
    ).values_list("content_hash", "embedding")
    return {content_hash: list(vector) for content_hash, vector in existing}


def _persist_progress(job, result):
    job.files_discovered = result.files_discovered
    job.files_indexed = result.files_indexed
    job.files_skipped = result.files_skipped
    job.chunks_created = result.chunks_created
    job.chunks_reused = result.chunks_reused
    job.save(
        update_fields=[
            "files_discovered",
            "files_indexed",
            "files_skipped",
            "chunks_created",
            "chunks_reused",
        ]
    )


@transaction.atomic
def _store(repository, chunks, vectors_by_hash, result):
    """Replace the repository's chunks in one transaction.

    Delete-then-insert rather than a diff: it is simpler, and the embeddings that
    matter were already reused via the content-hash cache, so the expensive part is
    unaffected. Atomic so a failure never leaves a repository half-indexed.
    """
    CodeChunk.objects.filter(repository=repository).delete()

    rows = []
    seen_spans = set()
    for chunk in chunks:
        # The unique constraint is on (repo, path, start, end); a pathological file
        # could yield a duplicate span, and one bad file should not abort the insert.
        span = (chunk.file_path, chunk.line_start, chunk.line_end)
        if span in seen_spans:
            continue
        seen_spans.add(span)

        rows.append(
            CodeChunk(
                repository=repository,
                file_path=chunk.file_path,
                symbol=chunk.symbol,
                kind=chunk.kind,
                language=chunk.language,
                line_start=chunk.line_start,
                line_end=chunk.line_end,
                content=chunk.content,
                content_hash=chunk.content_hash,
                embedding=vectors_by_hash.get(chunk.content_hash),
            )
        )

    CodeChunk.objects.bulk_create(rows, batch_size=500)
    result.chunks_created = len(rows)
