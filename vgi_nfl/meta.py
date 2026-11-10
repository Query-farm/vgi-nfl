"""Metadata helpers shared by the NFL catalog, its functions, and its Arrow schemas."""

from __future__ import annotations

import json
from typing import Any

import pyarrow as pa
from vgi.metadata import FunctionExample

_COMMENT_KEY = b"comment"


def field(name: str, kind: pa.DataType, comment: str, *, nullable: bool = True) -> pa.Field:
    """Build an Arrow field carrying its SQL column comment."""
    return pa.field(name, kind, nullable=nullable, metadata={_COMMENT_KEY: comment.encode()})


def comment_of(value: pa.Field) -> str:
    """Return the comment stored on an Arrow field."""
    if value.metadata and _COMMENT_KEY in value.metadata:
        return value.metadata[_COMMENT_KEY].decode()
    return ""


def column_comments(schema: pa.Schema) -> dict[str, str]:
    """Return the column-comment mapping expected by a catalog table."""
    return {value.name: comment_of(value) for value in schema if comment_of(value)}


def sql_type(kind: pa.DataType) -> str:
    """Render the DuckDB type name for one of the Arrow types this worker emits."""
    if pa.types.is_decimal(kind):
        return f"DECIMAL({kind.precision},{kind.scale})"
    if pa.types.is_timestamp(kind):
        return "TIMESTAMP WITH TIME ZONE" if kind.tz else "TIMESTAMP"
    if pa.types.is_date(kind):
        return "DATE"
    if pa.types.is_boolean(kind):
        return "BOOLEAN"
    if pa.types.is_int32(kind):
        return "INTEGER"
    if pa.types.is_int64(kind):
        return "BIGINT"
    if pa.types.is_float64(kind):
        return "DOUBLE"
    if pa.types.is_string(kind):
        return "VARCHAR"
    raise ValueError(f"Unsupported NFL result type: {kind}")


def result_columns_schema(schema: pa.Schema) -> str:
    """Render a static Arrow result schema as compact VGI discovery metadata."""
    return json.dumps(
        [
            {
                "name": value.name,
                "type": sql_type(value.type),
                "description": comment_of(value).removesuffix("."),
            }
            for value in schema
        ],
        separators=(",", ":"),
    )


def function_tags(
    *,
    category: str,
    schema: pa.Schema,
    doc_llm: str,
    doc_md: str,
    examples: list[tuple[str, str]],
    source: str,
) -> dict[str, str]:
    """Build the discovery tags every NFL table function carries."""
    return {
        "provider": "nfl",
        "source": source,
        "vgi.category": category,
        "vgi.result_columns_schema": result_columns_schema(schema),
        "vgi.doc_llm": doc_llm,
        "vgi.doc_md": doc_md,
        "vgi.example_queries": json.dumps(
            [{"description": description, "sql": sql} for description, sql in examples]
        ),
    }


def function_examples(examples: list[tuple[str, str]]) -> list[FunctionExample]:
    """Mirror the tagged example queries as SDK function examples."""
    return [FunctionExample(sql=sql, description=description) for description, sql in examples]


def meta_class(
    *,
    name: str,
    description: str,
    category: str,
    schema: pa.Schema,
    doc_llm: str,
    doc_md: str,
    examples: list[tuple[str, str]],
    source: str,
) -> type:
    """Build the nested ``Meta`` class the VGI SDK reads for function discovery."""
    attributes: dict[str, Any] = {
        "__doc__": "Function discovery metadata.",
        "name": name,
        "description": description,
        "categories": ["football", category],
        "projection_pushdown": True,
        "tags": function_tags(
            category=category,
            schema=schema,
            doc_llm=doc_llm,
            doc_md=doc_md,
            examples=examples,
            source=source,
        ),
        "examples": function_examples(examples),
    }
    return type("Meta", (), attributes)
