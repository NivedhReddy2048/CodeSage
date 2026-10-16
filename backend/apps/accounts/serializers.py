from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.models import Membership, Organization, User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "github_id", "github_login", "email", "avatar_url"]
        read_only_fields = fields


class OrganizationSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ["id", "name", "slug", "is_personal", "role", "created_at"]
        read_only_fields = fields

    @extend_schema_field(serializers.ChoiceField(choices=Membership.Role.choices, allow_null=True))
    def get_role(self, organization):
        """The requesting user's role in this organisation.

        Read from an annotation the view attaches, so listing N organisations stays one
        query instead of N.
        """
        return getattr(organization, "current_user_role", None)


class GitHubCallbackSerializer(serializers.Serializer):
    """Inbound payload for POST /api/auth/github/callback/."""

    code = serializers.CharField(write_only=True, trim_whitespace=True)
    state = serializers.CharField(write_only=True, trim_whitespace=True)


class AuthTokenResponseSerializer(serializers.Serializer):
    """Response shape for a successful login. Declared for the OpenAPI schema."""

    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)
    user = UserSerializer(read_only=True)
    created = serializers.BooleanField(
        read_only=True, help_text="True when this login created the account."
    )


class GitHubStartResponseSerializer(serializers.Serializer):
    """Response shape for GET /api/auth/github/start/."""

    authorize_url = serializers.CharField(read_only=True)
    state = serializers.CharField(read_only=True)


class MembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "user", "role", "created_at"]
        read_only_fields = fields
