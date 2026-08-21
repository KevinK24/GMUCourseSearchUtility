"""Contract tests against the real Banner API.

Deselected by default (see `addopts` in pyproject.toml) so the normal suite
stays offline and fast. Run them deliberately:

    pytest -m live

CI runs these on a schedule. That is the point: nobody has to watch GMU for
Banner changes — if the contract drifts, this fails and GitHub sends mail.

A failure here means one of two things: GMU changed Banner (the tool needs
updating), or their servers are briefly down (re-run before assuming the worst).
"""
import pytest

from gmu_courses.banner import BannerClient
from gmu_courses.models import Section

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def client():
    with BannerClient() as c:
        yield c


@pytest.fixture(scope="module")
def terms(client):
    return client.list_terms(max_results=10)


def test_terms_are_returned(terms):
    assert terms, "Banner returned no terms at all"
    for t in terms:
        assert t.code.isdigit() and len(t.code) == 6, f"odd term code: {t.code!r}"
        assert t.description


def test_a_registerable_term_exists(terms):
    """The default-term picker depends on at least one term lacking '(View Only)'."""
    live = [t for t in terms if "view only" not in t.description.lower()]
    assert live, f"every term is View Only: {[t.description for t in terms]}"


@pytest.fixture(scope="module")
def cs_sections(client, terms):
    term = next(t for t in terms if "view only" not in t.description.lower())
    return list(client.search(term.code, subject="CS"))


def test_search_returns_parseable_sections(cs_sections):
    assert cs_sections, "CS returned zero sections — subject filtering may have changed"
    for s in cs_sections:
        assert isinstance(s, Section)
        assert s.crn and s.crn.isdigit()
        assert s.subject == "CS"
        assert s.course_number


def test_sections_carry_the_fields_the_ui_renders(cs_sections):
    """Every column in the results table needs its field to survive parsing."""
    assert any(s.title for s in cs_sections), "no section has a title"
    assert any(s.credits is not None for s in cs_sections), "no section has credits"
    assert any(s.instructors for s in cs_sections), "no section has an instructor"
    assert any(s.seats_total > 0 for s in cs_sections), "no section has a seat count"


def test_meeting_times_still_parse(cs_sections):
    """Day/time filtering and conflict detection are worthless without these."""
    timed = [m for s in cs_sections for m in s.meetings if not m.is_async]
    assert timed, "not one section has a scheduled meeting time"
    for m in timed[:25]:
        assert m.days, "a non-async meeting has no days set"
        assert m.begin is not None and m.end is not None
        assert m.begin < m.end, f"meeting ends before it starts: {m.begin}-{m.end}"


def test_modality_classification_still_recognizes_sections(cs_sections):
    """If GMU renames instructional methods, everything silently becomes 'unknown'."""
    known = [s for s in cs_sections if s.modality != "unknown"]
    ratio = len(known) / len(cs_sections)
    assert ratio > 0.8, (
        f"only {ratio:.0%} of sections classified into a known modality — "
        "instructionalMethodDescription wording probably changed. Seen: "
        f"{sorted({s.instructional_method_desc for s in cs_sections})[:5]}"
    )


def test_course_number_filter_still_narrows(client, terms):
    term = next(t for t in terms if "view only" not in t.description.lower())
    narrowed = list(client.search(term.code, subject="CS", course_number="211"))
    assert narrowed, "CS 211 returned nothing — course-number filtering may have changed"
    assert all(s.course_number.startswith("211") for s in narrowed)


def test_keyword_search_still_narrows(client, terms):
    term = next(t for t in terms if "view only" not in t.description.lower())
    hits = list(client.search(term.code, keyword="security"))
    assert hits, "keyword search returned nothing"
    # A term holds ~6,700 sections; a keyword that returns most of them means
    # the parameter stopped being honoured.
    assert len(hits) < 2000, f"keyword search looks unfiltered ({len(hits)} hits)"
