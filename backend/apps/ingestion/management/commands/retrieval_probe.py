"""Compare vector-only and hybrid retrieval for one query, side by side.

    python manage.py retrieval_probe "function that looks up a user by id"

The measurement behind the Phase 5 retrieval numbers, kept runnable so they can be
re-checked after any change to chunking, indexing or fusion. Spends one Gemini
embedding call per run.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.models import CodeChunk
from apps.ingestion.retrieval import (
    CANDIDATE_DEPTH,
    embed_query,
    hybrid_search,
    text_search,
    vector_search,
)
from apps.repos.models import Repository


class Command(BaseCommand):
    help = "Show vector-only vs hybrid (vector + full-text, RRF) retrieval for a query."

    def add_arguments(self, parser):
        parser.add_argument("query")
        parser.add_argument(
            "--repo", help="Repository full name. Optional when only one repository is indexed."
        )
        parser.add_argument("--limit", type=int, default=5)

    def handle(self, *args, query, repo, limit, **options):
        repository = self._repository(repo)
        embedding = embed_query(query)
        if embedding is None:
            self.stdout.write("Query embedding unavailable: vector results will be empty.")

        dense = vector_search(repository, embedding, limit=CANDIDATE_DEPTH)
        lexical = text_search(repository, query, limit=CANDIDATE_DEPTH)
        fused = hybrid_search(repository, query, embedding, limit=limit)
        vector_rank = {chunk.pk: rank for rank, chunk in enumerate(dense, start=1)}
        text_rank = {chunk.pk: rank for rank, chunk in enumerate(lexical, start=1)}

        self.stdout.write(f'{repository.full_name} - "{query}"\n')
        self.stdout.write("Vector only (cosine):")
        for rank, chunk in enumerate(dense[:limit], start=1):
            self.stdout.write(f"  {rank}. {_label(chunk)}  distance={chunk.distance:.4f}")

        self.stdout.write("\nHybrid (RRF over vector + full-text):")
        for rank, (chunk, score) in enumerate(fused, start=1):
            moved = vector_rank.get(chunk.pk, "-")
            self.stdout.write(
                f"  {rank}. {_label(chunk)}  rrf={score:.4f}  "
                f"(vector rank {moved}, text rank {text_rank.get(chunk.pk, '-')})"
            )

    def _repository(self, full_name):
        if full_name:
            repository = Repository.objects.filter(full_name__iexact=full_name).first()
            if repository is None:
                raise CommandError(f"No repository named {full_name}.")
            return repository

        indexed = Repository.objects.filter(
            pk__in=CodeChunk.objects.values("repository").distinct()
        )
        if indexed.count() != 1:
            names = ", ".join(r.full_name for r in indexed) or "none"
            raise CommandError(f"Pass --repo; indexed repositories: {names}.")
        return indexed.get()


def _label(chunk):
    return f"{chunk.file_path}:{chunk.line_start}-{chunk.line_end} {chunk.symbol or '(module)'}"
