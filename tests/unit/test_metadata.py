from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from mariadb_mcp.config import load_config
from mariadb_mcp.errors import ErrorCode, MCPAppError
from mariadb_mcp.tools.metadata import MetadataService


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.rows: list[tuple[Any, ...]] = []
        self.closed = False

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        self.connection.queries.append((query, params))
        if "information_schema.TABLES" in query:
            names = sorted(self.connection.tables)
            if "LIMIT 1" in query:
                if "TABLE_NAME IN" in query:
                    allowed = set(params[1:])
                    names = [name for name in names if name in allowed]
                self.rows = [(names[0],)] if names else []
                return
            if "TABLE_NAME IN" in query:
                allowed = set(params[1:-2])
                names = [name for name in names if name in allowed]
            limit, offset = params[-2:]
            self.rows = [(name,) for name in names[offset : offset + limit]]
        elif "SELECT PRIVILEGES FROM information_schema.COLUMNS" in query:
            self.rows = [("select",)] if params[2] == "id" else []
        elif "information_schema.COLUMNS" in query:
            self.rows = [
                ("id", "bigint", "bigint(20) unsigned", "NO", "select"),
                ("label", "varchar", "varchar(64)", "YES", "select"),
                ("customer_id", "bigint", "bigint(20)", "YES", "select"),
                ("secret", "varchar", "varchar(255)", "YES", "select"),
            ]
        elif "information_schema.KEY_COLUMN_USAGE" in query:
            self.rows = [
                ("PRIMARY", "id", None, None, None, 1),
                ("fk_customer", "customer_id", "appdb", "customers", "id", 1),
            ]
        elif "information_schema.STATISTICS" in query:
            self.rows = [
                ("PRIMARY", 0, "id", 1),
                ("idx_label", 1, "label", 1),
                ("idx_secret", 1, "secret", 1),
            ]
        else:
            raise AssertionError(f"Unexpected metadata SQL: {query}")

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self) -> None:
        self.schemas = {"appdb"}
        self.tables = ["customers", "orders", "private"]
        self.queries: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


def make_service(
    tmp_path: Path,
    *,
    tables: str = '["appdb.orders", "appdb.customers"]',
    columns: str = '{ "appdb.orders" = ["id", "label", "customer_id"] }',
    connection: FakeConnection | None = None,
) -> tuple[MetadataService, FakeConnection]:
    path = tmp_path / "mcp.toml"
    path.write_text(
        f"""
        [database]
        host = "localhost"
        username = "mcp_ro"
        default_database = "appdb"
        [access]
        allowed_databases = ["appdb"]
        allowed_tables = {tables}
        allowed_columns = {columns}
        """,
        encoding="utf-8",
    )
    config = load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})
    db = connection or FakeConnection()

    @contextmanager
    def connection_factory() -> Iterator[FakeConnection]:
        yield db

    return MetadataService(config, connection_factory), db


def test_lists_only_allowed_and_account_visible_databases(tmp_path: Path) -> None:
    service, connection = make_service(tmp_path)

    result = service.list_databases()

    assert result == {"databases": ["appdb"], "partial": False}
    assert all("SHOW DATABASES" not in query for query, _ in connection.queries)
    assert connection.queries[0][1] == ("appdb", "orders", "customers")


def test_table_listing_filters_policy_and_paginates(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path)

    result = service.list_tables("appdb", page_size=1, offset=0)

    assert result["tables"] == ["customers"]
    assert result["has_more"] is True
    assert result["next_offset"] == 1


def test_describes_columns_keys_indexes_and_visible_foreign_keys(
    tmp_path: Path,
) -> None:
    service, _ = make_service(tmp_path)

    result = service.describe_table("appdb", "orders")

    assert [column["name"] for column in result["columns"]] == [
        "id",
        "label",
        "customer_id",
    ]
    assert [column["type"] for column in result["columns"]] == [
        "bigint(20) unsigned",
        "varchar(64)",
        "bigint(20)",
    ]
    assert result["primary_key"] == ["id"]
    assert result["indexes"] == [
        {"name": "PRIMARY", "unique": True, "columns": ["id"]},
        {"name": "idx_label", "unique": False, "columns": ["label"]},
    ]
    assert result["foreign_keys"] == [
        {
            "name": "fk_customer",
            "referenced_database": "appdb",
            "referenced_table": "customers",
            "columns": [{"local": "customer_id", "referenced": "id"}],
        }
    ]
    assert result["partial"] is True


@pytest.mark.parametrize(
    "database,table", [("otherdb", "orders"), ("appdb", "private")]
)
def test_rejects_objects_outside_policy_without_echoing_names(
    tmp_path: Path, database: str, table: str
) -> None:
    service, _ = make_service(tmp_path)

    with pytest.raises(MCPAppError) as error:
        service.describe_table(database, table)

    assert error.value.code is ErrorCode.AUTHORIZATION_DENIED
    assert database not in str(error.value)
    assert table not in str(error.value)
