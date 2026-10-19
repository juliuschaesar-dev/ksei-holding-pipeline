"""Generate the dbt unit-test files whose fixtures contain MD5 hashes.

The vault tests compare against hash keys and `md5_diff` values, which nobody should type by hand.
This script computes them independently of dbt (with Python's hashlib, following the rules in
macros/datavault/dv_hash.sql) and writes:

    dbt/models/silver/_silver_unit_tests.yml
    dbt/models/gold/_gold_unit_tests.yml

After changing a vault model, its payload or the hash rules, run `make dbt-fixtures` and commit
the result. tests/unit/test_generated_fixtures.py fails when the files are out of date.
"""

import hashlib
from collections.abc import Callable
from pathlib import Path

from ksei.config import DATASETS

ROOT = Path(__file__).resolve().parents[1]
SILVER_FILE = ROOT / "dbt" / "models" / "silver" / "_silver_unit_tests.yml"
GOLD_FILE = ROOT / "dbt" / "models" / "gold" / "_gold_unit_tests.yml"

DELIMITER = "||"  # var dv_hash_delimiter
NULL_PLACEHOLDER = "^^"  # var dv_null_placeholder
HOLDING = DATASETS["holding_composition"]
MASTER = DATASETS["master_securities"]
INVESTOR_TYPES = ["is", "cp", "pf", "ib", "id", "mf", "sc", "fd", "ot"]
P1, P2 = "2026-08-31", "2026-09-30"


def fmt(value: object) -> str:
    """The text ClickHouse's toString gives for the values used in the fixtures."""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value)


def md5(*values: object) -> str:
    """Hash key as dv_hash computes it: trimmed parts, empty becomes the placeholder."""
    parts = [fmt(value).strip() or NULL_PLACEHOLDER for value in values]
    return hashlib.md5(DELIMITER.join(parts).encode()).hexdigest()  # noqa: S324


def csv(header: list[str], rows: list[dict[str, object]]) -> str:
    lines = ["          " + ",".join(header)]
    lines += ["          " + ",".join(fmt(row[name]) for name in header) for row in rows]
    return "\n".join(lines)


# --- silver: bronze rows in, vault rows out ----------------------------------------------------


def _blank(dataset) -> dict[str, object]:
    return {c.name: (0 if c.type in ("Int64", "Float64") else "") for c in dataset.schema}


def holding_row(code: str, period: str, **overrides: object) -> dict[str, object]:
    row = _blank(HOLDING)
    row.update(date=period, code=code, type="EQUITY", sec_num=1000, price=10.5, local_is=7)
    row.update(local_total=7, foreign_cp=3, foreign_total=3)
    row.update(overrides)
    row.update(_period=period, _source_file="f.zip", _ingested_at="2026-10-07 12:00:00")
    return row


def master_row(code: str, period: str, isin: str, **overrides: object) -> dict[str, object]:
    row = _blank(MASTER)
    for name in ("listing_date", "eff_date_isin", "maturity_date", "expire_date"):
        row[name] = "1970-01-01"
    row.update(date=period, code=code, isin_code=isin, description=f"{code} TBK", type="EQUITY")
    row.update(issuer=f"{code} PT", status="ACTIVE", currency="IDR", form="Electronic")
    row.update(overrides)
    row.update(_period=period, _source_file="f.zip", _ingested_at="2026-10-07 12:00:00")
    return row


HOLDING_HEADER = ["_period"] + [c.name for c in HOLDING.schema] + ["_source_file", "_ingested_at"]
MASTER_HEADER = ["_period"] + [c.name for c in MASTER.schema] + ["_source_file", "_ingested_at"]
# The satellites leave out the hub keys, the currency (a hub) and the date (it equals the period).
HOLDING_PAYLOAD = [c.name for c in HOLDING.schema if c.name not in ("code", "date")]
MASTER_PAYLOAD = [
    c.name for c in MASTER.schema if c.name not in ("code", "isin_code", "currency", "date")
]


