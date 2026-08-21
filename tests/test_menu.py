"""Tests for the menu's pure helpers.

The prompt flow itself needs a TTY and can't be driven here, but everything
between "user answered" and "results rendered" is ordinary logic.
"""
from datetime import time

import pytest

from gmu_courses import menu
from gmu_courses.models import MeetingTime, Section


def _section(crn="00001", course="211", days="MW", begin=(10, 0), end=(11, 15),
             modality="in-person", seats=10, instructors=("Smith, Ann",)):
    mt = MeetingTime(
        days=frozenset(days),
        begin=time(*begin) if begin else None,
        end=time(*end) if end else None,
        building="Planetary Hall",
        room="131",
        schedule_type="LEC",
    )
    return Section(
        crn=crn, subject="CS", course_number=course, title="Test Course",
        credits=3.0, instructors=instructors, seats_available=seats,
        seats_total=30, waitlist_count=0, meetings=(mt,), modality=modality,
        instructional_method_desc=None, schedule_type_desc="Lecture",
        campus="Fairfax", section_number="001", raw={},
    )


def _params(**overrides):
    base = {
        "subject": "CS", "course_number": None, "keyword": None,
        "flags": set(), "days_spec": None, "after_spec": None, "before_spec": None,
    }
    base.update(overrides)
    return base


def test_blank_to_none():
    assert menu._blank_to_none("  ") is None
    assert menu._blank_to_none("") is None
    assert menu._blank_to_none(None) is None
    assert menu._blank_to_none("  CS  ") == "CS"


def test_no_flags_no_predicates():
    preds, warns = menu._build_predicates(_params(), [])
    assert preds == []
    assert warns == []


def test_flags_map_to_predicates():
    preds, warns = menu._build_predicates(_params(flags={"open", "in-person"}), [])
    assert len(preds) == 2
    assert not warns
    keep = _section(seats=5, modality="in-person")
    assert all(p(keep) for p in preds)
    drop = _section(seats=0, modality="in-person")
    assert not all(p(drop) for p in preds)


def test_graduate_flag_overrides_upper_level():
    """min500 and min300 are mutually exclusive — grad wins, only one predicate."""
    preds, _ = menu._build_predicates(_params(flags={"min300", "min500"}), [])
    assert len(preds) == 1
    assert preds[0](_section(course="600"))
    assert not preds[0](_section(course="400"))


def test_bad_day_spec_warns_instead_of_crashing():
    params = _params(days_spec="XYZ")
    preds, warns = menu._build_predicates(params, [])
    assert preds == []
    assert len(warns) == 1
    assert "days" in warns[0]
    # Dropped filters must not be advertised in the results header.
    assert params["days_spec"] is None


def test_bad_time_spec_warns():
    params = _params(after_spec="9am")
    preds, warns = menu._build_predicates(params, [])
    assert preds == []
    assert warns and "start time" in warns[0]
    assert params["after_spec"] is None


def test_dropped_filter_absent_from_description():
    params = _params(days_spec="XYZ")
    menu._build_predicates(params, [])
    desc = menu._describe(params, kept=9, total=9, source="live")
    assert "XYZ" not in desc and "days=" not in desc


def test_valid_day_and_time_specs_build_predicates():
    preds, warns = menu._build_predicates(
        _params(days_spec="MWF", after_spec="09:00", before_spec="17:00"), []
    )
    assert len(preds) == 3
    assert not warns
    assert all(p(_section(days="MW", begin=(10, 0), end=(11, 15))) for p in preds)


def test_no_conflicts_without_schedule_warns():
    preds, warns = menu._build_predicates(_params(flags={"no_conflicts"}), [])
    assert preds == []
    assert warns and "conflict" in warns[0].lower()


def test_no_conflicts_with_schedule_filters():
    mine = [_section(crn="AAA", days="MW", begin=(13, 30), end=(14, 45))]
    preds, warns = menu._build_predicates(_params(flags={"no_conflicts"}), mine)
    assert len(preds) == 1
    assert not warns
    overlapping = _section(crn="BBB", days="MW", begin=(14, 0), end=(15, 0))
    clear = _section(crn="CCC", days="TR", begin=(13, 30), end=(14, 45))
    assert not preds[0](overlapping)
    assert preds[0](clear)


def test_describe_includes_filters_and_counts():
    desc = menu._describe(
        _params(flags={"open"}, days_spec="MWF"), kept=4, total=9, source="cached"
    )
    assert "subject=CS" in desc
    assert "days=MWF" in desc
    assert "open" in desc
    assert "4/9 after filters" in desc
    assert "[cached]" in desc


def test_describe_hides_advanced_marker():
    """'advanced' is a UI-only flag — it shouldn't leak into the results header."""
    desc = menu._describe(_params(flags={"advanced"}), kept=3, total=3, source="live")
    assert "advanced" not in desc


def test_section_label_shows_meeting_and_seats():
    label = menu._section_label(_section(crn="77863", days="MW", begin=(13, 30), end=(14, 45)))
    assert "77863" in label
    assert "MW" in label
    assert "13:30-14:45" in label
    assert "10/30" in label
    assert "Smith" in label


def test_section_label_handles_async():
    async_sec = _section(days="", begin=None, end=None, instructors=())
    label = menu._section_label(async_sec)
    assert "async" in label
    assert "TBA" in label
