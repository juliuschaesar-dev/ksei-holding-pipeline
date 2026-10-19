"""Shared setup for the integration tests: a fixture server standing in for KSEI.

The stack's real databases are used, with fictional 2001 periods that are removed again at the
end, so real data is never touched.
"""

import threading
from collections.abc import Iterator
from datetime import UTC, date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ksei import tasks
from ksei.client import KseiClient
from ksei.config import DATASETS, Dataset, Settings
from ksei.storage import Storage
from ksei.warehouse import ClickHouse, load_bronze
from tests.smoke.conftest import read_env_file
from tests.unit.test_parser import release_zip

PERIODS = (date(2001, 1, 31), date(2001, 2, 28))
BAD_PERIOD = date(2001, 3, 31)  # only used to prove that unconvertible values fail the load
CLEANUP_PERIODS = (*PERIODS, BAD_PERIOD)
HOLDING = DATASETS["holding_composition"]
MASTER = DATASETS["master_securities"]

# The satellites carry the period, so the fictional rows (period < 2002) are found there, and the
# hubs and the link are found through them. The satellites are therefore deleted last.
FICTIONAL_LINKS = (
    "SELECT lmd5_master_securities FROM silver.satellite_master_securities "
    "WHERE period < '2002-01-01'"
)
FICTIONAL_SECURITIES = (
    "SELECT hmd5_security FROM silver.satellite_holding_composition WHERE period < '2002-01-01' "
    "UNION DISTINCT SELECT hmd5_security FROM silver.link_master_securities "
    f"WHERE lmd5_master_securities IN ({FICTIONAL_LINKS})"
)
FICTIONAL_ISINS = (
    "SELECT hmd5_isin FROM silver.link_master_securities "
    f"WHERE lmd5_master_securities IN ({FICTIONAL_LINKS})"
)
VAULT_CLEANUP = (
    f"DELETE FROM silver.hub_security WHERE hmd5_security IN ({FICTIONAL_SECURITIES})",
    f"DELETE FROM silver.hub_isin WHERE hmd5_isin IN ({FICTIONAL_ISINS})",
    "DELETE FROM silver.link_master_securities "
    f"WHERE lmd5_master_securities IN ({FICTIONAL_LINKS})",
    "DELETE FROM silver.satellite_holding_composition WHERE period < '2002-01-01'",
    "DELETE FROM silver.satellite_master_securities WHERE period < '2002-01-01'",
)
GOLD_TABLES = (
    "gold.fact_security_monthly",
    "gold.fact_holding_monthly",
    "gold.mart_foreign_ownership_monthly",
)


def holding_row(code: str, period: date) -> list[str]:
    """A holding row that satisfies the dbt data tests: totals are the sum of their parts."""
    values = ["0"] * len(HOLDING.header)
    for name, value in {
        "date": f"{period:%d-%b-%Y}".upper(),
        "code": code,
        "type": "EQUITY",
        "sec_num": "",  # empty for some securities
        "price": "10",
        "local_is": "10",
        "local_total": "10",
        "foreign_cp": "5",
        "foreign_total": "5",
    }.items():
        values[HOLDING.columns.index(name)] = value
    return values


def master_row(code: str, period: date) -> list[str]:
    values = [""] * len(MASTER.header)
    for name, value in {
        "date": f"{period:%d-%b-%Y}".upper(),
        "code": code,
        "description": f"{code} TBK",
        "type": "EQUITY",
        "isin_code": f"ID{code}",
        "issuer": f"{code}, PT",
        "status": "ACTIVE",
        "currency": "IDR",
        "form": "Electronic",
    }.items():
        values[MASTER.columns.index(name)] = value
    return values


def _zip_for(dataset: Dataset, period: date) -> bytes:
    if dataset is HOLDING:
        rows = [holding_row(f"H{period.month}{i}", period) for i in range(3)]
    else:
        rows = [master_row(f"M{period.month}{i}", period) for i in range(2)]
    return release_zip(list(dataset.header), rows)


