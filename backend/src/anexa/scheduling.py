from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter


def validate_schedule(cron: str, timezone: str = "UTC") -> None:
    """Raise ValueError if the cron expression or timezone is unusable."""
    if len(cron.split()) != 5 or not croniter.is_valid(cron):
        raise ValueError(f"invalid cron expression: {cron!r} (expected 5 fields)")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone: {timezone!r}") from exc


def next_fire(cron: str, timezone: str = "UTC", after: datetime | None = None) -> str:
    """Next time `cron` fires strictly after `after` (default now), evaluated
    in `timezone`, returned as a UTC ISO string comparable with models.utcnow()."""
    validate_schedule(cron, timezone)
    base = (after or datetime.now(UTC)).astimezone(ZoneInfo(timezone))
    nxt: datetime = croniter(cron, base).get_next(datetime)
    return nxt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
