"""Recording audit entries from the actions that matter."""

import ipaddress
import logging

from django.conf import settings

from apps.audit.models import AuditLogEntry

logger = logging.getLogger(__name__)

Action = AuditLogEntry.Action

# The reason recorded when a revoked refresh token comes back. Entries written
# before AUTH_REFRESH_REJECTED existed carry it under AUTH_SIGN_IN_FAILED.
REVOKED_REFRESH_REASON = "revoked refresh token presented again"


def action_label(entry):
    """The label to show for an entry.

    The log is append-only, so entries filed as "Sign-in failed" for a replayed
    refresh token before the dedicated action existed cannot be corrected in place;
    they are labelled for what they were when shown.
    """
    if (
        entry.action == Action.AUTH_SIGN_IN_FAILED
        and (entry.metadata or {}).get("reason") == REVOKED_REFRESH_REASON
    ):
        return Action.AUTH_REFRESH_REJECTED.label
    return entry.get_action_display()


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


# Cloudflare's published edge ranges, https://www.cloudflare.com/ips/ ("Last
# updated: Sep 28, 2023"; checked 2026-11-03). A client address inside one of these
# is Cloudflare's, not the client's: the hop count stopped one proxy short.
CLOUDFLARE_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
)


def _forwarded_chain(request):
    return [
        part.strip()
        for part in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")
        if part.strip()
    ]


def client_ip_warning(request, ip):
    """Why `ip` looks like a proxy's address rather than the client's, or "".

    Only behind a proxy (TRUSTED_PROXY_HOPS > 0): locally the socket peer is
    127.0.0.1 and that is correct. In production a client address that is private
    or internal (Render's own proxy, 10.x) or Cloudflare's means the hop count is
    too LOW: the entry read is a proxy's. Render's chain was measured as client,
    Cloudflare, Render, so 3 (docs/DEPLOY.md). A count that is too HIGH reads an
    entry the client wrote, which can look like anything; only a header shorter
    than the count gives that away.
    """
    hops = getattr(settings, "TRUSTED_PROXY_HOPS", 0)
    if request is None or hops <= 0:
        return ""
    chain = _forwarded_chain(request)
    if len(chain) < hops:
        return (
            f"X-Forwarded-For has {len(chain)} entries but TRUSTED_PROXY_HOPS is {hops}, "
            "so the socket peer (a proxy) was recorded"
        )
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return f"{ip!r} is not an IP address; check TRUSTED_PROXY_HOPS ({hops})"
    if any(address in network for network in CLOUDFLARE_NETWORKS):
        return (
            f"{ip} is a Cloudflare edge address, not a client: TRUSTED_PROXY_HOPS ({hops}) "
            "is probably one too low"
        )
    if not address.is_global:
        return (
            f"{ip} is a private or internal address, not a client: TRUSTED_PROXY_HOPS "
            f"({hops}) is probably too low"
        )
    return ""


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
        chain = _forwarded_chain(request)
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

    ip = client_ip(request)
    metadata = {
        "ip": ip,
        "user_agent": (request.META.get("HTTP_USER_AGENT", "") if request else "")[:200],
        **metadata,
    }
    # A misconfigured hop count is invisible otherwise: the log fills with a
    # proxy's address that looks plausible. Said in the entry and in the log.
    if warning := client_ip_warning(request, ip):
        metadata["ip_warning"] = warning
        logger.warning("Client IP looks wrong for %s: %s", action, warning)
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
