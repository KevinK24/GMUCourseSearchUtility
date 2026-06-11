"""`gmu` CLI entrypoint."""
from __future__ import annotations

import sys

import click
import httpx

from pathlib import Path

from . import __version__
from .banner import BannerClient, BannerError
from . import cache
from . import filters as F
from . import history as hist
from . import ical
from . import schedule as sched
from .models import Section, Term
from .render import console, render_section_detail, render_sections, render_terms


def _pick_default_term(client: BannerClient) -> Term:
    """First term not marked '(View Only)' — i.e. the next registerable term."""
    terms = client.list_terms(max_results=10)
    for t in terms:
        if "view only" not in t.description.lower():
            return t
    return terms[0]


def _resolve_term(client: BannerClient, code: str | None) -> Term:
    if code is None:
        return _pick_default_term(client)
    for t in client.list_terms(max_results=20):
        if t.code == code:
            return t
    # Unknown code — still let the user proceed; the search call will error.
    return Term(code=code, description=f"term {code}")


_EPILOG = """\
\b
Examples:
  gmu terms                                       List semesters and their codes
  gmu search -s CS                                All Computer Science sections (default term)
  gmu search -s CS -c 211                         CS 211 sections only
  gmu search -k "machine learning"                Title keyword search
  gmu search -s MATH --days MWF --after 10:00     Math sections meeting only MWF after 10am
  gmu search -s CS --modality online --open       Online CS sections with open seats
  gmu search -s CS --min-level 300                CS courses at 300-level and above (upper division+)
  gmu search -s CS --min-level 300 --max-level 499  Undergrad upper-division CS only (300s and 400s)
  gmu search -s MATH --no-conflicts               Hide sections that overlap CRNs in your saved schedule
  gmu search -s CS -c 211 --pick                  Interactive picker — space toggles, enter adds to schedule
  gmu show 77863                                  Details for a CRN you've seen in a search
  gmu schedule edit                               Open your schedule file in your editor
  gmu schedule add 77863                          Append a CRN to your schedule
  gmu schedule show                               Print what's currently in your schedule
  gmu schedule export -o fall26.ics               Export your schedule as a .ics calendar file
  gmu history add CS 211                          Mark a course as already taken (colors search rows red)
  gmu history edit                                Bulk-edit the list of courses you've taken
  gmu cache clear                                 Wipe the local result cache

Row colors in `gmu search` results (automatic, no flag needed):
  green   = open to take, no constraint
  yellow  = this CRN is in your saved schedule
  magenta = conflicts with something in your schedule
  red     = course is in your taken-history file

Day codes: M Tue=T W Thu=R F Sat=S Sun=U  (e.g. --days MWF or --days TR)
"""


@click.group(context_settings={"help_option_names": ["-h", "--help"]}, epilog=_EPILOG)
@click.version_option(version=__version__, prog_name="gmu")
def main() -> None:
    """Search George Mason University's Schedule of Classes."""


@main.command("terms")
def terms_cmd() -> None:
    """List available semesters with their codes."""
    with BannerClient() as bc:
        render_terms(bc.list_terms())


