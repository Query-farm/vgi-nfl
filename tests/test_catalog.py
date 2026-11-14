"""Tests for the SQL-facing catalog shape and its discovery metadata."""

from __future__ import annotations

import json

import pytest

from vgi_nfl.espn_functions import ESPN_FUNCTIONS
from vgi_nfl.meta import comment_of, result_columns_schema, sql_type
from vgi_nfl.nflverse_functions import NFLVERSE_FUNCTIONS
from vgi_nfl.worker import NFL_CATALOG

ALL_FUNCTIONS = [*ESPN_FUNCTIONS, *NFLVERSE_FUNCTIONS]
SCHEMA = NFL_CATALOG.schemas[0]


def test_catalog_surface() -> None:
    assert NFL_CATALOG.name == "nfl"
    assert SCHEMA.path == ["main"]
    assert {table.name for table in SCHEMA.tables} == {
        "current_scoreboard",
        "current_standings",
        "current_injuries",
        "current_week",
        "teams",
        "players",
    }
    names = [function.Meta.name for function in SCHEMA.functions]
    assert len(names) == len(set(names)) == 29
    assert {
        "scoreboard",
        "standings",
        "team_schedule",
        "game_summary",
        "box_score_team",
        "box_score_player",
        "drives",
        "scoring_plays",
        "play_by_play",
        "play_by_play_game",
        "player_stats_week",
        "player_stats_season",
        "team_stats",
        "player_game_log",
        "schedule",
        "roster",
        "depth_chart",
        "draft",
        "combine",
        "snap_counts",
        "ngs_passing",
        "ngs_receiving",
        "ngs_rushing",
    } <= set(names)
    assert {table.function for table in SCHEMA.tables} <= set(SCHEMA.functions)


@pytest.mark.parametrize("function", ALL_FUNCTIONS, ids=lambda function: function.Meta.name)
def test_every_function_is_documented(function: type) -> None:
    tags = function.Meta.tags
    for key in (
        "vgi.doc_llm",
        "vgi.doc_md",
        "vgi.example_queries",
        "vgi.result_columns_schema",
        "source",
    ):
        assert tags[key], key
    examples = json.loads(tags["vgi.example_queries"])
    assert examples and all(f"nfl.main.{function.Meta.name}" in example["sql"] for example in examples)
    assert function.Meta.examples
    columns = json.loads(tags["vgi.result_columns_schema"])
    assert [column["name"] for column in columns] == function.FIXED_SCHEMA.names
    assert all(column["description"] for column in columns)
    assert function.__doc__
    metadata = function.get_metadata()
    assert all(parameter.description for parameter in metadata.parameters)


@pytest.mark.parametrize("table", SCHEMA.tables, ids=lambda table: table.name)
def test_tables_carry_titles_comments_and_keys(table) -> None:
    for key in ("vgi.title", "vgi.doc_llm", "vgi.doc_md", "vgi.keywords", "vgi.example_queries"):
        assert table.tags[key], key
    assert set(table.column_comments) == set(table.function.FIXED_SCHEMA.names)
    kinds = {record.definition.kind for record in table.constraints}
    assert kinds == {"PRIMARY_KEY", "NOT_NULL"}
    for example in json.loads(table.tags["vgi.example_queries"]):
        assert f"nfl.main.{table.name}" in example["sql"]


def test_catalog_discovery_contract_is_machine_readable() -> None:
    tags = NFL_CATALOG.tags
    for key in ("vgi.title", "vgi.subtitle", "vgi.doc_llm", "vgi.doc_md", "vgi.copyright", "vgi.license"):
        assert tags[key]
    examples = json.loads(tags["vgi.executable_examples"])
    tasks = json.loads(tags["vgi.agent_test_tasks"])
    assert all({"name", "description", "sql", "expected_result"} <= example.keys() for example in examples)
    assert 6 <= len(tasks) <= 12
    assert all(set(task) == {"name", "prompt"} for task in tasks)
    assert len({task["name"] for task in tasks}) == len(tasks)
    categories = {category["name"] for category in json.loads(SCHEMA.tags["vgi.categories"])}
    assert {function.Meta.tags["vgi.category"] for function in ALL_FUNCTIONS} <= categories


def test_result_type_rendering() -> None:
    import pyarrow as pa

    assert sql_type(pa.int64()) == "BIGINT"
    assert sql_type(pa.float64()) == "DOUBLE"
    assert sql_type(pa.timestamp("us")) == "TIMESTAMP"
    with pytest.raises(ValueError, match="Unsupported"):
        sql_type(pa.list_(pa.int32()))
    schema = pa.schema([pa.field("x", pa.int32())])
    assert json.loads(result_columns_schema(schema)) == [{"name": "x", "type": "INTEGER", "description": ""}]
    assert comment_of(schema.field("x")) == ""


def test_agent_task_graders_stay_in_step_with_catalog() -> None:
    import re
    from pathlib import Path

    sidecar = (Path(__file__).resolve().parent.parent / "vgi-agent-tests.yaml").read_text()
    graded = re.findall(r"^  - name: (\S+)$", sidecar, flags=re.MULTILINE)
    public = [task["name"] for task in json.loads(NFL_CATALOG.tags["vgi.agent_test_tasks"])]
    assert graded == public
    assert sidecar.count("check_sql:") + sidecar.count("reference_sql:") >= len(public)
