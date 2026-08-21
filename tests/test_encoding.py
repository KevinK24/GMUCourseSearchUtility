"""Guards against text that can't be printed on a legacy Windows console.

Windows consoles frequently default to cp1252. Anything we print that isn't
representable there raises UnicodeEncodeError, which for help text means
`gmu search --help` dies outright. These tests keep that from regressing.
"""
import io

import click
import pytest

from gmu_courses import cli
from gmu_courses.cli import main


def _walk(cmd, path=""):
    label = f"{path} {cmd.name}".strip() if path else cmd.name
    yield label, cmd
    if isinstance(cmd, click.Group):
        for sub in cmd.commands.values():
            yield from _walk(sub, label)


def _help_strings():
    """Every string Click can print while rendering help, with a label."""
    for label, cmd in _walk(main):
        for attr in ("help", "short_help", "epilog"):
            value = getattr(cmd, attr, None)
            if value:
                yield f"{label}.{attr}", value
        for param in cmd.params:
            value = getattr(param, "help", None)
            if value:
                yield f"{label} [{param.name}].help", value


@pytest.mark.parametrize("label,text", list(_help_strings()), ids=lambda v: v if isinstance(v, str) else "")
def test_help_text_is_printable_on_a_cp1252_console(label, text):
    try:
        text.encode("cp1252")
    except UnicodeEncodeError as e:
        bad = text[e.start:e.end]
        pytest.fail(
            f"{label} contains {bad!r} (U+{ord(bad[0]):04X}), which cp1252 can't "
            "encode — this crashes --help on a default Windows console. "
            "Use an ASCII equivalent (>=, <=, ->)."
        )


def test_encoding_guard_survives_streams_without_reconfigure(monkeypatch):
    """pytest capture and plain pipes lack .reconfigure — must not raise."""
    monkeypatch.setattr(cli.sys, "stdout", io.StringIO())
    monkeypatch.setattr(cli.sys, "stderr", io.StringIO())
    cli._make_output_encoding_safe()  # must not raise


def test_encoding_guard_sets_replace_on_a_real_wrapper(monkeypatch):
    wrapper = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(cli.sys, "stdout", wrapper)
    monkeypatch.setattr(cli.sys, "stderr", wrapper)
    cli._make_output_encoding_safe()
    assert wrapper.errors == "replace"
    # And the whole point: unencodable text now degrades instead of raising.
    wrapper.write("instructor: Nguyễn")  # U+1EC5 is not in cp1252
    wrapper.flush()
