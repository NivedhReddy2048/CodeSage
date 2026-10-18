"""Tests for the work that runs after the webhook has been answered."""

from unittest import mock

import pytest

from apps.accounts.models import Organization
from apps.accounts.services import get_or_create_user_from_github
from apps.repos import tasks
from apps.repos.github_app import GitHubAppError
from apps.repos.models import AppInstallation, Repository, WebhookEvent
from apps.reviews.models import PullRequest

INSTALLATION_ID = 172631969


@pytest.fixture
def owner():
    """A user whose GitHub login matches the account the App is installed on."""
    user, _ = get_or_create_user_from_github(
        {
            "id": 181383619,
            "login": "NivedhReddy2048",
            "name": "",
            "email": "",
            "avatar_url": "",
        }
    )
    return user


def payload(action="opened", number=7):
    return {
        "action": action,
        "pull_request": {
            "id": 99001,
            "number": number,
            "title": "Fix the off-by-one",
            "state": "open",
            "user": {"login": "NivedhReddy2048"},
            "head": {"sha": "b" * 40},
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
            "id": INSTALLATION_ID,
            "account": {"login": "NivedhReddy2048", "type": "User"},
            "repository_selection": "selected",
        },
    }


def store(event="pull_request", action="opened", body=None, delivery="d-1"):
    body = payload(action=action) if body is None else body
    return WebhookEvent.objects.create(
        delivery_id=delivery,
        event=event,
        action=action,
        installation_id=(body.get("installation") or {}).get("id"),
        repository_full_name=(body.get("repository") or {}).get("full_name", ""),
        payload=body,
    )


# ------------------------------------------------------------------ happy path


@pytest.mark.django_db
def test_opened_pr_creates_records_and_posts_the_ack(owner):
    event = store()

    with mock.patch.object(
        tasks.github_app, "create_issue_comment", return_value={"id": 4242}
    ) as comment:
        tasks.handle_webhook_event(event.pk)

    installation = AppInstallation.objects.get(installation_id=INSTALLATION_ID)
    assert installation.account_login == "NivedhReddy2048"

    repository = Repository.objects.get(github_id=555000)
    assert repository.full_name == "NivedhReddy2048/codesage-testbed"
    # Attributed to the installing user's personal workspace.
    assert repository.organization == owner.memberships.get().organization

    pull_request = PullRequest.objects.get()
    assert pull_request.number == 7
    assert pull_request.head_sha == "b" * 40
    assert pull_request.ack_comment_id == 4242

    comment.assert_called_once()
    args = comment.call_args.args
    assert args[0] == INSTALLATION_ID
    assert args[1] == "NivedhReddy2048/codesage-testbed"
    assert args[2] == 7
    assert "CodeSage is reviewing this PR" in args[3]

    event.refresh_from_db()
    assert event.processed_at is not None


@pytest.mark.django_db
def test_synchronize_edits_the_existing_comment_instead_of_adding_one(owner):
    """Five pushes must leave one bot comment, not five."""
    with mock.patch.object(tasks.github_app, "create_issue_comment", return_value={"id": 4242}):
        tasks.handle_webhook_event(store(delivery="d-open").pk)

    with (
        mock.patch.object(tasks.github_app, "create_issue_comment") as create,
        mock.patch.object(tasks.github_app, "update_issue_comment") as update,
    ):
        tasks.handle_webhook_event(store(action="synchronize", delivery="d-sync").pk)

    create.assert_not_called()
    update.assert_called_once()
    assert update.call_args.args[2] == 4242
    assert PullRequest.objects.count() == 1


@pytest.mark.django_db
def test_synchronize_updates_the_head_sha(owner):
    with mock.patch.object(tasks.github_app, "create_issue_comment", return_value={"id": 1}):
        tasks.handle_webhook_event(store(delivery="d-open").pk)

    body = payload(action="synchronize")
    body["pull_request"]["head"]["sha"] = "c" * 40

    with mock.patch.object(tasks.github_app, "update_issue_comment"):
        tasks.handle_webhook_event(store(action="synchronize", body=body, delivery="d-sync").pk)

    assert PullRequest.objects.get().head_sha == "c" * 40