@main.command("search")
@click.option("--term", "-t", "term_code", help="Term code, e.g. 202670. Default: next registerable term.")
@click.option("--subject", "-s", help="Subject code, e.g. CS, MATH, ENGH.")
@click.option("--course", "-c", "course_number", help="Course number, e.g. 211.")
@click.option("--keyword", "-k", help="Title keyword search.")
@click.option("--days", "days_spec", help="Restrict to sections meeting only on these days. e.g. MWF or TR (R=Thu).")
@click.option("--after", "after_spec", help="Every meeting must begin at or after this time. HH:MM.")
@click.option("--before", "before_spec", help="Every meeting must end at or before this time. HH:MM.")
@click.option(
    "--modality",
    type=click.Choice(["in-person", "online", "hybrid"], case_sensitive=False),
    help="Filter by modality.",
)
@click.option("--min-level", "min_level_n", type=int, help="Course number ≥ N. e.g. --min-level 300 keeps upper-division and graduate courses.")
@click.option("--max-level", "max_level_n", type=int, help="Course number ≤ N. Pair with --min-level for a range, e.g. 300 to 499 for undergrad upper.")
@click.option("--open", "open_only", is_flag=True, help="Only sections with open seats.")
@click.option("--no-conflicts", "no_conflicts", is_flag=True, help="Hide sections that overlap your saved schedule (see `gmu schedule`).")
@click.option("--pick", is_flag=True, help="After the table prints, drop into an interactive checkbox picker to add CRN(s) to your schedule.")
@click.option("--fresh", is_flag=True, help="Bypass disk cache and re-fetch from Banner.")
def search_cmd(
    term_code: str | None,
    subject: str | None,
    course_number: str | None,
    keyword: str | None,
    days_spec: str | None,
    after_spec: str | None,
    before_spec: str | None,
    modality: str | None,
    min_level_n: int | None,
    max_level_n: int | None,
    open_only: bool,
    no_conflicts: bool,
    pick: bool,
    fresh: bool,
) -> None:
    """Search for sections in a term.

    At least one of --subject / --course / --keyword is required.
    """
    if not any((subject, course_number, keyword)):
        raise click.UsageError("Pass at least one of --subject, --course, or --keyword.")

    predicates: list[F.SectionFilter] = []
    try:
        if days_spec:
            predicates.append(F.days_subset(F.parse_days(days_spec)))
        if after_spec:
            predicates.append(F.begins_at_or_after(F.parse_time(after_spec)))
        if before_spec:
            predicates.append(F.ends_at_or_before(F.parse_time(before_spec)))
    except ValueError as e:
        raise click.UsageError(str(e)) from e
    if modality:
        predicates.append(F.modality_is(modality))
    if min_level_n is not None:
        predicates.append(F.min_level(min_level_n))
    if max_level_n is not None:
        predicates.append(F.max_level(max_level_n))
    if open_only:
        predicates.append(F.open_seats)

    # Resolve the schedule once — both --no-conflicts filtering and the magenta
    # conflict coloring use the same resolved sections.
    entries = sched.read_entries()
    my_sections, missing = sched.resolve(entries) if entries else ([], [])
    if missing:
        click.echo(
            f"(note: {len(missing)} schedule CRN(s) not in cache, conflict checks will skip them: "
            f"{', '.join(missing)}. Run `gmu search` covering each subject first.)",
            err=True,
        )
    if no_conflicts:
        if not entries:
            click.echo(
                f"(no CRNs in {sched.SCHEDULE_FILE} — --no-conflicts has nothing to compare against)",
                err=True,
            )
        elif my_sections:
            predicates.append(F.no_conflicts(my_sections))

    try:
        with BannerClient() as bc:
            term = _resolve_term(bc, term_code)
            raw_sections: list[dict] | None = None
            if not fresh:
                raw_sections = cache.load_sections(term.code, subject, course_number, keyword)
            if raw_sections is None:
                with console.status(f"Querying {term.description}…", spinner="dots"):
                    raw_sections = list(
                        bc.search_raw(
                            term.code,
                            subject=subject,
                            course_number=course_number,
                            keyword=keyword,
                        )
                    )
                cache.store_sections(term.code, subject, course_number, keyword, raw_sections)
                source = "live"
            else:
                source = "cached"
    except BannerError as e:
        raise click.ClickException(str(e)) from e
    except httpx.HTTPError as e:
        raise click.ClickException(f"Network error talking to Banner: {e}") from e

    fetched = [Section.from_json(d) for d in raw_sections]
    sections = F.apply_filters(fetched, predicates) if predicates else fetched

    parts = []
    if subject:
        parts.append(f"subject={subject.upper()}")
    if course_number:
        parts.append(f"course={course_number}")
    if keyword:
        parts.append(f"keyword={keyword!r}")
    if days_spec:
        parts.append(f"days={days_spec.upper()}")
    if after_spec:
        parts.append(f"after={after_spec}")
    if before_spec:
        parts.append(f"before={before_spec}")
    if modality:
        parts.append(f"mod={modality}")
    if min_level_n is not None:
        parts.append(f"min-level={min_level_n}")
    if max_level_n is not None:
        parts.append(f"max-level={max_level_n}")
    if open_only:
        parts.append("open")
    if no_conflicts:
        parts.append("no-conflicts")
    query_desc = ", ".join(parts)
    if predicates:
        query_desc += f"  ({len(sections)}/{len(fetched)} after filters)"
    query_desc += f"  [{source}]"
    taken = hist.read_courses()
    render_sections(
        sections,
        term.description,
        query_desc,
        taken_courses=taken or None,
        scheduled_sections=my_sections or None,
    )

    if pick:
        _interactive_pick(sections, my_sections, taken)


