from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mariadb_mcp.config import load_config
from mariadb_mcp.errors import ErrorCode, MCPAppError
from mariadb_mcp.write_policy import (
    WriteTargetSchema,
    resolve_write_target,
    validate_delete_request,
    validate_insert_request,
    validate_update_request,
)


def make_config(
    tmp_path: Path,
    *,
    access_columns: str = '["id", "label"]',
    writes: str = """
    [writes]
    max_affected_rows = 10
    insert_columns = { "appdb.orders" = ["label"] }
    update_columns = { "appdb.orders" = ["label"] }
    delete_tables = ["appdb.orders"]
    """,
):
    path = tmp_path / "mcp.toml"
    path.write_text(
        f"""
        [database]
        host = "localhost"
        username = "mcp_rw"
        [access]
        allowed_databases = ["appdb"]
        allowed_tables = ["appdb.orders"]
        allowed_columns = {{ "appdb.orders" = {access_columns} }}
        {writes}
        """,
        encoding="utf-8",
    )
    return load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})


def schema(
    *,
    engine: str = "InnoDB",
    columns: tuple[str, ...] = ("id", "label"),
    primary_key: tuple[str, ...] = ("id",),
    is_base_table: bool = True,
    complete: bool = True,
) -> WriteTargetSchema:
    return WriteTargetSchema(
        columns=frozenset(columns),
        engine=engine,
        primary_key=primary_key,
        is_base_table=is_base_table,
        complete=complete,
    )


def test_insert_validates_permitted_columns_and_json_scalar_values(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)

    validated = validate_insert_request(
        config,
        "appdb",
        "orders",
        {"label": "new order"},
        schema(),
    )

    assert validated.database == "appdb"
    assert validated.table == "orders"
    assert validated.values == (("label", "new order"),)


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"id": 7},
        {"secret": "hidden"},
        {"label": ["nested", "value"]},
    ],
)
def test_insert_rejects_empty_or_unauthorized_values(
    tmp_path: Path, values: dict[str, Any]
) -> None:
    with pytest.raises(MCPAppError):
        validate_insert_request(
            make_config(tmp_path), "appdb", "orders", values, schema()
        )


def test_update_validates_values_filters_and_readable_primary_key(
    tmp_path: Path,
) -> None:
    validated = validate_update_request(
        make_config(tmp_path),
        "appdb",
        "orders",
        {"label": "updated"},
        {"id": 7},
        schema(),
    )

    assert validated.values == (("label", "updated"),)
    assert validated.filters == (("id", 7),)
    assert validated.target.primary_key == ("id",)


@pytest.mark.parametrize(
    ("values", "filters"),
    [
        ({"label": "x"}, {}),
        ({}, {"id": 1}),
        ({"id": 1}, {"id": 1}),
        ({"label": "x"}, {"secret": "value"}),
    ],
)
def test_update_rejects_empty_or_unauthorized_values_and_filters(
    tmp_path: Path, values: dict[str, Any], filters: dict[str, Any]
) -> None:
    with pytest.raises(MCPAppError):
        validate_update_request(
            make_config(tmp_path), "appdb", "orders", values, filters, schema()
        )


def test_null_filter_is_preserved_for_is_null_compilation(tmp_path: Path) -> None:
    validated = validate_delete_request(
        make_config(tmp_path),
        "appdb",
        "orders",
        {"label": None},
        schema(),
    )

    assert validated.filters == (("label", None),)


@pytest.mark.parametrize(
    "target_schema",
    [
        None,
        schema(engine="MyISAM"),
        schema(primary_key=()),
        schema(is_base_table=False),
        schema(complete=False),
        schema(columns=("label",), primary_key=("id",)),
    ],
)
def test_delete_fails_closed_without_transactional_stable_target(
    tmp_path: Path, target_schema: WriteTargetSchema | None
) -> None:
    with pytest.raises(MCPAppError) as error:
        validate_delete_request(
            make_config(tmp_path), "appdb", "orders", {"id": 1}, target_schema
        )

    assert error.value.code is ErrorCode.AUTHORIZATION_DENIED


def test_filter_and_primary_key_columns_must_be_readable(tmp_path: Path) -> None:
    config = make_config(tmp_path, access_columns='["label"]')

    with pytest.raises(MCPAppError) as error:
        validate_delete_request(config, "appdb", "orders", {"label": "x"}, schema())

    assert error.value.code is ErrorCode.AUTHORIZATION_DENIED


def test_write_policy_must_allow_the_operation_and_table(tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        writes="""
        [writes]
        max_affected_rows = 10
        insert_columns = { "appdb.orders" = ["label"] }
        """,
    )

    with pytest.raises(MCPAppError) as error:
        validate_delete_request(config, "appdb", "orders", {"id": 1}, schema())

    assert error.value.code is ErrorCode.AUTHORIZATION_DENIED


class MetadataCursor:
    def __init__(self) -> None:
        self.query = ""
        self.parameters: tuple[Any, ...] = ()
        self.closed = False

    def execute(self, query: str, parameters: tuple[Any, ...]) -> None:
        self.query = query
        self.parameters = parameters

    def fetchone(self) -> tuple[str, str] | None:
        if "information_schema.TABLES" in self.query:
            return ("BASE TABLE", "InnoDB")
        return None

    def fetchall(self) -> list[tuple[Any, ...]]:
        if "information_schema.COLUMNS" in self.query:
            return [("id",), ("label",)]
        if "information_schema.KEY_COLUMN_USAGE" in self.query:
            return [("id", 1)]
        return []

    def close(self) -> None:
        self.closed = True


class MetadataConnection:
    def __init__(self) -> None:
        self.cursor_instance = MetadataCursor()

    def cursor(self, *, buffered: bool = True) -> MetadataCursor:
        return self.cursor_instance


def test_resolves_transaction_engine_columns_and_primary_key_from_metadata() -> None:
    connection = MetadataConnection()

    resolved = resolve_write_target(connection, "appdb", "orders")

    assert resolved == schema()
    assert connection.cursor_instance.closed is True
