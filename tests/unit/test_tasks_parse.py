import io
from datetime import UTC, datetime

import polars as pl
import pytest

from ksei.config import DATASETS
from ksei.storage import Storage
from ksei.tasks import parse_to_parquet
from tests.unit.test_parser import holding_row, release_zip

pytestmark = pytest.mark.unit

HOLDING = DATASETS["holding_composition"]
PERIOD = datetime(2026, 9, 30).date()
RAW_KEY = HOLDING.raw_key(PERIOD, "BalanceposEfek20260930.zip")


def now() -> datetime:
    return datetime(2026, 10, 7, tzinfo=UTC)


def test_parse_to_parquet_writes_the_parsed_object_next_to_the_raw_one(storage: Storage) -> None:
    storage.put(RAW_KEY, release_zip(list(HOLDING.header), [holding_row("AADI")]))

    key = parse_to_parquet(storage, HOLDING, PERIOD, now)

    assert key == "bronze/holding_composition/parsed/year=2026/month=09/data.parquet"
    df = pl.read_parquet(io.BytesIO(storage.get(key)))
    assert df["code"].to_list() == ["AADI"]
    assert df["_source_file"][0] == "BalanceposEfek20260930.zip"


def test_parse_to_parquet_can_be_rerun_and_replaces_the_output(storage: Storage) -> None:
    storage.put(RAW_KEY, release_zip(list(HOLDING.header), [holding_row("AADI")]))

    first = parse_to_parquet(storage, HOLDING, PERIOD, now)
    second = parse_to_parquet(storage, HOLDING, PERIOD, now)

    assert first == second
    assert len(storage.list_keys("bronze/holding_composition/parsed/")) == 1


def test_parse_to_parquet_fails_when_the_raw_file_is_missing(storage: Storage) -> None:
    with pytest.raises(FileNotFoundError, match="year=2026/month=09"):
        parse_to_parquet(storage, HOLDING, PERIOD, now)