def holding_diff(row: dict[str, object]) -> str:  # parent key, child key (period), payload
    return md5(row["code"], row["_period"], *[row[name] for name in HOLDING_PAYLOAD])


def master_diff(row: dict[str, object]) -> str:  # parent keys, child key (period), payload
    keys = (row["code"], row["isin_code"], row["currency"], row["_period"])
    return md5(*keys, *[row[name] for name in MASTER_PAYLOAD])


def link_key(code: str, isin: str, currency: str = "IDR") -> str:
    return md5(code, isin, currency)


def _master_input(rows: list[dict[str, object]]) -> str:
    return f"""      - input: source('bronze', 'stg_master_securities')
        format: csv
        rows: |
{csv(MASTER_HEADER, rows)}"""


def _holding_input(rows: list[dict[str, object]]) -> str:
    return f"""      - input: source('bronze', 'stg_holding_composition')
        format: csv
        rows: |
{csv(HOLDING_HEADER, rows)}"""


def _this_input(rows: list[str]) -> str:
    body = "\n".join("          " + row for row in rows)
    return f"""      - input: this
        format: csv
        rows: |
          lmd5_master_securities,period,md5_diff,load_timestamp
{body}"""


def silver_unit_tests() -> str:
    holding_a = holding_row("AAAA", P2)
    master_a, master_b = master_row("AAAA", P2, "ISIN_A1"), master_row("AAAA", P2, "ISIN_A2")
    master_old = master_row("CCCC", P2, "ISIN_C", sector="OLD")
    master_new = master_row("CCCC", P2, "ISIN_C", sector="NEW")
    master_other = master_row("DDDD", P2, "ISIN_D")
    master_other_period = master_row("CCCC", P1, "ISIN_C", sector="OLD")
    old_row = f"{link_key('CCCC', 'ISIN_C')},{P2},{master_diff(master_old)},2026-10-01 00:00:00.000"
    new_row = f"{link_key('CCCC', 'ISIN_C')},{P2},{master_diff(master_new)},2026-10-02 00:00:00.000"
    return f"""version: 2

unit_tests:
  - name: hub_security_collects_codes_from_both_sources_once_each
    model: hub_security
    given:
{_master_input([master_row("AAAA", P2, "I1"), master_row("AAAA", P1, "I1"), master_row("ONLYM", P2, "I2")])}
{_holding_input([holding_row("AAAA", P2), holding_row("ONLYH", P2)])}
    expect:
      format: csv
      rows: |
        hmd5_security,code,record_source
        {md5("AAAA")},AAAA,bronze.stg_holding_composition
        {md5("ONLYH")},ONLYH,bronze.stg_holding_composition
        {md5("ONLYM")},ONLYM,bronze.stg_master_securities

  - name: hub_isin_collects_each_isin_once_from_the_master_file
    model: hub_isin
    given:
{_master_input([master_row("AAAA", P2, "ISIN_1"), master_row("AAAA", P1, "ISIN_1"), master_row("BBBB", P2, "ISIN_2")])}
    expect:
      format: csv
      rows: |
        hmd5_isin,isin_code,record_source
        {md5("ISIN_1")},ISIN_1,bronze.stg_master_securities
        {md5("ISIN_2")},ISIN_2,bronze.stg_master_securities

  - name: hub_currency_collects_each_currency_once_from_the_master_file
    model: hub_currency
    given:
{_master_input([master_row("AAAA", P2, "ISIN_1"), master_row("BBBB", P2, "ISIN_2"), master_row("CCCC", P2, "ISIN_3", currency="USD")])}
    expect:
      format: csv
      rows: |
        hmd5_currency,currency,record_source
        {md5("IDR")},IDR,bronze.stg_master_securities
        {md5("USD")},USD,bronze.stg_master_securities

  - name: link_ties_a_code_an_isin_and_a_currency_once
    model: link_master_securities
    given:
{_master_input([master_row("AAAA", P2, "ISIN_1"), master_row("AAAA", P1, "ISIN_1"), master_row("AAAA", P2, "ISIN_2", currency="USD")])}
    expect:
      format: csv
      rows: |
        lmd5_master_securities,hmd5_security,hmd5_isin,hmd5_currency
        {link_key("AAAA", "ISIN_1")},{md5("AAAA")},{md5("ISIN_1")},{md5("IDR")}
        {link_key("AAAA", "ISIN_2", "USD")},{md5("AAAA")},{md5("ISIN_2")},{md5("USD")}

  - name: holding_satellite_is_keyed_by_security_and_period
    model: satellite_holding_composition
    given:
{_holding_input([holding_a, holding_row("AAAA", P1)])}
    expect:
      format: csv
      rows: |
        hmd5_security,period,md5_diff,price,local_is,record_source,meta_is_active,is_deleted
        {md5("AAAA")},{P1},{holding_diff(holding_row("AAAA", P1))},10.5,7,bronze.stg_holding_composition,1,0
        {md5("AAAA")},{P2},{holding_diff(holding_a)},10.5,7,bronze.stg_holding_composition,1,0

  - name: master_satellite_is_keyed_by_the_link_and_period_and_drops_exact_duplicates
    model: satellite_master_securities
    given:
{_master_input([master_a, master_b, master_b])}
    expect:
      format: csv
      rows: |
        lmd5_master_securities,period,md5_diff
        {link_key("AAAA", "ISIN_A1")},{P2},{master_diff(master_a)}
        {link_key("AAAA", "ISIN_A2")},{P2},{master_diff(master_b)}

  - name: satellite_loads_a_changed_payload_as_a_new_row
    model: satellite_master_securities
    overrides:
      macros:
        is_incremental: true
    given:
{_master_input([master_new])}
{_this_input([old_row])}
    expect:
      format: csv
      rows: |
        lmd5_master_securities,period,md5_diff,sector
        {link_key("CCCC", "ISIN_C")},{P2},{master_diff(master_new)},NEW

  - name: satellite_skips_a_payload_that_is_already_the_current_version
    model: satellite_master_securities
    overrides:
      macros:
        is_incremental: true
    given:
{_master_input([master_new, master_other])}
{_this_input([new_row])}
    expect:
      format: csv
      rows: |
        lmd5_master_securities,period,md5_diff
        {link_key("DDDD", "ISIN_D")},{P2},{master_diff(master_other)}

  - name: satellite_reloads_a_payload_that_returns_to_an_earlier_value
    model: satellite_master_securities
    overrides:
      macros:
        is_incremental: true
    given:
{_master_input([master_old])}
{_this_input([old_row, new_row])}
    expect:
      format: csv
      rows: |
        lmd5_master_securities,period,md5_diff,sector
        {link_key("CCCC", "ISIN_C")},{P2},{master_diff(master_old)},OLD

  - name: satellite_treats_the_same_payload_in_another_period_as_a_separate_row
    model: satellite_master_securities
    overrides:
      macros:
        is_incremental: true
    given:
{_master_input([master_other_period])}
{_this_input([old_row])}
    expect:
      format: csv
      rows: |
        lmd5_master_securities,period,md5_diff
        {link_key("CCCC", "ISIN_C")},{P1},{master_diff(master_other_period)}
"""


