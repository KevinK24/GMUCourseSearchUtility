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
        "subject": "CS", "course_numbers": [], "keyword": None, "min_level": None,
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


def test_no_level_selected_adds_no_predicate():
    preds, warns = menu._build_predicates(_params(min_level=None), [])
    assert preds == [] and warns == []


@pytest.mark.parametrize(
    "level,boundary,below",
    [(300, "300", "299"), (500, "500", "499"), (650, "650", "649"), (400, "400", "399")],
)
def test_min_level_is_inclusive_at_the_boundary(level, boundary, below):
    """Includes 400, which no preset offered — custom values must work too."""
    preds, _ = menu._build_predicates(_params(min_level=level), [])
    assert len(preds) == 1
    assert preds[0](_section(course=boundary))
    assert not preds[0](_section(course=below))


def test_min_level_is_a_single_value_so_it_cannot_be_double_selected():
    """The old checkbox let two floors be ticked and silently dropped one.

    A single integer makes that unrepresentable rather than merely discouraged.
    """
    params = _params(min_level=300)
    preds, _ = menu._build_predicates(params, [])
    assert len(preds) == 1
    assert preds[0](_section(course="300"))
    assert preds[0](_section(course="700")), "300+ must still include higher levels"


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


def test_single_course_number_adds_no_predicate():
    """One number goes to Banner directly, so nothing is filtered client-side."""
    preds, warns = menu._build_predicates(_params(course_numbers=["211"]), [])
    assert preds == []
    assert warns == []


def test_multiple_course_numbers_filter_client_side():
    preds, warns = menu._build_predicates(
        _params(course_numbers=["530", "542", "618"]), []
    )
    assert len(preds) == 1
    assert not warns
    assert preds[0](_section(course="530"))
    assert preds[0](_section(course="618"))
    assert not preds[0](_section(course="531"))
    assert not preds[0](_section(course="600"))


def test_describe_lists_every_requested_course_number():
    desc = menu._describe(
        _params(course_numbers=["530", "542"]), kept=4, total=60, source="cached"
    )
    assert "course=530,542" in desc
    assert "4/60 after filters" in desc


def test_describe_shows_the_selected_level():
    desc = menu._describe(_params(min_level=650), kept=3, total=9, source="live")
    assert "level>=650" in desc


def test_describe_shows_a_custom_level():
    desc = menu._describe(_params(min_level=425), kept=3, total=9, source="live")
    assert "level>=425" in desc


def test_describe_omits_level_when_none_selected():
    desc = menu._describe(_params(min_level=None), kept=9, total=9, source="live")
    assert "level>=" not in desc


# --------------------------------------------------------------------------
# adding courses to history
# --------------------------------------------------------------------------

def test_split_course_specs_splits_on_commas_only():
    """'CS 555' has a space in it, so whitespace splitting would corrupt entries."""
    assert menu.split_course_specs("CS 555, ISA 650") == ["CS 555", "ISA 650"]
    assert menu.split_course_specs("  CS555 ,, ISA650 , ") == ["CS555", "ISA650"]
    assert menu.split_course_specs("") == []
    assert menu.split_course_specs("   ") == []
    assert menu.split_course_specs("CS 555") == ["CS 555"]


@pytest.fixture
def temp_history(tmp_path, monkeypatch):
    """Point the history module at a throwaway file."""
    monkeypatch.setattr(menu.hist, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(menu.hist, "HISTORY_FILE", tmp_path / "my_history.txt")
    return tmp_path / "my_history.txt"


def test_add_courses_to_history_writes_and_normalizes(temp_history):
    added, dupes, bad = menu.add_courses_to_history("cs555, ISA 650, isa652")
    assert added == ["CS 555", "ISA 650", "ISA 652"]
    assert dupes == [] and bad == []
    assert menu.hist.read_courses() == {"CS 555", "ISA 650", "ISA 652"}


def test_add_courses_to_history_reports_duplicates(temp_history):
    menu.add_courses_to_history("CS 555")
    added, dupes, bad = menu.add_courses_to_history("CS 555, ISA 650")
    assert added == ["ISA 650"]
    assert dupes == ["CS 555"]
    assert bad == []


def test_add_courses_to_history_reports_unparseable(temp_history):
    added, dupes, bad = menu.add_courses_to_history("CS 555, not-a-course, 999")
    assert added == ["CS 555"]
    assert bad == ["not-a-course", "999"]
    # A bad entry must not block the good ones in the same batch.
    assert menu.hist.read_courses() == {"CS 555"}


def test_add_courses_survives_a_pasted_block(temp_history):
    """The realistic case: pasting a comma-joined transcript list."""
    raw = "CS 555, CS 583, CS 700, INFS 774, ISA 562, ISA 650, ISA 652, ISA 656, ISA 681, ISA 797"
    added, dupes, bad = menu.add_courses_to_history(raw)
    assert len(added) == 10
    assert not dupes and not bad
    assert "INFS 774" in menu.hist.read_courses()
