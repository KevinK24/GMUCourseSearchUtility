"""Client-side predicates over Section.

All filters are pure: `Section -> bool`. Compose them with `apply_filters`.
Async meetings (no scheduled days/times) always pass day/time filters —
they impose no schedule constraint.
"""
from __future__ import annotations

from datetime import time
from typing import Callable, Iterable

from .models import MeetingTime, Section


SectionFilter = Callable[[Section], bool]

_VALID_DAYS = frozenset("MTWRFSU")


def parse_days(spec: str) -> frozenset[str]:
    """`"MWF"` or `"M,W,F"` or `"mwf"` → frozenset({'M','W','F'}). Raises ValueError."""
    chars = spec.upper().replace(",", "").replace(" ", "")
    days = frozenset(chars)
    bad = days - _VALID_DAYS
    if bad:
        raise ValueError(
            f"Unknown day code(s) {sorted(bad)} in {spec!r}. "
            "Use M T W R F S U (Tue=T, Thu=R, Sat=S, Sun=U)."
        )
    return days


def parse_time(spec: str) -> time:
    """`"9:30"`, `"09:30"`, `"14:00"` → time. Raises ValueError."""
    parts = spec.split(":")
    if len(parts) != 2:
        raise ValueError(f"Time must be HH:MM, got {spec!r}.")
    h, m = int(parts[0]), int(parts[1])
    return time(h, m)


def days_subset(allowed: frozenset[str]) -> SectionFilter:
    """Every scheduled meeting must occur only on days in `allowed`."""
    def predicate(s: Section) -> bool:
        for m in s.meetings:
            if m.is_async:
                continue
            if not m.days.issubset(allowed):
                return False
        return True
    return predicate


def begins_at_or_after(t: time) -> SectionFilter:
    def predicate(s: Section) -> bool:
        for m in s.meetings:
            if m.begin is not None and m.begin < t:
                return False
        return True
    return predicate


def ends_at_or_before(t: time) -> SectionFilter:
    def predicate(s: Section) -> bool:
        for m in s.meetings:
            if m.end is not None and m.end > t:
                return False
        return True
    return predicate


def course_number_value(course_number: str) -> int | None:
    """Numeric prefix of a course number. 'CS 211' → 211, '211L' → 211, 'X' → None."""
    digits = ""
    for c in course_number:
        if c.isdigit():
            digits += c
        else:
            break
    return int(digits) if digits else None


def min_level(level: int) -> SectionFilter:
    """Course number ≥ level. e.g. min_level(300) keeps 300-/400-/500-/… level courses."""
    def predicate(s: Section) -> bool:
        n = course_number_value(s.course_number)
        return n is not None and n >= level
    return predicate


def max_level(level: int) -> SectionFilter:
    """Course number ≤ level. Pairs with min_level for ranges (e.g. 300-499 undergrad upper)."""
    def predicate(s: Section) -> bool:
        n = course_number_value(s.course_number)
        return n is not None and n <= level
    return predicate


def modality_is(kind: str) -> SectionFilter:
    kind = kind.lower()
    return lambda s: s.modality == kind


def open_seats(s: Section) -> bool:
    return s.is_open


def meetings_overlap(a: MeetingTime, b: MeetingTime) -> bool:
    """True iff two meetings share at least one day and their time ranges overlap.

    Async meetings (no days, no times) never conflict — they impose no
    schedule constraint.
    """
    if a.is_async or b.is_async:
        return False
    if not (a.days & b.days):
        return False
    if a.begin is None or a.end is None or b.begin is None or b.end is None:
        return False
    return a.begin < b.end and b.begin < a.end


def sections_conflict(a: Section, b: Section) -> bool:
    """True iff any meeting in `a` overlaps any meeting in `b`."""
    if a.crn == b.crn:
        return False  # a section never conflicts with itself
    return any(meetings_overlap(ma, mb) for ma in a.meetings for mb in b.meetings)


def no_conflicts(my_sections: Iterable[Section]) -> SectionFilter:
    """Keep only sections that don't overlap any of `my_sections`."""
    mine = tuple(my_sections)
    return lambda s: not any(sections_conflict(s, m) for m in mine)


def apply_filters(sections: Iterable[Section], filters: Iterable[SectionFilter]) -> list[Section]:
    fs = tuple(filters)
    return [s for s in sections if all(f(s) for f in fs)]
