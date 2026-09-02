from datetime import date

import pytest

from otradio.dates import parse_release_date


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Gunsmoke 52-07-26 (014) Gentleman's Disagreement.mp3", date(1952, 7, 26)),
        ("Jb1953-09-13BackFromVacationInHawaii.mp3", date(1953, 9, 13)),
        ("Dragnet_51-07-26_111_The_Big_Late_Script.mp3", date(1951, 7, 26)),
        ("Suspense 470724 255 Murder by an Expert (128-44) 27864 29m02s.mp3", date(1947, 7, 24)),
        ("XMinusOne55-07-28011TheEmbassy.mp3", date(1955, 7, 28)),
        ("Some Commercial 19520726 spot.mp3", date(1952, 7, 26)),
        ("1959/08/02 Have Gun Will Travel.mp3", date(1959, 8, 2)),
    ],
)
def test_parses_known_filename_shapes(filename, expected):
    assert parse_release_date(filename) == expected


def test_four_digit_year_does_not_crash():
    """Regression: the old regex matched '1953-09-' and raised ParserError at startup."""
    assert parse_release_date("Jb1953-09-13BackFromVacationInHawaii.mp3") == date(1953, 9, 13)


@pytest.mark.parametrize(
    "filename",
    [
        "No date here at all.mp3",
        "Episode 128-44 27864 29m02s.mp3",
        "",
    ],
)
def test_returns_none_when_no_date_present(filename):
    assert parse_release_date(filename) is None


@pytest.mark.parametrize(
    "filename",
    [
        "Show 1953-0913 odd.mp3",
        "Show 999999 nope.mp3",
    ],
)
def test_returns_none_when_match_is_unparseable(filename):
    """Matches the pattern but dateutil rejects it. Must degrade, not raise."""
    assert parse_release_date(filename) is None


def test_two_digit_year_is_forced_into_the_twentieth_century():
    assert parse_release_date("Show 52-07-26.mp3").year == 1952
