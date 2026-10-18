from rest_framework import serializers

from apps.repos.models import Repository


class RepositorySerializer(serializers.ModelSerializer):
    installation_id = serializers.IntegerField(
        source="installation.installation_id", read_only=True, allow_null=True
    )
    connected_by_login = serializers.CharField(
        source="connected_by.github_login", read_only=True, default=""
    )

    class Meta:
        model = Repository
        fields = [
            "id",
            "github_id",
            "full_name",
            "owner",
            "name",
            "default_branch",
            "private",
            "installation_id",
            "connected_by_login",
            "created_at",
        ]
        read_only_fields = fields


class InstallableRepositorySerializer(serializers.Serializer):
    """A repository the App installation can reach, connected or not.

    Not a ModelSerializer: these come straight from GitHub and may have no local row.
    """

    github_id = serializers.IntegerField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    owner = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    default_branch = serializers.CharField(read_only=True)
    private = serializers.BooleanField(read_only=True)
    connected = serializers.BooleanField(read_only=True)


class InstallableResponseSerializer(serializers.Serializer):
    installed = serializers.BooleanField(read_only=True)
    install_url = serializers.CharField(read_only=True)
    repositories = InstallableRepositorySerializer(many=True, read_only=True)


class RepositoryConnectSerializer(serializers.Serializer):
    github_id = serializers.IntegerField(
        help_text="GitHub's numeric repository id, as returned by /api/repos/installable/."
    )
