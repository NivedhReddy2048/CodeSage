from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.ingestion.models import IngestionJob


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
    def get_is_active(self, job):
        """Whether the frontend should keep polling."""
        return job.status in (IngestionJob.Status.PENDING, IngestionJob.Status.RUNNING)


class IngestionStatusSerializer(serializers.Serializer):
    """Latest job for a repository, plus how many chunks are currently stored."""

    job = IngestionJobSerializer(read_only=True, allow_null=True)
    chunk_count = serializers.IntegerField(read_only=True)
    indexed_files = serializers.IntegerField(read_only=True)
