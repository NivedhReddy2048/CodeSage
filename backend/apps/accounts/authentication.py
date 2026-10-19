"""JWT authentication that also carries the caller's chosen organisation.

The workspace switcher sends `X-Organization-Id` on every request. Reading it here,
at authentication time, means `current_organization(user)` can honour it without
every view having to thread the request through. The header is only a *request*:
`current_organization` checks the caller is actually a member before using it, so
naming another tenant's id falls back to the caller's own organisation rather than
granting anything.
"""

from rest_framework_simplejwt.authentication import JWTAuthentication

ORGANIZATION_HEADER = "X-Organization-Id"


class OrganizationAwareJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None

        user, token = result
        user.requested_organization_id = parse_organization_id(
            request.headers.get(ORGANIZATION_HEADER)
        )
        return user, token


def parse_organization_id(value):
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


try:
    from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme

    class OrganizationAwareJWTScheme(SimpleJWTScheme):
        """Keep the Swagger page's Bearer auth: same scheme, plus the org header."""

        target_class = "apps.accounts.authentication.OrganizationAwareJWTAuthentication"
        name = "jwtAuth"
except ImportError:  # pragma: no cover - drf-spectacular is a hard dependency
    pass
