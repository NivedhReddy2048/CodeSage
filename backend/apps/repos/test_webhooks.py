"""Tests for the webhook receiver.

The signature check is the security boundary for the whole PR loop, so it is tested
from both sides: a correct delivery must be accepted, and every way of getting it
wrong must be rejected *before* any work happens.
"""

import json
from unittest import mock

import pytest
from django.urls import reverse

from apps.repos import webhooks
from apps.repos.models import WebhookEvent
from apps.repos.webhooks import WebhookSignatureError, expected_signature

SECRET = "test-webhook-secret-at-least-32-characters"


@pytest.fixture(autouse=True)
def webhook_settings(settings):
    settings.GITHUB_WEBHOOK_SECRET = SECRET
    # Inline, so assertions do not race a background thread.
    settings.BACKGROUND_TASKS_EAGER = True
    return settings


def pull_request_payload(action="opened", number=1):
    return {
        "action": action,
        "number": number,
        "pull_request": {
            "id": 99001,
            "number": number,
            "title": "Add a thing",
            "state": "open",
            "user": {"login": "NivedhReddy2048"},
            "head": {"sha": "a" * 40},
            "base": {"ref": "main"},
        },
        "repository": {
            "id": 555000,
            "full_name": "NivedhReddy2048/codesage-testbed",
            "name": "codesage-testbed",
            "owner": {"login": "NivedhReddy2048"},
            "default_branch": "main",
            "private": False,
        },
        "installation": {
            "id": 172631969,
            "account": {"login": "NivedhReddy2048", "type": "User"},
            "repository_selection": "selected",
        },
    }


def post_delivery(
    client,
    payload,
    *,
    event="pull_request",
    delivery="d-1",
    secret=SECRET,
    signature=None,
    raw=None,
):
    body = raw if raw is not None else json.dumps(payload).encode()
    headers = {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
    }
    if signature is not False:
        headers[webhooks.SIGNATURE_HEADER] = (
            signature if signature else expected_signature(body, secret)
        )
    return client.post(
        reverse("github-webhook"),
        data=body,
        content_type="application/json",
        headers=headers,
    )


# ------------------------------------------------------------- signature unit tests


def test_signature_round_trip():
    body = b'{"a":1}'
    webhooks.verify_signature(body, expected_signature(body, SECRET), SECRET)


def test_signature_rejects_a_modified_body():
    signature = expected_signature(b'{"a":1}', SECRET)

    with pytest.raises(WebhookSignatureError, match="does not match"):
        webhooks.verify_signature(b'{"a":2}', signature, SECRET)


def test_signature_rejects_the_wrong_secret():
    body = b'{"a":1}'

    with pytest.raises(WebhookSignatureError, match="does not match"):
        webhooks.verify_signature(body, expected_signature(body, "other-secret"), SECRET)


def test_signature_rejects_a_missing_header():
    with pytest.raises(WebhookSignatureError, match="Missing"):
        webhooks.verify_signature(b"{}", "", SECRET)


def test_signature_rejects_sha1():
    """GitHub still sends the legacy X-Hub-Signature; we must not accept SHA-1."""
    with pytest.raises(WebhookSignatureError, match="not SHA-256"):
        webhooks.verify_signature(b"{}", "sha1=abcdef", SECRET)


def test_signature_refuses_when_no_secret_is_configured():
    """Failing closed: an unset secret must not mean 'trust everyone'."""
    with pytest.raises(WebhookSignatureError, match="not configured"):
        webhooks.verify_signature(b"{}", "sha256=whatever", "")


# ---------------------------------------------------------------- endpoint security


@pytest.mark.django_db
def test_valid_delivery_is_accepted(client):
    with mock.patch("apps.repos.views.run_in_background") as enqueue:
        response = post_delivery(client, pull_request_payload())

    assert response.status_code == 202
    assert WebhookEvent.objects.count() == 1
    enqueue.assert_called_once()


@pytest.mark.django_db
def test_tampered_body_is_rejected_and_stores_nothing(client):
    body = json.dumps(pull_request_payload()).encode()
    good_signature = expected_signature(body, SECRET)
    tampered = body.replace(b"Add a thing", b"Add a thinG")

    with mock.patch("apps.repos.views.run_in_background") as enqueue:
        response = post_delivery(client, None, raw=tampered, signature=good_signature)

    assert response.status_code == 401
    # Nothing persisted and nothing queued: rejection happens first.
    assert WebhookEvent.objects.count() == 0
    enqueue.assert_not_called()