# --- gold: vault rows in, star-schema rows out -------------------------------------------------

SECURITY_HASH = md5("AAAA")
ISIN_A_HASH, ISIN_B_HASH = md5("ISIN_A"), md5("ISIN_B")
LINK_A, LINK_B = link_key("AAAA", "ISIN_A"), link_key("AAAA", "ISIN_B")
CURRENCY_HASH = md5("IDR")
HOLDING_SATELLITE_COLUMNS = ["hmd5_security", "period", "md5_diff", "load_timestamp"]
HOLDING_SATELLITE_COLUMNS += ["meta_is_active", "is_deleted", "type", "sec_num", "price"]
HOLDING_SATELLITE_COLUMNS += ["local_total", "foreign_total"]
HOLDING_SATELLITE_COLUMNS += [f"local_{t}" for t in INVESTOR_TYPES]
HOLDING_SATELLITE_COLUMNS += [f"foreign_{t}" for t in INVESTOR_TYPES]
MASTER_SATELLITE_COLUMNS = (
    "lmd5_master_securities,period,md5_diff,load_timestamp,meta_is_active,is_deleted,"
    "description,type,issuer,status,stock_exchange,listing_date,form,maturity_date,interest,"
    "interest_type,sector,exercise_price,nominal_value,num_of_sec,originated_amt,current_amt,"
    "total_scripless,local_pct,foreign_pct,total_pct,closing_price"
)


