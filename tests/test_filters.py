from datetime import time

import pytest

from gmu_courses import filters as F
from gmu_courses.models import MeetingTime, Section


def make_section(
    days="MW",
    begin=time(10, 0),
    end=time(11, 15),
    modality="in-person",
    seats_available=10,
):
    mt = MeetingTime(
        days=frozenset(days),
        begin=begin,
        end=end,
        building="X",
        room="1",
        schedule_type="LEC",
    )
    return Section(
        crn="00001",
        subject="CS",
        course_number="211",
        title="Test",
        credits=3.0,
        instructors=("Smith, A.",),
        seats_available=seats_available,
        seats_total=30,
        waitlist_count=0,
        meetings=(mt,) if begin is not None or days else (),
        modality=modality,
        instructional_method_desc=None,
        schedule_type_desc="Lecture",
        campus="Fairfax",
        section_number="001",
        raw={},
    )


def make_async_section(modality="online"):
    return Section(
        crn="00002",
        subject="CS",
        course_number="504",
        title="Async",
        credits=3.0,
        instructors=("Smith, A.",),
        seats_available=5,
        seats_total=30,
        waitlist_count=0,
        meetings=(MeetingTime(frozenset(), None, None, "ON", "LINE", "LEC"),),
        modality=modality,
        instructional_method_desc="Online Async",
        schedule_type_desc="Lecture",
        campus="Online",
        section_number="DL1",
        raw={},
    )


def test_parse_days_basic():
    assert F.parse_days("MWF") == frozenset("MWF")
    assert F.parse_days("tr") == frozenset("TR")
    assert F.parse_days("M, W, F") == frozenset("MWF")


def test_parse_days_invalid():
    with pytest.raises(ValueError):
        F.parse_days("MXY")


def test_parse_time_basic():
    assert F.parse_time("9:30") == time(9, 30)
    assert F.parse_time("14:00") == time(14, 0)


def test_days_subset_allows_only_listed_days():
    f = F.days_subset(frozenset("MWF"))
    assert f(make_section(days="MW"))
    assert f(make_section(days="MWF"))
    assert not f(make_section(days="TR"))
    assert not f(make_section(days="MTR"))


def test_days_subset_passes_async():
    f = F.days_subset(frozenset("MWF"))
    assert f(make_async_section()), "async meeting should not block day filter"


def test_time_window():
    after = F.begins_at_or_after(time(10, 0))
    before = F.ends_at_or_before(time(15, 0))
    s = make_section(begin=time(10, 0), end=time(11, 15))
    assert after(s) and before(s)
    early = make_section(begin=time(9, 0), end=time(10, 15))
    assert not after(early)
    late = make_section(begin=time(14, 30), end=time(15, 45))
    assert not before(late)


def test_modality():
    assert F.modality_is("online")(make_async_section())
    assert not F.modality_is("in-person")(make_async_section())


def test_open_seats():
    assert F.open_seats(make_section(seats_available=5))
    assert not F.open_seats(make_section(seats_available=0))


def test_course_number_value():
    assert F.course_number_value("211") == 211
    assert F.course_number_value("211L") == 211   # lab suffix
    assert F.course_number_value("100H") == 100   # honors suffix
    assert F.course_number_value("XXX") is None
    assert F.course_number_value("") is None


def test_min_level():
    f = F.min_level(300)
    s100 = make_section(); object.__setattr__(s100, "course_number", "100")
    s300 = make_section(); object.__setattr__(s300, "course_number", "300")
    s211L = make_section(); object.__setattr__(s211L, "course_number", "211L")
    s500 = make_section(); object.__setattr__(s500, "course_number", "500")
    assert not f(s100)
    assert f(s300)
    assert not f(s211L)
    assert f(s500)


def test_max_level():
    f = F.max_level(499)
    s100 = make_section(); object.__setattr__(s100, "course_number", "100")
    s500 = make_section(); object.__setattr__(s500, "course_number", "500")
    s499 = make_section(); object.__setattr__(s499, "course_number", "499")
    assert f(s100)
    assert f(s499)
    assert not f(s500)


def _section(crn, days, begin_hm, end_hm):
    mt = MeetingTime(
        days=frozenset(days),
        begin=time(*begin_hm),
        end=time(*end_hm),
        building="X", room="1", schedule_type="LEC",
    )
    return Section(
        crn=crn, subject="CS", course_number="211", title="x", credits=3.0,
        instructors=(), seats_available=1, seats_total=1, waitlist_count=0,
        meetings=(mt,), modality="in-person", instructional_method_desc=None,
        schedule_type_desc="Lecture", campus="Fairfax", section_number="001", raw={},
    )


def test_meetings_overlap_basic():
    a = MeetingTime(frozenset("MW"), time(10, 0), time(11, 15), "X", "1", "LEC")
    b = MeetingTime(frozenset("MW"), time(11, 0), time(12, 15), "X", "1", "LEC")
    c = MeetingTime(frozenset("MW"), time(11, 15), time(12, 30), "X", "1", "LEC")  # touches, not overlaps
    d = MeetingTime(frozenset("TR"), time(10, 0), time(11, 15), "X", "1", "LEC")   # no shared days
    assert F.meetings_overlap(a, b)
    assert not F.meetings_overlap(a, c)  # half-open intervals — end == begin is OK
    assert not F.meetings_overlap(a, d)


def test_async_never_conflicts():
    a = MeetingTime(frozenset("MW"), time(10, 0), time(11, 15), "X", "1", "LEC")
    async_m = MeetingTime(frozenset(), None, None, "ON", "LINE", "LEC")
    assert not F.meetings_overlap(a, async_m)
    assert not F.meetings_overlap(async_m, async_m)


def test_no_conflicts_filter():
    mine = [_section("AAA", "MW", (13, 30), (14, 45))]
    candidates = [
        _section("BBB", "MW", (14, 0), (15, 0)),    # overlaps mine
        _section("CCC", "MW", (15, 0), (16, 15)),   # after mine, no overlap
        _section("DDD", "TR", (13, 30), (14, 45)),  # same time, different days
    ]
    keep = F.no_conflicts(mine)
    assert not keep(candidates[0])
    assert keep(candidates[1])
    assert keep(candidates[2])


def test_section_does_not_conflict_with_itself():
    s = _section("AAA", "MW", (13, 30), (14, 45))
    assert not F.sections_conflict(s, s)
    keep = F.no_conflicts([s])
    assert keep(s)  # search results often re-include CRNs the user is in


def test_apply_filters_composes():
    sections = [
        make_section(days="MW", begin=time(10, 0), end=time(11, 15)),
        make_section(days="TR", begin=time(10, 0), end=time(11, 15)),
        make_section(days="MW", begin=time(8, 0), end=time(9, 15)),
        make_async_section(),
    ]
    out = F.apply_filters(
        sections,
        [
            F.days_subset(frozenset("MWF")),
            F.begins_at_or_after(time(9, 30)),
        ],
    )
    # First section passes; TR fails day filter; early MW fails time filter;
    # async passes both (no scheduled time).
    assert len(out) == 2
    assert {s.crn for s in out} == {"00001", "00002"}
