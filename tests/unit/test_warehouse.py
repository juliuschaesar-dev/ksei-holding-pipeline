from datetime import date

import pytest
import respx

from ksei.config import DATASETS, Settings
from ksei.config import PERIOD as CALENDAR
from ksei.warehouse import (
    ClickHouse,
    WarehouseError,
    ensure_reference_table,
    ensure_table,
    load_bronze,
    load_reference,
    loaded_periods,
    reference_is_loaded,
)
from tests.unit.support import CLICKHOUSE_URL, sent_sql
from tests.unit.test_config import ENV

pytestmark = pytest.mark.unit

URL = CLICKHOUSE_URL
HOLDING = DATASETS["holding_composition"]
PERIOD = date(2026, 9, 30)
PARSED_KEY = "bronze/holding_composition/parsed/year=2026/month=09/data.parquet"


@respx.mock
def test_execute_posts_the_sql_with_basic_auth_and_returns_the_body(ch: ClickHouse) -> None:
    route = respx.post(URL).respond(200, text="42\n")

    assert ch.execute("SELECT 42") == "42\n"

    request = route.calls.last.request
    assert request.content == b"SELECT 42"
    assert request.headers["authorization"].startswith("Basic ")


@respx.mock
def test_execute_passes_parameters_as_query_params(ch: ClickHouse) -> None:
    route = respx.post(URL).respond(200, text="")

    ch.execute("SELECT {k:String}", {"k": "a/b"})

    assert route.calls.last.request.url.params["param_k"] == "a/b"


@respx.mock
def test_execute_raises_with_the_clickhouse_error_message(ch: ClickHouse) -> None:
    respx.post(URL).respond(500, text="Code: 62. DB::Exception: Syntax error")

    with pytest.raises(WarehouseError, match="Syntax error"):
        ch.execute("SELEKT 1")


@respx.mock
def test_ensure_table_creates_a_typed_table_from_the_registry(ch: ClickHouse) -> None:
    route = respx.post(URL).respond(200, text="")

    ensure_table(ch, HOLDING)

    (sql,) = sent_sql(route)
    assert "CREATE TABLE IF NOT EXISTS bronze.stg_holding_composition (" in sql
    assert "`date` Date," in sql
    assert "`sec_num` Int64," in sql
    assert "`price` Float64," in sql
    assert "`type` String," in sql
    assert "`_period` Date," in sql
    assert "`_ingested_at` DateTime" in sql
    assert "Nullable" not in sql
    assert "PARTITION BY _period" in sql


@respx.mock
def test_load_converts_each_column_to_its_type_in_the_insert(ch: ClickHouse) -> None:
    route = respx.post(URL).respond(200, text="")

    load_bronze(ch, HOLDING, PERIOD, PARSED_KEY)

    insert = sent_sql(route)[-1]
    assert "toDate(parseDateTime(`date`, '%d-%b-%Y'))" in insert
    assert "accurateCast(if(`sec_num` = '', '0', `sec_num`), 'Int64')" in insert
    assert "accurateCast(`price`, 'Float64')" in insert
    assert "toDate(`_period`)" in insert
    assert "parseDateTimeBestEffort(`_ingested_at`, 'UTC')" in insert


@respx.mock
def test_load_replaces_empty_optional_cells_with_the_type_default(ch: ClickHouse) -> None:
    route = respx.post(URL).respond(200, text="")

    load_bronze(ch, DATASETS["master_securities"], PERIOD, PARSED_KEY)

    insert = sent_sql(route)[-1]
    assert "Nullable" not in insert and "nullIf" not in insert
    assert "`stock_exchange`," in insert  # an empty string stays an empty string
    assert "accurateCast(if(`interest` = '', '0', `interest`), 'Float64')" in insert
    # an empty date becomes 1970-01-01; real values that do not parse still raise
    assert (
        "toDate(parseDateTime(if(`listing_date` = '', '01-JAN-1970', `listing_date`), '%d-%b-%Y'))"
    ) in insert
    assert "`issuer`," in insert


@respx.mock
def test_load_still_rejects_an_empty_required_value(ch: ClickHouse) -> None:
    route = respx.post(URL).respond(200, text="")

    load_bronze(ch, HOLDING, PERIOD, PARSED_KEY)

    insert = sent_sql(route)[-1]
    assert "accurateCast(`price`, 'Float64')" in insert  # no default: a blank price fails
    assert "if(`price`" not in insert
    assert "toDate(parseDateTime(`date`, '%d-%b-%Y'))" in insert


