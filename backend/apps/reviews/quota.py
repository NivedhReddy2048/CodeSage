"""Daily review caps for the public free demo.

The production GitHub App can be installed by any account, and every review
spends a shared free-tier quota (Groq's daily tokens, phase 8's capacity notes).
So reviews are capped per UTC day: per workspace, and across all of them. Both
caps are env settings, lowered on evaluation days when the eval needs the quota.

A refused review is not dropped. The PR gets one comment saying so, the app shows
a banner, and the missed-webhook catch-up (apps/repos/catchup.py) reviews the PR's
head after the reset. The operator's `manage.py rerun_review` is not capped.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.reviews.models import Review

# Any constant works; it names the one lock every review admission takes, so two
# webhooks arriving together cannot both see "4 of 5" and both start.
ADMISSION_LOCK_KEY = 7_207_001


@dataclass(frozen=True)
class Denial:
    """Which cap refused the review, and when it lifts."""

    scope: str  # "workspace" or "global"
    used: int
    limit: int
    resets_at: datetime

    @property
    def detail(self):
        if self.scope == "workspace":
            return f"This workspace has used its {self.limit} free reviews for today."
        return f"The demo's shared limit of {self.limit} reviews for today is used up."

    @property
    def message(self):
        return f"Daily free-demo limit reached. {self.detail} It resets at 00:00 UTC (05:30 IST)."


def day_start(now=None):
    now = now or timezone.now()
    return datetime.combine(now.astimezone(UTC).date(), time.min, tzinfo=UTC)


def resets_at(now=None):
    return day_start(now) + timedelta(days=1)


def seconds_until_reset(now=None):
    now = now or timezone.now()
    return max(60, int((resets_at(now) - now).total_seconds()))


def reviews_today(organization=None):
    reviews = Review.objects.filter(created_at__gte=day_start())
    if organization is not None:
        reviews = reviews.filter(pull_request__repository__organization=organization)
    return reviews.count()


def denial(organization):
    """The cap that would refuse a review for `organization` now, or None."""
    workspace_limit = settings.DEMO_REVIEWS_PER_WORKSPACE_PER_DAY
    global_limit = settings.DEMO_REVIEWS_PER_DAY
    used = reviews_today(organization)
    if used >= workspace_limit:
        return Denial("workspace", used, workspace_limit, resets_at())
    used_everywhere = reviews_today()
    if used_everywhere >= global_limit:
        return Denial("global", used_everywhere, global_limit, resets_at())
    return None


@contextmanager
def admission(organization):
    """Yield None if a review may start, else the Denial.

    Create the Review INSIDE the block: the count and the insert share one
    transaction under an advisory lock, so concurrent admissions queue on it. The
    lock is transaction-scoped, which Neon's PgBouncer (transaction mode) keeps.
    Do no network I/O inside the block; it holds the lock.
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [ADMISSION_LOCK_KEY])
        yield denial(organization)


def usage(organization):
    """Today's numbers for the app's banner and the dashboard's demo note."""
    workspace_limit = settings.DEMO_REVIEWS_PER_WORKSPACE_PER_DAY
    global_limit = settings.DEMO_REVIEWS_PER_DAY
    used = reviews_today(organization) if organization is not None else 0
    used_everywhere = reviews_today()
    scope = None
    if organization is not None and used >= workspace_limit:
        scope = "workspace"
    elif used_everywhere >= global_limit:
        scope = "global"
    return {
        "workspace": {"used": used, "limit": workspace_limit},
        "global": {"used": used_everywhere, "limit": global_limit},
        "limited": scope is not None,
        "scope": scope,
        "resets_at": resets_at(),
    }
