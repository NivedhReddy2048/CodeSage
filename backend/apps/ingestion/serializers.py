from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.ingestion.models import IngestionJob


def ingestion_public_reason(error):
    """A short reason an indexing job failed, safe to show any member.

    The raw text can carry provider response bodies and quota details (embedding
    errors come straight from Gemini), so only owners and admins see it.
    """
    text = (error or "").lower()
    if not text:
        return ""
    if "gemini" in text or "embedding" in text or "quota" in text:
        return "The embedding provider was unavailable"
    if "installation" in text:
        return "The GitHub App is not installed for this repository"
    # Before the GitHub check: the size-limit message also mentions the archive.
    if "exceeds" in text and "limit" in text:
        return "The repository is larger than the indexing limit"
    if "github" in text or "archive" in text or "resolve" in text:
        return "Could not fetch the repository source from GitHub"
    return "Indexing hit an internal error"


class IngestionJobSerializer(serializers.ModelSerializer):
    duration_seconds = serializers.FloatField(read_only=True, allow_null=True)
    is_active = serializers.SerializerMethodField()

    class Meta:
        model = IngestionJob
        fields = [
            "id",
            "status",
            "is_active",
            "commit_sha",
            "files_discovered",
            "files_indexed",
            "files_skipped",
            "chunks_created",
            "chunks_reused",
            "embedding_api_calls",
            "error",
            "started_at",
            "finished_at",
            "created_at",
            "duration_seconds",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.BooleanField())
    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["error_summary"] = ingestion_public_reason(data["error"])
        if not self.context.get("show_error_details"):
            data["error"] = ""
        return data

    def get_is_active(self, job):
        """Whether the frontend should keep polling."""
        return job.status in (IngestionJob.Status.PENDING, IngestionJob.Status.RUNNING)


class IngestionStatusSerializer(serializers.Serializer):
    """Latest job for a repository, plus how many chunks are currently stored."""

    job = IngestionJobSerializer(read_only=True, allow_null=True)
    chunk_count = serializers.IntegerField(read_only=True)
    indexed_files = serializers.IntegerField(read_only=True)
    can_manage = serializers.BooleanField(read_only=True)
    # What the index holds now: the last job that finished, even while another runs.
    last_indexed_commit = serializers.CharField(read_only=True)
    last_indexed_at = serializers.DateTimeField(read_only=True, allow_null=True)