@pytest.mark.django_db
def test_missing_signature_is_rejected(client):
    response = post_delivery(client, pull_request_payload(), signature=False)

    assert response.status_code == 401
    assert WebhookEvent.objects.count() == 0


@pytest.mark.django_db
def test_wrong_secret_is_rejected(client):
    response = post_delivery(client, pull_request_payload(), secret="not-the-secret")

    assert response.status_code == 401
    assert WebhookEvent.objects.count() == 0


@pytest.mark.django_db
def test_unconfigured_secret_rejects_everything(client, webhook_settings):
    webhook_settings.GITHUB_WEBHOOK_SECRET = ""

    response = post_delivery(client, pull_request_payload())

    assert response.status_code == 401


# ------------------------------------------------------------------- the 10s budget


@pytest.mark.django_db
def test_handler_does_no_github_work_inline(client):
    """The core of spec section 13: the response must not wait on GitHub.

    Patching the dispatcher proves the GitHub calls are deferred, not merely fast.
    """
    with (
        mock.patch("apps.repos.views.run_in_background") as enqueue,
        mock.patch("apps.repos.github_app.requests.request") as api,
    ):
        response = post_delivery(client, pull_request_payload())

    assert response.status_code == 202
    api.assert_not_called()
    enqueue.assert_called_once()


@pytest.mark.django_db
def test_enqueued_with_the_stored_event_id(client):
    with mock.patch("apps.repos.views.run_in_background") as enqueue:
        post_delivery(client, pull_request_payload())

    event = WebhookEvent.objects.get()
    args = enqueue.call_args.args
    assert args[1] == event.pk


# --------------------------------------------------------------------- idempotency


@pytest.mark.django_db
def test_redelivery_of_the_same_id_does_not_queue_twice(client):
    """GitHub reuses the delivery id on a manual redelivery."""
    payload = pull_request_payload()

    with mock.patch("apps.repos.views.run_in_background") as enqueue:
        first = post_delivery(client, payload, delivery="same-id")
        second = post_delivery(client, payload, delivery="same-id")

    assert first.status_code == 202
    # Still 202: a redelivery is not an error, it just must not duplicate work.
    assert second.status_code == 202
    assert WebhookEvent.objects.count() == 1
    assert enqueue.call_count == 1


@pytest.mark.django_db
def test_distinct_deliveries_are_both_processed(client):
    with mock.patch("apps.repos.views.run_in_background") as enqueue:
        post_delivery(client, pull_request_payload(), delivery="d-a")
        post_delivery(client, pull_request_payload(action="synchronize"), delivery="d-b")

    assert WebhookEvent.objects.count() == 2
    assert enqueue.call_count == 2


# ------------------------------------------------------------------ malformed input


@pytest.mark.django_db
def test_missing_delivery_headers_is_a_400(client):
    body = json.dumps(pull_request_payload()).encode()

    response = client.post(
        reverse("github-webhook"),
        data=body,
        content_type="application/json",
        headers={webhooks.SIGNATURE_HEADER: expected_signature(body, SECRET)},
    )

    assert response.status_code == 400
    assert WebhookEvent.objects.count() == 0


@pytest.mark.django_db
def test_non_json_body_is_a_400(client):
    response = post_delivery(client, None, raw=b"not json at all")

    assert response.status_code == 400


@pytest.mark.django_db
def test_json_that_is_not_an_object_is_a_400(client):
    response = post_delivery(client, None, raw=b'["a", "list"]')

    assert response.status_code == 400


@pytest.mark.django_db
def test_an_unknown_event_type_is_stored_but_not_acted_on(client):
    with mock.patch("apps.repos.tasks.github_app") as api:
        response = post_delivery(
            client, {"zen": "Keep it logically awesome."}, event="ping", delivery="p-1"
        )

    assert response.status_code == 202
    event = WebhookEvent.objects.get()
    assert event.event == "ping"
    assert event.processed_at is not None
    api.create_issue_comment.assert_not_called()


@pytest.mark.django_db
def test_the_endpoint_needs_no_authentication(client):
    """GitHub cannot present a JWT, so the signature is the only credential."""
    response = post_delivery(client, pull_request_payload())

    assert response.status_code != 403