def _holding_satellite_row(**overrides: object) -> str:
    row = dict.fromkeys(HOLDING_SATELLITE_COLUMNS, 0)
    row.update(hmd5_security=SECURITY_HASH, period=P2, md5_diff="d1", meta_is_active=1)
    row.update(load_timestamp="2026-10-07 12:00:00.000", type="equity ", sec_num=1000, price=2)
    row.update(overrides)
    return ",".join(str(row[name]) for name in HOLDING_SATELLITE_COLUMNS)


def _padded(row: str) -> str:
    """Rows are written up to `sector`; the measure columns that follow default to 0."""
    missing = MASTER_SATELLITE_COLUMNS.count(",") + 1 - (row.count(",") + 1)
    return row + ",0" * missing


def _master_satellite_inputs(master_rows: list[str]) -> str:
    body = "\n".join("          " + _padded(row) for row in master_rows)
    return f"""      - input: ref('satellite_master_securities')
        format: csv
        rows: |
          {MASTER_SATELLITE_COLUMNS}
{body}
      - input: ref('link_master_securities')
        format: csv
        rows: |
          lmd5_master_securities,hmd5_security,hmd5_isin,hmd5_currency
          {LINK_A},{SECURITY_HASH},{ISIN_A_HASH},{CURRENCY_HASH}
          {LINK_B},{SECURITY_HASH},{ISIN_B_HASH},{CURRENCY_HASH}
      - input: ref('hub_security')
        format: csv
        rows: |
          hmd5_security,code
          {SECURITY_HASH},AAAA
      - input: ref('hub_isin')
        format: csv
        rows: |
          hmd5_isin,isin_code
          {ISIN_A_HASH},ISIN_A
          {ISIN_B_HASH},ISIN_B
      - input: ref('hub_currency')
        format: csv
        rows: |
          hmd5_currency,currency
          {CURRENCY_HASH},IDR"""


