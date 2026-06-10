import json
from pathlib import Path

import pytest

from gmu_courses.models import Section

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def cs_payload():
    return json.loads((FIXTURES / "cs_search_202670.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def cs_p100_payload():
    return json.loads((FIXTURES / "cs_search_p100.json").read_text("utf-8"))


def test_parses_all_sections(cs_payload):
    sections = [Section.from_json(d) for d in cs_payload["data"]]
    assert len(sections) == 50
    assert all(s.crn and s.subject == "CS" for s in sections)


def test_in_person_lecture_fields(cs_payload):
    # First section in the fixture is CS 100 — known TR 09:00-10:15 in-person.
    s = Section.from_json(cs_payload["data"][0])
    assert s.subject_course == "CS 100"
    assert s.title == "Principles of Computing"
    assert s.modality == "in-person"
    assert s.credits == 3.0
    assert s.instructors and "Abdelmoumin" in s.instructors[0]
    assert len(s.meetings) == 1
    m = s.meetings[0]
    assert m.days == frozenset("TR")
    assert m.begin and m.begin.hour == 9 and m.begin.minute == 0
    assert m.end and m.end.hour == 10 and m.end.minute == 15
    assert m.schedule_type == "LEC"
    assert not m.is_async


def test_async_section(cs_p100_payload):
    async_secs = [
        Section.from_json(d)
        for d in cs_p100_payload["data"]
        if "Async" in (d.get("instructionalMethodDescription") or "")
    ]
    assert async_secs, "fixture should contain at least one async section"
    s = async_secs[0]
    assert s.modality == "online"
    assert all(m.is_async for m in s.meetings)
    assert all(not m.days for m in s.meetings)


def test_open_seats_property(cs_payload):
    sections = [Section.from_json(d) for d in cs_payload["data"]]
    full = [s for s in sections if s.seats_available == 0]
    open_ = [s for s in sections if s.seats_available > 0]
    for s in full:
        assert not s.is_open
    for s in open_:
        assert s.is_open
