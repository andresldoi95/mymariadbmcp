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


def test_direct_write_grants_allow_opted_in_user_but_not_read_only_user(
    tmp_path: Path,
) -> None:
    writer_path = os.environ.get("MARIADB_MCP_WRITE_CONFIG")
    if os.environ.get("MARIADB_MCP_INTEGRATION") != "1" or not writer_path:
        pytest.skip(
            "Set MARIADB_MCP_INTEGRATION=1 and MARIADB_MCP_WRITE_CONFIG "
            "for a disposable database."
        )

    password = os.environ.get("MARIADB_MCP_PASSWORD", "")
    writer_config = load_config(Path(writer_path))
    writer = WriteService(writer_config)
    label = f"privilege-{uuid4().hex}"
    result = writer.insert("mcp_test", "sample_records", {"label": label})
    assert result["affected_rows"] == 1

    readonly_path = tmp_path / "readonly-with-write-policy.toml"
    readonly_path.write_text(
        """
        [database]
        host = "mariadb"
        port = 3306
        default_database = "mcp_test"
        username = "mcp_ro"
        tls_verify = true
        ca_file = "/etc/mysql/certs/ca.pem"

        [access]
        allowed_databases = ["mcp_test"]

        [writes]
        max_affected_rows = 2
        insert_columns = { "mcp_test.sample_records" = ["label"] }
        """,
        encoding="utf-8",
    )
    readonly_config = load_config(
        readonly_path,
        environ={"MARIADB_MCP_PASSWORD": password},
    )
    readonly_writer = WriteService(readonly_config)
    reader = QueryService(readonly_config)
    denied_label = f"denied-{uuid4().hex}"

    with pytest.raises(MCPAppError) as error:
        readonly_writer.insert("mcp_test", "sample_records", {"label": denied_label})

    persisted_count = reader.execute(
        "SELECT COUNT(*) FROM mcp_test.sample_records WHERE label = ?", [label]
    )["rows"][0][0]
    denied_count = reader.execute(
        "SELECT COUNT(*) FROM mcp_test.sample_records WHERE label = ?",
        [denied_label],
    )["rows"][0][0]

    assert error.value.code is ErrorCode.DATABASE_ERROR
    assert persisted_count == 1
    assert denied_count == 0
    assert denied_label not in str(error.value)
