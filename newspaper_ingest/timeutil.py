"""
Date and time helpers. All run-time stamps use US Eastern time, not the
machine's own timezone (the GitHub Actions runners are on UTC).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

EASTERN_TZ = ZoneInfo("America/New_York")


def now_eastern():
    """The current moment, in US Eastern time."""
    return datetime.now(EASTERN_TZ)


def format_eastern_timestamp(dt=None):
    """'2026-10-17 02:07:32 PM EDT' - the display format for every run-time
    stamp. Pass a specific now_eastern() result to keep several timestamps
    in one run in sync; omit it to use right now."""
    if dt is None:
        dt = now_eastern()
    return dt.strftime("%Y-%m-%d %I:%M:%S %p %Z")


def format_date_long(date_iso):
    """'1885-01-16' -> 'Jan 16, 1885' (no leading zero on the day)."""
    date_obj = datetime.strptime(date_iso, "%Y-%m-%d")
    return f"{date_obj.strftime('%b')} {date_obj.day}, {date_obj.year}"


def parse_iso_date_or_none(date_text):
    """A datetime for a valid 'YYYY-MM-DD' string, otherwise None."""
    try:
        return datetime.strptime(date_text, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
