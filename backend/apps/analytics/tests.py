"""Dashboard aggregates against hand-computed fixture data."""

from decimal import Decimal

import pytest

from apps.reviews.models import Review
from tests import factories


@pytest.fixture
def world(db):
    alice, org_a = factories.user("alice")
    bob, org_b = factories.user("bob")
    repo_a = factories.repository(org_a, "alice/app")
    repo_a2 = factories.repository(org_a, "alice/lib")
    repo_b = factories.repository(org_b, "bob/app")

    pr1 = factories.pull_request(repo_a, 1)
    pr2 = factories.pull_request(repo_a2, 2)

    # PR 1 reviewed twice: only the latest completed review counts for "per PR".
    factories.review(
        pr1,
        duration_ms=4000,
        cost_inr="0.1000",
        findings=[("blocking", "security", "security")] * 3,
        days_ago=3,
    )
    factories.review(
        pr1,
        duration_ms=6000,
        cost_inr="0.1000",
        findings=[("blocking", "security", "security"), ("nit", "style", "test_coverage")],
        days_ago=1,
    )
    factories.review(
        pr2,
        duration_ms=8000,
        cost_inr="0.0500",
        findings=[("nit", "testing", "test_coverage")] * 4,
    )
    # Degraded and failed: counted, but no findings and no latency.
    factories.review(pr2, Review.Status.FAILED, degraded=True, duration_ms=900, cost_inr="0.0100")
    factories.review(pr2, Review.Status.FAILED, duration_ms=100, cost_inr="0")
    # Outside the window.
    factories.review(pr2, findings=[("blocking", "security", "security")] * 9, days_ago=60)
    # Another tenant: must never be counted.
    factories.review(
        factories.pull_request(repo_b),
        duration_ms=99000,
        cost_inr="9.0000",
        findings=[("blocking", "security", "security")] * 7,
    )
    return locals()


def get(world, query=""):
    response = factories.client(world["alice"]).get(f"/api/analytics/overview/{query}")
    assert response.status_code == 200
    return response.data


def test_summary_kpis(world):
    summary = get(world)["summary"]

    assert summary["reviews"] == 5
    assert summary["completed_reviews"] == 3
    assert summary["degraded_reviews"] == 1
    assert summary["failed_reviews"] == 1
    assert summary["prs_reviewed"] == 2
    # Findings over the three completed reviews: 3 + 2 + 4.
    assert (summary["findings"], summary["blocking"], summary["nits"]) == (9, 4, 5)
    assert summary["blocking_ratio"] == round(4 / 9, 3)
    # Per PR uses each PR's latest completed review: PR1 -> 2, PR2 -> 4.
    assert summary["avg_findings_per_pr"] == 3.0
    # ...and so does the card's breakdown: PR1's latest (1 blocking, 1 nit) + PR2's
    # (4 nits). The all-reviews totals above count PR1's first review too.
    assert (summary["latest_review_blocking"], summary["latest_review_nits"]) == (1, 5)
    # Completed reviews only: (4000 + 6000 + 8000) / 3.
    assert summary["avg_latency_ms"] == 6000
    # Every review in the window: 0.10 + 0.10 + 0.05 + 0.01 + 0.
    assert Decimal(summary["est_cost_inr_total"]) == Decimal("0.2600")
    assert Decimal(summary["est_cost_inr_avg"]) == Decimal("0.0520")


def test_the_cost_is_labelled_an_estimate(world):
    assert "paid-tier" in get(world)["cost_basis"]


def test_breakdowns_by_category_and_agent(world):
    data = get(world)

    assert data["by_category"] == [
        {"key": "security", "count": 4, "blocking": 4},
        {"key": "testing", "count": 4, "blocking": 0},
        {"key": "style", "count": 1, "blocking": 0},
    ]
    assert data["by_agent"] == [
        {"key": "test_coverage", "count": 5, "blocking": 0},
        {"key": "security", "count": 4, "blocking": 4},
    ]


def test_the_timeseries_is_zero_filled_and_daily(world):
    series = get(world, "?days=7")["timeseries"]

    assert len(series) == 8  # seven days back to today, inclusive
    assert sum(day["reviews"] for day in series) == 5
    assert sum(day["findings"] for day in series) == 9
    assert any(day["reviews"] == 0 and day["est_cost_inr"] == "0.0000" for day in series)


def test_a_repository_filter_narrows_everything(world):
    summary = get(world, f"?repository={world['repo_a'].pk}")["summary"]

    assert (summary["reviews"], summary["findings"], summary["prs_reviewed"]) == (2, 5, 1)


def test_the_spec_per_repository_path_is_the_same_view(world):
    response = factories.client(world["alice"]).get(
        f"/api/repos/{world['repo_a'].pk}/findings/analytics/"
    )

    assert response.status_code == 200
    assert response.data["summary"]["reviews"] == 2


def test_another_organisations_repository_is_not_found(world):
    api = factories.client(world["alice"])

    assert api.get(f"/api/analytics/overview/?repository={world['repo_b'].pk}").status_code == 404
    assert api.get(f"/api/repos/{world['repo_b'].pk}/findings/analytics/").status_code == 404


def test_another_tenant_sees_only_their_own_numbers(world):
    summary = factories.client(world["bob"]).get("/api/analytics/overview/").data["summary"]

    assert (summary["reviews"], summary["findings"]) == (1, 7)


def test_an_empty_organisation_gets_zeros_not_errors(db):
    newcomer, _ = factories.user("newcomer")

    summary = factories.client(newcomer).get("/api/analytics/overview/").data["summary"]

    assert summary["reviews"] == 0
    assert summary["avg_latency_ms"] is None
    assert summary["avg_findings_per_pr"] is None
    assert summary["est_cost_inr_avg"] is None