def _filename(dataset: Dataset, period: date) -> str:
    stamp = f"{period:%Y%m%d}"
    return f"BalanceposEfek{stamp}.zip" if dataset is HOLDING else f"StatisEfek{stamp}.txt.zip"


FILES = {
    f"/Download/{_filename(ds, p)}": _zip_for(ds, p) for ds in DATASETS.values() for p in PERIODS
}


def _archive_html(dataset: Dataset) -> bytes:
    links = "".join(
        f'<a class="btn" href="/Download/{_filename(dataset, p)}">download</a>' for p in PERIODS
    )
    return (
        '<select id="ArchiveYearFilterYear"><option value="2001" selected>2001</option></select>'
        f"{links}"
    ).encode()


class FixtureKsei(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = FILES.get(self.path)
        if body is None:
            for dataset in DATASETS.values():
                if self.path == dataset.archive_path:
                    body = _archive_html(dataset)
        self.send_response(200 if body is not None else 404)
        self.end_headers()
        self.wfile.write(body or b"")

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture(scope="module")
def settings() -> Iterator[Settings]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureKsei)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = read_env_file()
    yield Settings.from_env(
        {
            **env,
            "KSEI_USER_AGENT": "integration-test",
            "KSEI_MIN_DELAY_SECONDS": "0",
            "KSEI_BASE_URL": f"http://127.0.0.1:{server.server_port}",
            "S3_ENDPOINT_URL": "http://localhost:8333",
            "CLICKHOUSE_HOST": "localhost",
        }
    )
    server.shutdown()


def _table_exists(ch: ClickHouse, table: str) -> bool:
    database, name = table.split(".")
    found = ch.execute(
        "SELECT count() FROM system.tables WHERE database = {d:String} AND name = {t:String}",
        {"d": database, "t": name},
    )
    return found.strip() == "1"


def drop_fictional_periods(ch: ClickHouse) -> None:
    """Remove the fictional periods from bronze and from every dbt table that has them."""
    for dataset in DATASETS.values():
        for period in CLEANUP_PERIODS:
            ch.execute(
                f"ALTER TABLE {dataset.table} DROP PARTITION {{p:String}}",
                {"p": period.isoformat()},
            )
    if _table_exists(ch, "silver.hub_security"):
        for statement in VAULT_CLEANUP:
            ch.execute(f"{statement} SETTINGS mutations_sync = 2")
    for table in GOLD_TABLES:
        if _table_exists(ch, table):
            ch.execute(
                f"DELETE FROM {table} WHERE period < '2002-01-01' SETTINGS mutations_sync = 2"
            )


@pytest.fixture(scope="module")
def ch(settings: Settings) -> Iterator[ClickHouse]:
    warehouse = ClickHouse.from_settings(settings)
    yield warehouse
    drop_fictional_periods(warehouse)


@pytest.fixture(scope="module")
def storage(settings: Settings) -> Iterator[Storage]:
    store = Storage.from_settings(settings)
    yield store
    for dataset in DATASETS.values():
        for period in CLEANUP_PERIODS:
            for key in store.list_keys(dataset.raw_key(period, "")):
                store._s3.delete_object(Bucket=settings.s3_bucket, Key=key)
            store._s3.delete_object(Bucket=settings.s3_bucket, Key=dataset.parsed_key(period))


def run_pipeline(settings: Settings, ch: ClickHouse, storage: Storage, dataset: Dataset) -> int:
    """Run all four steps for the dataset; return how many periods were new."""
    client = KseiClient.from_settings(settings)
    new = tasks.detect_new_periods(client, ch, dataset)
    for link in new:
        tasks.download_to_bronze(client, storage, dataset, link)
        tasks.parse_to_parquet(storage, dataset, link.period, lambda: datetime.now(UTC))
        load_bronze(ch, dataset, link.period, dataset.parsed_key(link.period))
    return len(new)


def count(ch: ClickHouse, dataset: Dataset, period: date) -> int:
    return int(
        ch.execute(
            f"SELECT count() FROM {dataset.table} WHERE _period = {{p:String}}",
            {"p": period.isoformat()},
        )
    )
