from __future__ import annotations

from pathlib import Path

import pytest

from mariadb_mcp.config import load_config
from mariadb_mcp.errors import ErrorCode, MCPAppError
from mariadb_mcp.sql_policy import TableSchema, validate_read_query

SCHEMAS = {
    ("appdb", "orders"): TableSchema(frozenset({"id", "customer_id", "label"})),
    ("appdb", "customers"): TableSchema(frozenset({"id", "name"})),
    ("appdb", "items"): TableSchema(frozenset({"order_id", "sku"})),
    ("appdb", "archived_orders"): TableSchema(frozenset({"id"})),
}


def make_config(
    tmp_path: Path,
    *,
    tables: str = '"appdb.orders", "appdb.customers", "appdb.items"',
    columns: str = "",
):
    path = tmp_path / "mcp.toml"
    column_setting = f"allowed_columns = {{ {columns} }}" if columns else ""
    path.write_text(
        f"""
        [database]
        host = "localhost"
        username = "mcp_ro"
        default_database = "appdb"
        [access]
        allowed_databases = ["appdb"]
        allowed_tables = [{tables}]
        {column_setting}
        """,
        encoding="utf-8",
    )
    return load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})


def resolve_schema(database: str, table: str) -> TableSchema | None:
    return SCHEMAS.get((database, table))


def test_accepts_select_and_authorizes_join_tables_and_columns(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    validated = validate_read_query(
        "SELECT o.id, c.name FROM appdb.orders AS o "
        "JOIN appdb.customers AS c ON o.customer_id = c.id "
        "WHERE o.id = ? ORDER BY o.id LIMIT 10 OFFSET 0",
        config,
        resolve_schema,
    )

    assert validated.statement_count == 1
    assert set(validated.tables) == {("appdb", "orders"), ("appdb", "customers")}
    assert {("appdb", "orders", "customer_id"), ("appdb", "customers", "id")} <= set(
        validated.columns
    )


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE appdb.orders SET label = 'x'",
        "DELETE FROM appdb.orders",
        "INSERT INTO appdb.orders (id) VALUES (1)",
        "CREATE TABLE appdb.bad (id INT)",
        "SELECT id FROM appdb.orders; SELECT id FROM appdb.orders",
        "SELECT id FROM appdb.orders /* hidden */",
        "SELECT id FROM appdb.orders # hidden\n",
        "SELECT id FROM appdb.orders -- hidden\n",
        "SELECT id FROM appdb.orders FOR UPDATE",
        "SELECT o.label FROM appdb.orders o JOIN appdb.customers c USING (id)",
        "SELECT o.label FROM appdb.orders o NATURAL JOIN appdb.customers c",
        "SELECT missing_alias.* FROM appdb.orders o",
        "SELECT id FROM appdb.orders INTO OUTFILE '/tmp/out'",
        "SELECT @x FROM appdb.orders",
        'SELECT "secret" FROM appdb.orders',
        "SELECT id FROM appdb.orders UNION SELECT id FROM appdb.archived_orders",
        "WITH q AS (SELECT id FROM appdb.orders) SELECT id FROM q",
        "SELECT id FROM appdb.orders WHERE id IN (SELECT order_id FROM appdb.items)",
        "SELECT SLEEP(10) FROM appdb.orders",
        "EXPLAIN SELECT id FROM appdb.orders",
    ],
)
def test_rejects_unsupported_or_state_changing_sql(tmp_path: Path, sql: str) -> None:
    config = make_config(tmp_path)

    with pytest.raises(MCPAppError) as error:
        validate_read_query(sql, config, resolve_schema)

    assert error.value.code in {
        ErrorCode.UNSUPPORTED_QUERY,
        ErrorCode.AUTHORIZATION_DENIED,
    }
    assert "secret" not in str(error.value)


def test_comment_markers_inside_quoted_values_are_not_treated_as_comments(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)

    validated = validate_read_query(
        "SELECT '/* not a comment */' AS label FROM appdb.orders LIMIT 1",
        config,
        resolve_schema,
    )

    assert validated.tables == (("appdb", "orders"),)


def test_rejects_unauthorized_table_and_database_even_when_aliased(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)

    with pytest.raises(MCPAppError) as error:
        validate_read_query(
            "SELECT p.id FROM appdb.private AS p",
            config,
            resolve_schema,
        )

    assert error.value.code is ErrorCode.AUTHORIZATION_DENIED
    assert "private" not in str(error.value)


def test_rejects_ambiguous_unqualified_join_column(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    with pytest.raises(MCPAppError) as error:
        validate_read_query(
            "SELECT id FROM appdb.orders o JOIN appdb.customers c ON o.id = c.id",
            config,
            resolve_schema,
        )

    assert error.value.code is ErrorCode.AUTHORIZATION_DENIED


def test_column_allowlist_applies_to_predicates_and_wildcards(tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        tables='"appdb.orders"',
        columns='"appdb.orders" = ["id", "label"]',
    )

    with pytest.raises(MCPAppError) as predicate_error:
        validate_read_query(
            "SELECT id FROM appdb.orders WHERE customer_id = 1",
            config,
            resolve_schema,
        )
    with pytest.raises(MCPAppError) as wildcard_error:
        validate_read_query("SELECT * FROM appdb.orders", config, resolve_schema)
    with pytest.raises(MCPAppError) as quoted_error:
        validate_read_query("SELECT `secret` FROM appdb.orders", config, resolve_schema)

    assert predicate_error.value.code is ErrorCode.AUTHORIZATION_DENIED
    assert wildcard_error.value.code is ErrorCode.UNSUPPORTED_QUERY
    assert quoted_error.value.code is ErrorCode.AUTHORIZATION_DENIED


def test_rejects_unknown_or_incomplete_metadata_fail_closed(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    with pytest.raises(MCPAppError) as error:
        validate_read_query(
            "SELECT id FROM appdb.orders",
            config,
            lambda _database, _table: None,
        )

    assert error.value.code is ErrorCode.AUTHORIZATION_DENIED


def test_rejects_unencodable_sql_text_as_invalid_input(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    with pytest.raises(MCPAppError) as error:
        validate_read_query("SELECT '\ud800'", config, resolve_schema)

    assert error.value.code is ErrorCode.INVALID_INPUT
