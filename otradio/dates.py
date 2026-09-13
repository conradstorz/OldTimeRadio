"""Extract release dates from recording filenames."""

import re
from datetime import date

from dateutil.parser import parse as _parse_datetime

# Ordered alternation: the four-digit-year form is tried first, anchored to
# "19" because every recording in this library predates 2000. The old pattern
# put the six-digit form first, so "1953-09-13" matched only "1953-09-" and
# raised ParserError at startup.
#
# There is deliberately no trailing (?!\d) boundary: OTR filenames routinely
# glue an episode number to the date, as in "XMinusOne55-07-28011TheEmbassy",
# and a trailing boundary would reject those.
_DATE_PATTERN = re.compile(
    r"(?<!\d)(?:19\d{2}[-/]?\d{2}[-/]?\d{2}|\d{2}[-/]?\d{2}[-/]?\d{2})"
)


def parse_release_date(filename: str) -> date | None:
    """Return the broadcast date encoded in a filename, or None.

    Returns None when the filename carries no date, or carries something that
    looks like one but cannot be parsed. Never raises: an undated recording is
    still playable.
    """
    match = _DATE_PATTERN.search(filename)
    if match is None:
        return None

    try:
        parsed = _parse_datetime(match.group(0), yearfirst=True)
    except (ValueError, OverflowError):
        # dateutil's ParserError subclasses ValueError.
        return None

    if parsed.year > 1999:
        # dateutil resolves two-digit years into the 21st century.
        parsed = parsed.replace(year=parsed.year - 100)
    return parsed.date()


def decade_of(d: date) -> int:
    """Return the decade a date falls in, as its starting year (1947 -> 1940)."""
    return d.year - d.year % 10
