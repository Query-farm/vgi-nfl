"""Tests for the strict upstream-value conversions."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pyarrow as pa

from vgi_nfl.convert import (
    athlete_id_from_links,
    batch_from_rows,
    clock_seconds,
    split_pair,
    to_bool,
    to_date,
    to_decimal,
    to_int,
    to_text,
    to_timestamp,
)


def test_to_int_handles_display_strings_and_markers() -> None:
    assert to_int("3,587") == 3587
    assert to_int("5.000") == 5
    assert to_int(7.0) == 7
    assert to_int(7.5) is None
    assert to_int("--") is None
    assert to_int("") is None
    assert to_int(True) is None
    assert to_int(None) is None
    assert to_int("4.5") is None


def test_to_decimal_rounds_to_scale() -> None:
    assert to_decimal("0.8235294", 3) == Decimal("0.824")
    assert to_decimal(".824") == Decimal("0.824")
    assert to_decimal("--") is None
    assert to_decimal("NaN") is None
    assert to_decimal(None) is None
    assert to_decimal(False) is None


def test_text_bool_and_dates() -> None:
    assert to_text("  x ") == "x"
    assert to_text("") is None
    assert to_text({"a": 1}) is None
    assert to_bool(True) is True
    assert to_bool("true") is None
    assert to_timestamp("2025-09-05T00:20Z") == datetime(2025, 9, 5, 0, 20, tzinfo=UTC)
    assert to_timestamp("2025-12-14T18:00:00.000+00:00") == datetime(2025, 12, 14, 18, tzinfo=UTC)
    assert to_timestamp("2025-09-05T00:20:00") == datetime(2025, 9, 5, 0, 20, tzinfo=UTC)
    assert to_timestamp("garbage") is None
    assert to_timestamp(None) is None
    assert to_date("2003-02-11T08:00Z") == date(2003, 2, 11)
    assert to_date(date(2020, 1, 1)) == date(2020, 1, 1)
    assert to_date("2026-13-01") is None
    assert to_date("short") is None


def test_clock_pairs_and_links() -> None:
    assert clock_seconds("25:08") == 1508
    assert clock_seconds("bad") is None
    assert split_pair("21/34", "/") == (21, 34)
    assert split_pair("7-11", "-") == (7, 11)
    assert split_pair("--", "/") == (None, None)
    links = [{"href": "https://www.espn.com/nfl/player/_/id/4709718/jayden-williams"}]
    assert athlete_id_from_links(links) == 4709718
    assert athlete_id_from_links([{"href": "https://example.test"}]) is None


def test_batch_from_rows_respects_projection() -> None:
    schema = pa.schema([pa.field("b", pa.int32()), pa.field("a", pa.string())])
    batch = batch_from_rows([{"a": "x", "b": 1, "c": 3}], schema)
    assert batch.schema == schema
    assert batch.to_pylist() == [{"b": 1, "a": "x"}]
