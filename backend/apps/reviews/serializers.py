from rest_framework import serializers

from apps.reviews.comment import public_reason
from apps.reviews.models import AgentRunRecord, LLMCall, Review, ReviewFinding


class ErrorDetailMixin:
    """Raw errors only for owners and admins; everyone gets a short reason.

    Provider errors carry HTTP bodies, quota figures and organisation ids. A member
    sees `error_summary` ("AI providers unavailable"); `error` is blanked unless the
    view put `show_error_details=True` in the context, which it does only for the
    owner/admin roles. Nested serializers share the root context, so one flag covers
    the review, its calls and its agent runs.
    """

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if "error" in data:
            data["error_summary"] = public_reason(data["error"]) if data["error"] else ""
            if not self.context.get("show_error_details"):
                data["error"] = ""
        return data


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
            "placement",
            "message",
            "citation",
            "dismissed",
        ]
        read_only_fields = fields


class LLMCallSerializer(ErrorDetailMixin, serializers.ModelSerializer):
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


class AgentRunSerializer(ErrorDetailMixin, serializers.ModelSerializer):
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


class ReviewSerializer(ErrorDetailMixin, serializers.ModelSerializer):
    findings = ReviewFindingSerializer(many=True, read_only=True)
    calls = LLMCallSerializer(many=True, read_only=True)
    agent_runs = AgentRunSerializer(many=True, read_only=True)
    repository = serializers.CharField(source="pull_request.repository.full_name", read_only=True)
    repository_id = serializers.IntegerField(source="pull_request.repository_id", read_only=True)
    pr_number = serializers.IntegerField(source="pull_request.number", read_only=True)
    pr_title = serializers.CharField(source="pull_request.title", read_only=True)
    stalled = serializers.BooleanField(read_only=True)
    pr_url = serializers.SerializerMethodField()
    can_manage = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = [
            "id",
            "repository",
            "repository_id",
            "pr_number",
            "pr_title",
            "pr_url",
            "can_manage",
            "status",
            "stalled",
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
            "progress",
            "created_at",
            "started_at",
            "finished_at",
            "findings",
            "calls",
            "agent_runs",
        ]
        read_only_fields = fields

    def get_pr_url(self, review) -> str:
        pull_request = review.pull_request
        return f"https://github.com/{pull_request.repository.full_name}/pull/{pull_request.number}"

    def get_can_manage(self, review) -> bool:
        """Whether the caller may re-run it. Also what unlocks raw error details."""
        return bool(self.context.get("show_error_details"))


class ReviewListSerializer(serializers.ModelSerializer):
    """One row of the reviews list, with counts annotated by the view."""

    repository = serializers.CharField(source="pull_request.repository.full_name", read_only=True)
    repository_id = serializers.IntegerField(source="pull_request.repository_id", read_only=True)
    pr_number = serializers.IntegerField(source="pull_request.number", read_only=True)
    pr_title = serializers.CharField(source="pull_request.title", read_only=True)
    stalled = serializers.BooleanField(read_only=True)
    finding_count = serializers.IntegerField(read_only=True)
    blocking_count = serializers.IntegerField(read_only=True)
    nit_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Review
        fields = [
            "id",
            "repository",
            "repository_id",
            "pr_number",
            "pr_title",
            "status",
            "stalled",
            "degraded",
            "used_fallback",
            "head_sha",
            "model_used",
            "duration_ms",
            "estimated_cost_inr",
            "finding_count",
            "blocking_count",
            "nit_count",
            "created_at",
        ]
        read_only_fields = fields


class ReviewSummarySerializer(serializers.ModelSerializer):
    """List view: no findings or calls, so a long list stays cheap."""

    pr_number = serializers.IntegerField(source="pull_request.number", read_only=True)
    pr_title = serializers.CharField(source="pull_request.title", read_only=True)
    stalled = serializers.BooleanField(read_only=True)
    finding_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Review
        fields = [
            "id",
            "pr_number",
            "pr_title",
            "status",
            "stalled",
            "head_sha",
            "model_used",
            "used_fallback",
            "duration_ms",
            "estimated_cost_inr",
            "finding_count",
            "created_at",
        ]
        read_only_fields = fields
