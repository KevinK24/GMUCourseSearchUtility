"""User's saved list of CRNs they're taking / considering.

Plain text file, one CRN per line, `#` introduces a comment.

CRNs are resolved against the disk cache (same mechanism as `gmu show`), so
the user has to have run a `gmu search` covering each CRN's subject before
it can participate in conflict checks. Unresolved CRNs are reported, not
silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir

from . import cache
from .models import Section

CONFIG_DIR = Path(user_config_dir("gmu-courses"))
SCHEDULE_FILE = CONFIG_DIR / "my_schedule.txt"

_INITIAL_CONTENT = """\
# gmu-courses — my schedule
#
# One CRN per line. Lines starting with # are comments and are ignored.
# Anything after a # on a line is also a comment, so you can annotate:
#
#   77863    # CS 211 sec 001 — MW 13:30-14:45
#   77866    # CS 211 lab sec 201 — R 11:30-12:20
#
# Use `gmu schedule add <CRN>` / `remove <CRN>` from the CLI, or just edit
# this file in your editor of choice. Then `gmu search ... --no-conflicts`
# will hide sections whose meetings overlap with anything listed here.
"""


@dataclass(frozen=True)
class ScheduleEntry:
    crn: str
    note: str  # the inline `# comment` if any, stripped of leading whitespace


def ensure_file() -> Path:
    """Make sure the schedule file exists. Returns its path."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not SCHEDULE_FILE.exists():
        SCHEDULE_FILE.write_text(_INITIAL_CONTENT, encoding="utf-8")
    return SCHEDULE_FILE


def read_entries() -> list[ScheduleEntry]:
    """Parse the schedule file. Returns [] if the file doesn't exist yet."""
    if not SCHEDULE_FILE.exists():
        return []
    entries: list[ScheduleEntry] = []
    for raw in SCHEDULE_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        crn_part, _, note = line.partition("#")
        crn = crn_part.strip()
        if not crn:
            continue
        entries.append(ScheduleEntry(crn=crn, note=note.strip()))
    # Dedupe, preserving first occurrence.
    seen: set[str] = set()
    unique: list[ScheduleEntry] = []
    for e in entries:
        if e.crn in seen:
            continue
        seen.add(e.crn)
        unique.append(e)
    return unique


def add_crn(crn: str, note: str = "") -> bool:
    """Append a CRN if it isn't already present. Returns True if added."""
    ensure_file()
    existing = {e.crn for e in read_entries()}
    if crn in existing:
        return False
    line = f"{crn}"
    if note:
        line += f"    # {note}"
    with SCHEDULE_FILE.open("a", encoding="utf-8") as f:
        if not SCHEDULE_FILE.read_text(encoding="utf-8").endswith("\n"):
            f.write("\n")
        f.write(line + "\n")
    return True


def remove_crn(crn: str) -> bool:
    """Comment out the line(s) containing this CRN. Returns True if anything matched.

    We comment rather than delete so the user can recover edits + notes if
    they removed the wrong CRN.
    """
    if not SCHEDULE_FILE.exists():
        return False
    new_lines: list[str] = []
    touched = False
    for raw in SCHEDULE_FILE.read_text(encoding="utf-8").splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("#"):
            new_lines.append(raw)
            continue
        crn_part, _, _ = stripped.partition("#")
        if crn_part.strip() == crn:
            new_lines.append(f"# removed: {raw}")
            touched = True
        else:
            new_lines.append(raw)
    if touched:
        SCHEDULE_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return touched


def resolve(entries: list[ScheduleEntry]) -> tuple[list[Section], list[str]]:
    """Look each CRN up in the disk cache. Returns (resolved, unresolved_crns)."""
    resolved: list[Section] = []
    missing: list[str] = []
    for e in entries:
        hit = cache.find_section_by_crn(e.crn)
        if hit is None:
            missing.append(e.crn)
            continue
        raw, _term_code = hit
        resolved.append(Section.from_json(raw))
    return resolved, missing
