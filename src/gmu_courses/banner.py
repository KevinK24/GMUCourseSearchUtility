"""Banner 9 Student Self-Service JSON API client for GMU.

GMU's Banner 9 SSB at ssbstureg.gmu.edu serves a stateful JSON API. Every
search reuses session state on the server, so we must reset between searches
or filters from the previous query leak into the next one.
"""
from __future__ import annotations

import truststore
truststore.inject_into_ssl()  # use the OS cert store; GMU's cert chain is incomplete in certifi's bundle

from typing import Iterator

import httpx

from .models import Section, Term

BASE_URL = "https://ssbstureg.gmu.edu/StudentRegistrationSsb"
_UA = "gmu-courses/0.1 (personal course-planning CLI)"


class BannerError(RuntimeError):
    pass


class BannerClient:
    def __init__(self, *, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": _UA, "Accept": "application/json"},
            follow_redirects=True,
        )
        self._term_in_session: str | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BannerClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def list_terms(self, *, max_results: int = 20) -> list[Term]:
        r = self._client.get(
            f"{BASE_URL}/ssb/classSearch/getTerms",
            params={"searchTerm": "", "offset": 1, "max": max_results},
        )
        r.raise_for_status()
        return [Term(code=t["code"], description=t["description"]) for t in r.json()]

    def _select_term(self, term_code: str) -> None:
        """Set the active term in session state. Resets prior search filters."""
        # Always reset, even if same term — Banner keeps prior search params otherwise.
        self._client.post(f"{BASE_URL}/ssb/classSearch/resetDataForm")
        self._client.get(f"{BASE_URL}/ssb/term/termSelection", params={"mode": "search"})
        r = self._client.post(
            f"{BASE_URL}/ssb/term/search",
            params={"mode": "search"},
            data={
                "term": term_code,
                "studyPath": "",
                "studyPathText": "",
                "startDatepicker": "",
                "endDatepicker": "",
            },
        )
        r.raise_for_status()
        self._term_in_session = term_code

    def search(
        self,
        term_code: str,
        *,
        subject: str | None = None,
        course_number: str | None = None,
        keyword: str | None = None,
        page_size: int = 50,
    ) -> Iterator[Section]:
        for raw in self.search_raw(
            term_code,
            subject=subject,
            course_number=course_number,
            keyword=keyword,
            page_size=page_size,
        ):
            yield Section.from_json(raw)

    def search_raw(
        self,
        term_code: str,
        *,
        subject: str | None = None,
        course_number: str | None = None,
        keyword: str | None = None,
        page_size: int = 50,
    ) -> Iterator[dict]:
        if not any((subject, course_number, keyword)):
            raise BannerError(
                "Pass at least one of subject / course_number / keyword — "
                "an unbounded query returns thousands of sections."
            )
        self._select_term(term_code)
        offset = 0
        while True:
            params: dict[str, str | int] = {
                "txt_term": term_code,
                "pageOffset": offset,
                "pageMaxSize": page_size,
                "sortColumn": "subjectDescription",
                "sortDirection": "asc",
            }
            if subject:
                params["txt_subject"] = subject.upper()
            if course_number:
                params["txt_courseNumber"] = course_number
            if keyword:
                params["txt_keywordlike"] = keyword
            r = self._client.get(
                f"{BASE_URL}/ssb/searchResults/searchResults", params=params
            )
            r.raise_for_status()
            payload = r.json()
            sections = payload.get("data") or []
            if not sections:
                break
            for s in sections:
                yield s
            offset += len(sections)
            total = payload.get("totalCount") or 0
            if offset >= total:
                break

