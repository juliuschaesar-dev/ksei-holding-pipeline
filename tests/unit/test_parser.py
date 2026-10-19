import io
import zipfile
from datetime import UTC, datetime

import polars as pl
import pytest

from ksei.config import DATASETS
from ksei.config import PERIOD as CALENDAR
from ksei.parser import ParserError, parse_reference, parse_release

pytestmark = pytest.mark.unit

HOLDING = DATASETS["holding_composition"]
MASTER = DATASETS["master_securities"]
PERIOD = datetime(2026, 9, 30).date()
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def make_zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buffer.getvalue()


def release_zip(header: list[str], rows: list[list[str]], name: str = "file.txt") -> bytes:
    lines = ["|".join(header)] + ["|".join(r) for r in rows]
    return make_zip({name: ("\r\n".join(lines) + "\r\n").encode()})


def holding_row(code: str, local_total: str = "10", foreign_total: str = "5") -> list[str]:
    values = ["0"] * len(HOLDING.header)
    values[0], values[1], values[2] = "30-SEP-2026", code, "EQUITY"
    values[3] = ""  # Sec. Num is sometimes empty
    values[14], values[24] = local_total, foreign_total
    return values


def master_row(code: str, description: str = "A DESCRIPTION") -> list[str]:
    values = [""] * len(MASTER.header)
    values[0], values[1], values[2], values[3] = "30-SEP-2026", code, description, "EQUITY"
    return values


def parse(dataset, payload: bytes) -> pl.DataFrame:
    out = parse_release(dataset, payload, "src.zip", PERIOD, lambda: NOW)
    return pl.read_parquet(io.BytesIO(out))


def test_registry_header_and_columns_line_up_with_the_documented_layout() -> None:
    assert len(HOLDING.header) == len(HOLDING.columns) == 25
    assert len(MASTER.header) == len(MASTER.columns) == 28
    assert len(set(HOLDING.columns)) == len(HOLDING.columns)


def test_parse_keeps_every_source_column_as_a_string() -> None:
    df = parse(HOLDING, release_zip(list(HOLDING.header), [holding_row("AADI")]))

    assert df.columns[:25] == list(HOLDING.columns)
    assert set(df.schema.values()) == {pl.String}


def test_duplicate_total_header_is_renamed_by_position() -> None:
    df = parse(HOLDING, release_zip(list(HOLDING.header), [holding_row("AADI", "111", "222")]))

    assert df["local_total"][0] == "111"
    assert df["foreign_total"][0] == "222"


def test_empty_fields_stay_empty_strings_and_values_are_not_altered() -> None:
    df = parse(HOLDING, release_zip(list(HOLDING.header), [holding_row("AADI")]))

    assert df["sec_num"][0] == ""
    assert df["date"][0] == "30-SEP-2026"


def test_metadata_columns_use_period_source_file_and_injected_clock() -> None:
    df = parse(HOLDING, release_zip(list(HOLDING.header), [holding_row("AADI")]))

    assert df["_period"][0] == "2026-09-30"
    assert df["_source_file"][0] == "src.zip"
    assert df["_ingested_at"][0] == "2026-10-07T12:00:00+00:00"


def test_record_with_an_embedded_bare_line_feed_stays_one_row() -> None:
    rows = [master_row("A", "FIRST PART\nSECOND PART"), master_row("B")]
    df = parse(MASTER, release_zip(list(MASTER.header), rows))

    assert df.height == 2
    assert df["description"][0] == "FIRST PART\nSECOND PART"


def test_unexpected_header_fails_and_names_the_difference() -> None:
    header = list(HOLDING.header)
    header[4] = "Harga"

    with pytest.raises(ParserError, match="Harga"):
        parse(HOLDING, release_zip(header, [holding_row("AADI")]))


def test_file_with_only_a_header_fails_as_empty() -> None:
    with pytest.raises(ParserError, match="no data rows"):
        parse(HOLDING, release_zip(list(HOLDING.header), []))


def test_row_with_the_wrong_number_of_fields_fails_with_its_line_number() -> None:
    bad = holding_row("AADI")[:-1]

    with pytest.raises(ParserError, match=r"line 3.*24 fields"):
        parse(HOLDING, release_zip(list(HOLDING.header), [holding_row("OK"), bad]))


@pytest.mark.parametrize("members", [{}, {"a.txt": b"x", "b.txt": b"y"}])
def test_zip_must_contain_exactly_one_file(members: dict[str, bytes]) -> None:
    with pytest.raises(ParserError, match="exactly one file"):
        parse(HOLDING, make_zip(members))


def raw_file(row: list[str], header: tuple[str, ...]) -> bytes:
    return "|".join(header).encode() + b"\r\n" + "|".join(row).encode() + b"\r\n"


