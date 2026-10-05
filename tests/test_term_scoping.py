"""Conflict checking must not reach across terms.

A saved schedule outlives the semester it was built for. When the next term's
offerings appear, every section in the old schedule still has meeting times,
and comparing them against the new term's candidates invents conflicts that
cannot exist — hiding valid options when --no-conflicts is on.
"""
from datetime import time

from gmu_courses import filters as F
from gmu_courses import schedule as sched
from gmu_courses.models import MeetingTime, Section


def _section(crn, term, days="MW", begin=(13, 30), end=(14, 45), course="211"):
    mt = MeetingTime(
        days=frozenset(days),
        begin=time(*begin),
        end=time(*end),
        building="X",
        room="1",
        schedule_type="LEC",
    )
    return Section(
        crn=crn, subject="CS", course_number=course, title="Test", credits=3.0,
        instructors=(), seats_available=5, seats_total=30, waitlist_count=0,
        meetings=(mt,), modality="in-person", instructional_method_desc=None,
        schedule_type_desc="Lecture", campus="Fairfax", section_number="001",
        raw={"term": term, "termDesc": {"202670": "Fall 2026", "202710": "Spring 2027"}[term]},
    )


def test_section_exposes_its_term():
    s = _section("77863", "202670")
    assert s.term == "202670"
    assert s.term_desc == "Fall 2026"


def test_section_without_term_in_payload_is_none():
    s = _section("77863", "202670")
    object.__setattr__(s, "raw", {})
    assert s.term is None
    assert s.term_desc is None


def test_sections_in_term_filters():
    fall = _section("77863", "202670")
    spring = _section("18267", "202710")
    assert sched.sections_in_term([fall, spring], "202710") == [spring]
    assert sched.sections_in_term([fall, spring], "202670") == [fall]
    assert sched.sections_in_term([fall, spring], "202640") == []


def test_fall_schedule_does_not_block_spring_candidate():
    """The actual regression: identical meeting times, different semesters."""
    my_fall = _section("77863", "202670", days="MW", begin=(13, 30), end=(14, 45))
    spring_candidate = _section(
        "18267", "202710", days="MW", begin=(13, 30), end=(14, 45), course="321"
    )

    # Term-blind comparison sees a clash...
    assert F.sections_conflict(spring_candidate, my_fall), (
        "sanity check: the meeting times really do overlap"
    )

    # ...but scoping to the term being searched removes it from consideration.
    scoped = sched.sections_in_term([my_fall], "202710")
    assert scoped == []
    assert F.no_conflicts(scoped)(spring_candidate)


def test_same_term_conflict_still_detected():
    """Scoping must not break the case the feature exists for."""
    mine = _section("18200", "202710", days="MW", begin=(13, 30), end=(14, 45))
    clashing = _section("18267", "202710", days="MW", begin=(14, 0), end=(15, 0), course="321")
    clear = _section("18268", "202710", days="TR", begin=(13, 30), end=(14, 45), course="330")

    scoped = sched.sections_in_term([mine], "202710")
    assert scoped == [mine]
    keep = F.no_conflicts(scoped)
    assert not keep(clashing)
    assert keep(clear)


def test_mixed_term_schedule_scopes_to_the_searched_term():
    mine = [
        _section("77863", "202670", days="MW", begin=(13, 30), end=(14, 45)),
        _section("18200", "202710", days="MW", begin=(13, 30), end=(14, 45)),
    ]
    candidate = _section("18999", "202710", days="MW", begin=(14, 0), end=(15, 0), course="400")

    scoped = sched.sections_in_term(mine, "202710")
    assert len(scoped) == 1 and scoped[0].crn == "18200"
    # Still blocked, but by the Spring entry — not the Fall one.
    assert not F.no_conflicts(scoped)(candidate)
