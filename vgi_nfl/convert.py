"""Small, strict conversions from upstream JSON values to typed Arrow values."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any

import pyarrow as pa

_CLOCK = re.compile(r"^\s*(\d+):(\d{2})\s*$")
_ATHLETE_ID = re.compile(r"/id/(\d+)")


def mapping(value: Any) -> Mapping[str, Any]:
    """Return ``value`` when it is a mapping, otherwise an empty one."""
    return value if isinstance(value, Mapping) else {}


def sequence(value: Any) -> Sequence[Any]:
    """Return ``value`` when it is a list, otherwise an empty one."""
    return value if isinstance(value, list) else []


def to_int(value: Any) -> int | None:
    """Parse an integer-like value without treating booleans as integers.

    Display strings such as ``"3,587"`` and float strings with no fraction
    (``"5.000"``) are accepted; ``"--"`` and other markers become NULL.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        number = to_decimal(text)
        if number is not None and number == number.to_integral_value():
            return int(number)
        return None


def to_decimal(value: Any, scale: int | None = None) -> Decimal | None:
    """Parse a finite decimal, returning NULL for display markers such as ``--``.

    With ``scale`` the value is rounded half-even to that many places, so it
    fits a fixed ``DECIMAL(p, scale)`` column.
    """
    if value is None or isinstance(value, bool):
        return None
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        result = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite():
        return None
    if scale is not None:
        result = result.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_EVEN)
    return result


def to_bool(value: Any) -> bool | None:
    """Return a boolean only for genuine JSON booleans."""
    return value if isinstance(value, bool) else None


def to_text(value: Any) -> str | None:
    """Return a non-empty string, or NULL."""
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def to_timestamp(value: Any) -> datetime | None:
    """Parse ESPN's ISO-8601 timestamps (``2025-09-05T00:20Z`` and friends) into UTC."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(text)
    except (ValueError, OverflowError):
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def to_date(value: Any) -> date | None:
    """Parse a calendar date, taking the date part of a timestamp when needed."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def clock_seconds(value: Any) -> int | None:
    """Convert an ``MM:SS`` display clock into whole seconds."""
    match = _CLOCK.match(value) if isinstance(value, str) else None
    return int(match.group(1)) * 60 + int(match.group(2)) if match else None


def split_pair(value: Any, separator: str) -> tuple[int | None, int | None]:
    """Split ESPN pair displays such as ``21/34`` or ``7-11`` into two integers."""
    if not isinstance(value, str) or separator not in value:
        return None, None
    left, _, right = value.partition(separator)
    return to_int(left), to_int(right)


def athlete_id_from_links(links: Any) -> int | None:
    """Recover an ESPN athlete id from a player-card link when no id field is present."""
    for link in sequence(links):
        match = _ATHLETE_ID.search(str(mapping(link).get("href", "")))
        if match:
            return int(match.group(1))
    return None


def batch_from_rows(rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> pa.RecordBatch:
    """Build a record batch in the requested (possibly projected) column order."""
    return pa.RecordBatch.from_arrays(
        [pa.array([row.get(value.name) for row in rows], type=value.type) for value in schema],
        schema=schema,
    )