# ------------------------------------------------------------- ignored and failing


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["closed", "edited", "labeled", "assigned"])
def test_non_reviewable_actions_post_nothing(owner, action):
    """These actions change no code, so they must not spend a review."""
    event = store(action=action, delivery=f"d-{action}")

    with mock.patch.object(tasks.github_app, "create_issue_comment") as comment:
        tasks.handle_webhook_event(event.pk)

    comment.assert_not_called()
    assert PullRequest.objects.count() == 0
    event.refresh_from_db()
    assert event.processed_at is not None


@pytest.mark.django_db
def test_reopened_is_reviewable(owner):
    """Changed in phase 4.

    Phase 2 treated `reopened` as a no-op because it does not alter the diff. But a
    PR reopened after being closed has had no review of this branch state, and the
    user's expectation on reopening is that it gets looked at.
    """
    event = store(action="reopened", delivery="d-reopened")

    with (
        mock.patch.object(
            tasks.github_app, "create_issue_comment", return_value={"id": 1}
        ) as comment,
        mock.patch("apps.reviews.tasks.review_pull_request_task.delay") as queued,
    ):
        tasks.handle_webhook_event(event.pk)

    comment.assert_called_once()
    queued.assert_called_once()
    assert PullRequest.objects.count() == 1


@pytest.mark.django_db
def test_no_matching_user_means_no_attribution_and_no_comment():
    """Without a local user for the installing account there is no tenant to use."""
    event = store()

    with mock.patch.object(tasks.github_app, "create_issue_comment") as comment:
        tasks.handle_webhook_event(event.pk)

    comment.assert_not_called()
    assert Repository.objects.count() == 0
    # The installation is still recorded, so the UI can offer to link it later.
    assert AppInstallation.objects.filter(installation_id=INSTALLATION_ID).exists()


@pytest.mark.django_db
def test_an_explicit_organization_link_wins_over_the_fallback(owner):
    """The connect flow's choice must not be overridden by login matching."""
    chosen = Organization.objects.create(name="Team", slug="team")
    AppInstallation.objects.create(
        installation_id=INSTALLATION_ID,
        account_login="NivedhReddy2048",
        organization=chosen,
    )

    with mock.patch.object(tasks.github_app, "create_issue_comment", return_value={"id": 1}):
        tasks.handle_webhook_event(store().pk)

    assert Repository.objects.get().organization == chosen


@pytest.mark.django_db
def test_a_github_failure_does_not_crash_the_task(owner):
    """The webhook is already answered; a failed comment must only be logged."""
    event = store()

    with mock.patch.object(
        tasks.github_app, "create_issue_comment", side_effect=GitHubAppError("403")
    ):
        tasks.handle_webhook_event(event.pk)

    assert PullRequest.objects.get().ack_comment_id is None
    event.refresh_from_db()
    assert event.processed_at is not None


@pytest.mark.django_db
def test_a_comment_response_without_an_id_is_tolerated(owner):
    with mock.patch.object(tasks.github_app, "create_issue_comment", return_value={}):
        tasks.handle_webhook_event(store().pk)

    assert PullRequest.objects.get().ack_comment_id is None


@pytest.mark.django_db
def test_a_payload_without_a_pr_number_is_skipped(owner):
    body = payload()
    body["pull_request"].pop("number")

    with mock.patch.object(tasks.github_app, "create_issue_comment") as comment:
        tasks.handle_webhook_event(store(body=body).pk)

    comment.assert_not_called()
    assert PullRequest.objects.count() == 0


@pytest.mark.django_db
def test_a_vanished_event_is_handled_quietly():
    tasks.handle_webhook_event(999999)  # must not raise


# ------------------------------------------------------------------ installations


@pytest.mark.django_db
def test_installation_created_event_records_the_installation():
    body = {
        "action": "created",
        "installation": {
            "id": INSTALLATION_ID,
            "account": {"login": "NivedhReddy2048", "type": "User"},
            "repository_selection": "selected",
        },
    }

    tasks.handle_webhook_event(store(event="installation", action="created", body=body).pk)

    installation = AppInstallation.objects.get(installation_id=INSTALLATION_ID)
    assert installation.repository_selection == "selected"
    assert installation.suspended is False


