"""Turn a KSEI release (zip) or a reference file (CSV) into an all-strings Parquet."""

import csv
import io
import zipfile
from collections.abc import Callable
from datetime import date, datetime

import polars as pl

from ksei.config import Dataset, Reference

DELIMITER = "|"
RECORD_END = "\r\n"  # a bare "\n" can occur inside a field, so never split on it


class ParserError(Exception):
    """The file does not look like the documented layout."""


def _read_single_member(payload: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            names = zf.namelist()
            if len(names) != 1:
                raise ParserError(f"zip must contain exactly one file, found {len(names)}")
            return zf.read(names[0])
    except zipfile.BadZipFile as exc:
        raise ParserError("payload is not a valid zip file") from exc


def _decode(raw: bytes) -> str:
    """UTF-8 (covers plain ASCII), else Windows-1252: some releases hold bytes like 0x96."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp1252")
    except UnicodeDecodeError as exc:
        raise ParserError(f"cannot decode file as UTF-8 or Windows-1252: {exc}") from exc


def _split_records(raw: bytes) -> list[list[str]]:
    return [line.split(DELIMITER) for line in _decode(raw).split(RECORD_END) if line != ""]


def _data_rows(name: str, expected: tuple[str, ...], records: list[list[str]]) -> list[list[str]]:
    """Check the header and the width of every row; return the data rows."""
    if not records:
        raise ParserError("file is empty")
    header, rows = records[0], records[1:]
    if tuple(header) != expected:
        missing = sorted(set(expected) - set(header))
        extra = sorted(set(header) - set(expected))
        raise ParserError(f"unexpected header for {name}: missing {missing}, unexpected {extra}")
    if not rows:
        raise ParserError("file has a header but no data rows")
    for number, row in enumerate(rows, start=2):
        if len(row) != len(header):
            raise ParserError(
                f"line {number}: expected {len(header)} fields, found {len(row)} fields"
            )
    return rows


def _parquet(columns: dict[str, list[str]]) -> bytes:
    frame = pl.DataFrame(columns, schema=dict.fromkeys(columns, pl.String))
    buffer = io.BytesIO()
    frame.write_parquet(buffer)
    return buffer.getvalue()


def parse_release(
    dataset: Dataset,
    payload: bytes,
    source_file: str,
    period: date,
    now: Callable[[], datetime],
) -> bytes:
    """Return Parquet bytes: every source column as a string plus lineage columns."""
    rows = _data_rows(dataset.name, dataset.header, _split_records(_read_single_member(payload)))
    columns = {name: [row[i] for row in rows] for i, name in enumerate(dataset.columns)}
    height = len(rows)
    columns["_period"] = [period.isoformat()] * height
    columns["_source_file"] = [source_file] * height
    columns["_ingested_at"] = [now().isoformat()] * height
    return _parquet(columns)


def parse_reference(
    reference: Reference, payload: bytes, source_file: str, now: Callable[[], datetime]
) -> bytes:
    """Return Parquet bytes of a comma-separated reference file: all strings plus lineage."""
    reader = csv.reader(io.StringIO(_decode(payload), newline=""))
    rows = _data_rows(reference.name, reference.header, [row for row in reader if row])
    columns = {name: [row[i] for row in rows] for i, name in enumerate(reference.columns)}
    columns["_source_file"] = [source_file] * len(rows)
    columns["_ingested_at"] = [now().isoformat()] * len(rows)
    return _parquet(columns)
