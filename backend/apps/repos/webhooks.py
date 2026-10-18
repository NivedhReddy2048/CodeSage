"""GitHub webhook signature verification.

This is the security boundary for the entire PR loop: the endpoint is public, so the
signature is the only thing distinguishing a real GitHub delivery from anyone who
knows the URL. Everything here operates on the RAW request body — re-serialising the
parsed JSON would change the bytes and break the HMAC.
"""

import hashlib
import hmac

from django.conf import settings

SIGNATURE_HEADER = "X-Hub-Signature-256"
SIGNATURE_PREFIX = "sha256="


class WebhookSignatureError(Exception):
    """The delivery could not be proven to come from GitHub."""


def expected_signature(raw_body, secret):
    """The `sha256=...` value GitHub should have sent for this exact body."""
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify_signature(raw_body, provided_signature, secret=None):
    """Raise WebhookSignatureError unless `provided_signature` matches `raw_body`."""
    secret = settings.GITHUB_WEBHOOK_SECRET if secret is None else secret

    if not secret:
        # Refusing is the safe default: without a secret every caller would otherwise
        # be trusted, which is worse than the endpoint being unavailable.
        raise WebhookSignatureError("Webhook secret is not configured.")

    if not provided_signature:
        raise WebhookSignatureError(f"Missing {SIGNATURE_HEADER} header.")

    if not provided_signature.startswith(SIGNATURE_PREFIX):
        raise WebhookSignatureError("Signature is not SHA-256.")

    # compare_digest, not ==, so the comparison time does not leak how much of the
    # signature was correct.
    if not hmac.compare_digest(expected_signature(raw_body, secret), provided_signature):
        raise WebhookSignatureError("Signature does not match the payload.")
