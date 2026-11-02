"""The keep-warm schedule pings every 5 minutes from 08:00 to 23:55 IST, and never
outside that window.

Cron is written in UTC and IST is UTC+5:30, which is easy to get wrong by an hour
or by the half hour; a wrong window silently costs instance hours or lets
webhooks hit a sleeping service. This expands the workflow's cron lines and
compares them with the intended window.
"""

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "keep-warm.yml"
IST_OFFSET_MINUTES = 5 * 60 + 30


def expand(field, low, high):
    """The values one cron field matches: *, a, a-b, */n, a-b/n, comma lists."""
    values = set()
    for part in field.split(","):
        spec, _, step = part.partition("/")
        step = int(step) if step else 1
        if spec == "*":
            start, stop = low, high
        elif "-" in spec:
            start, stop = (int(x) for x in spec.split("-"))
        else:
            start = stop = int(spec)
        values.update(range(start, stop + 1, step))
    return values


def scheduled_ist_minutes():
    """Every minute of the day (IST, 0-1439) that some cron line fires on."""
    lines = re.findall(r'cron:\s*"([^"]+)"', WORKFLOW.read_text())
    assert lines, "no cron lines found"
    fired = set()
    for line in lines:
        minute, hour, day, month, weekday = line.split()
        assert (day, month, weekday) == ("*", "*", "*"), line
        for h in expand(hour, 0, 23):
            for m in expand(minute, 0, 59):
                fired.add((h * 60 + m + IST_OFFSET_MINUTES) % (24 * 60))
    return fired


def test_pings_every_five_minutes_from_0800_to_2355_ist_and_never_otherwise():
    expected = set(range(8 * 60, 24 * 60, 5))  # 08:00, 08:05, ..., 23:55 IST

    assert scheduled_ist_minutes() == expected


def test_the_awake_window_fits_the_free_hours_with_room_for_other_services():
    """Awake from the first ping to ~15 min after the last: about 16 h 10 min a day."""
    fired = sorted(scheduled_ist_minutes())
    awake_minutes = fired[-1] + 15 - fired[0]
    monthly_hours = awake_minutes * 31 / 60

    assert awake_minutes == 16 * 60 + 10
    assert round(monthly_hours) == 501
    assert monthly_hours < 750 - 200  # leaves ~249 h for the account's other services
