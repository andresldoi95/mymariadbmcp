from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from mariadb_mcp.config import load_config
from mariadb_mcp.errors import ErrorCode, MCPAppError
from mariadb_mcp.query_service import QueryService
from mariadb_mcp.write_service import WriteService

pytestmark = pytest.mark.integration


def _write_config():
    path = os.environ.get("MARIADB_MCP_WRITE_CONFIG")
    if os.environ.get("MARIADB_MCP_INTEGRATION") != "1" or not path:
        pytest.skip(
            "Set MARIADB_MCP_INTEGRATION=1 and MARIADB_MCP_WRITE_CONFIG "
            "for a disposable write-enabled database."
        )
    return load_config(Path(path))


def test_insert_commits_one_row_and_rolls_back_constraint_failure() -> None:
    config = _write_config()
    writer = WriteService(config)
    reader = QueryService(config)
    label = f"write-{uuid4().hex}"

    result = writer.insert("mcp_test", "sample_records", {"label": label})
    count = reader.execute(
        "SELECT COUNT(*) FROM mcp_test.sample_records WHERE label = ?", [label]
    )["rows"][0][0]

    assert result["status"] == "success"
    assert result["affected_rows"] == 1
    assert count == 1

    with pytest.raises(MCPAppError) as error:
        writer.insert("mcp_test", "sample_records", {"label": "first"})

    assert error.value.code is ErrorCode.DATABASE_ERROR
    duplicate_count = reader.execute(
        "SELECT COUNT(*) FROM mcp_test.sample_records WHERE label = ?", ["first"]
    )["rows"][0][0]
    assert duplicate_count == 1


def test_update_is_bounded_and_rolls_back_over_cap() -> None:
    config = _write_config()
    writer = WriteService(config)
    reader = QueryService(config)
    original_label = f"update-{uuid4().hex}"
    updated_label = f"updated-{uuid4().hex}"
    writer.insert("mcp_test", "sample_records", {"label": original_label})

    result = writer.update(
        "mcp_test",
        "sample_records",
        {"label": updated_label},
        {"label": original_label},
    )
    updated_count = reader.execute(
        "SELECT COUNT(*) FROM mcp_test.sample_records WHERE label = ?",
        [updated_label],
    )["rows"][0][0]

    assert result["affected_rows"] == 1
    assert updated_count == 1

    before = reader.execute(
        "SELECT COUNT(*) FROM mcp_test.sample_records WHERE group_key = ?",
        ["fixture"],
    )["rows"][0][0]
    with pytest.raises(MCPAppError) as error:
        writer.update(
            "mcp_test",
            "sample_records",
            {"label": "over-cap"},
            {"group_key": "fixture"},
        )
    after = reader.execute(
        "SELECT COUNT(*) FROM mcp_test.sample_records WHERE group_key = ?",
        ["fixture"],
    )["rows"][0][0]
    changed_count = reader.execute(
        "SELECT COUNT(*) FROM mcp_test.sample_records WHERE label = ?", ["over-cap"]
    )["rows"][0][0]

    assert error.value.code is ErrorCode.RESULT_LIMIT
    assert after == before
    assert changed_count == 0


def test_delete_is_bounded_and_rolls_back_over_cap() -> None:
    config = _write_config()
    writer = WriteService(config)
    reader = QueryService(config)
    label = f"delete-{uuid4().hex}"
    writer.insert("mcp_test", "sample_records", {"label": label})

    result = writer.delete("mcp_test", "sample_records", {"label": label})
    count = reader.execute(
        "SELECT COUNT(*) FROM mcp_test.sample_records WHERE label = ?", [label]
    )["rows"][0][0]
    no_match = writer.delete("mcp_test", "sample_records", {"label": label})

    assert result["affected_rows"] == 1
    assert count == 0
    assert no_match["affected_rows"] == 0

    before = reader.execute(
        "SELECT COUNT(*) FROM mcp_test.sample_records WHERE group_key = ?",
        ["fixture"],
    )["rows"][0][0]
    with pytest.raises(MCPAppError) as error:
        writer.delete("mcp_test", "sample_records", {"group_key": "fixture"})
    after = reader.execute(
        "SELECT COUNT(*) FROM mcp_test.sample_records WHERE group_key = ?",
        ["fixture"],
    )["rows"][0][0]

    assert error.value.code is ErrorCode.RESULT_LIMIT
    assert after == before
