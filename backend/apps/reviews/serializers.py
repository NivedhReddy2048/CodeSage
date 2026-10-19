from rest_framework import serializers

from apps.reviews.models import AgentRunRecord, LLMCall, Review, ReviewFinding


class ReviewFindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReviewFinding
        fields = [
            "id",
            "agent",
            "severity",
            "category",
            "file_path",
            "line",
            "message",
            "citation",
            "dismissed",
        ]
        read_only_fields = fields


class LLMCallSerializer(serializers.ModelSerializer):
    class Meta:
        model = LLMCall
        fields = [
            "id",
            "provider",
            "model",
            "input_tokens",
            "output_tokens",
            "latency_ms",
            "succeeded",
            "is_fallback",
            "error",
        ]
        read_only_fields = fields


class AgentRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentRunRecord
        fields = [
            "id",
            "name",
            "model",
            "requested_model",
            "provider",
            "input_tokens",
            "output_tokens",
            "latency_ms",
            "succeeded",
            "used_fallback",
            "findings_count",
            "skipped_reason",
            "error",
            "detail",
        ]
        read_only_fields = fields


class ReviewSerializer(serializers.ModelSerializer):
    findings = ReviewFindingSerializer(many=True, read_only=True)
    calls = LLMCallSerializer(many=True, read_only=True)
    agent_runs = AgentRunSerializer(many=True, read_only=True)
    repository = serializers.CharField(source="pull_request.repository.full_name", read_only=True)
    pr_number = serializers.IntegerField(source="pull_request.number", read_only=True)
    pr_title = serializers.CharField(source="pull_request.title", read_only=True)

    class Meta:
        model = Review
        fields = [
            "id",
            "repository",
            "pr_number",
            "pr_title",
            "status",
            "head_sha",
            "model_used",
            "used_fallback",
            "total_input_tokens",
            "total_output_tokens",
            "duration_ms",
            "estimated_cost_usd",
            "estimated_cost_inr",
            "degraded",
            "truncated",
            "skipped_files",
            "error",
            "created_at",
            "finished_at",
            "findings",
            "calls",
            "agent_runs",
        ]
        read_only_fields = fields


class ReviewSummarySerializer(serializers.ModelSerializer):
    """List view: no findings or calls, so a long list stays cheap."""

    pr_number = serializers.IntegerField(source="pull_request.number", read_only=True)
    pr_title = serializers.CharField(source="pull_request.title", read_only=True)
    finding_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Review
        fields = [
            "id",
            "pr_number",
            "pr_title",
            "status",
            "head_sha",
            "model_used",
            "used_fallback",
            "duration_ms",
            "estimated_cost_inr",
            "finding_count",
            "created_at",
        ]
        read_only_fields = fields
