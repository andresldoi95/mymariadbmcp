from __future__ import annotations

import os
from pathlib import Path

import pytest

from mariadb_mcp.config import load_config
from mariadb_mcp.connection import connection_scope

pytestmark = pytest.mark.integration


def test_configured_statement_deadline_is_applied_by_mariadb() -> None:
    config_path = os.environ.get("MARIADB_MCP_TEST_TIMEOUT_CONFIG")
    if os.environ.get("MARIADB_MCP_INTEGRATION") != "1" or not config_path:
        pytest.skip(
            "Set MARIADB_MCP_INTEGRATION=1 and "
            "MARIADB_MCP_TEST_TIMEOUT_CONFIG for a disposable database."
        )
    config = load_config(Path(config_path))
    import mariadb

    with connection_scope(config) as connection:
        cursor = connection.cursor(buffered=True)
        try:
            cursor.execute("SELECT @@SESSION.max_statement_time")
            assert float(cursor.fetchone()[0]) == config.limits.query_timeout_seconds

            # This raw read-only probe is deliberately outside the app SQL subset;
            # it verifies MariaDB enforces the session deadline itself.
            with pytest.raises(mariadb.Error) as timeout:
                cursor.execute("SELECT SLEEP(3)")
            assert getattr(timeout.value, "errno", None) == 1969
        finally:
            cursor.close()
