"""The functions the DAG tasks call: primitives in (strings from XCom), primitives out."""

from datetime import date
from pathlib import Path

import pytest
import respx
from moto import mock_aws

from ksei.config import DATASETS, Settings
from ksei.storage import Storage, ensure_buckets, s3_client
from ksei.tasks import run_detect, run_download, run_load, run_parse
from tests.unit.test_config import ENV
from tests.unit.test_parser import holding_row, release_zip

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
HOLDING = DATASETS["holding_composition"]
KSEI = "https://ksei.example"
CLICKHOUSE = "http://ch.local:8123"
# moto only intercepts AWS addresses, so S3 uses one in these tests
SETTINGS = Settings.from_env(
    {
        **ENV,
        "KSEI_BASE_URL": KSEI,
        "KSEI_MIN_DELAY_SECONDS": "0",
        "S3_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com",
    }
)
PERIOD = "2026-09-30"
ZIP_URL = f"{KSEI}/Download/BalanceposEfek20260930.zip"
RAW_KEY = HOLDING.raw_key(date(2026, 9, 30), "BalanceposEfek20260930.zip")


@pytest.fixture
def storage():
    with mock_aws():
        ensure_buckets(SETTINGS)
        yield Storage(s3_client(SETTINGS.s3_endpoint_url, "k", "s"), SETTINGS.s3_bucket)


@respx.mock
def test_run_detect_returns_the_unloaded_periods_as_plain_strings() -> None:
    page = (FIXTURES / "archive_holding_2025.html").read_text(encoding="utf-8")
    respx.get(f"{KSEI}{HOLDING.archive_path}").respond(200, text=page.replace("2026", "2025"))
    respx.get(f"{KSEI}{HOLDING.archive_path}/2026").respond(200, text="")  # not offered any more
    respx.post(CLICKHOUSE).respond(200, text="")  # nothing loaded yet

    result = run_detect(SETTINGS, HOLDING)

    assert result == [
        {"period": "2025-12-30", "url": f"{KSEI}/Download/BalanceposEfek20251230.zip"}
    ]


@respx.mock
def test_run_download_stores_the_zip_and_returns_the_period(storage: Storage) -> None:
    respx.get(ZIP_URL).respond(200, content=b"zip-bytes")

    period = run_download(SETTINGS, HOLDING, {"period": PERIOD, "url": ZIP_URL})

    assert period == PERIOD
    assert storage.get(RAW_KEY) == b"zip-bytes"


def test_run_parse_writes_the_parquet_and_returns_the_period(storage: Storage) -> None:
    storage.put(RAW_KEY, release_zip(list(HOLDING.header), [holding_row("AAAA")]))

    period = run_parse(SETTINGS, HOLDING, PERIOD)

    assert period == PERIOD
    assert storage.exists(HOLDING.parsed_key(date(2026, 9, 30)))


@respx.mock
def test_run_load_loads_the_parsed_file_of_the_period_and_returns_it() -> None:
    route = respx.post(CLICKHOUSE).respond(200, text="")

    period = run_load(SETTINGS, HOLDING, PERIOD)

    assert period == PERIOD
    inserts = [
        c.request.content.decode()
        for c in route.calls
        if "INSERT INTO" in c.request.content.decode()
    ]
    assert len(inserts) == 1
    assert route.calls.last.request.url.params["param_key"] == HOLDING.parsed_key(date(2026, 9, 30))
