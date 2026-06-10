"""Rich-based rendering for sections and terms."""
from __future__ import annotations

from datetime import time
from typing import Iterable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import filters as F
from .models import MeetingTime, Section, Term

_DAY_ORDER = "MTWRFSU"

console = Console()


def _format_days(days: Iterable[str]) -> str:
    if not days:
        return ""
    return "".join(d for d in _DAY_ORDER if d in days)


def _format_time(t: time | None) -> str:
    return t.strftime("%H:%M") if t else ""


def _format_meeting(m: MeetingTime) -> str:
    if m.is_async:
        return "async"
    days = _format_days(m.days)
    when = f"{_format_time(m.begin)}-{_format_time(m.end)}" if m.begin else ""
    return f"{days} {when}".strip()


def _seats_text(s: Section) -> Text:
    label = f"{s.seats_available}/{s.seats_total}"
    if s.waitlist_count:
        label += f" wl{s.waitlist_count}"
    color = "green" if s.is_open else "red"
    return Text(label, style=color)


def _modality_text(s: Section) -> Text:
    colors = {"in-person": "cyan", "online": "magenta", "hybrid": "yellow"}
    return Text(s.modality, style=colors.get(s.modality, "white"))


def render_terms(terms: list[Term]) -> None:
    table = Table(title="GMU semesters", header_style="bold")
    table.add_column("Code")
    table.add_column("Description")
    for t in terms:
        table.add_row(t.code, t.description)
    console.print(table)


def _row_style(
    s: Section,
    taken_courses: set[str] | None,
    scheduled_crn_set: set[str] | None,
    scheduled_sections: list[Section] | None,
) -> str:
    """Color a row by enrollment status, in priority order.

    red > yellow > magenta > green:
      red     = course in history (already taken)
      yellow  = this exact CRN is in your schedule
      magenta = conflicts with something in your schedule
      green   = open to take, no constraint
    """
    if taken_courses and s.subject_course in taken_courses:
        return "red"
    if scheduled_crn_set and s.crn in scheduled_crn_set:
        return "yellow"
    if scheduled_sections and any(F.sections_conflict(s, ss) for ss in scheduled_sections):
        return "magenta"
    return "green"


def render_sections(
    sections: list[Section],
    term_desc: str,
    query_desc: str,
    *,
    taken_courses: set[str] | None = None,
    scheduled_sections: list[Section] | None = None,
) -> None:
    if not sections:
        console.print(f"[yellow]No sections matched[/yellow] ({query_desc}) in {term_desc}.")
        return
    title = f"{len(sections)} section(s) — {query_desc} — {term_desc}"
    table = Table(title=title, header_style="bold", show_lines=False)
    table.add_column("CRN")
    table.add_column("Course")
    table.add_column("Sec")
    table.add_column("Title", max_width=60, ratio=3)
    table.add_column("Meetings")
    table.add_column("Instructor", max_width=32, ratio=2)
    table.add_column("Mod")
    table.add_column("Cr")
    table.add_column("Seats", justify="right")
    scheduled_crn_set = {ss.crn for ss in scheduled_sections} if scheduled_sections else None
    show_legend = bool(taken_courses or scheduled_sections)
    for s in sections:
        meetings = "\n".join(_format_meeting(m) for m in s.meetings) or "async"
        instructors = "\n".join(s.instructors) or "TBA"
        credits = f"{s.credits:g}" if s.credits is not None else ""
        table.add_row(
            s.crn,
            s.subject_course,
            s.section_number or "",
            s.title,
            meetings,
            instructors,
            _modality_text(s),
            credits,
            _seats_text(s),
            style=_row_style(s, taken_courses, scheduled_crn_set, scheduled_sections),
        )
    console.print(table)
    if show_legend:
        console.print(
            "  [green]green[/green] = open to take   "
            "[yellow]yellow[/yellow] = in your schedule   "
            "[magenta]magenta[/magenta] = conflicts with your schedule   "
            "[red]red[/red] = already taken"
        )


def render_section_detail(s: Section, term_desc: str) -> None:
    lines: list[str] = []
    lines.append(f"[bold]{s.subject_course}[/bold] — {s.title}")
    lines.append(f"CRN {s.crn}  •  Section {s.section_number or '?'}  •  {term_desc}")
    lines.append("")
    lines.append(f"Credits: {s.credits if s.credits is not None else '?'}")
    lines.append(f"Schedule type: {s.schedule_type_desc or '?'}")
    lines.append(f"Modality: {s.modality}  ({s.instructional_method_desc or '?'})")
    lines.append(f"Campus: {s.campus or '?'}")
    seats_color = "green" if s.is_open else "red"
    lines.append(
        f"Seats: [{seats_color}]{s.seats_available}/{s.seats_total}[/{seats_color}]"
        + (f"  waitlist {s.waitlist_count}" if s.waitlist_count else "")
    )
    lines.append(f"Instructor(s): {', '.join(s.instructors) if s.instructors else 'TBA'}")
    lines.append("")
    lines.append("[bold]Meetings[/bold]")
    if not s.meetings:
        lines.append("  (no scheduled meetings — fully async)")
    else:
        for m in s.meetings:
            if m.is_async:
                lines.append("  • async")
                continue
            where = " ".join(p for p in (m.building, m.room) if p) or "?"
            lines.append(
                f"  • {_format_days(m.days)} {_format_time(m.begin)}-{_format_time(m.end)}"
                f"  @ {where}  ({m.schedule_type or '?'})"
            )
    console.print(Panel("\n".join(lines), title=s.subject_course, expand=False))
