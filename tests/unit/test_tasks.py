from datetime import date

import pytest
import respx

from ksei.client import KseiClient, Link
from ksei.config import DATASETS
from ksei.storage import Storage, sha256_hex
from ksei.tasks import download_to_bronze

pytestmark = pytest.mark.unit

URL = "https://web.ksei.co.id/Download/BalanceposEfek20260930.zip"
LINK = Link("holding_composition", date(2026, 9, 30), URL)
EXPECTED_KEY = "bronze/holding_composition/raw/year=2026/month=09/BalanceposEfek20260930.zip"


@pytest.fixture
def client() -> KseiClient:
    return KseiClient("test-agent", 0.0, base_url="https://ksei.example", sleep=lambda _s: None)


@respx.mock
def test_download_to_bronze_stores_the_zip_with_checksum_metadata(
    client: KseiClient, storage: Storage
) -> None:
    respx.get(URL).respond(200, content=b"zip-bytes")

    key = download_to_bronze(client, storage, DATASETS["holding_composition"], LINK)

    assert key == EXPECTED_KEY
    assert storage.get(key) == b"zip-bytes"
    assert storage.metadata(key) == {"sha256": sha256_hex(b"zip-bytes"), "source-url": URL}


@respx.mock
def test_download_to_bronze_is_a_noop_when_the_period_already_exists(
    client: KseiClient, storage: Storage
) -> None:
    route = respx.get(URL).respond(200, content=b"zip-bytes")
    dataset = DATASETS["holding_composition"]

    download_to_bronze(client, storage, dataset, LINK)
    key = download_to_bronze(client, storage, dataset, LINK)

    assert key == EXPECTED_KEY
    assert route.call_count == 1


class StubClient:
    def __init__(self, links: list[Link]) -> None:
        self._links = links

    def list_links(self, _dataset):
        return self._links


def test_detect_new_periods_returns_only_links_not_yet_loaded(monkeypatch) -> None:
    from ksei import tasks

    older = Link("holding_composition", date(2026, 8, 31), "http://x/BalanceposEfek20260831.zip")
    monkeypatch.setattr(tasks, "loaded_periods", lambda _ch, _ds: {date(2026, 8, 31)})

    new = tasks.detect_new_periods(
        StubClient([older, LINK]), object(), DATASETS["holding_composition"]
    )

    assert new == [LINK]


def test_detect_new_periods_is_empty_when_everything_is_loaded(monkeypatch) -> None:
    from ksei import tasks

    monkeypatch.setattr(tasks, "loaded_periods", lambda _ch, _ds: {LINK.period})

    assert (
        tasks.detect_new_periods(StubClient([LINK]), object(), DATASETS["holding_composition"])
        == []
    )
