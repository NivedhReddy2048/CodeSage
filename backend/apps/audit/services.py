"""Recording audit entries from the actions that matter."""

import logging

from django.conf import settings

from apps.audit.models import AuditLogEntry

logger = logging.getLogger(__name__)

Action = AuditLogEntry.Action


def record(organization, actor, action, target=None, target_label="", **metadata):
    """Append one entry. Never raises: a failed audit write must not fail the action.

    Losing an entry is bad; refusing to connect a repository because the audit table
    hiccuped would be worse, and the failure is logged loudly either way.
    """
    if organization is None:
        return None
    try:
        return AuditLogEntry.objects.create(
            organization=organization,
            actor=actor if getattr(actor, "pk", None) else None,
            actor_login=_login(actor),
            action=action,
            target_type=type(target).__name__.lower() if target is not None else "",
            target_id=str(getattr(target, "pk", "") or ""),
            target_label=(target_label or (str(target) if target is not None else ""))[:512],
            metadata=metadata,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Could not write audit entry %s for %s", action, organization)
        return None


def client_ip(request):
    """The caller's address, read the way a proxy chain can be trusted.

    Each proxy APPENDS the address it saw to X-Forwarded-For, so with
    TRUSTED_PROXY_HOPS proxies in front of us the client is that many entries from
    the right. The leftmost entry is whatever the client chose to send: reading it
    would let anyone write any address into the audit log. With no trusted proxy,
    or a header too short to hold one, the socket peer is the answer.
    """
    if request is None:
        return ""
    hops = getattr(settings, "TRUSTED_PROXY_HOPS", 0)
    if hops > 0:
        chain = [
            part.strip()
            for part in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")
            if part.strip()
        ]
        if len(chain) >= hops:
            return chain[-hops][:64]
    return (request.META.get("REMOTE_ADDR") or "")[:64]


def record_auth(user, action, request=None, **metadata):
    """An auth event, filed under every organisation the user belongs to.

    A sign-in is not an action inside one workspace, but each workspace's owners
    should see who signed in to it. With no user (a failed sign-in GitHub never
    identified) it is stored once without an organisation.
    """
    from apps.accounts.models import Membership

    metadata = {
        "ip": client_ip(request),
        "user_agent": (request.META.get("HTTP_USER_AGENT", "") if request else "")[:200],
        **metadata,
    }
    organizations = []
    if user is not None and getattr(user, "pk", None):
        organizations = [
            m.organization
            for m in Membership.objects.filter(user=user).select_related("organization")
        ]
    try:
        if not organizations:
            return [
                AuditLogEntry.objects.create(
                    organization=None,
                    actor=user if getattr(user, "pk", None) else None,
                    actor_login=_login(user),
                    action=action,
                    metadata=metadata,
                )
            ]
        return [
            AuditLogEntry.objects.create(
                organization=organization,
                actor=user,
                actor_login=_login(user),
                action=action,
                target_label=_login(user),
                metadata=metadata,
            )
            for organization in organizations
        ]
    except Exception:  # noqa: BLE001 - a failed audit write must not fail the sign-in
        logger.exception("Could not write auth audit entry %s", action)
        return []


def _login(actor):
    if actor is None:
        return ""
    return getattr(actor, "github_login", "") or getattr(actor, "username", "") or ""
