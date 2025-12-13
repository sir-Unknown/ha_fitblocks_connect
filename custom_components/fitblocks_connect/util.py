"""Helpers for the Fitblocks Connect integration."""

from __future__ import annotations

from datetime import datetime

from homeassistant.util import dt as dt_util


def parse_fitblocks_datetime(value: str) -> datetime | None:
    """Parse Fitblocks datetime strings and return them in UTC.

    The API sometimes returns naive datetimes in the format
    `YYYY-MM-DD HH:MM:SS`. These are interpreted in the Home Assistant default
    timezone before converting to UTC.
    """
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)

    return dt_util.as_utc(parsed)

