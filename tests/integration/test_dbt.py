"""dbt against the running stack, on the fictional 2001 periods the pipeline loads into bronze.

Runs the same commands as `make dbt-build` and `make dbt-test`. Digests are limited to the
fictional periods, so real data in the same tables does not matter.
"""

import subprocess

import httpx
import pytest
from tools.dbt import run

from ksei.config import DATASETS, Settings
from ksei.config import DATASETS as REGISTRY
from ksei.storage import Storage
from ksei.warehouse import ClickHouse, load_bronze
from tests.integration.conftest import (
    FICTIONAL_ISINS,
    FICTIONAL_LINKS,
    FICTIONAL_SECURITIES,
    run_pipeline,
)

pytestmark = pytest.mark.integration

# table -> (rows that belong to the fictional periods, columns left out of the hash).
# load_timestamp changes whenever a vault table is rebuilt, so it is not part of the comparison.
TABLES = {
    "silver.hub_security": (f"hmd5_security IN ({FICTIONAL_SECURITIES})", "load_timestamp"),
    "silver.hub_isin": (f"hmd5_isin IN ({FICTIONAL_ISINS})", "load_timestamp"),
    "silver.link_master_securities": (
        f"lmd5_master_securities IN ({FICTIONAL_LINKS})",
        "load_timestamp",
    ),
    "silver.satellite_master_securities": ("period < '2002-01-01'", "load_timestamp"),
    "silver.satellite_holding_composition": ("period < '2002-01-01'", "load_timestamp"),
    "gold.dim_period": ("1", ""),  # the whole calendar: it has no fictional rows
    "gold.fact_security_monthly": ("period < '2002-01-01'", ""),
    "gold.fact_holding_monthly": ("period < '2002-01-01'", ""),
    "gold.mart_foreign_ownership_monthly": ("period < '2002-01-01'", ""),
}


def dbt(*args: str) -> subprocess.CompletedProcess[str]:
    return run(list(args))


def digests(settings: Settings) -> dict[str, str]:
    """Row count and an order-independent hash of the fictional rows of every dbt table."""
    out = {}
    for table, (condition, left_out) in TABLES.items():
        columns = f"* EXCEPT ({left_out})" if left_out else "*"
        response = httpx.post(
            settings.clickhouse_url,
            content=(
                "SELECT count(), sum(cityHash64(toString(tuple(*)))) FROM "
                f"(SELECT {columns} FROM {table} WHERE {condition}) FORMAT TSV"
            ),
            auth=(settings.clickhouse_user, settings.clickhouse_password),
            timeout=60,
        )
        assert response.status_code == 200, response.text
        out[table] = response.text.strip()
    return out


@pytest.fixture(scope="module")
def first_build(settings: Settings, ch: ClickHouse, storage: Storage) -> dict[str, str]:
    for dataset in DATASETS.values():
        run_pipeline(settings, ch, storage, dataset)
    result = dbt("build", "--exclude", "test_type:unit")
    assert result.returncode == 0, result.stdout[-3000:]
    return digests(settings)


def test_models_build_from_bronze_and_every_data_test_passes(first_build: dict[str, str]) -> None:
    empty = [table for table, value in first_build.items() if value.startswith("0\t")]
    assert not empty, f"no fictional rows in: {empty}"


def test_unit_tests_pass() -> None:
    result = dbt("test", "--select", "test_type:unit")

    assert result.returncode == 0, result.stdout[-3000:]


def test_rerunning_the_build_leaves_every_table_identical(
    settings: Settings, first_build: dict[str, str]
) -> None:
    result = dbt("build", "--exclude", "test_type:unit")

    assert result.returncode == 0, result.stdout[-3000:]
    assert digests(settings) == first_build


def test_an_incremental_build_equals_a_full_rebuild(
    settings: Settings, first_build: dict[str, str]
) -> None:
    result = dbt("build", "--exclude", "test_type:unit", "--full-refresh")

    assert result.returncode == 0, result.stdout[-3000:]
    assert digests(settings) == first_build


