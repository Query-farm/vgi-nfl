"""Emit helpers shared by every NFL table function."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pyarrow as pa
from vgi.cache_control import CacheControl
from vgi_rpc.rpc import OutputCollector

from vgi_nfl.convert import batch_from_rows


def cache_control(ttl: int) -> CacheControl | None:
    """Forward the response's remaining freshness lifetime to VGI clients."""
    return CacheControl(ttl=ttl) if ttl > 0 else None


def emit_rows(out: OutputCollector, rows: Sequence[Mapping[str, Any]], schema: pa.Schema, ttl: int) -> None:
    """Emit flattened rows as one batch in the requested column order."""
    out.emit(batch_from_rows(rows, schema), cache_control=cache_control(ttl))
    out.finish()


def emit_table(out: OutputCollector, table: pa.Table, schema: pa.Schema, ttl: int) -> None:
    """Emit an Arrow table as one batch (the SDK accepts one data batch per call)."""
    table = table.select(schema.names).cast(schema).combine_chunks()
    batches = table.to_batches()
    batch = batches[0] if batches else pa.RecordBatch.from_pylist([], schema=schema)
    out.emit(batch, cache_control=cache_control(ttl))
    out.finish()
