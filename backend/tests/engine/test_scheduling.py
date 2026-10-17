from datetime import UTC, datetime

import pytest

from orgraph.models import utcnow
from orgraph.scheduling import next_fire, validate_schedule

NOON = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)  # a Monday


@pytest.mark.parametrize("cron", ["* * * * *", "0 9 * * MON", "*/15 2-4 1,15 * *"])
def test_valid_cron(cron):
    validate_schedule(cron, "Europe/Berlin")


@pytest.mark.parametrize(
    "cron", ["", "* * * *", "* * * * * *", "61 * * * *", "every day", "@daily"]
)
def test_invalid_cron(cron):
    with pytest.raises(ValueError, match="cron"):
        validate_schedule(cron)


@pytest.mark.parametrize("tz", ["Mars/Olympus", "", "../etc/passwd"])
def test_invalid_timezone(tz):
    with pytest.raises(ValueError, match="timezone"):
        validate_schedule("* * * * *", tz)


def test_next_fire_is_strictly_after():
    assert next_fire("0 12 * * *", "UTC", NOON) == "2026-01-06T12:00:00.000Z"
    assert next_fire("*/5 * * * *", "UTC", NOON) == "2026-01-05T12:05:00.000Z"


def test_next_fire_evaluates_in_timezone():
    # 09:00 in New York (UTC-5 in January) is 14:00 UTC.
    assert next_fire("0 9 * * *", "America/New_York", NOON) == "2026-01-05T14:00:00.000Z"
    # 09:00 in Kolkata (UTC+5:30) already passed today, so it is tomorrow 03:30 UTC.
    assert next_fire("0 9 * * *", "Asia/Kolkata", NOON) == "2026-01-06T03:30:00.000Z"


def test_next_fire_across_dst_change():
    # Clocks in Berlin go forward on 2026-03-29; 09:00 local moves from 08:00Z to 07:00Z.
    before = datetime(2026, 3, 28, 12, 0, tzinfo=UTC)
    assert next_fire("0 9 * * *", "Europe/Berlin", before) == "2026-03-29T07:00:00.000Z"


def test_next_fire_defaults_to_now_and_sorts_with_utcnow():
    now = utcnow()
    upcoming = next_fire("* * * * *")
    assert upcoming > now
    assert len(upcoming) == len(now) and upcoming.endswith("Z")


def test_next_fire_rejects_bad_input():
    with pytest.raises(ValueError):
        next_fire("nope")
    with pytest.raises(ValueError):
        next_fire("* * * * *", "Nowhere/Land")
