import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from gmu_courses import ical
from gmu_courses.models import Section

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def cs_payload():
    return json.loads((FIXTURES / "cs_search_202670.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def cs_p100_payload():
    return json.loads((FIXTURES / "cs_search_p100.json").read_text("utf-8"))


@pytest.fixture
def in_person_section(cs_payload):
    # First section in the fixture is CS 100, TR 09:00-10:15.
    return Section.from_json(cs_payload["data"][0])


@pytest.fixture
def async_section(cs_p100_payload):
    for d in cs_p100_payload["data"]:
        if "Async" in (d.get("instructionalMethodDescription") or ""):
            return Section.from_json(d)
    pytest.fail("fixture should contain an async section")


def test_calendar_envelope():
    cal = ical.build_calendar([])
    assert cal.startswith("BEGIN:VCALENDAR\r\n")
    assert cal.endswith("END:VCALENDAR\r\n")
    assert "VERSION:2.0" in cal
    assert "PRODID:" in cal
    assert "BEGIN:VTIMEZONE" in cal and "TZID:America/New_York" in cal


def test_in_person_section_produces_event(in_person_section):
    cal = ical.build_calendar([in_person_section])
    assert cal.count("BEGIN:VEVENT") == 1
    # TR meeting at 09:00-10:15
    assert "BYDAY=TU,TH" in cal
    assert "DTSTART;TZID=America/New_York" in cal
    assert "T090000" in cal
    assert "T101500" in cal
    assert f"UID:{in_person_section.crn}-meeting0@gmu-courses" in cal
    assert in_person_section.title in cal


def test_async_section_produces_no_event(async_section):
    cal = ical.build_calendar([async_section])
    assert cal.count("BEGIN:VEVENT") == 0


def test_dtstart_lands_on_a_byday(in_person_section):
    """The first occurrence must be a Tue or Thu (the BYDAY values)."""
    cal = ical.build_calendar([in_person_section])
    # Pull the DTSTART line — "DTSTART;TZID=America/New_York:20260825T090000"
    line = next(line for line in cal.splitlines() if line.startswith("DTSTART;"))
    date_str = line.split(":")[1][:8]  # YYYYMMDD
    dt = datetime.strptime(date_str, "%Y%m%d")
    # Tuesday=1, Thursday=3
    assert dt.weekday() in (1, 3), f"first occurrence {dt:%A} isn't Tue or Thu"


def test_ical_escape():
    assert ical._ical_escape("a,b") == "a\\,b"
    assert ical._ical_escape("a;b") == "a\\;b"
    assert ical._ical_escape("a\\b") == "a\\\\b"
    assert ical._ical_escape("a\nb") == "a\\nb"


def test_fold_long_line():
    # 80-char line should fold to multiple ≤75-octet lines with leading-space continuation.
    line = "X" * 80
    folded = ical._fold(line)
    assert "\r\n " in folded
    for chunk in folded.split("\r\n"):
        assert len(chunk) <= 75


def test_short_line_not_folded():
    assert ical._fold("BEGIN:VEVENT") == "BEGIN:VEVENT"


def test_until_uses_term_end(in_person_section):
    cal = ical.build_calendar([in_person_section])
    # Fixture term is Fall 2026, ends 12/16/2026.
    assert "UNTIL=20261216" in cal
