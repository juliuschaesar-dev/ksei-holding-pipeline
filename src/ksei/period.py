"""One-time load of the period calendar: source file -> SeaweedFS bronze -> ClickHouse bronze.

The calendar is a static reference file, not a KSEI release, so it is fetched from the location in
PERIOD_SOURCE_URL and not through the KSEI client. Every step skips what is already done, so the
load can run on every start of the stack.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from ksei.config import PERIOD, Settings
from ksei.parser import parse_reference
from ksei.storage import Storage, sha256_hex
from ksei.warehouse import ClickHouse, load_reference, reference_is_loaded

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 60.0


def fetch_source(url: str, user_agent: str) -> bytes:
    """Download the file; a file-share link answers with a redirect to the real location."""
    response = httpx.get(
        url, headers={"User-Agent": user_agent}, follow_redirects=True, timeout=TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response.content


def init_period(
    settings: Settings, *, storage: Storage, ch: ClickHouse, now: Callable[[], datetime]
) -> None:
    """Make bronze.stg_period hold the calendar, doing only the steps that are still missing."""
    if not storage.exists(PERIOD.raw_key):
        data = fetch_source(settings.period_source_url, settings.user_agent)
        # parse first: a share link can answer 200 with a sign-in page, and raw is write-once
        parquet = parse_reference(PERIOD, data, PERIOD.filename, now)
        meta = {"sha256": sha256_hex(data), "source-url": settings.period_source_url}
        storage.put_raw(PERIOD.raw_key, data, meta)
        storage.put(PERIOD.parsed_key, parquet)
        log.info("stored %s (%d bytes)", PERIOD.raw_key, len(data))
    elif not storage.exists(PERIOD.parsed_key):
        raw = storage.get(PERIOD.raw_key)
        storage.put(PERIOD.parsed_key, parse_reference(PERIOD, raw, PERIOD.filename, now))
    if reference_is_loaded(ch, PERIOD):
        log.info("%s already loaded, nothing to do", PERIOD.table)
        return
    load_reference(ch, PERIOD, PERIOD.parsed_key)


def run_init_period(settings: Settings) -> None:
    init_period(
        settings,
        storage=Storage.from_settings(settings),
        ch=ClickHouse.from_settings(settings),
        now=lambda: datetime.now(UTC),
    )