# --- what the satellites do when the source changes, loses a row, or gets it back -----------------
# These mutate the fictional periods in bronze and put them back, so they run last: the satellites
# keep the history they record, which the digest comparisons above must not see.

MASTER = REGISTRY["master_securities"]
FIRST_PERIOD, SECOND_PERIOD = "2001-01-31", "2001-02-28"
UPDATE_TABLE = MASTER.table
MASTER_SATELLITE_VERSIONS = """
SELECT s.meta_is_active, s.is_deleted, s.sector
FROM silver.satellite_master_securities AS s
INNER JOIN silver.link_master_securities AS l ON s.lmd5_master_securities = l.lmd5_master_securities
INNER JOIN silver.hub_security AS h ON l.hmd5_security = h.hmd5_security
WHERE h.code = {code:String} AND s.period = {period:String}
ORDER BY s.load_timestamp, s.md5_diff
FORMAT TSV
"""


def versions(ch: ClickHouse, code: str, period: str) -> list[tuple[str, ...]]:
    """(meta_is_active, is_deleted, sector) of every satellite row of a code in a period."""
    text = ch.execute(MASTER_SATELLITE_VERSIONS, {"code": code, "period": period})
    return [tuple(line.split("	")) for line in text.splitlines()]


def in_security_fact(ch: ClickHouse, code: str, period: str) -> bool:
    count = ch.execute(
        "SELECT count() FROM gold.fact_security_monthly WHERE security_code = {c:String} "
        "AND period = {p:String} FORMAT TSV",
        {"c": code, "p": period},
    )
    return count.strip() == "1"


def rebuild() -> None:
    result = dbt("build", "--exclude", "test_type:unit")
    assert result.returncode == 0, result.stdout[-3000:]


def restore_period(ch: ClickHouse, storage: Storage, period: str) -> None:
    from datetime import date

    day = date.fromisoformat(period)
    load_bronze(ch, MASTER, day, MASTER.parsed_key(day))


def test_a_changed_source_value_becomes_the_new_active_version_and_a_return_is_recorded(
    settings: Settings, ch: ClickHouse, storage: Storage, first_build: dict[str, str]
) -> None:
    assert versions(ch, "M10", FIRST_PERIOD) == [("1", "0", "")]

    try:
        ch.execute(
            f"ALTER TABLE {UPDATE_TABLE} UPDATE sector = 'CHANGED' "
            f"WHERE code = 'M10' AND _period = '{FIRST_PERIOD}' SETTINGS mutations_sync = 2"
        )
        rebuild()
        assert versions(ch, "M10", FIRST_PERIOD) == [("0", "0", ""), ("1", "0", "CHANGED")]
    finally:
        restore_period(ch, storage, FIRST_PERIOD)  # back to the original value: A -> B -> A
    rebuild()
    assert versions(ch, "M10", FIRST_PERIOD) == [
        ("0", "0", ""),
        ("0", "0", "CHANGED"),
        ("1", "0", ""),
    ]


def test_a_row_missing_from_the_source_is_flagged_deleted_and_restored_when_it_returns(
    settings: Settings, ch: ClickHouse, storage: Storage, first_build: dict[str, str]
) -> None:
    assert in_security_fact(ch, "M21", SECOND_PERIOD)

    try:
        ch.execute(f"DELETE FROM {UPDATE_TABLE} WHERE code = 'M21' AND _period = '{SECOND_PERIOD}'")
        rebuild()
        assert versions(ch, "M21", SECOND_PERIOD) == [("0", "0", ""), ("1", "1", "")]
        assert not in_security_fact(ch, "M21", SECOND_PERIOD)
    finally:
        restore_period(ch, storage, SECOND_PERIOD)  # the row comes back
    rebuild()
    assert versions(ch, "M21", SECOND_PERIOD) == [("0", "0", ""), ("0", "1", ""), ("1", "0", "")]
    assert in_security_fact(ch, "M21", SECOND_PERIOD)
