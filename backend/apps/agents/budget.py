"""A token budget for one review, per model.

Groq's live headers report **8000 tokens per minute**, and the bucket is per model.
This was first read as shared, because calling `gpt-oss-120b` and then `gpt-oss-20b`
once returned similar `remaining` values. Eval DEV run 1 measured it over 88 calls:
in the same reviews gpt-oss-20b fell to 1,447 tokens remaining while gpt-oss-120b
never went below 6,016.

So each model gets its own budget. Three agents on the cheap model and two on the
primary model at ~1300 tokens each would sit right on a shared ceiling, and a review
that simply fired every agent would intermittently 429 partway through and produce a
half-finished result. Budgeting up front is what turns that into a predictable,
explainable degradation instead.

The rule: spend on the highest-priority agents first, skip the rest, and say so in
the comment. A review missing its test-coverage pass is useful; a review that died
at agent four is not.
"""

import logging
import threading
from collections import defaultdict

logger = logging.getLogger(__name__)

# Rough but adequate. Tokenisers vary, and the point is to stay clear of the
# ceiling rather than to predict usage exactly; ~4 characters per token is the usual
# English/code approximation and errs slightly high for code, which is the safe
# direction.
CHARS_PER_TOKEN = 4


def estimate_tokens(text):
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


class TokenBudget:
    """Tracks spend across one review and decides what can still run.

    `total_tokens` is the budget of each pool. A pool is a model: agents on different
    models draw on different per-minute buckets. Calls that name no pool share one.
    The parallel agents reserve from their own threads, so changes are locked.
    """

    def __init__(self, total_tokens):
        self.total = max(0, total_tokens)
        self._spent = defaultdict(int)
        self.skipped = []
        self._lock = threading.Lock()

    @property
    def spent(self):
        return sum(self._spent.values())

    @property
    def remaining(self):
        """What is left in the default pool."""
        return self.remaining_in("")

    def remaining_in(self, pool):
        return max(0, self.total - self._spent[pool])

    def can_afford(self, estimated, pool=""):
        """Whether an agent's expected cost still fits."""
        return estimated <= self.remaining_in(pool)

    def reserve(self, agent, estimated, pool=""):
        """Claim budget for an agent, or record why it was skipped.

        Reserving before the call rather than accounting after it is deliberate:
        the decision to skip has to be made while there is still budget left to
        protect for the agents that matter more.
        """
        with self._lock:
            if not self.can_afford(estimated, pool):
                reason = (
                    f"token budget exhausted ({self.remaining_in(pool)} of {self.total} left"
                    f"{f' for {pool}' if pool else ''}, needed about {estimated})"
                )
                self.skipped.append((agent, reason))
                logger.info("Skipping %s: %s", agent, reason)
                return False
            self._spent[pool] += estimated
            return True

    def record_actual(self, estimated, actual, pool=""):
        """Replace an estimate with the real usage once a call returns.

        Without this the budget drifts from reality across a review - usually
        pessimistically, which would skip agents that would have fitted.
        """
        with self._lock:
            self._spent[pool] = max(0, self._spent[pool] - estimated + max(0, actual))

    def skip(self, agent, reason):
        self.skipped.append((agent, reason))
