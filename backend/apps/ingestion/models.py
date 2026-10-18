from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from pgvector.django import HnswIndex, VectorField

from apps.repos.models import Repository


class IngestionJob(models.Model):
    """One attempt at indexing a repository.

    Kept as a row rather than a log line because the frontend polls it for progress,
    and because a failed job's error needs somewhere to live that outlives the worker.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    repository = models.ForeignKey(
        Repository, on_delete=models.CASCADE, related_name="ingestion_jobs"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    commit_sha = models.CharField(max_length=64, blank=True)

    # Progress counters, updated as the job runs so the UI has something to show.
    files_discovered = models.IntegerField(default=0)
    files_indexed = models.IntegerField(default=0)
    files_skipped = models.IntegerField(default=0)
    chunks_created = models.IntegerField(default=0)
    # Chunks whose embedding was reused from an identical earlier chunk rather than
    # being paid for again. The gap between this and chunks_created is the saving.
    chunks_reused = models.IntegerField(default=0)
    embedding_api_calls = models.IntegerField(default=0)

    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.repository.full_name} ({self.status})"

    @property
    def duration_seconds(self):
        if not self.started_at or not self.finished_at:
            return None
        return (self.finished_at - self.started_at).total_seconds()


class CodeChunk(models.Model):
    """A coherent unit of source code with its embedding.

    One row per function, class, or fallback block. `line_start`/`line_end` exist so a
    finding can cite a real location (spec section 6's citation enforcement), and
    `content_hash` so re-indexing can reuse an embedding instead of buying it again.
    """

    class Kind(models.TextChoices):
        FUNCTION = "function", "Function"
        CLASS = "class", "Class"
        METHOD = "method", "Method"
        MODULE = "module", "Module-level code"
        BLOCK = "block", "Text block"

    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name="code_chunks")
    file_path = models.CharField(max_length=1024)
    symbol = models.CharField(max_length=512, blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.BLOCK)
    language = models.CharField(max_length=32, blank=True)

    line_start = models.IntegerField()
    line_end = models.IntegerField()
    content = models.TextField()

    # sha256 of the chunk text. The cache key that stops us re-embedding unchanged
    # code on every re-index.
    content_hash = models.CharField(max_length=64, db_index=True)

    # The lexical half of hybrid retrieval (spec section 6). `search_text` holds the
    # content plus identifiers split into words - findUserById becomes
    # "find user by id" - because a natural-language query cannot otherwise match an
    # opaque identifier token.
    search_text = models.TextField(blank=True, default="")

    # Maintained by a database trigger rather than in Python, so no code path can
    # insert a row with a stale or missing vector. Uses the `simple` config: `english`
    # stems identifier fragments into noise and drops short code words like "id" and
    # "by" as stopwords, which is most of the meaning in find_by_id.
    search_vector = SearchVectorField(null=True, editable=False)

    # Dimension is fixed at migration time, so it is read from settings rather than
    # hardcoded here - see EMBEDDING_DIMENSIONS and spec section 6 for why it is 1536
    # and not the model's 3072 default.
    embedding = VectorField(dimensions=settings.EMBEDDING_DIMENSIONS, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            # Cosine distance, matching how retrieval queries it. An index built for
            # a different operator class would simply not be used.
            HnswIndex(
                name="codechunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
            models.Index(fields=["repository", "file_path"]),
            GinIndex(fields=["search_vector"], name="codechunk_search_gin"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["repository", "file_path", "line_start", "line_end"],
                name="unique_chunk_span_per_file",
            )
        ]
        ordering = ["file_path", "line_start"]

    def __str__(self):
        label = self.symbol or self.kind
        return f"{self.file_path}:{self.line_start}-{self.line_end} ({label})"

    @property
    def citation(self):
        """The (file_path, line_range) tuple every grounded finding must carry."""
        return self.file_path, (self.line_start, self.line_end)
