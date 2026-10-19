"""The only code path that talks to KSEI: polite, rate-limited, retrying HTTP."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from ksei.config import Dataset, Settings

log = logging.getLogger(__name__)


class DownloadError(Exception):
    """A KSEI request failed permanently or no usable links were found."""


@dataclass(frozen=True)
class Link:
    dataset: str
    period: date
    url: str


class _ArchivePage(HTMLParser):
    """Collects every <a href> and the year <option> values of an archive page."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.years: list[str] = []
        self.selected_year: str | None = None
        self._option: dict[str, str | None] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and values.get("href"):
            self.hrefs.append(values["href"] or "")
        elif tag == "option" and values.get("value"):
            year = values["value"] or ""
            self.years.append(year)
            if "selected" in values:
                self.selected_year = year


class KseiClient:
    def __init__(
        self,
        user_agent: str,
        min_delay_seconds: float,
        *,
        base_url: str,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 5,
        backoff_seconds: float = 5.0,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._http = httpx.Client(headers={"User-Agent": user_agent}, timeout=timeout_seconds)
        self._base_url = base_url.rstrip("/")
        self._min_delay = min_delay_seconds
        self._clock = clock
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        # Treat construction as a request: another process (task) may have just talked to KSEI.
        self._last_request: float | None = clock()

    @classmethod
    def from_settings(cls, settings: Settings) -> KseiClient:
        return cls(settings.user_agent, settings.min_delay_seconds, base_url=settings.ksei_base_url)

    def _pause(self, backoff: float) -> None:
        """Sleep once for the larger of the backoff and the remaining minimum spacing."""
        remaining = 0.0
        if self._last_request is not None:
            remaining = self._min_delay - (self._clock() - self._last_request)
        wait = max(backoff, remaining)
        if wait > 0:
            self._sleep(wait)

    def _get(self, url: str) -> httpx.Response:
        reason = "no response"
        for attempt in range(1, self._max_attempts + 1):
            self._pause(self._backoff * 2 ** (attempt - 2) if attempt > 1 else 0.0)
            try:
                response = self._http.get(url)
            except httpx.TransportError as exc:
                reason = type(exc).__name__
            else:
                self._last_request = self._clock()
                if response.status_code < 400:
                    return response
                if response.status_code < 500:
                    raise DownloadError(f"{url}: HTTP {response.status_code}")
                reason = f"HTTP {response.status_code}"
            log.warning("attempt %d/%d for %s failed: %s", attempt, self._max_attempts, url, reason)
            self._last_request = self._clock()
        raise DownloadError(f"{url}: gave up after {self._max_attempts} attempts ({reason})")

    def download(self, url: str) -> bytes:
        return self._get(url).content

    def _page_links(self, dataset: Dataset, page: _ArchivePage, page_url: str) -> list[Link]:
        links = []
        for href in page.hrefs:
            absolute = urljoin(page_url, href)
            match = dataset.link_pattern.search(urlsplit(absolute).path)
            if match:
                period = datetime.strptime(match.group(1), "%Y%m%d").date()
                links.append(Link(dataset.name, period, absolute))
        return links

    def list_links(self, dataset: Dataset) -> list[Link]:
        """All download links of a dataset across every year offered by the archive."""
        parse = _ArchivePage()
        archive_url = self._base_url + dataset.archive_path
        parse.feed(self._get(archive_url).text)
        found = self._page_links(dataset, parse, archive_url)
        current = parse.selected_year or (parse.years[0] if parse.years else None)
        for year in parse.years:
            if year == current:
                continue
            page = _ArchivePage()
            year_url = f"{archive_url}/{year}"
            page.feed(self._get(year_url).text)
            found += self._page_links(dataset, page, year_url)
        unique = {link.url: link for link in found}
        if not unique:
            raise DownloadError(f"no download links found for {dataset.name}")
        return sorted(unique.values(), key=lambda link: link.period)
