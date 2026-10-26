from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from mariadb_mcp.config import load_config
from mariadb_mcp.errors import ErrorCode, MCPAppError
from mariadb_mcp.query_service import QueryService
from mariadb_mcp.sql_policy import TableSchema


class FakeCursor:
    description = [("id", "BIGINT", None, None, None, None, False)]

    def __init__(self, rows: list[tuple[Any, ...]], *, error: Exception | None = None):
        self.rows = list(rows)
        self.error = error
        self.closed = False
        self.executed: tuple[str, tuple[Any, ...]] | None = None

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> None:
        self.executed = (sql, parameters)
        if self.error:
            raise self.error

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows.pop(0) if self.rows else None

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.fake_cursor = cursor
        self.closed = False

    def cursor(self, *, buffered: bool) -> FakeCursor:
        assert buffered is False
        return self.fake_cursor

    def close(self) -> None:
        self.closed = True


def make_service(
    tmp_path: Path,
    rows: list[tuple[Any, ...]],
    *,
    max_rows: int = 1000,
    max_bytes: int = 2 * 1024 * 1024,
    error: Exception | None = None,
) -> tuple[QueryService, FakeConnection, FakeCursor]:
    path = tmp_path / "mcp.toml"
    path.write_text(
        f"""
        [database]
        host = "localhost"
        username = "mcp_ro"
        default_database = "appdb"
        [access]
        allowed_databases = ["appdb"]
        allowed_tables = ["appdb.orders"]
        [limits]
        max_rows = {max_rows}
        max_result_bytes = {max_bytes}
        """,
        encoding="utf-8",
    )
    config = load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})
    cursor = FakeCursor(rows, error=error)
    connection = FakeConnection(cursor)

    @contextmanager
    def connection_factory() -> Iterator[FakeConnection]:
        try:
            yield connection
        finally:
            connection.close()

    def schema_resolver(
        _connection: FakeConnection, database: str, table: str
    ) -> TableSchema | None:
        if (database, table) == ("appdb", "orders"):
            return TableSchema(frozenset({"id", "label"}))
        return None

    return (
        QueryService(
            config,
            connection_factory,
            schema_resolver=schema_resolver,
        ),
        connection,
        cursor,
    )


def test_returns_structured_rows_and_uses_bound_values_without_rewriting_sql(
    tmp_path: Path,
) -> None:
    service, connection, cursor = make_service(tmp_path, [(7,), (8,)])
    sql = "SELECT id FROM appdb.orders WHERE label = ? ORDER BY id LIMIT 2"

    result = service.execute(sql, ["needle"])

    assert cursor.executed == (sql, ("needle",))
    assert result["columns"] == [{"name": "id", "type": "BIGINT"}]
    assert result["rows"] == [[7], [8]]
    assert result["row_count"] == 2
    assert result["truncated"] is False
    assert result["has_more"] is False
    assert cursor.closed is True
    assert connection.closed is True


def test_result_type_codes_include_readable_types_and_precision(tmp_path: Path) -> None:
    service, _, cursor = make_service(tmp_path, [("12.34", "hello", 7)])
    cursor.description = [
        ("amount", 246, None, None, 10, 2, True),
        ("label", 253, 64, 64, None, None, True),
        ("count", 8, None, None, 20, 0, False),
    ]

    result = service.execute(
        "SELECT ROUND(id, 2) AS amount, LOWER(label) AS label, "
        "COUNT(*) AS count FROM appdb.orders",
        [],
    )

    assert result["columns"] == [
        {"name": "amount", "type": "DECIMAL(10,2)"},
        {"name": "label", "type": "VARCHAR(64)"},
        {"name": "count", "type": "BIGINT"},
    ]


def test_row_cap_fetches_only_one_extra_row_and_reports_truncation(
    tmp_path: Path,
) -> None:
    service, _, _ = make_service(tmp_path, [(1,), (2,), (3,), (4,)], max_rows=2)

    result = service.execute("SELECT id FROM appdb.orders", [])

    assert result["rows"] == [[1], [2]]
    assert result["truncated"] is True
    assert result["truncation_reason"] == "row_limit"
    assert result["has_more"] is True


def test_byte_cap_stops_streaming_without_returning_oversized_row(
    tmp_path: Path,
) -> None:
    service, _, _ = make_service(
        tmp_path,
        [("x" * 700,), ("y" * 700,)],
        max_bytes=1024,
    )

    result = service.execute("SELECT label FROM appdb.orders", [])

    assert result["truncated"] is True
    assert result["truncation_reason"] == "byte_limit"
    assert result["row_count"] <= 1


def test_parameter_count_must_match_placeholders(tmp_path: Path) -> None:
    service, connection, cursor = make_service(tmp_path, [(1,)])

    with pytest.raises(MCPAppError) as error:
        service.execute("SELECT id FROM appdb.orders WHERE id = ?", [])

    assert error.value.code is ErrorCode.INVALID_INPUT
    assert connection.closed is True
    assert cursor.executed is None


def test_timeout_and_database_errors_are_safe_and_resources_close(
    tmp_path: Path,
) -> None:
    service, connection, cursor = make_service(
        tmp_path,
        [],
        error=TimeoutError("password=sentinel database=private"),
    )

    with pytest.raises(MCPAppError) as error:
        service.execute("SELECT id FROM appdb.orders", [])

    assert error.value.code is ErrorCode.QUERY_TIMEOUT
    assert "sentinel" not in str(error.value)
    assert "private" not in str(error.value)
    assert cursor.closed is True
    assert connection.closed is True


def test_mariadb_statement_deadline_error_maps_to_query_timeout(
    tmp_path: Path,
) -> None:
    class OperationalError(Exception):
        errno = 1969

    service, connection, cursor = make_service(
        tmp_path,
        [],
        error=OperationalError("query execution interrupted"),
    )

    with pytest.raises(MCPAppError) as error:
        service.execute("SELECT id FROM appdb.orders", [])

    assert error.value.code is ErrorCode.QUERY_TIMEOUT
    assert cursor.closed is True
    assert connection.closed is True


def test_concurrency_limit_rejects_without_opening_connection(tmp_path: Path) -> None:
    service, connection, _ = make_service(tmp_path, [(1,)])
    for _ in range(4):
        service._semaphore.acquire()

    try:
        with pytest.raises(MCPAppError) as error:
            service.execute("SELECT id FROM appdb.orders", [])
    finally:
        for _ in range(4):
            service._semaphore.release()

    assert error.value.code is ErrorCode.RESULT_LIMIT
    assert connection.closed is False