def test_windows_1252_bytes_in_a_text_field_are_decoded() -> None:
    # Regression: nine real releases (2025-06 to 2026-02) hold 0x96 (en dash) and 0xA0 (nbsp).
    raw = raw_file(master_row("A", "PT ABC @ TBK"), MASTER.header).replace(b"@", b"\x96")

    df = parse(MASTER, make_zip({"f.txt": raw}))

    assert df["description"][0] == "PT ABC – TBK"


def test_utf8_content_is_still_decoded_as_utf8() -> None:
    raw = raw_file(master_row("A", "CAFÉ"), MASTER.header).replace(
        "CAFÉ".encode("latin-1"), "CAFÉ".encode()
    )

    assert parse(MASTER, make_zip({"f.txt": raw}))["description"][0] == "CAFÉ"


def test_bytes_valid_in_neither_utf8_nor_windows_1252_fail_loudly() -> None:
    raw = raw_file(master_row("A", "BAD @"), MASTER.header).replace(b"@", b"\x81")

    with pytest.raises(ParserError, match="decode"):
        parse(MASTER, make_zip({"f.txt": raw}))


def test_a_corrupt_zip_fails_with_a_clear_message() -> None:
    with pytest.raises(ParserError, match="not a valid zip"):
        parse(HOLDING, b"this is not a zip")


# --- the reference calendar: a plain CSV, not a zip --------------------------------------------


def calendar_row(day: str, **cells: str) -> list[str]:
    values = dict.fromkeys(CALENDAR.columns, "1")
    values.update(date_actual=day, date_actual_time=f"{day} 00:00:00.000", day_suffix="1st")
    values.update(week_of_year_iso="2000-W52-6", weekend_flag="1")
    values.update(cells)
    return [values[name] for name in CALENDAR.columns]


def calendar_csv(
    rows: list[list[str]], header: list[str] | None = None, end: str = "\r\n"
) -> bytes:
    def quote(cell: str) -> str:
        return f'"{cell}"' if cell in {"1st", "2000-W52-6"} else cell

    lines = [",".join(header or list(CALENDAR.header))]
    lines += [",".join(quote(cell) for cell in row) for row in rows]
    return (end.join(lines) + end).encode()


def parse_calendar(payload: bytes) -> pl.DataFrame:
    return pl.read_parquet(
        io.BytesIO(parse_reference(CALENDAR, payload, "raw_period.csv", lambda: NOW))
    )


def test_parse_reference_keeps_every_column_as_a_string_and_adds_lineage() -> None:
    df = parse_calendar(calendar_csv([calendar_row("2000-01-01")]))

    assert df.columns == [*CALENDAR.columns, "_source_file", "_ingested_at"]
    assert set(df.schema.values()) == {pl.String}
    assert df["date_actual"][0] == "2000-01-01"
    assert df["date_actual_time"][0] == "2000-01-01 00:00:00.000"
    assert df["_source_file"][0] == "raw_period.csv"
    assert df["_ingested_at"][0] == NOW.isoformat()


def test_parse_reference_unquotes_quoted_cells() -> None:
    df = parse_calendar(calendar_csv([calendar_row("2000-01-01")]))

    assert df["day_suffix"][0] == "1st"
    assert df["week_of_year_iso"][0] == "2000-W52-6"


def test_parse_reference_keeps_an_empty_cell_empty() -> None:
    df = parse_calendar(calendar_csv([calendar_row("2000-09-11", week_of_year_iso="")]))

    assert df["week_of_year_iso"][0] == ""


def test_parse_reference_accepts_a_bare_line_feed_between_rows() -> None:
    rows = [calendar_row("2000-01-01"), calendar_row("2000-01-02")]
    payload = calendar_csv(rows).replace(b"\r\n", b"\n", 1)

    assert parse_calendar(payload)["date_actual"].to_list() == ["2000-01-01", "2000-01-02"]


def test_parse_reference_rejects_a_changed_header() -> None:
    header = [*CALENDAR.header[:-1], "weekend"]

    with pytest.raises(ParserError, match=r"unexpected header for period.*weekend_flag"):
        parse_calendar(calendar_csv([calendar_row("2000-01-01")], header=header))


def test_parse_reference_rejects_a_row_with_the_wrong_number_of_fields() -> None:
    with pytest.raises(ParserError, match="line 2: expected 26 fields, found 25 fields"):
        parse_calendar(calendar_csv([calendar_row("2000-01-01")[:-1]]))


def test_parse_reference_rejects_an_empty_file_and_a_header_only_file() -> None:
    with pytest.raises(ParserError, match="file is empty"):
        parse_calendar(b"")
    with pytest.raises(ParserError, match="no data rows"):
        parse_calendar(calendar_csv([]))
