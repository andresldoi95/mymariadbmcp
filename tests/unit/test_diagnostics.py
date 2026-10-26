from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from mariadb_mcp.config import load_config
from mariadb_mcp.tools.diagnostics import DiagnosticsService


class DiagnosticCursor:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.closed = False

    def execute(self, query: str) -> None:
        assert query == "SELECT 1"
        if self.error:
            raise self.error

    def fetchone(self) -> tuple[int]:
        return (1,)

    def close(self) -> None:
        self.closed = True


class DiagnosticConnection:
    def __init__(self, cursor: DiagnosticCursor) -> None:
        self.fake_cursor = cursor
        self.closed = False

    def cursor(self, *, buffered: bool) -> DiagnosticCursor:
        assert buffered is True
        return self.fake_cursor

    def close(self) -> None:
        self.closed = True


def make_service(
    tmp_path: Path,
    *,
    host: str = "localhost",
    username: str = "mcp_ro",
    error: Exception | None = None,
) -> tuple[DiagnosticsService, DiagnosticConnection, DiagnosticCursor]:
    path = tmp_path / "mcp.toml"
    path.write_text(
        f"""
        [database]
        host = "{host}"
        username = "{username}"
        [access]
        allowed_databases = ["appdb"]
        """,
        encoding="utf-8",
    )
    config = load_config(path, environ={"MARIADB_MCP_PASSWORD": "sentinel-password"})
    cursor = DiagnosticCursor(error)
    connection = DiagnosticConnection(cursor)

    @contextmanager
    def connection_factory() -> Iterator[DiagnosticConnection]:
        try:
            if error and isinstance(error, ConnectionError):
                raise error
            yield connection
        finally:
            connection.close()

    return DiagnosticsService(config, connection_factory), connection, cursor


def test_successful_diagnostics_return_only_curated_fields(tmp_path: Path) -> None:
    service, connection, cursor = make_service(tmp_path)

    result = service.diagnose()

    assert result == {
        "status": "ok",
        "category": "connected",
        "message": "Database connection is available.",
    }
    assert connection.closed is True
    assert cursor.closed is True


def test_failed_diagnostics_do_not_leak_connection_or_secret_details(
    tmp_path: Path,
) -> None:
    service, connection, _ = make_service(
        tmp_path,
        host="db.internal",
        username="sensitive_user",
        error=ConnectionError("password=sentinel-password host=db.internal"),
    )

    result = service.diagnose()
    response = repr(result)

    assert result["status"] == "unavailable"
    assert result["category"] == "connection_failed"
    assert "sentinel-password" not in response
    assert "db.internal" not in response
    assert "sensitive_user" not in response
    assert connection.closed is True


def test_malformed_configuration_has_a_diagnostic_only_result() -> None:
    result = DiagnosticsService(None).diagnose()

    assert result == {
        "status": "misconfigured",
        "category": "configuration_invalid",
        "message": "Server configuration is missing or invalid.",
    }
