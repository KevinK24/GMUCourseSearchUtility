"""Adding and removing CRNs from the saved schedule."""
import pytest

from gmu_courses import menu


@pytest.fixture
def temp_schedule(tmp_path, monkeypatch):
    """Point schedule storage at a throwaway file, with an empty cache.

    The empty cache dir keeps annotation deterministic — nothing resolves, so
    no course names get appended to the lines.
    """
    monkeypatch.setattr(menu.sched, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(menu.sched, "SCHEDULE_FILE", tmp_path / "my_schedule.txt")
    monkeypatch.setattr(menu.cache, "CACHE_DIR", tmp_path / "cache")
    return tmp_path / "my_schedule.txt"


def test_split_crn_specs():
    assert menu.split_crn_specs("77863, 77866") == ["77863", "77866"]
    assert menu.split_crn_specs(" 77863 ") == ["77863"]
    assert menu.split_crn_specs("77863,,77866,") == ["77863", "77866"]
    assert menu.split_crn_specs("") == []


def test_add_crns_writes_them(temp_schedule):
    added, dupes, bad = menu.add_crns_to_schedule("77863, 77866")
    assert added == ["77863", "77866"]
    assert not dupes and not bad
    assert {e.crn for e in menu.sched.read_entries()} == {"77863", "77866"}


def test_add_crns_reports_duplicates(temp_schedule):
    menu.add_crns_to_schedule("77863")
    added, dupes, bad = menu.add_crns_to_schedule("77863, 77866")
    assert added == ["77866"]
    assert dupes == ["77863"]


def test_add_crns_rejects_non_numeric(temp_schedule):
    added, dupes, bad = menu.add_crns_to_schedule("77863, CS211")
    assert added == ["77863"]
    assert bad == ["CS211"]
    # A bad entry must not stop the good ones beside it.
    assert {e.crn for e in menu.sched.read_entries()} == {"77863"}


def test_remove_crns(temp_schedule):
    menu.add_crns_to_schedule("77863, 77866, 78073")
    removed, missing = menu.remove_crns_from_schedule(["77863", "78073"])
    assert removed == ["77863", "78073"]
    assert not missing
    assert {e.crn for e in menu.sched.read_entries()} == {"77866"}


def test_remove_reports_crns_that_were_not_there(temp_schedule):
    menu.add_crns_to_schedule("77863")
    removed, missing = menu.remove_crns_from_schedule(["77863", "99999"])
    assert removed == ["77863"]
    assert missing == ["99999"]


def test_remove_from_empty_schedule_is_harmless(temp_schedule):
    removed, missing = menu.remove_crns_from_schedule(["77863"])
    assert removed == []
    assert missing == ["77863"]


def test_removal_comments_out_rather_than_deleting(temp_schedule):
    """The line must survive so a mistaken removal can be undone by hand."""
    menu.add_crns_to_schedule("77863")
    menu.remove_crns_from_schedule(["77863"])
    body = temp_schedule.read_text(encoding="utf-8")
    assert "77863" in body, "the CRN should still be recoverable in the file"
    assert "# removed:" in body
    assert menu.sched.read_entries() == []


def test_re_adding_a_removed_crn_works(temp_schedule):
    """A commented-out line must not count as already present."""
    menu.add_crns_to_schedule("77863")
    menu.remove_crns_from_schedule(["77863"])
    added, dupes, bad = menu.add_crns_to_schedule("77863")
    assert added == ["77863"]
    assert not dupes
    assert {e.crn for e in menu.sched.read_entries()} == {"77863"}