def gold_unit_tests() -> str:
    two_periods = "\n".join(
        [
            "          " + ",".join(HOLDING_SATELLITE_COLUMNS),
            "          " + _holding_satellite_row(period=P1, local_is=10, local_total=10),
            "          " + _holding_satellite_row(local_is=10, local_total=10),
        ]
    )
    holding_rows = "\n".join(
        [
            "          " + ",".join(HOLDING_SATELLITE_COLUMNS),
            "          "
            + _holding_satellite_row(
                local_is=10, local_ot=3, foreign_is=5, local_total=13, foreign_total=5
            ),
        ]
    )
    return f"""version: 2

unit_tests:
  - name: fact_security_monthly_cleans_the_vault_attributes_and_keeps_the_lowest_isin
    model: fact_security_monthly
    given:
{
        _master_satellite_inputs(
            [
                f"{LINK_B},{P2},d2,2026-10-07 12:00:00.000,1,0,B TBK,sukuk ,B PT,ACTIVE,IDX,2000-01-03,Electronic,1970-01-01,0,,",
                f"{LINK_A},{P2},d1,2026-10-07 12:00:00.000,1,0,A TBK,equity ,A PT,active,,1970-01-01,Electronic,2030-01-01,5.65,Fixed,financial institution",
            ]
        )
    }
    expect:
      format: csv
      rows: |
        period,security_code,isin_code,description,security_type,issuer,status,stock_exchange,listing_date,currency,maturity_date,interest_rate,interest_type,sector
        {P2},AAAA,ISIN_A,A TBK,EQUITY,A PT,ACTIVE,,,IDR,2030-01-01,5.65,FIXED,FINANCIAL INSTITUTION

  - name: fact_security_monthly_keeps_every_measure_of_the_master_file
    model: fact_security_monthly
    given:
{
        _master_satellite_inputs(
            [
                f"{LINK_A},{P2},m1,2026-10-07 12:00:00.000,1,0,A TBK,EQUITY,A TBK PT,ACTIVE,,1970-01-01,Electronic,1970-01-01,5.65,Fixed,,12.5,100,1000,5000.5,4000.25,3000,60.5,39.5,100,7.75",
            ]
        )
    }
    expect:
      format: csv
      rows: |
        security_code,interest_rate,exercise_price,nominal_value,num_of_sec,originated_amt,current_amt,total_scripless,local_pct,foreign_pct,total_pct,closing_price
        AAAA,5.65,12.5,100,1000,5000.5,4000.25,3000,60.5,39.5,100,7.75

  - name: fact_security_monthly_uses_only_the_current_version_of_a_changed_row
    model: fact_security_monthly
    given:
{
        _master_satellite_inputs(
            [
                f"{LINK_A},{P2},old,2026-10-01 00:00:00.000,0,0,A TBK,EQUITY,A TBK PT,ACTIVE,,1970-01-01,Electronic,1970-01-01,0,,OLD",
                f"{LINK_A},{P2},new,2026-10-07 00:00:00.000,1,0,A TBK,EQUITY,A TBK PT,ACTIVE,,1970-01-01,Electronic,1970-01-01,0,,NEW",
            ]
        )
    }
    expect:
      format: csv
      rows: |
        security_code,sector
        AAAA,NEW

  - name: fact_security_monthly_keeps_each_period_of_a_code_and_its_description_separate
    model: fact_security_monthly
    given:
{
        _master_satellite_inputs(
            [
                f"{LINK_A},{P1},a1,2026-10-07 00:00:00.000,1,0,AUG NAME,EQUITY,AUG NAME PT,ACTIVE,,1970-01-01,Electronic,1970-01-01,0,,AUG",
                f"{LINK_A},{P2},a2,2026-10-07 00:00:00.000,1,0,SEP NAME,EQUITY,SEP NAME PT,ACTIVE,,1970-01-01,Electronic,1970-01-01,0,,SEP",
            ]
        )
    }
    expect:
      format: csv
      rows: |
        period,security_code,description,sector
        {P1},AAAA,AUG NAME,AUG
        {P2},AAAA,SEP NAME,SEP

  - name: fact_security_monthly_leaves_out_a_security_deleted_at_the_source
    model: fact_security_monthly
    given:
{
        _master_satellite_inputs(
            [
                f"{LINK_A},{P2},d1,2026-10-01 00:00:00.000,0,0,A TBK,EQUITY,A TBK PT,ACTIVE,,1970-01-01,Electronic,1970-01-01,0,,LIVE",
                f"{LINK_A},{P2},d1x,2026-10-07 00:00:00.000,1,1,A TBK,EQUITY,A TBK PT,ACTIVE,,1970-01-01,Electronic,1970-01-01,0,,LIVE",
                f"{LINK_B},{P2},d2,2026-10-07 00:00:00.000,1,0,B TBK,EQUITY,B TBK PT,ACTIVE,,1970-01-01,Electronic,1970-01-01,0,,KEPT",
            ]
        )
    }
    expect:
      format: csv
      rows: |
        isin_code,sector
        ISIN_B,KEPT

  - name: fact_unpivots_investor_types_drops_zero_quantities_and_values_them_and_cleans_the_type
    model: fact_holding_monthly
    given:
      - input: ref('satellite_holding_composition')
        format: csv
        rows: |
{holding_rows}
      - input: ref('hub_security')
        format: csv
        rows: |
          hmd5_security,code
          {SECURITY_HASH},AAAA
    expect:
      format: csv
      rows: |
        holding_key,period,security_code,security_type,residency,investor_type,investor_type_name,quantity,price,holding_value,sec_num,total_quantity,is_latest_period
        {P2}|AAAA|local|IS,{P2},AAAA,EQUITY,local,IS,Insurance,10,2,20,1000,13,1
        {P2}|AAAA|local|OT,{P2},AAAA,EQUITY,local,OT,Others,3,2,6,1000,13,1
        {P2}|AAAA|foreign|IS,{P2},AAAA,EQUITY,foreign,IS,Insurance,5,2,10,1000,5,1

  - name: fact_holding_flags_only_the_rows_of_the_latest_period
    model: fact_holding_monthly
    given:
      - input: ref('satellite_holding_composition')
        format: csv
        rows: |
{two_periods}
      - input: ref('hub_security')
        format: csv
        rows: |
          hmd5_security,code
          {SECURITY_HASH},AAAA
    expect:
      format: csv
      rows: |
        period,is_latest_period
        {P1},0
        {P2},1

  - name: mart_takes_the_type_from_the_holding_file_and_only_the_currency_from_the_master_file
    model: mart_foreign_ownership_monthly
    given:
      - input: ref('fact_holding_monthly')
        format: csv
        rows: |
          period,security_code,security_type,residency,holding_value
          {P1},AAAA,EQUITY,local,90
          {P1},AAAA,EQUITY,foreign,10
          {P2},AAAA,EQUITY,local,80
          {P2},AAAA,EQUITY,foreign,20
          {P2},USDB,SUKUK,foreign,1000
          {P2},ONLY,MUTUAL FUND,local,5
      - input: ref('fact_security_monthly')
        format: csv
        rows: |
          period,security_code,currency
          {P1},AAAA,IDR
          {P2},AAAA,IDR
          {P2},USDB,USD
    expect:
      format: csv
      rows: |
        period,security_type,local_value,foreign_value,total_value,foreign_share_pct,previous_period,foreign_value_change,foreign_share_change_pp,is_latest_period
        {P1},EQUITY,90,10,100,10,,,,0
        {P2},EQUITY,80,20,100,20,{P1},10,10,1
        {P2},MUTUAL FUND,5,0,5,0,,,,1

  - name: mart_investor_type_ranks_the_types_of_each_period_by_value
    model: mart_investor_type_monthly
    given:
      - input: ref('fact_holding_monthly')
        format: csv
        rows: |
          period,investor_type,investor_type_name,residency,holding_value
          {P1},CP,Corporate,local,10
          {P2},CP,Corporate,local,60
          {P2},CP,Corporate,foreign,20
          {P2},ID,Individual,local,50
    expect:
      format: csv
      rows: |
        period,investor_type,investor_type_name,holding_value,foreign_value,foreign_share_pct,holder_rank,is_latest_period
        {P1},CP,Corporate,10,0,0,1,0
        {P2},CP,Corporate,80,20,25,1,1
        {P2},ID,Individual,50,0,0,2,1
"""


GENERATED: dict[Path, Callable[[], str]] = {
    SILVER_FILE: silver_unit_tests,
    GOLD_FILE: gold_unit_tests,
}


def main() -> None:
    for path, generate in GENERATED.items():
        path.write_text(generate(), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
