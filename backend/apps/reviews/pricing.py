"""Turn token counts into an estimated cost (spec section 14).

"Estimated" is load-bearing. The project runs entirely on free tiers, so the real
spend is zero; this is a projection of what the same work would cost on a paid plan.
Every surface that displays it says so, because presenting a projection as a bill
would be dishonest.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings

PER_MILLION = Decimal(1_000_000)


def price_for(model):
    """Per-million-token prices for a model, or None when it is not in the table.

    Returns None rather than guessing: a made-up price shown to three decimal places
    looks exactly as authoritative as a real one.
    """
    entry = settings.LLM_PRICING.get(model)
    if not entry:
        return None
    return Decimal(str(entry["input"])), Decimal(str(entry["output"]))


def estimate_usd(calls):
    """Total USD across a set of calls, each with model and token counts.

    Counts failed calls too: a retry that produced nothing still consumed input
    tokens, and hiding that would understate what the free tier is absorbing.
    """
    total = Decimal(0)

    for call in calls:
        prices = price_for(call.model)
        if prices is None:
            continue
        input_price, output_price = prices
        total += (Decimal(call.input_tokens or 0) / PER_MILLION) * input_price
        total += (Decimal(call.output_tokens or 0) / PER_MILLION) * output_price

    return total.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def to_inr(usd):
    rate = Decimal(str(settings.USD_TO_INR))
    return (Decimal(usd) * rate).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def unpriced_models(calls):
    """Models used but absent from the price table, so the gap can be disclosed."""
    return sorted({call.model for call in calls if call.model and price_for(call.model) is None})


def format_footer(duration_ms, cost_inr, model, used_fallback, unpriced=()):
    """The one-line summary appended to the PR comment.

    Example: "Reviewed in 12 s - est. Rs 0.40 at paid-tier rates - openai/gpt-oss-120b"
    """
    seconds = max(duration_ms, 0) / 1000
    duration = f"{seconds:.0f} s" if seconds >= 1 else f"{duration_ms} ms"

    parts = [f"Reviewed in {duration}"]

    if unpriced:
        # Say so rather than printing a confident 0.00 that is really "unknown".
        parts.append(f"cost unknown (no price listed for {', '.join(unpriced)})")
    else:
        parts.append(f"est. ₹{cost_inr:.2f} at paid-tier rates")

    if model:
        parts.append(f"`{model}`" + (" (fallback)" if used_fallback else ""))

    return " · ".join(parts)
