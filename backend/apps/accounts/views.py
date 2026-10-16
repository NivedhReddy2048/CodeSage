from django.db.models import OuterRef, Subquery
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts import github
from apps.accounts.models import Membership, Organization
from apps.accounts.serializers import (
    AuthTokenResponseSerializer,
    GitHubCallbackSerializer,
    GitHubStartResponseSerializer,
    OrganizationSerializer,
    UserSerializer,
)
from apps.accounts.services import get_or_create_user_from_github


class GitHubLoginStartView(APIView):
    """Hand the frontend the GitHub authorize URL and a signed state nonce."""

    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: GitHubStartResponseSerializer},
        description=(
            "Returns the GitHub authorize URL to redirect the browser to, plus a "
            "signed state value the caller must echo back to the callback endpoint."
        ),
    )
    def get(self, request):
        state = github.build_state()
        return Response({"authorize_url": github.build_authorize_url(state), "state": state})


class GitHubCallbackView(APIView):
    """Exchange a GitHub authorization code for CodeSage JWTs."""

    permission_classes = [AllowAny]

    @extend_schema(
        request=GitHubCallbackSerializer,
        responses={
            200: AuthTokenResponseSerializer,
            400: OpenApiResponse(description="Invalid state, or GitHub rejected the code."),
        },
        description=(
            "Verifies the state nonce, exchanges the code with GitHub, matches or "
            "creates the user (creating a personal organisation on first login), and "
            "returns an access/refresh pair."
        ),
    )
    def post(self, request):
        serializer = GitHubCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data["code"]
        state = serializer.validated_data["state"]

        try:
            github.verify_state(state)
            token = github.exchange_code_for_token(code)
            profile = github.fetch_user_profile(token)
        except github.GitHubOAuthError as exc:
            # A failed exchange is the caller's problem (stale code, replayed state),
            # not a server fault, so this is a 400 rather than a 502.
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        user, created = get_or_create_user_from_github(profile)

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
                "created": created,
            }
        )


class CurrentUserView(APIView):
    """Who am I? Used by the frontend to prove a stored token still works."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: UserSerializer})
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class OrganizationListView(generics.ListAPIView):
    """Organisations the caller belongs to, each annotated with their role."""

    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        my_role = Membership.objects.filter(
            organization=OuterRef("pk"), user=self.request.user
        ).values("role")[:1]

        return (
            Organization.objects.filter(memberships__user=self.request.user)
            .annotate(current_user_role=Subquery(my_role))
            .order_by("name")
        )
