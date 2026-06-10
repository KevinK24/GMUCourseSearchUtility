"""User's record of courses they've already taken.

Plain text, one course per line, `#` introduces a comment. Entries are matched
against a section's `subject_course` (e.g. "CS 211"), so taking the lecture
doesn't auto-exclude lab sections — list those separately if needed.

Mirrors schedule.py in structure but keys on course identity (subject + number),
not term-specific CRNs.
"""
from __future__ import annotations

from pathlib import Path

from platformdirs import user_config_dir

CONFIG_DIR = Path(user_config_dir("gmu-courses"))
HISTORY_FILE = CONFIG_DIR / "my_history.txt"

_INITIAL_CONTENT = """\
# gmu-courses — courses I've already taken
#
# One course per line as "<SUBJECT> <NUMBER>". Case and whitespace are forgiving:
# "cs211", "CS 211", "CS  211" all normalize to "CS 211".
#
# Lines starting with # are comments. Annotate freely:
#
#   CS 112        # took spring 2025, B+
#   MATH 113
#   ENGH 101      # transferred from NOVA
#
# Use `gmu history add "CS 211"` / `remove "CS 211"` from the CLI, or edit
# this file in your editor. Sections you've already taken will show red in
# `gmu search` results.
"""


def normalize(spec: str) -> str | None:
    """`"cs211"`, `"CS 211"`, `"  math   113  "` → `"CS 211"` / `"MATH 113"`.

    Returns None if the spec doesn't look like a course identifier.
    """
    s = "".join(spec.split()).upper()
    i = 0
    while i < len(s) and s[i].isalpha():
        i += 1
    subject = s[:i]
    number = s[i:]
    if not subject or not number or not number[0].isdigit():
        return None
    return f"{subject} {number}"


def ensure_file() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not HISTORY_FILE.exists():
        HISTORY_FILE.write_text(_INITIAL_CONTENT, encoding="utf-8")
    return HISTORY_FILE


def read_courses() -> set[str]:
    """Parse the history file → set of normalized "SUBJECT NUMBER" strings."""
    if not HISTORY_FILE.exists():
        return set()
    out: set[str] = set()
    for raw in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        course_part, _, _note = line.partition("#")
        norm = normalize(course_part)
        if norm:
            out.add(norm)
    return out


def add_course(spec: str, note: str = "") -> tuple[bool, str | None]:
    """Append a course if it's not already present.

    Returns (added, normalized) — added is False if duplicate or unparseable;
    normalized is the canonical form, or None if the spec didn't parse.
    """
    norm = normalize(spec)
    if not norm:
        return False, None
    ensure_file()
    if norm in read_courses():
        return False, norm
    line = norm
    if note:
        line += f"    # {note}"
    body = HISTORY_FILE.read_text(encoding="utf-8")
    sep = "" if body.endswith("\n") or not body else "\n"
    HISTORY_FILE.write_text(body + sep + line + "\n", encoding="utf-8")
    return True, norm


def remove_course(spec: str) -> tuple[bool, str | None]:
    """Comment out lines matching `spec`. Returns (removed_any, normalized)."""
    norm = normalize(spec)
    if not norm or not HISTORY_FILE.exists():
        return False, norm
    new_lines: list[str] = []
    touched = False
    for raw in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("#"):
            new_lines.append(raw)
            continue
        course_part, _, _ = stripped.partition("#")
        if normalize(course_part) == norm:
            new_lines.append(f"# removed: {raw}")
            touched = True
        else:
            new_lines.append(raw)
    if touched:
        HISTORY_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return touched, norm
