"""Recording audit entries from the actions that matter."""

import logging

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


def _login(actor):
    if actor is None:
        return ""
    return getattr(actor, "github_login", "") or getattr(actor, "username", "") or ""
