"""Domain model for GMU course sections."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Any


_DAY_KEYS = (
    ("monday", "M"),
    ("tuesday", "T"),
    ("wednesday", "W"),
    ("thursday", "R"),
    ("friday", "F"),
    ("saturday", "S"),
    ("sunday", "U"),
)


def _parse_hhmm(s: str | None) -> time | None:
    if not s:
        return None
    s = s.zfill(4)
    return time(int(s[:2]), int(s[2:]))


@dataclass(frozen=True)
class Term:
    code: str
    description: str


@dataclass(frozen=True)
class MeetingTime:
    days: frozenset[str]
    begin: time | None
    end: time | None
    building: str | None
    room: str | None
    schedule_type: str | None  # "LEC", "LAB", "REC", ...

    @property
    def is_async(self) -> bool:
        return self.begin is None and not self.days

    @classmethod
    def from_json(cls, mt: dict[str, Any]) -> MeetingTime:
        days = frozenset(short for key, short in _DAY_KEYS if mt.get(key))
        return cls(
            days=days,
            begin=_parse_hhmm(mt.get("beginTime")),
            end=_parse_hhmm(mt.get("endTime")),
            building=mt.get("buildingDescription") or mt.get("building"),
            room=mt.get("room"),
            schedule_type=mt.get("meetingScheduleType"),
        )


def _classify_modality(method_desc: str | None) -> str:
    """Map Banner's instructionalMethodDescription to a coarse bucket."""
    if not method_desc:
        return "unknown"
    s = method_desc.lower()
    # GMU encodes F2F percentage: "76-100%" = in person, "0-1%" = online,
    # anything in between is hybrid.
    if "76-100" in s or "100%" in s:
        return "in-person"
    if "0-1%" in s or "online" in s:
        return "online"
    return "hybrid"


@dataclass(frozen=True)
class Section:
    crn: str
    subject: str
    course_number: str
    title: str
    credits: float | None
    instructors: tuple[str, ...]
    seats_available: int
    seats_total: int
    waitlist_count: int
    meetings: tuple[MeetingTime, ...]
    modality: str  # "in-person" | "online" | "hybrid" | "unknown"
    instructional_method_desc: str | None
    schedule_type_desc: str | None  # "Lecture", "Lab", "Recitation", ...
    campus: str | None
    section_number: str | None
    raw: dict[str, Any] = field(repr=False, compare=False)

    @property
    def subject_course(self) -> str:
        return f"{self.subject} {self.course_number}"

    @property
    def is_open(self) -> bool:
        return self.seats_available > 0

    @property
    def all_meeting_days(self) -> frozenset[str]:
        return frozenset().union(*(m.days for m in self.meetings))

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Section:
        meetings = tuple(
            MeetingTime.from_json(mf["meetingTime"])
            for mf in (d.get("meetingsFaculty") or [])
            if mf.get("meetingTime")
        )
        instructors = tuple(
            f["displayName"] for f in (d.get("faculty") or []) if f.get("displayName")
        )
        credits = d.get("creditHours")
        if credits is None:
            credits = d.get("creditHourLow")
        return cls(
            crn=str(d["courseReferenceNumber"]),
            subject=d["subject"],
            course_number=str(d["courseNumber"]),
            title=d.get("courseTitle") or "",
            credits=float(credits) if credits is not None else None,
            instructors=instructors,
            seats_available=int(d.get("seatsAvailable") or 0),
            seats_total=int(d.get("maximumEnrollment") or 0),
            waitlist_count=int(d.get("waitCount") or 0),
            meetings=meetings,
            modality=_classify_modality(d.get("instructionalMethodDescription")),
            instructional_method_desc=d.get("instructionalMethodDescription"),
            schedule_type_desc=d.get("scheduleTypeDescription"),
            campus=d.get("campusDescription"),
            section_number=d.get("sequenceNumber"),
            raw=d,
        )
