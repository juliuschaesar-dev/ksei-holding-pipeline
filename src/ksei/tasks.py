"""Task logic called by the Airflow DAG; the DAG file only wires these together."""

import logging
import posixpath
from collections.abc import Callable
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

from ksei.client import KseiClient, Link
from ksei.config import Dataset, Settings
from ksei.parser import parse_release
from ksei.storage import Storage, sha256_hex
from ksei.warehouse import ClickHouse, load_bronze, loaded_periods

log = logging.getLogger(__name__)


def download_to_bronze(client: KseiClient, storage: Storage, dataset: Dataset, link: Link) -> str:
    """Store the release zip under bronze/raw. Returns its key; a no-op if already stored."""
    filename = posixpath.basename(urlsplit(link.url).path)
    key = dataset.raw_key(link.period, filename)
    if storage.exists(key):
        log.info("bronze raw already present, skipping download: %s", key)
        return key
    data = client.download(link.url)
    storage.put_raw(key, data, {"sha256": sha256_hex(data), "source-url": link.url})
    log.info("stored %s (%d bytes)", key, len(data))
    return key


def parse_to_parquet(
    storage: Storage, dataset: Dataset, period: date, now: Callable[[], datetime]
) -> str:
    """Parse the stored raw zip of a period into bronze/parsed. Returns the parquet key."""
    prefix = dataset.raw_key(period, "")
    raw_keys = storage.list_keys(prefix)
    if len(raw_keys) != 1:
        raise FileNotFoundError(f"expected one raw file under {prefix}, found {len(raw_keys)}")
    raw_key = raw_keys[0]
    parquet = parse_release(dataset, storage.get(raw_key), posixpath.basename(raw_key), period, now)
    key = dataset.parsed_key(period)
    storage.put(key, parquet)
    log.info("parsed %s -> %s", raw_key, key)
    return key


def detect_new_periods(client: KseiClient, ch: ClickHouse, dataset: Dataset) -> list[Link]:
    """Archive links whose period is not yet loaded into the bronze table (oldest first)."""
    loaded = loaded_periods(ch, dataset)
    return [link for link in client.list_links(dataset) if link.period not in loaded]


# Entry points for the Airflow tasks: strings in (they come from XCom), strings out. The DAG file
# only wires these together; clients are built here, from the settings of the task's environment.


def run_detect(settings: Settings, dataset: Dataset) -> list[dict[str, str]]:
    links = detect_new_periods(
        KseiClient.from_settings(settings), ClickHouse.from_settings(settings), dataset
    )
    return [{"period": link.period.isoformat(), "url": link.url} for link in links]


def run_download(settings: Settings, dataset: Dataset, link: dict[str, str]) -> str:
    period = date.fromisoformat(link["period"])
    download_to_bronze(
        KseiClient.from_settings(settings),
        Storage.from_settings(settings),
        dataset,
        Link(dataset.name, period, link["url"]),
    )
    return link["period"]


def run_parse(settings: Settings, dataset: Dataset, period: str) -> str:
    parse_to_parquet(
        Storage.from_settings(settings),
        dataset,
        date.fromisoformat(period),
        lambda: datetime.now(UTC),
    )
    return period


def run_load(settings: Settings, dataset: Dataset, period: str) -> str:
    day = date.fromisoformat(period)
    load_bronze(ClickHouse.from_settings(settings), dataset, day, dataset.parsed_key(day))
    return period