@respx.mock
def test_load_bronze_replaces_the_period_partition_then_inserts_from_s3(ch: ClickHouse) -> None:
    route = respx.post(URL).respond(200, text="")

    load_bronze(ch, HOLDING, PERIOD, PARSED_KEY)

    create, drop, insert = sent_sql(route)
    assert "CREATE TABLE IF NOT EXISTS" in create
    assert "DROP PARTITION {period:String}" in drop
    assert "INSERT INTO bronze.stg_holding_composition (" in insert
    assert "s3(ksei_s3, filename={key:String}, format='Parquet')" in insert
    params = [call.request.url.params for call in route.calls]
    assert params[1]["param_period"] == "2026-09-30"
    assert params[2]["param_key"] == PARSED_KEY


@respx.mock
def test_load_bronze_never_uses_mutations(ch: ClickHouse) -> None:
    route = respx.post(URL).respond(200, text="")

    load_bronze(ch, HOLDING, PERIOD, PARSED_KEY)

    assert not any("UPDATE" in s or "DELETE" in s for s in sent_sql(route))


@respx.mock
def test_loaded_periods_returns_the_distinct_periods_in_the_table(ch: ClickHouse) -> None:
    route = respx.post(URL).mock(
        side_effect=[
            respx.MockResponse(200, text=""),  # ensure_table
            respx.MockResponse(200, text="2026-08-31\n2026-09-30\n"),
        ]
    )

    assert loaded_periods(ch, HOLDING) == {date(2026, 8, 31), date(2026, 9, 30)}
    assert (
        "SELECT DISTINCT _period FROM bronze.stg_holding_composition FORMAT" in sent_sql(route)[1]
    )


@respx.mock
def test_clickhouse_from_settings_targets_the_configured_server() -> None:
    settings = Settings.from_env({**ENV, "CLICKHOUSE_HOST": "ch.local"})
    route = respx.post(URL).respond(200, text="1")

    assert ClickHouse.from_settings(settings).execute("SELECT 1") == "1"
    assert route.called


# --- reference tables: loaded in full, not by period -------------------------------------------

CALENDAR_KEY = "bronze/period/parsed/data.parquet"


@respx.mock
def test_ensure_reference_table_creates_a_typed_table_without_a_period_partition(
    ch: ClickHouse,
) -> None:
    route = respx.post(URL).respond(200, text="")

    ensure_reference_table(ch, CALENDAR)

    (sql,) = sent_sql(route)
    assert "CREATE TABLE IF NOT EXISTS bronze.stg_period (" in sql
    assert "`date_actual` Date," in sql
    assert "`date_actual_time` DateTime," in sql
    assert "`day_of_week` Int64," in sql
    assert "`week_of_year_iso` String," in sql
    assert "`_source_file` String," in sql
    assert "`_ingested_at` DateTime" in sql
    assert "`_period`" not in sql and "PARTITION BY" not in sql
    assert "Nullable" not in sql
    assert "ORDER BY (date_actual)" in sql


@respx.mock
def test_load_reference_converts_each_column_with_the_date_format_of_the_file(
    ch: ClickHouse,
) -> None:
    route = respx.post(URL).respond(200, text="")

    load_reference(ch, CALENDAR, CALENDAR_KEY)

    insert = sent_sql(route)[-1]
    assert "toDate(parseDateTime(`date_actual`, '%Y-%m-%d'))" in insert
    assert "toDate(parseDateTime(`last_day_of_year`, '%Y-%m-%d'))" in insert
    assert "parseDateTimeBestEffort(`date_actual_time`, 'UTC')" in insert
    assert "accurateCast(`weekend_flag`, 'Int64')" in insert
    assert "`day_name`," in insert  # a string stays as it is
    assert "`week_of_year_iso`," in insert  # an empty string stays empty
    assert "parseDateTimeBestEffort(`_ingested_at`, 'UTC')" in insert
    assert "`_period`" not in insert  # a reference file has no period column


@respx.mock
def test_load_reference_replaces_the_whole_table_then_inserts_from_s3(ch: ClickHouse) -> None:
    route = respx.post(URL).respond(200, text="")

    load_reference(ch, CALENDAR, CALENDAR_KEY)

    create, truncate, insert = sent_sql(route)
    assert "CREATE TABLE IF NOT EXISTS bronze.stg_period" in create
    assert truncate == "TRUNCATE TABLE bronze.stg_period"
    assert "INSERT INTO bronze.stg_period (" in insert
    assert "s3(ksei_s3, filename={key:String}, format='Parquet')" in insert
    assert route.calls[2].request.url.params["param_key"] == CALENDAR_KEY


@respx.mock
def test_reference_is_loaded_only_when_the_table_has_rows(ch: ClickHouse) -> None:
    respx.post(URL).mock(
        side_effect=[
            respx.MockResponse(200, text=""),  # ensure_reference_table
            respx.MockResponse(200, text="0\n"),
            respx.MockResponse(200, text=""),
            respx.MockResponse(200, text="18628\n"),
        ]
    )

    assert reference_is_loaded(ch, CALENDAR) is False
    assert reference_is_loaded(ch, CALENDAR) is True