def _interactive_pick(
    sections: list[Section],
    my_sections: list[Section],
    taken: set[str],
) -> None:
    """Show a checkbox picker over add-able sections, append selected CRNs to schedule."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        click.echo(
            "(--pick requires an interactive terminal; skipping)",
            err=True,
        )
        return

    scheduled_crns = {s.crn for s in my_sections}
    candidates = [
        s for s in sections
        if s.subject_course not in taken and s.crn not in scheduled_crns
    ]
    if not candidates:
        click.echo("(nothing to pick — every result is already in your schedule or history)")
        return

    try:
        import questionary
    except ImportError:
        raise click.ClickException(
            "--pick needs the `questionary` package. Install with: pip install questionary"
        )

    def _label(s: Section) -> str:
        if s.meetings and s.meetings[0].begin is not None:
            m = s.meetings[0]
            days = "".join(d for d in "MTWRFSU" if d in m.days)
            when = f"{m.begin.strftime('%H:%M')}-{m.end.strftime('%H:%M')}" if m.end else m.begin.strftime("%H:%M")
        else:
            days, when = "async", ""
        seats = f"{s.seats_available}/{s.seats_total}"
        instructor = s.instructors[0].split(",")[0] if s.instructors else "TBA"
        return f"{s.crn}  {s.subject_course:9s} sec {s.section_number or '?':<3s}  {days:5s} {when:<11s}  {instructor:<20s}  {seats:>7s}  {s.title}"

    choices = [questionary.Choice(title=_label(s), value=s) for s in candidates]
    picked = questionary.checkbox(
        f"Select CRN(s) to add to your schedule ({len(candidates)} option(s); space=toggle, enter=confirm):",
        choices=choices,
    ).ask()

    if not picked:
        click.echo("(nothing added)")
        return

    added_count = 0
    for s in picked:
        note = f"{s.subject_course} sec {s.section_number or '?'}"
        if sched.add_crn(s.crn, note=note):
            added_count += 1
    if added_count:
        click.echo(f"Added {added_count} CRN(s) to {sched.SCHEDULE_FILE.name}.")
    else:
        click.echo("(all selected CRNs were already in your schedule)")


@main.command("show")
@click.argument("crn")
def show_cmd(crn: str) -> None:
    """Show full detail for a section by CRN.

    Looks up the CRN in the local cache. Run a `gmu search` first if you
    haven't already — Banner has no public CRN-lookup endpoint.
    """
    hit = cache.find_section_by_crn(crn)
    if hit is None:
        raise click.ClickException(
            f"CRN {crn} not found in local cache. Run `gmu search` first "
            "for the relevant subject or term, then retry."
        )
    raw, term_code = hit
    section = Section.from_json(raw)
    # Best-effort: fetch the term description for nicer display.
    term_desc = f"term {term_code}"
    try:
        with BannerClient() as bc:
            for t in bc.list_terms():
                if t.code == term_code:
                    term_desc = t.description
                    break
    except (httpx.HTTPError, BannerError):
        pass
    render_section_detail(section, term_desc)


@main.group("history")
def history_group() -> None:
    """Manage the list of courses you've already taken."""


@history_group.command("path")
def history_path() -> None:
    """Print the on-disk location of your history file."""
    hist.ensure_file()
    click.echo(str(hist.HISTORY_FILE))


@history_group.command("edit")
def history_edit() -> None:
    """Open the history file in your default editor."""
    p = hist.ensure_file()
    click.launch(str(p))


@history_group.command("add")
@click.argument("course", nargs=-1, required=True)
def history_add(course: tuple[str, ...]) -> None:
    """Append a course you've taken. e.g. `gmu history add CS 211` or `gmu history add cs211`."""
    spec = " ".join(course)
    added, norm = hist.add_course(spec)
    if norm is None:
        raise click.UsageError(f"Couldn't parse {spec!r} as a course (expected like 'CS 211').")
    if added:
        click.echo(f"Added {norm} to your history.")
    else:
        click.echo(f"{norm} is already in your history.")


@history_group.command("remove")
@click.argument("course", nargs=-1, required=True)
def history_remove(course: tuple[str, ...]) -> None:
    """Remove a course from your history (line is commented out, not deleted)."""
    spec = " ".join(course)
    removed, norm = hist.remove_course(spec)
    if norm is None:
        raise click.UsageError(f"Couldn't parse {spec!r} as a course.")
    if removed:
        click.echo(f"Removed {norm} from your history.")
    else:
        click.echo(f"{norm} was not in your history.")