@pytest.mark.django_db
def test_installation_suspend_and_unsuspend():
    body = {
        "action": "suspend",
        "installation": {
            "id": INSTALLATION_ID,
            "account": {"login": "NivedhReddy2048", "type": "User"},
        },
    }

    tasks.handle_webhook_event(
        store(event="installation", action="suspend", body=body, delivery="s1").pk
    )
    assert AppInstallation.objects.get(installation_id=INSTALLATION_ID).suspended is True

    body["action"] = "unsuspend"
    tasks.handle_webhook_event(
        store(event="installation", action="unsuspend", body=body, delivery="s2").pk
    )
    assert AppInstallation.objects.get(installation_id=INSTALLATION_ID).suspended is False


@pytest.mark.django_db
def test_installation_deleted_removes_it_but_keeps_repositories(owner):
    with mock.patch.object(tasks.github_app, "create_issue_comment", return_value={"id": 1}):
        tasks.handle_webhook_event(store(delivery="d-open").pk)
    assert Repository.objects.count() == 1

    body = {
        "action": "deleted",
        "installation": {
            "id": INSTALLATION_ID,
            "account": {"login": "NivedhReddy2048", "type": "User"},
        },
    }
    tasks.handle_webhook_event(
        store(event="installation", action="deleted", body=body, delivery="d-del").pk
    )

    assert not AppInstallation.objects.filter(installation_id=INSTALLATION_ID).exists()
    repository = Repository.objects.get()
    assert repository.installation is None


@pytest.mark.django_db
def test_a_payload_without_an_installation_is_ignored():
    tasks.handle_webhook_event(
        store(event="installation", action="created", body={"action": "created"}).pk
    )

    assert AppInstallation.objects.count() == 0


@pytest.mark.django_db
def test_sparse_payloads_do_not_blank_existing_fields():
    AppInstallation.objects.create(
        installation_id=INSTALLATION_ID,
        account_login="NivedhReddy2048",
        account_type="User",
        repository_selection="selected",
    )
    sparse = {"action": "created", "installation": {"id": INSTALLATION_ID}}

    tasks.upsert_installation(sparse)

    installation = AppInstallation.objects.get(installation_id=INSTALLATION_ID)
    assert installation.account_login == "NivedhReddy2048"
    assert installation.repository_selection == "selected"


# ---------------------------------------------------------------------- dispatcher


@pytest.mark.django_db
def test_eager_dispatch_runs_inline(settings):
    from apps.repos.dispatch import run_in_background

    settings.BACKGROUND_TASKS_EAGER = True
    calls = []

    assert run_in_background(calls.append, "x") is None
    assert calls == ["x"]


@pytest.mark.django_db
def test_dispatch_swallows_and_logs_failures(settings):
    """A background exception must not escape; the webhook is already answered."""
    from apps.repos.dispatch import run_in_background

    settings.BACKGROUND_TASKS_EAGER = True

    def boom():
        raise RuntimeError("nope")

    run_in_background(boom)  # must not raise


@pytest.mark.django_db
def test_threaded_dispatch_actually_runs(settings):
    import threading

    from apps.repos.dispatch import run_in_background

    settings.BACKGROUND_TASKS_EAGER = False
    done = threading.Event()

    thread = run_in_background(done.set)
    thread.join(timeout=5)

    assert done.is_set()


# ------------------------------------------------------------------- edge coverage


@pytest.mark.django_db
def test_a_user_with_no_personal_org_cannot_be_attributed_to():
    """Defensive: every user gets a personal org at signup, but the code must not
    assume one exists when attributing an installation."""
    from apps.accounts.models import Membership, User

    user = User.objects.create(username="orgless", github_login="NivedhReddy2048")
    Membership.objects.filter(user=user).delete()

    installation = AppInstallation.objects.create(
        installation_id=INSTALLATION_ID, account_login="NivedhReddy2048"
    )

    assert tasks.resolve_organization(installation) is None


@pytest.mark.django_db
def test_ensure_repository_without_an_installation_returns_none():
    assert tasks.ensure_repository(payload(), None) is None


@pytest.mark.django_db
def test_ensure_repository_without_a_repo_id_returns_none(owner):
    installation = AppInstallation.objects.create(
        installation_id=INSTALLATION_ID, account_login="NivedhReddy2048"
    )
    body = payload()
    body["repository"].pop("id")

    assert tasks.ensure_repository(body, installation) is None


@pytest.mark.django_db
def test_pull_request_str(owner):
    with mock.patch.object(tasks.github_app, "create_issue_comment", return_value={"id": 1}):
        tasks.handle_webhook_event(store().pk)

    assert str(PullRequest.objects.get()) == "NivedhReddy2048/codesage-testbed#7"
