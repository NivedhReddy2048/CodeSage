from django.db.models import OuterRef, Subquery
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts import github
from apps.accounts.models import Membership, Organization, User
from apps.accounts.serializers import (
    AuthTokenResponseSerializer,
    GitHubCallbackSerializer,
    GitHubStartResponseSerializer,
    LogoutRequestSerializer,
    MemberRoleSerializer,
    MembershipSerializer,
    OrganizationSerializer,
    UserSerializer,
)
from apps.accounts.services import get_or_create_user_from_github
from apps.audit.services import Action, record_auth


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
            record_auth(None, Action.AUTH_SIGN_IN_FAILED, request, reason=str(exc)[:200])
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        user, created = get_or_create_user_from_github(profile)

        refresh = RefreshToken.for_user(user)
        record_auth(user, Action.AUTH_SIGNED_IN, request, first_sign_in=created)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
                "created": created,
            }
        )


class LogoutView(APIView):
    """Sign out server-side: the refresh token is blacklisted, so a copy is useless.

    Authenticated by the refresh token itself rather than the access token, which
    may already have expired by the time someone presses "Sign out". Always 204: a
    token that is invalid or already revoked has nothing left to revoke, and saying
    which would tell a caller whether a token they hold is still live.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=LogoutRequestSerializer,
        responses={204: OpenApiResponse(description="Signed out (or nothing to revoke).")},
    )
    def post(self, request):
        raw = str(request.data.get("refresh") or "")
        try:
            token = RefreshToken(raw)
        except TokenError:
            return Response(status=status.HTTP_204_NO_CONTENT)
        user = User.objects.filter(pk=token.get("user_id")).first()
        token.blacklist()
        record_auth(user, Action.AUTH_SIGNED_OUT, request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AuditedTokenRefreshView(TokenRefreshView):
    """Token refresh that records a refused replay of a revoked refresh token.

    A blacklisted token comes back only if someone kept a copy: the same browser
    racing itself, or a stolen token. Either way its owner's workspaces should see
    it, so it is audited as a failed sign-in before the 401 goes out.
    """

    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except InvalidToken:
            owner = _revoked_token_owner(str(request.data.get("refresh") or ""))
            if owner is not None:
                record_auth(
                    owner,
                    Action.AUTH_SIGN_IN_FAILED,
                    request,
                    reason="revoked refresh token presented again",
                )
            raise


def _revoked_token_owner(raw):
    """The user a validly signed but blacklisted refresh token belongs to, or None."""
    from rest_framework_simplejwt.state import token_backend
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

    try:
        payload = token_backend.decode(raw, verify=True)
    except Exception:  # noqa: BLE001 - forged, expired or garbage: nobody to attribute
        return None
    if not BlacklistedToken.objects.filter(token__jti=payload.get("jti")).exists():
        return None
    return User.objects.filter(pk=payload.get("user_id")).first()


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


class MemberListView(APIView):
    """Members of the caller's current organisation, with their roles."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MembershipSerializer(many=True)})
    def get(self, request):
        from apps.repos.services import current_organization

        organization = current_organization(request.user)
        if organization is None:
            return Response([])
        members = Membership.objects.filter(organization=organization).select_related("user")
        return Response(MembershipSerializer(members.order_by("created_at"), many=True).data)


class MemberRoleView(APIView):
    """Change one member's role. Owners only; audit-logged."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=MemberRoleSerializer,
        responses={
            200: MembershipSerializer,
            400: OpenApiResponse(description="Invalid role, or it would leave no owner."),
            403: OpenApiResponse(description="Requires the owner role."),
            404: OpenApiResponse(description="Not a member of your organisation."),
        },
    )
    def patch(self, request, pk):
        from apps.audit.services import Action
        from apps.audit.services import record as audit
        from apps.repos.services import current_organization, role_in

        organization = current_organization(request.user)
        # Scoped lookup: a membership in another organisation reads as absent.
        membership = (
            Membership.objects.filter(pk=pk, organization=organization)
            .select_related("user")
            .first()
        )
        if membership is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if role_in(request.user, organization) != Membership.Role.OWNER:
            return Response(
                {"detail": "Changing roles requires the owner role."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = MemberRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_role = serializer.validated_data["role"]
        old_role = membership.role

        if old_role == new_role:
            return Response(MembershipSerializer(membership).data)

        if old_role == Membership.Role.OWNER:
            owners = Membership.objects.filter(
                organization=organization, role=Membership.Role.OWNER
            ).count()
            if owners <= 1:
                return Response(
                    {"detail": "An organisation must keep at least one owner."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        membership.role = new_role
        membership.save(update_fields=["role"])
        audit(
            organization,
            request.user,
            Action.MEMBER_ROLE_CHANGED,
            target=membership.user,
            target_label=membership.user.github_login or membership.user.username,
            old_role=old_role,
            new_role=new_role,
        )
        return Response(MembershipSerializer(membership).data)
