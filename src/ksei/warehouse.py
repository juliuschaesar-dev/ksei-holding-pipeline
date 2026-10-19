"""ClickHouse access over the HTTP interface, and the typed bronze load."""

import logging
from datetime import date

import httpx

from ksei.config import Column, Dataset, Reference, Settings

log = logging.getLogger(__name__)

DATE_FORMAT = "%d-%b-%Y"  # 30-SEP-2026

# Columns every bronze table gets from the parser: (name, ClickHouse type, SELECT expression).
LINEAGE = (
    ("_period", "Date", "toDate(`_period`)"),
    ("_source_file", "String", "`_source_file`"),
    ("_ingested_at", "DateTime", "parseDateTimeBestEffort(`_ingested_at`, 'UTC')"),
)
FILE_LINEAGE = LINEAGE[1:]  # a reference file has no period


class WarehouseError(Exception):
    """ClickHouse rejected a statement."""


class ClickHouse:
    def __init__(self, url: str, user: str, password: str, timeout_seconds: float = 600.0) -> None:
        self._url = url
        self._http = httpx.Client(auth=(user, password), timeout=timeout_seconds)

    @classmethod
    def from_settings(cls, settings: Settings) -> ClickHouse:
        return cls(settings.clickhouse_url, settings.clickhouse_user, settings.clickhouse_password)

    def execute(self, sql: str, params: dict[str, str] | None = None) -> str:
        query = {f"param_{name}": value for name, value in (params or {}).items()}
        response = self._http.post(self._url, params=query, content=sql.encode())
        if response.status_code != 200:
            raise WarehouseError(f"ClickHouse HTTP {response.status_code}: {response.text.strip()}")
        return response.text


# What an empty optional cell becomes. Plain ClickHouse types cannot hold NULL, so each type
# gets its own default (strings stay empty).
BLANK_DEFAULT = {"Int64": "0", "Float64": "0", "Date": "01-JAN-1970"}


def _convert(column: Column, date_format: str = DATE_FORMAT) -> str:
    """SELECT expression casting a string column to its type; bad values raise, never NULL."""
    source = f"`{column.name}`"
    if column.type == "String":
        return source
    if column.optional:  # evaluated for blank rows too, so substitute a parseable default
        source = f"if({source} = '', '{BLANK_DEFAULT[column.type]}', {source})"
    if column.type == "Date":
        return f"toDate(parseDateTime({source}, '{date_format}'))"
    if column.type == "DateTime":
        return f"parseDateTimeBestEffort({source}, 'UTC')"
    return f"accurateCast({source}, '{column.type}')"


def _create_table(
    ch: ClickHouse,
    table: str,
    schema: tuple[Column, ...],
    lineage: tuple[tuple[str, str, str], ...],
    clauses: str,
) -> None:
    columns = [(c.name, c.type) for c in schema] + [(name, type_) for name, type_, _ in lineage]
    body = ",\n    ".join(f"`{name}` {type_}" for name, type_ in columns)
    ch.execute(
        f"CREATE TABLE IF NOT EXISTS {table} (\n    {body}\n)\nENGINE = MergeTree\n{clauses}"
    )


def _insert_from_parquet(
    ch: ClickHouse,
    table: str,
    schema: tuple[Column, ...],
    lineage: tuple[tuple[str, str, str], ...],
    *,
    date_format: str,
    parsed_key: str,
) -> None:
    names = ", ".join(
        f"`{name}`" for name in (*(c.name for c in schema), *(n for n, _, _ in lineage))
    )
    expressions = ",\n    ".join(
        [*(_convert(column, date_format) for column in schema), *(expr for _, _, expr in lineage)]
    )
    ch.execute(
        f"INSERT INTO {table} ({names})\n"
        f"SELECT\n    {expressions}\n"
        "FROM s3(ksei_s3, filename={key:String}, format='Parquet')",
        {"key": parsed_key},
    )
    log.info("loaded %s into %s", parsed_key, table)


def ensure_table(ch: ClickHouse, dataset: Dataset) -> None:
    _create_table(
        ch, dataset.table, dataset.schema, LINEAGE, "PARTITION BY _period\nORDER BY (code)"
    )


def load_bronze(ch: ClickHouse, dataset: Dataset, period: date, parsed_key: str) -> None:
    """Replace one period: drop its partition, then insert the typed rows from S3 Parquet."""
    ensure_table(ch, dataset)
    ch.execute(
        f"ALTER TABLE {dataset.table} DROP PARTITION {{period:String}}",
        {"period": period.isoformat()},
    )
    _insert_from_parquet(
        ch, dataset.table, dataset.schema, LINEAGE, date_format=DATE_FORMAT, parsed_key=parsed_key
    )


def loaded_periods(ch: ClickHouse, dataset: Dataset) -> set[date]:
    ensure_table(ch, dataset)
    text = ch.execute(f"SELECT DISTINCT _period FROM {dataset.table} FORMAT TSV")
    return {date.fromisoformat(line) for line in text.splitlines() if line}


def ensure_reference_table(ch: ClickHouse, reference: Reference) -> None:
    _create_table(
        ch, reference.table, reference.schema, FILE_LINEAGE, f"ORDER BY ({reference.columns[0]})"
    )


def load_reference(ch: ClickHouse, reference: Reference, parsed_key: str) -> None:
    """Replace the whole table with the typed rows of the S3 Parquet."""
    ensure_reference_table(ch, reference)
    ch.execute(f"TRUNCATE TABLE {reference.table}")
    _insert_from_parquet(
        ch,
        reference.table,
        reference.schema,
        FILE_LINEAGE,
        date_format=reference.date_format,
        parsed_key=parsed_key,
    )


def reference_is_loaded(ch: ClickHouse, reference: Reference) -> bool:
    ensure_reference_table(ch, reference)
    return int(ch.execute(f"SELECT count() FROM {reference.table} FORMAT TSV")) > 0
