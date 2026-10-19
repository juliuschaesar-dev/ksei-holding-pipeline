from datetime import date

import pytest

from ksei.config import DATASETS, PERIOD, ConfigError, Settings

pytestmark = pytest.mark.unit

ENV = {
    "KSEI_USER_AGENT": "test-agent/1.0",
    "KSEI_MIN_DELAY_SECONDS": "2.5",
    "S3_ENDPOINT_URL": "http://s3.local",
    "S3_ACCESS_KEY": "key",
    "S3_SECRET_KEY": "secret",
    "S3_BUCKET": "lake",
    "S3_LOGS_BUCKET": "logs",
    "CLICKHOUSE_HOST": "ch.local",
    "CLICKHOUSE_HTTP_PORT": "8123",
    "CLICKHOUSE_PIPELINE_USER": "test-user",
    "CLICKHOUSE_PIPELINE_PASSWORD": "pw",
    "KSEI_BASE_URL": "https://ksei.example",
    "PERIOD_SOURCE_URL": "https://source.example/raw_period.csv",
}


def test_settings_read_values_from_env() -> None:
    settings = Settings.from_env(ENV)
    assert settings.user_agent == "test-agent/1.0"
    assert settings.min_delay_seconds == 2.5
    assert settings.s3_bucket == "lake"


def test_settings_read_clickhouse_values_and_the_ksei_base_url() -> None:
    settings = Settings.from_env(ENV)
    assert settings.clickhouse_url == "http://ch.local:8123"
    assert settings.clickhouse_user == "test-user"
    assert settings.ksei_base_url == "https://ksei.example"


def test_settings_read_the_period_source_url() -> None:
    assert Settings.from_env(ENV).period_source_url == "https://source.example/raw_period.csv"


@pytest.mark.parametrize("name", list(ENV))
def test_every_setting_is_required_and_a_missing_one_is_named_in_the_error(name: str) -> None:
    env = {k: v for k, v in ENV.items() if k != name}
    with pytest.raises(ConfigError, match=name):
        Settings.from_env(env)


def test_registry_has_both_datasets() -> None:
    assert set(DATASETS) == {"master_securities", "holding_composition"}


@pytest.mark.parametrize("name", ["master_securities", "holding_composition"])
def test_registry_entries_are_complete(name: str) -> None:
    ds = DATASETS[name]
    assert ds.name == name
    assert ds.archive_path == f"/archive_download/{name}"
    assert ds.table == f"bronze.stg_{name}"
    assert ds.link_pattern.groups == 1


def test_bronze_keys_render_for_a_period() -> None:
    ds = DATASETS["holding_composition"]
    period = date(2026, 9, 30)
    assert (
        ds.raw_key(period, "BalanceposEfek20260930.zip")
        == "bronze/holding_composition/raw/year=2026/month=09/BalanceposEfek20260930.zip"
    )
    assert (
        ds.parsed_key(period) == "bronze/holding_composition/parsed/year=2026/month=09/data.parquet"
    )


def column_types(name: str) -> dict[str, str]:
    return {c.name: c.type for c in DATASETS[name].schema}


def test_every_column_has_a_header_a_name_and_a_clickhouse_type() -> None:
    for dataset in DATASETS.values():
        assert all(c.header and c.name and c.type for c in dataset.schema)
        assert dataset.header == tuple(c.header for c in dataset.schema)
        assert dataset.columns == tuple(c.name for c in dataset.schema)


def optional_columns(name: str) -> set[str]:
    return {c.name for c in DATASETS[name].schema if c.optional}


def test_holding_composition_types() -> None:
    types = column_types("holding_composition")
    assert types["date"] == "Date"
    assert types["type"] == "String"
    assert types["sec_num"] == "Int64"
    assert types["price"] == "Float64"
    assert types["local_total"] == types["foreign_id"] == "Int64"
    assert optional_columns("holding_composition") == {"sec_num"}  # empty for some securities


def test_master_securities_types() -> None:
    types = column_types("master_securities")
    assert types["listing_date"] == "Date"
    assert types["stock_exchange"] == "String"
    assert types["interest"] == "Float64"
    assert types["local_pct"] == "Float64"
    assert types["num_of_sec"] == "Int64"
    assert types["issuer"] == "String"
    assert {"listing_date", "stock_exchange", "interest", "num_of_sec"} <= optional_columns(
        "master_securities"
    )
    assert not {"code", "date", "issuer", "type"} & optional_columns("master_securities")


def test_only_plain_standard_column_types_are_used() -> None:
    allowed = {"String", "Int64", "Float64", "Date", "DateTime"}
    for dataset in DATASETS.values():
        for column in dataset.schema:
            assert column.type in allowed, f"{column.name}: {column.type}"


def test_period_reference_names_its_table_and_its_bronze_keys() -> None:
    assert PERIOD.table == "bronze.stg_period"
    assert PERIOD.raw_key == "bronze/period/raw/raw_period.csv"
    assert PERIOD.parsed_key == "bronze/period/parsed/data.parquet"


def test_period_reference_declares_the_calendar_columns_with_their_types() -> None:
    types = {c.name: c.type for c in PERIOD.schema}

    assert len(PERIOD.schema) == 26
    assert PERIOD.header == PERIOD.columns  # the file's headers are already the column names
    assert types["date_actual"] == "Date"
    assert types["date_actual_time"] == "DateTime"
    assert types["day_name"] == "String"
    assert types["day_of_week"] == types["year_actual"] == types["weekend_flag"] == "Int64"
    assert types["first_day_of_month"] == types["last_day_of_year"] == "Date"
    assert PERIOD.date_format == "%Y-%m-%d"


def test_period_reference_allows_only_the_iso_week_to_be_empty() -> None:
    assert {c.name for c in PERIOD.schema if c.optional} == {"week_of_year_iso"}
    assert all(c.type in {"String", "Int64", "Float64", "Date", "DateTime"} for c in PERIOD.schema)
