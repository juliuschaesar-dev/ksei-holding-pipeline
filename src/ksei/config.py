"""Environment settings and the dataset registry (single home for dataset knowledge)."""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date


class ConfigError(Exception):
    """A required setting is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    user_agent: str
    min_delay_seconds: float
    s3_endpoint_url: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str
    s3_logs_bucket: str
    clickhouse_host: str
    clickhouse_port: str
    clickhouse_user: str
    clickhouse_password: str
    ksei_base_url: str
    period_source_url: str

    @property
    def clickhouse_url(self) -> str:
        return f"http://{self.clickhouse_host}:{self.clickhouse_port}"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env

        def required(name: str) -> str:
            try:
                return source[name]
            except KeyError:
                raise ConfigError(f"missing required environment variable {name}") from None

        return cls(
            user_agent=required("KSEI_USER_AGENT"),
            min_delay_seconds=float(required("KSEI_MIN_DELAY_SECONDS")),
            s3_endpoint_url=required("S3_ENDPOINT_URL"),
            s3_access_key=required("S3_ACCESS_KEY"),
            s3_secret_key=required("S3_SECRET_KEY"),
            s3_bucket=required("S3_BUCKET"),
            s3_logs_bucket=required("S3_LOGS_BUCKET"),
            clickhouse_host=required("CLICKHOUSE_HOST"),
            clickhouse_port=required("CLICKHOUSE_HTTP_PORT"),
            clickhouse_user=required("CLICKHOUSE_PIPELINE_USER"),
            clickhouse_password=required("CLICKHOUSE_PIPELINE_PASSWORD"),
            ksei_base_url=required("KSEI_BASE_URL"),
            period_source_url=required("PERIOD_SOURCE_URL"),
        )


@dataclass(frozen=True)
class Column:
    header: str  # as written in the source file
    name: str  # bronze column name
    type: str  # ClickHouse type of the bronze column (plain; never Nullable)
    optional: bool = False  # may be empty in the source; stored as the type's default


@dataclass(frozen=True)
class Dataset:
    name: str
    archive_path: str  # path on the KSEI host; the base URL comes from Settings
    link_pattern: re.Pattern[str]  # group 1 is the release date, YYYYMMDD
    table: str
    schema: tuple[Column, ...]

    @property
    def header(self) -> tuple[str, ...]:
        """Exact header row of the source file."""
        return tuple(c.header for c in self.schema)

    @property
    def columns(self) -> tuple[str, ...]:
        """Bronze column names, same order as `header`."""
        return tuple(c.name for c in self.schema)

    def _prefix(self, kind: str, period: date) -> str:
        return f"bronze/{self.name}/{kind}/year={period:%Y}/month={period:%m}"

    def raw_key(self, period: date, filename: str) -> str:
        return f"{self._prefix('raw', period)}/{filename}"

    def parsed_key(self, period: date) -> str:
        return f"{self._prefix('parsed', period)}/data.parquet"


@dataclass(frozen=True)
class Reference:
    """A static reference file (not a KSEI release): fetched once and loaded in full."""

    name: str
    filename: str
    table: str
    date_format: str  # ClickHouse parseDateTime format of its Date columns
    schema: tuple[Column, ...]

    @property
    def header(self) -> tuple[str, ...]:
        """Exact header row of the source file."""
        return tuple(c.header for c in self.schema)

    @property
    def columns(self) -> tuple[str, ...]:
        """Bronze column names, same order as `header`."""
        return tuple(c.name for c in self.schema)

    @property
    def raw_key(self) -> str:
        return f"bronze/{self.name}/raw/{self.filename}"

    @property
    def parsed_key(self) -> str:
        return f"bronze/{self.name}/parsed/data.parquet"


def _schema(rows: list[tuple[str, str, str] | tuple[str, str, str, bool]]) -> tuple[Column, ...]:
    return tuple(Column(*row) for row in rows)


_INVESTOR_TYPES = ("is", "cp", "pf", "ib", "id", "mf", "sc", "fd", "ot")

_HOLDING_SCHEMA = _schema(
    [
        ("Date", "date", "Date"),
        ("Code", "code", "String"),
        ("Type", "type", "String"),
        ("Sec. Num", "sec_num", "Int64", True),
        ("Price", "price", "Float64"),
        *[(f"Local {t.upper()}", f"local_{t}", "Int64") for t in _INVESTOR_TYPES],
        ("Total", "local_total", "Int64"),
        *[(f"Foreign {t.upper()}", f"foreign_{t}", "Int64") for t in _INVESTOR_TYPES],
        ("Total", "foreign_total", "Int64"),
    ]
)

_MASTER_SCHEMA = _schema(
    [
        ("Date", "date", "Date"),
        ("Code", "code", "String"),
        ("Description", "description", "String"),
        ("Type", "type", "String"),
        ("Isin Code", "isin_code", "String"),
        ("Issuer", "issuer", "String"),
        ("Status", "status", "String"),
        ("Stock Exchange", "stock_exchange", "String", True),
        ("Listing Date", "listing_date", "Date", True),
        ("Currency", "currency", "String"),
        ("Form", "form", "String"),
        ("Eff. Date Isin", "eff_date_isin", "Date", True),
        ("Maturity Date", "maturity_date", "Date", True),
        ("Expire Date", "expire_date", "Date", True),
        ("Exercise Price", "exercise_price", "Float64", True),
        ("Interest", "interest", "Float64", True),
        ("Interest Type", "interest_type", "String", True),
        ("Interest Freq", "interest_freq", "String", True),
        ("Nominal Value", "nominal_value", "Float64", True),
        ("Num. of Sec", "num_of_sec", "Int64", True),
        ("Originated Amt", "originated_amt", "Float64", True),
        ("Current Amt", "current_amt", "Float64", True),
        ("Total Scripless", "total_scripless", "Float64", True),
        ("Local (%)", "local_pct", "Float64", True),
        ("Foreign (%)", "foreign_pct", "Float64", True),
        ("Total (%)", "total_pct", "Float64", True),
        ("Sector", "sector", "String", True),
        ("Closing Price", "closing_price", "Float64", True),
    ]
)

_ARCHIVE = "/archive_download"

DATASETS: dict[str, Dataset] = {
    "master_securities": Dataset(
        name="master_securities",
        archive_path=f"{_ARCHIVE}/master_securities",
        link_pattern=re.compile(r"/Download/StatisEfek(\d{8})\.txt\.zip$"),
        table="bronze.stg_master_securities",
        schema=_MASTER_SCHEMA,
    ),
    "holding_composition": Dataset(
        name="holding_composition",
        archive_path=f"{_ARCHIVE}/holding_composition",
        link_pattern=re.compile(r"/Download/BalanceposEfek(\d{8})\.zip$"),
        table="bronze.stg_holding_composition",
        schema=_HOLDING_SCHEMA,
    ),
}


# The calendar of reporting periods: one row per day, 2000-01-01 to 2050-12-31. It is the source
# of gold.dim_period, so its headers already are the column names. One source row has no ISO week.
PERIOD = Reference(
    name="period",
    filename="raw_period.csv",
    table="bronze.stg_period",
    date_format="%Y-%m-%d",
    schema=_schema(
        [
            ("date_actual", "date_actual", "Date"),
            ("date_actual_time", "date_actual_time", "DateTime"),
            ("day_suffix", "day_suffix", "String"),
            ("day_name", "day_name", "String"),
            ("day_of_week", "day_of_week", "Int64"),
            ("day_of_month", "day_of_month", "Int64"),
            ("day_of_quarter", "day_of_quarter", "Int64"),
            ("day_of_year", "day_of_year", "Int64"),
            ("week_of_month", "week_of_month", "Int64"),
            ("week_of_year", "week_of_year", "Int64"),
            ("week_of_year_iso", "week_of_year_iso", "String", True),
            ("month_actual", "month_actual", "Int64"),
            ("month_name", "month_name", "String"),
            ("month_name_abbreviated", "month_name_abbreviated", "String"),
            ("quarter_actual", "quarter_actual", "Int64"),
            ("quarter_name", "quarter_name", "String"),
            ("year_actual", "year_actual", "Int64"),
            ("first_day_of_week", "first_day_of_week", "Date"),
            ("last_day_of_week", "last_day_of_week", "Date"),
            ("first_day_of_month", "first_day_of_month", "Date"),
            ("last_day_of_month", "last_day_of_month", "Date"),
            ("first_day_of_quarter", "first_day_of_quarter", "Date"),
            ("last_day_of_quarter", "last_day_of_quarter", "Date"),
            ("first_day_of_year", "first_day_of_year", "Date"),
            ("last_day_of_year", "last_day_of_year", "Date"),
            ("weekend_flag", "weekend_flag", "Int64"),
        ]
    ),
)
