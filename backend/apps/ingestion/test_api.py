"""Tests for the ingestion task, status endpoint and re-index endpoint."""

from unittest import mock

import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Membership, Organization
from apps.accounts.services import get_or_create_user_from_github
from apps.ingestion.models import CodeChunk, IngestionJob
from apps.ingestion.services import start_ingestion
from apps.repos.models import AppInstallation, Repository


def make_user(github_id=1, login="owner"):
    user, _ = get_or_create_user_from_github(
        {"id": github_id, "login": login, "name": "", "email": "", "avatar_url": ""}
    )
    return user


def auth(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def owner(db):
    return make_user()


@pytest.fixture
def repository(owner):
    installation = AppInstallation.objects.create(installation_id=999, account_login="owner")
    return Repository.objects.create(
        organization=owner.memberships.get().organization,
        installation=installation,
        github_id=1,
        full_name="owner/repo",
        owner="owner",
        name="repo",
        default_branch="main",
    )


@pytest.fixture(autouse=True)
def no_real_task():
    """Never let a test reach a broker or the real indexer."""
    with mock.patch("apps.ingestion.tasks.index_repository_task.delay") as delay:
        yield delay


# ------------------------------------------------------------------- queueing


@pytest.mark.django_db
def test_start_ingestion_creates_a_pending_job_and_queues_it(repository, no_real_task):
    job, started = start_ingestion(repository)

    assert started is True
    assert job.status == IngestionJob.Status.PENDING
    no_real_task.assert_called_once_with(job.pk)


@pytest.mark.django_db
def test_a_second_job_is_not_queued_while_one_is_running(repository, no_real_task):
    """Two concurrent runs would race on the indexer's delete-then-insert."""
    first, _ = start_ingestion(repository)
    no_real_task.reset_mock()

    second, started = start_ingestion(repository)

    assert started is False
    assert second.pk == first.pk
    no_real_task.assert_not_called()


@pytest.mark.django_db
def test_a_new_job_is_queued_once_the_previous_finished(repository):
    first, _ = start_ingestion(repository)
    first.status = IngestionJob.Status.DONE
    first.save()

    second, started = start_ingestion(repository)

    assert started is True
    assert second.pk != first.pk


@pytest.mark.django_db
def test_a_broker_failure_marks_the_job_failed_rather_than_500ing(repository):
    with mock.patch(
        "apps.ingestion.tasks.index_repository_task.delay",
        side_effect=OSError("broker unreachable"),
    ):
        job, started = start_ingestion(repository)

    assert started is False
    assert job.status == IngestionJob.Status.FAILED
    assert "broker unreachable" in job.error


# ------------------------------------------------------------- connect trigger


@pytest.mark.django_db
def test_connecting_a_repository_starts_indexing(owner, no_real_task):
    """A newly connected repo should be useful without a second action."""
    AppInstallation.objects.create(installation_id=42, account_login="owner")
    remote = {
        "id": 555,
        "full_name": "owner/new",
        "name": "new",
        "owner": {"login": "owner"},
        "default_branch": "main",
        "private": False,
    }

    with mock.patch(
        "apps.repos.views.github_app.list_installation_repositories",
        return_value=[remote],
    ):
        response = auth(owner).post(
            reverse("repository-connect"), {"github_id": 555}, format="json"
        )

    assert response.status_code == 201
    assert IngestionJob.objects.filter(repository__github_id=555).exists()
    no_real_task.assert_called_once()


@pytest.mark.django_db
def test_reconnecting_does_not_start_a_second_index(owner, no_real_task):
    AppInstallation.objects.create(installation_id=42, account_login="owner")
    remote = {
        "id": 555,
        "full_name": "owner/new",
        "name": "new",
        "owner": {"login": "owner"},
        "default_branch": "main",
        "private": False,
    }
    client = auth(owner)

    with mock.patch(
        "apps.repos.views.github_app.list_installation_repositories",
        return_value=[remote],
    ):
        client.post(reverse("repository-connect"), {"github_id": 555}, format="json")
        client.post(reverse("repository-connect"), {"github_id": 555}, format="json")

    assert IngestionJob.objects.count() == 1


# ----------------------------------------------------------------- status API


@pytest.mark.django_db
def test_status_requires_authentication(repository):
    url = reverse("ingestion-status", args=[repository.pk])

    assert APIClient().get(url).status_code == 401


@pytest.mark.django_db
def test_status_reports_no_job_before_indexing(owner, repository):
    response = auth(owner).get(reverse("ingestion-status", args=[repository.pk]))

    assert response.status_code == 200
    body = response.json()
    assert body["job"] is None
    assert body["chunk_count"] == 0


@pytest.mark.django_db
def test_status_reports_progress_counters(owner, repository):
    IngestionJob.objects.create(
        repository=repository,
        status=IngestionJob.Status.RUNNING,
        files_discovered=20,
        files_indexed=12,
        files_skipped=8,
        chunks_created=40,
        chunks_reused=35,
        embedding_api_calls=2,
    )

    body = auth(owner).get(reverse("ingestion-status", args=[repository.pk])).json()

    job = body["job"]
    assert job["status"] == "running"
    assert job["is_active"] is True
    assert job["files_indexed"] == 12
    assert job["chunks_reused"] == 35
    assert job["embedding_api_calls"] == 2


@pytest.mark.django_db
def test_status_counts_stored_chunks_and_files(owner, repository):
    for index in range(3):
        CodeChunk.objects.create(
            repository=repository,
            file_path="app/a.py" if index < 2 else "app/b.py",
            symbol=f"f{index}",
            line_start=index * 10 + 1,
            line_end=index * 10 + 5,
            content="x = 1",
            content_hash=f"hash{index}",
        )

    body = auth(owner).get(reverse("ingestion-status", args=[repository.pk])).json()

    assert body["chunk_count"] == 3
    assert body["indexed_files"] == 2


@pytest.mark.django_db
def test_a_finished_job_is_not_active(owner, repository):
    IngestionJob.objects.create(repository=repository, status=IngestionJob.Status.DONE)

    body = auth(owner).get(reverse("ingestion-status", args=[repository.pk])).json()

    assert body["job"]["is_active"] is False


@pytest.mark.django_db
def test_another_organizations_repository_is_invisible(repository):
    other = make_user(github_id=2, login="someone-else")

    response = auth(other).get(reverse("ingestion-status", args=[repository.pk]))

    assert response.status_code == 404


# ---------------------------------------------------------------- reindex API


@pytest.mark.django_db
def test_reindex_queues_a_job(owner, repository, no_real_task):
    response = auth(owner).post(reverse("repository-reindex", args=[repository.pk]))

    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    no_real_task.assert_called_once()


@pytest.mark.django_db
def test_reindex_while_running_returns_the_existing_job(owner, repository, no_real_task):
    existing = IngestionJob.objects.create(
        repository=repository, status=IngestionJob.Status.RUNNING
    )
    no_real_task.reset_mock()

    response = auth(owner).post(reverse("repository-reindex", args=[repository.pk]))

    assert response.status_code == 200
    assert response.json()["id"] == existing.pk
    no_real_task.assert_not_called()


@pytest.mark.django_db
def test_a_member_cannot_trigger_a_reindex(repository, no_real_task):
    """Indexing spends Gemini quota, so it is an owner/admin action."""
    member = make_user(github_id=3, login="member")
    Membership.objects.filter(user=member).delete()
    Membership.objects.create(
        user=member,
        organization=repository.organization,
        role=Membership.Role.MEMBER,
    )

    response = auth(member).post(reverse("repository-reindex", args=[repository.pk]))

    assert response.status_code == 403
    no_real_task.assert_not_called()


@pytest.mark.django_db
def test_an_admin_can_trigger_a_reindex(repository, no_real_task):
    admin = make_user(github_id=4, login="admin")
    Membership.objects.filter(user=admin).delete()
    Membership.objects.create(
        user=admin, organization=repository.organization, role=Membership.Role.ADMIN
    )

    response = auth(admin).post(reverse("repository-reindex", args=[repository.pk]))

    assert response.status_code == 202


@pytest.mark.django_db
def test_reindexing_another_organizations_repository_is_a_404(repository, no_real_task):
    outsider = make_user(github_id=5, login="outsider")
    Organization.objects.create(name="Theirs", slug="theirs")

    response = auth(outsider).post(reverse("repository-reindex", args=[repository.pk]))

    assert response.status_code == 404
    no_real_task.assert_not_called()


# --------------------------------------------------------------------- the task


@pytest.mark.django_db
def test_the_task_runs_the_indexer(repository):
    from apps.ingestion.tasks import index_repository_task

    job = IngestionJob.objects.create(repository=repository)

    with mock.patch("apps.ingestion.tasks.index_repository") as index:
        index.return_value = mock.Mock(chunks_created=5, chunks_reused=2)
        result = index_repository_task(job.pk)

    index.assert_called_once()
    assert result["job_id"] == job.pk


@pytest.mark.django_db
def test_the_task_tolerates_a_deleted_job():
    """A job can be removed between queueing and the worker picking it up."""
    from apps.ingestion.tasks import index_repository_task

    assert index_repository_task(999999) is None
