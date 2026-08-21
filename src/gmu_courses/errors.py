"""Exception types.

Kept in their own module so `models` and `banner` can both raise them without
importing each other.
"""
from __future__ import annotations

ISSUES_URL = "https://github.com/KevinK24/GMUCourseSearchUtility/issues"

_DRIFT_HINT = (
    "\n\nThis usually means GMU changed something about Banner and gmu-courses "
    "hasn't caught up yet.\nIt is not something you did wrong, and no setting on "
    "your end will fix it.\n"
    f"Please check for a newer version, or report it here:\n  {ISSUES_URL}"
)


class BannerError(RuntimeError):
    """Something went wrong talking to Banner."""


class BannerAPIChanged(BannerError):
    """Banner's response didn't look the way this tool expects.

    Raised when an endpoint returns an unexpected status, non-JSON, or JSON
    missing fields we depend on — i.e. the upstream contract drifted. The
    message always carries the "how to report this" hint, so callers can just
    print it.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail.rstrip() + _DRIFT_HINT)
        self.detail = detail
