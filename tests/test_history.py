from gmu_courses.history import normalize


def test_normalize_canonicalizes_spacing_and_case():
    assert normalize("cs211") == "CS 211"
    assert normalize("CS 211") == "CS 211"
    assert normalize("CS  211") == "CS 211"
    assert normalize("  math   113  ") == "MATH 113"
    assert normalize("ENGH101") == "ENGH 101"


def test_normalize_rejects_garbage():
    assert normalize("") is None
    assert normalize("211") is None         # no subject
    assert normalize("CS") is None          # no number
    assert normalize("CS-211") is None      # punctuation in middle (not a real GMU pattern)


def test_normalize_accepts_lab_suffix():
    # GMU sometimes writes lab sections as "CS 211L" — treat as own course id.
    assert normalize("CS 211L") == "CS 211L"