@history_group.command("show")
def history_show() -> None:
    """List the courses currently in your history."""
    courses = sorted(hist.read_courses())
    if not courses:
        click.echo(f"History is empty. Edit {hist.HISTORY_FILE} or run `gmu history add <COURSE>`.")
        return
    click.echo(f"{len(courses)} course(s) in your history:")
    for c in courses:
        click.echo(f"  {c}")


@main.group("schedule")
def schedule_group() -> None:
    """Manage the list of CRNs you're taking (for --no-conflicts on search)."""


@schedule_group.command("path")
def schedule_path() -> None:
    """Print the on-disk location of your schedule file."""
    sched.ensure_file()
    click.echo(str(sched.SCHEDULE_FILE))


@schedule_group.command("edit")
def schedule_edit() -> None:
    """Open the schedule file in your default editor."""
    p = sched.ensure_file()
    click.launch(str(p))


@schedule_group.command("add")
@click.argument("crn")
def schedule_add(crn: str) -> None:
    """Append a CRN to your schedule."""
    note = ""
    hit = cache.find_section_by_crn(crn)
    if hit is not None:
        sec = Section.from_json(hit[0])
        note = f"{sec.subject_course} sec {sec.section_number or '?'}"
    added = sched.add_crn(crn, note=note)
    if added:
        click.echo(f"Added CRN {crn}" + (f"  ({note})" if note else "") + ".")
    else:
        click.echo(f"CRN {crn} is already in your schedule.")


@schedule_group.command("remove")
@click.argument("crn")
def schedule_remove(crn: str) -> None:
    """Remove a CRN from your schedule (line is commented out, not deleted)."""
    if sched.remove_crn(crn):
        click.echo(f"Removed CRN {crn} from your schedule.")
    else:
        click.echo(f"CRN {crn} was not in your schedule.")


@schedule_group.command("show")
def schedule_show() -> None:
    """Render your current schedule as a table."""
    entries = sched.read_entries()
    if not entries:
        click.echo(f"Schedule is empty. Edit {sched.SCHEDULE_FILE} or run `gmu schedule add <CRN>`.")
        return
    resolved, missing = sched.resolve(entries)
    if resolved:
        render_sections(resolved, "your schedule", f"{len(resolved)} CRN(s) resolved")
    if missing:
        click.echo(
            f"\nCould not resolve {len(missing)} CRN(s) — not in cache yet: "
            f"{', '.join(missing)}.\nRun `gmu search` covering their subject, then retry.",
            err=True,
        )


@schedule_group.command("export")
@click.option(
    "--output",
    "-o",
    "output_path",
    type=click.Path(dir_okay=False, writable=True, resolve_path=True, path_type=Path),
    default=Path("my_gmu_schedule.ics"),
    show_default=True,
    help="Where to write the .ics file.",
)
def schedule_export(output_path: Path) -> None:
    """Export your schedule to an .ics file (Apple/Google/Outlook Calendar)."""
    entries = sched.read_entries()
    if not entries:
        raise click.ClickException(
            f"Schedule is empty. Add CRNs first: `gmu schedule add <CRN>` or edit {sched.SCHEDULE_FILE}."
        )
    resolved, missing = sched.resolve(entries)
    if missing:
        click.echo(
            f"(warning: {len(missing)} CRN(s) not in cache, skipped: {', '.join(missing)}. "
            "Run `gmu search` covering their subject and retry to include them.)",
            err=True,
        )
    if not resolved:
        raise click.ClickException(
            "None of the CRNs in your schedule could be resolved from the cache. "
            "Run `gmu search` covering each subject first."
        )
    body = ical.build_calendar(resolved)
    output_path.write_text(body, encoding="utf-8", newline="")
    n_events = body.count("BEGIN:VEVENT")
    click.echo(
        f"Wrote {n_events} event(s) for {len(resolved)} section(s) to {output_path}.\n"
        "Import: double-click on macOS/Windows, or 'Import' in Google Calendar settings."
    )


@main.group("cache")
def cache_group() -> None:
    """Manage the local result cache."""


@cache_group.command("clear")
def cache_clear() -> None:
    """Delete all cached search results."""
    n = cache.clear()
    click.echo(f"Removed {n} cached file(s) from {cache.CACHE_DIR}.")


@cache_group.command("path")
def cache_path() -> None:
    """Print the on-disk cache directory."""
    click.echo(str(cache.CACHE_DIR))


if __name__ == "__main__":
    sys.exit(main())
