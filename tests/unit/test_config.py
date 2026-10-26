from __future__ import annotations

from pathlib import Path

import pytest

from mariadb_mcp.config import ConfigurationError, load_config


def write_config(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_settings_and_secret_from_environment(tmp_path: Path) -> None:
    path = write_config(
        tmp_path / "mcp.toml",
        """
        [database]
        host = "localhost"
        port = 3307
        default_database = "appdb"
        username = "mcp_ro"

        [access]
        allowed_databases = ["appdb"]
        allowed_tables = ["appdb.orders"]
        allowed_columns = { "appdb.orders" = ["id", "label"] }

        [limits]
        query_timeout_seconds = 8
        max_rows = 50
        """,
    )

    config = load_config(path, environ={"MARIADB_MCP_PASSWORD": "sentinel"})

    assert config.database.host == "localhost"
    assert config.database.port == 3307
    assert config.database.password == "sentinel"
    assert config.access.allowed_databases == ("appdb",)
    assert config.access.allowed_tables["appdb"] == ("orders",)
    assert config.access.allowed_columns["appdb.orders"] == ("id", "label")
    assert config.limits.query_timeout_seconds == 8
    assert config.limits.max_rows == 50
    assert "sentinel" not in repr(config)


def test_missing_allowlist_fails_closed_without_revealing_database_names(
    tmp_path: Path,
) -> None:
    path = write_config(
        tmp_path / "mcp.toml",
        """
        [database]
        host = "localhost"
        username = "mcp_ro"
        """,
    )

    config = load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})

    assert config.access.allowed_databases == ()
    assert not config.access.database_allowed("private_db")


@pytest.mark.parametrize(
    ("database_fields", "env", "message"),
    [
        ('host = ""\nusername = "mcp_ro"', {"MARIADB_MCP_PASSWORD": "x"}, "host"),
        (
            'host = "localhost"\nport = 0\nusername = "mcp_ro"',
            {"MARIADB_MCP_PASSWORD": "x"},
            "port",
        ),
        (
            'host = "localhost"\nusername = ""',
            {"MARIADB_MCP_PASSWORD": "x"},
            "username",
        ),
        ('host = "localhost"\nusername = "mcp_ro"', {}, "password"),
        (
            'host = "db.example.net"\nusername = "mcp_ro"\ntls_verify = false',
            {"MARIADB_MCP_PASSWORD": "x"},
            "TLS",
        ),
    ],
)
def test_rejects_invalid_connection_configuration(
    tmp_path: Path,
    database_fields: str,
    env: dict[str, str],
    message: str,
) -> None:
    path = write_config(
        tmp_path / "mcp.toml",
        f"[database]\n{database_fields}\n",
    )

    with pytest.raises(ConfigurationError) as error:
        load_config(path, environ=env)

    if message:
        assert message.lower() in str(error.value).lower()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("query_timeout_seconds", 61),
        ("max_rows", 10_001),
        ("max_result_bytes", 8 * 1024 * 1024 + 1),
        ("max_concurrent_queries", 17),
        ("default_page_size", 0),
        ("connect_timeout_seconds", True),
    ],
)
def test_rejects_nonpositive_or_over_ceiling_limits(
    tmp_path: Path, key: str, value: int | bool
) -> None:
    path = write_config(
        tmp_path / "mcp.toml",
        f"""
        [database]
        host = "localhost"
        username = "mcp_ro"
        [access]
        allowed_databases = ["appdb"]
        [limits]
        {key} = {str(value).lower() if isinstance(value, bool) else value}
        """,
    )

    with pytest.raises(ConfigurationError):
        load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})


def test_rejects_tables_and_columns_outside_allowed_database(tmp_path: Path) -> None:
    path = write_config(
        tmp_path / "mcp.toml",
        """
        [database]
        host = "localhost"
        username = "mcp_ro"
        [access]
        allowed_databases = ["appdb"]
        allowed_tables = ["otherdb.orders"]
        """,
    )

    with pytest.raises(ConfigurationError):
        load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})


def test_empty_explicit_table_allowlist_does_not_expand_access(tmp_path: Path) -> None:
    path = write_config(
        tmp_path / "mcp.toml",
        """
        [database]
        host = "localhost"
        username = "mcp_ro"
        [access]
        allowed_databases = ["appdb"]
        allowed_tables = []
        """,
    )

    with pytest.raises(ConfigurationError):
        load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})


def test_table_allowlist_does_not_expand_to_other_allowed_databases(
    tmp_path: Path,
) -> None:
    path = write_config(
        tmp_path / "mcp.toml",
        """
        [database]
        host = "localhost"
        username = "mcp_ro"
        [access]
        allowed_databases = ["appdb", "otherdb"]
        allowed_tables = ["appdb.orders"]
        """,
    )
    config = load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})

    assert config.access.table_allowed("appdb", "orders") is True
    assert config.access.table_allowed("otherdb", "private") is False
