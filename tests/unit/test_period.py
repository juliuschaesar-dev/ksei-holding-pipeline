"""The one-time calendar load: source file -> SeaweedFS bronze -> ClickHouse bronze."""

import io
from datetime import UTC, datetime

import httpx
import polars as pl
import pytest
import respx
from moto import mock_aws

from ksei.config import PERIOD, Settings
from ksei.parser import ParserError
from ksei.period import fetch_source, init_period, run_init_period
from ksei.storage import Storage, ensure_buckets, sha256_hex
from ksei.warehouse import ClickHouse
from tests.unit.support import CLICKHOUSE_URL, sent_sql
from tests.unit.test_config import ENV
from tests.unit.test_parser import calendar_csv, calendar_row

pytestmark = pytest.mark.unit

SOURCE = "https://source.example/raw_period.csv"
CLICKHOUSE = CLICKHOUSE_URL
SETTINGS = Settings.from_env({**ENV, "PERIOD_SOURCE_URL": SOURCE})
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
PAYLOAD = calendar_csv([calendar_row("2000-01-01"), calendar_row("2000-01-02")])
EMPTY_TABLE = "0\n"
LOADED_TABLE = "2\n"


def clickhouse(rows_in_table: str) -> tuple[respx.Route, list[str]]:
    """A ClickHouse answering the row count with rows[0] (change it to simulate a loaded table)."""
    rows = [rows_in_table]

    def answer(request: httpx.Request) -> httpx.Response:
        counting = b"SELECT count()" in request.content
        return httpx.Response(200, text=rows[0] if counting else "")

    return respx.post(CLICKHOUSE).mock(side_effect=answer), rows


def run(storage: Storage, ch: ClickHouse) -> None:
    init_period(SETTINGS, storage=storage, ch=ch, now=lambda: NOW)


@respx.mock
def test_fetch_source_follows_the_redirect_of_a_file_share_link() -> None:
    respx.get(SOURCE).respond(303, headers={"location": "https://files.example/raw_period.csv"})
    respx.get("https://files.example/raw_period.csv").respond(200, content=b"a,b\r\n")

    assert fetch_source(SOURCE, SETTINGS.user_agent) == b"a,b\r\n"


@respx.mock
def test_fetch_source_sends_the_descriptive_user_agent() -> None:
    route = respx.get(SOURCE).respond(200, content=b"x")

    fetch_source(SOURCE, "test-agent/1.0")

    assert route.calls.last.request.headers["user-agent"] == "test-agent/1.0"


@respx.mock
def test_fetch_source_raises_when_the_server_refuses() -> None:
    respx.get(SOURCE).respond(404)

    with pytest.raises(httpx.HTTPStatusError):
        fetch_source(SOURCE, SETTINGS.user_agent)


@respx.mock
def test_first_run_stores_the_file_untouched_with_its_checksum_and_source(
    storage: Storage, ch: ClickHouse
) -> None:
    respx.get(SOURCE).respond(200, content=PAYLOAD)
    clickhouse(EMPTY_TABLE)

    run(storage, ch)

    assert storage.get(PERIOD.raw_key) == PAYLOAD
    assert storage.metadata(PERIOD.raw_key) == {"sha256": sha256_hex(PAYLOAD), "source-url": SOURCE}


@respx.mock
def test_first_run_writes_the_all_strings_parquet_next_to_it(
    storage: Storage, ch: ClickHouse
) -> None:
    respx.get(SOURCE).respond(200, content=PAYLOAD)
    clickhouse(EMPTY_TABLE)

    run(storage, ch)

    frame = pl.read_parquet(io.BytesIO(storage.get(PERIOD.parsed_key)))
    assert frame["date_actual"].to_list() == ["2000-01-01", "2000-01-02"]
    assert set(frame.schema.values()) == {pl.String}
    assert frame["_ingested_at"][0] == NOW.isoformat()


@respx.mock
def test_first_run_loads_the_parquet_into_the_bronze_table(
    storage: Storage, ch: ClickHouse
) -> None:
    respx.get(SOURCE).respond(200, content=PAYLOAD)
    route, _ = clickhouse(EMPTY_TABLE)

    run(storage, ch)

    statements = sent_sql(route)
    assert "TRUNCATE TABLE bronze.stg_period" in statements
    insert = next(
        i for i, sql in enumerate(statements) if sql.startswith("INSERT INTO bronze.stg_period")
    )
    assert route.calls[insert].request.url.params["param_key"] == PERIOD.parsed_key


@respx.mock
def test_a_second_run_downloads_and_loads_nothing(storage: Storage, ch: ClickHouse) -> None:
    source = respx.get(SOURCE).respond(200, content=PAYLOAD)
    route, rows = clickhouse(EMPTY_TABLE)
    run(storage, ch)
    rows[0], calls_of_first_run = LOADED_TABLE, route.call_count

    run(storage, ch)

    assert source.call_count == 1
    second_run = sent_sql(route)[calls_of_first_run:]
    assert not any(sql.startswith(("TRUNCATE", "INSERT")) for sql in second_run)


@respx.mock
def test_an_empty_table_is_reloaded_from_the_stored_file_without_downloading(
    storage: Storage, ch: ClickHouse
) -> None:
    storage.put_raw(PERIOD.raw_key, PAYLOAD, {})
    source = respx.get(SOURCE).respond(200, content=b"must not be fetched")
    route, _ = clickhouse(EMPTY_TABLE)

    run(storage, ch)

    assert source.call_count == 0
    assert any(sql.startswith("INSERT INTO bronze.stg_period") for sql in sent_sql(route))
    assert storage.exists(PERIOD.parsed_key)  # rebuilt from the raw file


@respx.mock
def test_a_page_that_is_not_the_calendar_is_rejected_before_anything_is_stored(
    storage: Storage, ch: ClickHouse
) -> None:
    respx.get(SOURCE).respond(200, content=b"<html><title>Sign in</title></html>")
    clickhouse(EMPTY_TABLE)

    with pytest.raises(ParserError, match="unexpected header for period"):
        run(storage, ch)

    assert not storage.exists(PERIOD.raw_key)  # the raw object is write-once, so keep it clean


@respx.mock
def test_run_init_period_builds_its_clients_from_the_settings() -> None:
    # moto only intercepts AWS addresses, so S3 uses one in this test
    settings = Settings.from_env(
        {
            **ENV,
            "PERIOD_SOURCE_URL": SOURCE,
            "S3_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com",
        }
    )
    respx.get(SOURCE).respond(200, content=PAYLOAD)
    route, _ = clickhouse(EMPTY_TABLE)

    with mock_aws():
        ensure_buckets(settings)
        run_init_period(settings)

        assert Storage.from_settings(settings).exists(PERIOD.raw_key)
    assert any(sql.startswith("INSERT INTO bronze.stg_period") for sql in sent_sql(route))
