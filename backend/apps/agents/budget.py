"""A token budget for one review.

Groq's live headers report **8000 tokens per minute**, and the bucket appears to be
shared across models rather than per-model: calling `gpt-oss-120b` and then
`gpt-oss-20b` returned identical `remaining` values and the same reset window.

Six agents at ~1300 tokens each would sit right on that ceiling, so a review that
simply fired every agent would intermittently 429 partway through and produce a
half-finished result. Budgeting up front is what turns that into a predictable,
explainable degradation instead.

The rule: spend on the highest-priority agents first, skip the rest, and say so in
the comment. A review missing its test-coverage pass is useful; a review that died
at agent four is not.
"""

import logging

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
    """Tracks spend across one review and decides what can still run."""

    def __init__(self, total_tokens):
        self.total = max(0, total_tokens)
        self.spent = 0
        self.skipped = []

    @property
    def remaining(self):
        return max(0, self.total - self.spent)

    def can_afford(self, estimated):
        """Whether an agent's expected cost still fits."""
        return estimated <= self.remaining

    def reserve(self, agent, estimated):
        """Claim budget for an agent, or record why it was skipped.

        Reserving before the call rather than accounting after it is deliberate:
        the decision to skip has to be made while there is still budget left to
        protect for the agents that matter more.
        """
        if not self.can_afford(estimated):
            reason = (
                f"token budget exhausted ({self.remaining} of {self.total} left, "
                f"needed about {estimated})"
            )
            self.skipped.append((agent, reason))
            logger.info("Skipping %s: %s", agent, reason)
            return False
        self.spent += estimated
        return True

    def record_actual(self, estimated, actual):
        """Replace an estimate with the real usage once a call returns.

        Without this the budget drifts from reality across a review - usually
        pessimistically, which would skip agents that would have fitted.
        """
        self.spent = max(0, self.spent - estimated + max(0, actual))

    def skip(self, agent, reason):
        self.skipped.append((agent, reason))
