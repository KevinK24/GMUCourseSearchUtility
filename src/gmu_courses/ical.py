"""iCalendar (RFC 5545) export for the user's saved schedule.

Each scheduled meeting in each section becomes a weekly-recurring VEVENT
running between Banner's `startDate` and `endDate` for that meeting. Async
meetings have no slot and are skipped.

Output is the universal `.ics` format — imports directly into Apple Calendar,
Google Calendar, and Outlook with no per-client tweaks.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable

from .models import Section

TZID = "America/New_York"

_ICAL_DAYS = {"M": "MO", "T": "TU", "W": "WE", "R": "TH", "F": "FR", "S": "SA", "U": "SU"}
_PY_WEEKDAY = {"M": 0, "T": 1, "W": 2, "R": 3, "F": 4, "S": 5, "U": 6}


def _parse_banner_date(s: str) -> date:
    """Banner returns dates as 'MM/DD/YYYY'."""
    m, d, y = s.split("/")
    return date(int(y), int(m), int(d))


def _first_occurrence(start: date, days: frozenset[str]) -> date:
    """First date on or after `start` whose weekday is in `days`."""
    targets = {_PY_WEEKDAY[d] for d in days}
    for i in range(7):
        candidate = start + timedelta(days=i)
        if candidate.weekday() in targets:
            return candidate
    raise ValueError(f"no matching day for {sorted(days)} within a week of {start}")


def _ical_escape(s: str) -> str:
    """Escape per RFC 5545 §3.3.11."""
    return (
        s.replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Line-fold to ≤75 octets per RFC 5545 §3.1, continuation lines start with a space."""
    if len(line) <= 75:
        return line
    parts = [line[:75]]
    line = line[75:]
    while len(line) > 74:
        parts.append(" " + line[:74])
        line = line[74:]
    if line:
        parts.append(" " + line)
    return "\r\n".join(parts)


def _format_local_dt(d: date, t: time) -> str:
    return datetime.combine(d, t).strftime("%Y%m%dT%H%M%S")


_VTIMEZONE_BLOCK = [
    "BEGIN:VTIMEZONE",
    f"TZID:{TZID}",
    "BEGIN:STANDARD",
    "DTSTART:20071104T020000",
    "TZOFFSETFROM:-0400",
    "TZOFFSETTO:-0500",
    "TZNAME:EST",
    "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU",
    "END:STANDARD",
    "BEGIN:DAYLIGHT",
    "DTSTART:20070311T020000",
    "TZOFFSETFROM:-0500",
    "TZOFFSETTO:-0400",
    "TZNAME:EDT",
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU",
    "END:DAYLIGHT",
    "END:VTIMEZONE",
]


def section_events(section: Section, dt_stamp: datetime | None = None) -> list[str]:
    """Build folded VEVENT lines for each scheduled meeting in `section`.

    Async meetings (no days, no times) produce no events. Returns an empty
    list for a fully-async section.
    """
    dt_stamp = dt_stamp or datetime.now(timezone.utc)
    raw_meetings = section.raw.get("meetingsFaculty") or []
    events: list[str] = []
    for i, mt in enumerate(section.meetings):
        if mt.is_async or mt.begin is None or mt.end is None or not mt.days:
            continue
        if i >= len(raw_meetings):
            continue
        meeting_raw = raw_meetings[i].get("meetingTime") or {}
        start_str = meeting_raw.get("startDate")
        end_str = meeting_raw.get("endDate")
        if not start_str or not end_str:
            continue
        term_start = _parse_banner_date(start_str)
        term_end = _parse_banner_date(end_str)
        first = _first_occurrence(term_start, mt.days)
        byday = ",".join(_ICAL_DAYS[d] for d in sorted(mt.days, key="MTWRFSU".index))
        location = " ".join(p for p in (mt.building, mt.room) if p)
        summary = f"{section.subject_course} — {section.title} (sec {section.section_number or '?'})"
        desc_parts = [f"CRN: {section.crn}"]
        if section.instructors:
            desc_parts.append(f"Instructor(s): {', '.join(section.instructors)}")
        if mt.schedule_type:
            desc_parts.append(f"Type: {mt.schedule_type}")
        description = "\n".join(desc_parts)
        until = datetime.combine(term_end, time(23, 59, 59)).strftime("%Y%m%dT%H%M%SZ")
        lines = [
            "BEGIN:VEVENT",
            f"UID:{section.crn}-meeting{i}@gmu-courses",
            f"DTSTAMP:{dt_stamp.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTART;TZID={TZID}:{_format_local_dt(first, mt.begin)}",
            f"DTEND;TZID={TZID}:{_format_local_dt(first, mt.end)}",
            f"RRULE:FREQ=WEEKLY;BYDAY={byday};UNTIL={until}",
            f"SUMMARY:{_ical_escape(summary)}",
        ]
        if location:
            lines.append(f"LOCATION:{_ical_escape(location)}")
        lines.append(f"DESCRIPTION:{_ical_escape(description)}")
        lines.append("END:VEVENT")
        events.extend(_fold(line) for line in lines)
    return events


def build_calendar(sections: Iterable[Section]) -> str:
    """Build a complete iCalendar document containing all the sections' meetings."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//gmu-courses//github.com/KevinK24/GMUCourseSearchUtility//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        *_VTIMEZONE_BLOCK,
    ]
    dt_stamp = datetime.now(timezone.utc)
    for s in sections:
        lines.extend(section_events(s, dt_stamp))
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
