"""Tenancy and authorisation helpers for repository management."""

from apps.accounts.models import Membership
from apps.repos.models import AppInstallation

# Roles allowed to change what the organisation reviews. A member can look, but
# rewiring the org's repositories is an owner/admin action.
REPO_MANAGEMENT_ROLES = {Membership.Role.OWNER, Membership.Role.ADMIN}


class PermissionDenied(Exception):
    """The caller may not do this to this organisation."""


def current_organization(user):
    """The organisation a request acts on behalf of.

    Phase 1 gives every user exactly one personal organisation, so that is the answer
    today. Phase 6 adds the workspace switcher, at which point this reads the choice
    from the request instead; keeping the lookup in one place means that change lands
    here and nowhere else.
    """
    membership = (
        Membership.objects.filter(user=user, organization__is_personal=True)
        .select_related("organization")
        .first()
    ) or (Membership.objects.filter(user=user).select_related("organization").first())
    return membership.organization if membership else None


def role_in(user, organization):
    if organization is None:
        return None
    membership = Membership.objects.filter(user=user, organization=organization).first()
    return membership.role if membership else None


def require_management_role(user, organization):
    """Raise unless `user` may change `organization`'s connected repositories."""
    role = role_in(user, organization)
    if role is None:
        raise PermissionDenied("You are not a member of this organisation.")
    if role not in REPO_MANAGEMENT_ROLES:
        raise PermissionDenied(
            "Connecting or disconnecting repositories requires the owner or admin role."
        )


def installations_for(user, organization):
    """Installations this user/organisation may act through.

    Either explicitly linked to the organisation, or installed on the account whose
    GitHub login matches the user's — the same two-step resolution the webhook path
    uses, so the UI and the webhook never disagree about which installation applies.
    """
    from django.db.models import Q

    query = Q(organization=organization)
    if user.github_login:
        query |= Q(account_login__iexact=user.github_login)
    return AppInstallation.objects.filter(query).distinct()
