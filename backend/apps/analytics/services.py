"""Aggregations for the dashboard, over Review and ReviewFinding (spec section 14).

Definitions, kept here so the numbers mean one thing everywhere:

- A *completed* review is status `done`: a model answered. Degraded and failed
  reviews are counted separately and never contribute findings or latency, because
  "the change was not reviewed" must not drag an average down to look like speed.
- *Findings per PR* uses each PR's latest completed review in the window, so
  re-running a review does not double-count its findings.
- *Cost* is the estimate at paid-tier rates over every review in the window,
  failed ones included: a failed call still consumed input tokens.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.reviews.models import Review, ReviewFinding

COST_BASIS = "Estimated at paid-tier rates. CodeSage runs on free tiers, so actual spend is zero."


def overview(organization, days=30, repository_id=None):
    until = timezone.now()
    since = until - timedelta(days=days)

    reviews = Review.objects.filter(
        pull_request__repository__organization=organization, created_at__gte=since
    )
    if repository_id is not None:
        reviews = reviews.filter(pull_request__repository_id=repository_id)

    completed = reviews.filter(status=Review.Status.DONE)
    findings = ReviewFinding.objects.filter(review__in=completed)

    counts = reviews.aggregate(
        # Prefixed: an aggregate may not share a name with a model field.
        n_total=Count("id"),
        n_completed=Count("id", filter=Q(status=Review.Status.DONE)),
        n_degraded=Count("id", filter=Q(degraded=True)),
        n_failed=Count("id", filter=Q(status=Review.Status.FAILED, degraded=False)),
        n_fallback=Count("id", filter=Q(used_fallback=True)),
        cost_total=Sum("estimated_cost_inr"),
    )
    latency = completed.aggregate(avg=Avg("duration_ms"))["avg"]
    severity = findings.aggregate(
        total=Count("id"),
        blocking=Count("id", filter=Q(severity="blocking")),
        nit=Count("id", filter=Q(severity="nit")),
    )

    per_pr = _findings_per_pr(completed)
    cost_total = counts["cost_total"] or Decimal(0)

    return {
        "range": {"days": days, "since": since, "until": until},
        "cost_basis": COST_BASIS,
        "summary": {
            "prs_reviewed": len(per_pr),
            "reviews": counts["n_total"],
            "completed_reviews": counts["n_completed"],
            "degraded_reviews": counts["n_degraded"],
            "failed_reviews": counts["n_failed"],
            "fallback_reviews": counts["n_fallback"],
            "findings": severity["total"],
            "blocking": severity["blocking"],
            "nits": severity["nit"],
            "blocking_ratio": _ratio(severity["blocking"], severity["total"]),
            "avg_findings_per_pr": _ratio(sum(per_pr.values()), len(per_pr), places=2),
            "avg_latency_ms": round(latency) if latency is not None else None,
            "est_cost_inr_total": _money(cost_total),
            "est_cost_inr_avg": _money(cost_total / counts["n_total"])
            if counts["n_total"]
            else None,
        },
        "timeseries": _timeseries(reviews, findings, since, until),
        "by_category": _breakdown(findings, "category"),
        "by_agent": _breakdown(findings, "agent"),
    }


def _findings_per_pr(completed):
    """{pull_request_id: findings in its latest completed review}."""
    latest = {}
    rows = completed.annotate(n=Count("findings")).values("pull_request_id", "id", "n")
    for row in rows.order_by("pull_request_id", "created_at", "id"):
        latest[row["pull_request_id"]] = row["n"]
    return latest


def _timeseries(reviews, findings, since, until):
    """One row per day, zero-filled, so a chart's x-axis has no silent gaps."""
    by_day = {
        row["day"]: row
        for row in reviews.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(
            reviews=Count("id"),
            avg_latency_ms=Avg("duration_ms", filter=Q(status=Review.Status.DONE)),
            est_cost_inr=Sum("estimated_cost_inr"),
        )
    }
    finding_days = {
        row["day"]: row
        for row in findings.annotate(day=TruncDate("review__created_at"))
        .values("day")
        .annotate(
            findings=Count("id"),
            blocking=Count("id", filter=Q(severity="blocking")),
            nits=Count("id", filter=Q(severity="nit")),
        )
    }

    series = []
    day = since.date()
    while day <= until.date():
        row = by_day.get(day, {})
        found = finding_days.get(day, {})
        latency = row.get("avg_latency_ms")
        series.append(
            {
                "date": day.isoformat(),
                "reviews": row.get("reviews", 0),
                "findings": found.get("findings", 0),
                "blocking": found.get("blocking", 0),
                "nits": found.get("nits", 0),
                "avg_latency_ms": round(latency) if latency is not None else None,
                "est_cost_inr": _money(row.get("est_cost_inr") or Decimal(0)),
            }
        )
        day += timedelta(days=1)
    return series


def _breakdown(findings, field):
    rows = (
        findings.values(field)
        .annotate(count=Count("id"), blocking=Count("id", filter=Q(severity="blocking")))
        .order_by("-count", field)
    )
    return [
        {"key": row[field] or "other", "count": row["count"], "blocking": row["blocking"]}
        for row in rows
    ]


def _ratio(numerator, denominator, places=3):
    if not denominator:
        return None
    return round(numerator / denominator, places)


def _money(value):
    return str(Decimal(value).quantize(Decimal("0.0001")))
