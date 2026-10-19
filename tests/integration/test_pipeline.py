"""Pipeline against the running stack (`make up`), with a fixture server standing in for KSEI.

The fixture server, fictional 2001 periods and cleanup live in conftest.py.
"""

import json
from datetime import UTC, datetime

import pytest

from ksei.config import DATASETS, Dataset, Settings
from ksei.parser import parse_release
from ksei.storage import Storage
from ksei.warehouse import LINEAGE, ClickHouse, WarehouseError, load_bronze
from tests.integration.conftest import (
    BAD_PERIOD,
    HOLDING,
    MASTER,
    PERIODS,
    count,
    holding_row,
    run_pipeline,
)
from tests.unit.test_parser import release_zip

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("dataset", list(DATASETS.values()), ids=list(DATASETS))
def test_one_run_lands_the_expected_rows_in_bronze(
    settings: Settings, ch: ClickHouse, storage: Storage, dataset: Dataset
) -> None:
    assert run_pipeline(settings, ch, storage, dataset) == 2

    expected = 3 if dataset is HOLDING else 2
    assert [count(ch, dataset, p) for p in PERIODS] == [expected, expected]


@pytest.mark.parametrize("dataset", list(DATASETS.values()), ids=list(DATASETS))
def test_a_second_run_finds_nothing_new_and_leaves_row_counts_unchanged(
    settings: Settings, ch: ClickHouse, storage: Storage, dataset: Dataset
) -> None:
    run_pipeline(settings, ch, storage, dataset)
    before = [count(ch, dataset, p) for p in PERIODS]

    assert run_pipeline(settings, ch, storage, dataset) == 0

    assert [count(ch, dataset, p) for p in PERIODS] == before


@pytest.mark.parametrize("dataset", list(DATASETS.values()), ids=list(DATASETS))
def test_reloading_a_period_does_not_duplicate_rows(
    settings: Settings, ch: ClickHouse, storage: Storage, dataset: Dataset
) -> None:
    run_pipeline(settings, ch, storage, dataset)
    period = PERIODS[0]
    before = count(ch, dataset, period)

    load_bronze(ch, dataset, period, dataset.parsed_key(period))
    load_bronze(ch, dataset, period, dataset.parsed_key(period))

    assert count(ch, dataset, period) == before


def scalar(ch: ClickHouse, sql: str, **params: str) -> str:
    return ch.execute(f"{sql} FORMAT TSV", params).strip()


@pytest.mark.parametrize("dataset", list(DATASETS.values()), ids=list(DATASETS))
def test_bronze_table_columns_have_the_registry_types(
    settings: Settings, ch: ClickHouse, storage: Storage, dataset: Dataset
) -> None:
    run_pipeline(settings, ch, storage, dataset)
    database, table = dataset.table.split(".")

    rows = ch.execute(
        "SELECT name, type FROM system.columns WHERE database = {d:String} AND table = {t:String} "
        "ORDER BY position FORMAT JSONCompact",
        {"d": database, "t": table},
    )

    actual = [tuple(row) for row in json.loads(rows)["data"]]
    expected = [(c.name, c.type) for c in dataset.schema] + [(n, t) for n, t, _ in LINEAGE]
    assert actual == expected


def test_holding_values_are_typed_and_empty_optional_cells_become_zero(
    settings: Settings, ch: ClickHouse, storage: Storage
) -> None:
    run_pipeline(settings, ch, storage, HOLDING)
    where = "WHERE _period = '2001-01-31'"

    assert scalar(ch, f"SELECT min(date) FROM {HOLDING.table} {where}") == "2001-01-31"
    assert scalar(ch, f"SELECT countIf(sec_num = 0) FROM {HOLDING.table} {where}") == "3"
    assert scalar(ch, f"SELECT sum(local_total) FROM {HOLDING.table} {where}") == "30"
    assert scalar(ch, f"SELECT toTypeName(price) FROM {HOLDING.table} LIMIT 1") == ("Float64")


def test_master_empty_optional_fields_take_the_type_default(
    settings: Settings, ch: ClickHouse, storage: Storage
) -> None:
    run_pipeline(settings, ch, storage, MASTER)
    where = "WHERE _period = '2001-01-31'"

    assert (
        scalar(
            ch, f"SELECT countIf(listing_date = toDate('1970-01-01')) FROM {MASTER.table} {where}"
        )
        == "2"
    )
    assert scalar(ch, f"SELECT countIf(stock_exchange = '') FROM {MASTER.table} {where}") == ("2")
    assert scalar(ch, f"SELECT min(date) FROM {MASTER.table} {where}") == "2001-01-31"


def test_a_value_that_cannot_be_converted_fails_the_load_loudly(
    settings: Settings, ch: ClickHouse, storage: Storage
) -> None:
    row = holding_row("BAD", BAD_PERIOD)
    row[HOLDING.columns.index("price")] = "abc"
    parquet = parse_release(
        HOLDING,
        release_zip(list(HOLDING.header), [row]),
        "bad.zip",
        BAD_PERIOD,
        lambda: datetime.now(UTC),
    )
    storage.put(HOLDING.parsed_key(BAD_PERIOD), parquet)

    with pytest.raises(WarehouseError, match="abc"):
        load_bronze(ch, HOLDING, BAD_PERIOD, HOLDING.parsed_key(BAD_PERIOD))

    assert count(ch, HOLDING, BAD_PERIOD) == 0
