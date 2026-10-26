from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from mariadb_mcp.config import load_config
from mariadb_mcp.connection import connection_scope
from mariadb_mcp.errors import MCPAppError


@dataclass
class FakeConnection:
    closed: bool = False

    def cursor(self, *, buffered: bool = True) -> FakeCursor:
        return FakeCursor()

    def close(self) -> None:
        self.closed = True


class FakeCursor:
    def __init__(self) -> None:
        self.query = ""
        self.closed = False

    def execute(self, query: str) -> None:
        self.query = query

    def fetchone(self) -> tuple[str, str | None]:
        return ("mcp_ro@localhost", None)

    def fetchall(self) -> list[tuple[str]]:
        return [("GRANT SELECT ON `appdb`.* TO `mcp_ro`@`localhost`",)]

    def close(self) -> None:
        self.closed = True


class FakeDriver:
    def __init__(self, connection: FakeConnection | None = None) -> None:
        self.connection = connection or FakeConnection()
        self.kwargs: dict[str, Any] | None = None

    def connect(self, **kwargs: Any) -> FakeConnection:
        self.kwargs = kwargs
        return self.connection


def test_connection_scope_applies_configured_timeouts_and_verified_tls() -> None:
    config = load_config(
        "tests/fixtures/remote.toml",
        environ={"MARIADB_MCP_PASSWORD": "secret"},
    )
    driver = FakeDriver()

    with connection_scope(config, driver=driver) as connection:
        assert connection is driver.connection
        assert driver.connection.closed is False

    assert driver.connection.closed is True
    assert driver.kwargs is not None
    assert driver.kwargs["connect_timeout"] == config.limits.connect_timeout_seconds
    assert driver.kwargs["read_timeout"] == config.limits.query_timeout_seconds
    assert driver.kwargs["write_timeout"] == config.limits.query_timeout_seconds
    assert driver.kwargs["ssl_verify_cert"] is True
    assert driver.kwargs["ssl_ca"] == "/etc/ssl/test-ca.pem"
    assert driver.kwargs["password"] == "secret"


def test_connection_is_closed_when_operation_raises() -> None:
    config = load_config(
        "tests/fixtures/local.toml",
        environ={"MARIADB_MCP_PASSWORD": "secret"},
    )
    driver = FakeDriver()

    with pytest.raises(RuntimeError):
        with connection_scope(config, driver=driver):
            raise RuntimeError("sentinel failure")

    assert driver.connection.closed is True


def test_connection_failure_does_not_surface_connector_message() -> None:
    config = load_config(
        "tests/fixtures/local.toml",
        environ={"MARIADB_MCP_PASSWORD": "secret"},
    )

    class BrokenDriver:
        def connect(self, **kwargs: Any) -> None:
            raise RuntimeError("password=secret db.internal")

    with pytest.raises(MCPAppError) as error:
        with connection_scope(config, driver=BrokenDriver()):
            pytest.fail("connection unexpectedly succeeded")

    assert "secret" not in str(error.value)
    assert "db.internal" not in str(error.value)


@pytest.mark.parametrize(
    "identity, grants",
    [
        ("root@localhost", [("GRANT ALL PRIVILEGES ON *.* TO `root`@`localhost`",)]),
        ("mcp_ro@localhost", [("GRANT SELECT, INSERT ON `appdb`.* TO `mcp_ro`",)]),
        ("mcp_ro@localhost", [("GRANT SELECT ON *.* TO `mcp_ro`",)]),
        ("mcp_ro@localhost", [("GRANT `reader` TO `mcp_ro`",)]),
    ],
)
def test_connection_rejects_admin_or_excessive_effective_grants(
    identity: str, grants: list[tuple[str]]
) -> None:
    config = load_config(
        "tests/fixtures/local.toml",
        environ={"MARIADB_MCP_PASSWORD": "secret"},
    )

    class GrantCursor(FakeCursor):
        def fetchone(self) -> tuple[str, str | None]:
            return (identity, None)

        def fetchall(self) -> list[tuple[str]]:
            return grants

    class GrantConnection(FakeConnection):
        def cursor(self, *, buffered: bool = True) -> GrantCursor:
            return GrantCursor()

    driver = FakeDriver(GrantConnection())
    with pytest.raises(Exception) as error:
        with connection_scope(config, driver=driver):
            pytest.fail("an unsafe runtime identity was accepted")

    assert "privilege" not in str(error.value).casefold()
    assert "root" not in str(error.value).casefold()
    assert driver.connection.closed is True


def test_connection_rejects_an_active_role_even_if_role_grants_are_not_visible() -> (
    None
):
    config = load_config(
        "tests/fixtures/local.toml",
        environ={"MARIADB_MCP_PASSWORD": "secret"},
    )

    class RoleCursor(FakeCursor):
        def fetchone(self) -> tuple[str, str]:
            return ("mcp_ro@localhost", "report_reader")

    class RoleConnection(FakeConnection):
        def cursor(self, *, buffered: bool = True) -> RoleCursor:
            return RoleCursor()

    driver = FakeDriver(RoleConnection())
    with pytest.raises(MCPAppError):
        with connection_scope(config, driver=driver):
            pytest.fail("an active inherited role was accepted")

    assert driver.connection.closed is True


def _writer_config(tmp_path: Path, *, writes: str = ""):
    path = tmp_path / "writer.toml"
    path.write_text(
        f"""
        [database]
        host = "localhost"
        username = "mcp_rw"
        default_database = "appdb"
        [access]
        allowed_databases = ["appdb"]
        allowed_tables = ["appdb.orders"]
        allowed_columns = {{ "appdb.orders" = ["id", "label"] }}
        {writes}
        """,
        encoding="utf-8",
    )
    return load_config(path, environ={"MARIADB_MCP_PASSWORD": "secret"})


def _grant_connection(grants: list[tuple[str]], identity: str = "mcp_rw@localhost"):
    class GrantCursor(FakeCursor):
        def fetchone(self) -> tuple[str, str | None]:
            return (identity, None)

        def fetchall(self) -> list[tuple[str]]:
            return grants

    class GrantConnection(FakeConnection):
        def cursor(self, *, buffered: bool = True) -> GrantCursor:
            return GrantCursor()

    return GrantConnection()


def test_preflight_accepts_only_scoped_grants_enabled_by_write_policy(
    tmp_path: Path,
) -> None:
    config = _writer_config(
        tmp_path,
        writes="""
        [writes]
        max_affected_rows = 10
        insert_columns = { "appdb.orders" = ["label"] }
        update_columns = { "appdb.orders" = ["label"] }
        delete_tables = ["appdb.orders"]
        """,
    )
    grants = [
        (
            "GRANT USAGE ON *.* TO `mcp_rw`@`localhost` "
            "IDENTIFIED BY PASSWORD '*0123456789ABCDEF' REQUIRE SSL",
        ),
        (
            "GRANT SELECT (`id`, `label`), INSERT (`label`), UPDATE (`label`), "
            "DELETE ON `appdb`.`orders` TO `mcp_rw`@`localhost`",
        ),
    ]

    with connection_scope(config, driver=FakeDriver(_grant_connection(grants))):
        pass


@pytest.mark.parametrize(
    "grant",
    [
        "GRANT INSERT ON *.* TO `mcp_rw`@`localhost`",
        "GRANT UPDATE ON `appdb`.* TO `mcp_rw`@`localhost`",
        "GRANT DELETE ON `appdb`.* TO `mcp_rw`@`localhost`",
        "GRANT INSERT, UPDATE ON `appdb`.`orders` TO `mcp_rw`@`localhost`",
        "GRANT ALL PRIVILEGES ON `appdb`.`orders` TO `mcp_rw`@`localhost`",
        "GRANT INSERT (`secret`) ON `appdb`.`orders` TO `mcp_rw`@`localhost`",
        "GRANT INSERT (`label`) ON `appdb`.`private` TO `mcp_rw`@`localhost`",
        "GRANT INSERT (`label`) ON `appdb`.`orders` TO PUBLIC",
        "GRANT INSERT (`label`) ON `appdb`.`orders` TO `mcp_rw`@`localhost` "
        "WITH GRANT OPTION",
        "GRANT `writer_role` TO `mcp_rw`@`localhost`",
    ],
)
def test_preflight_rejects_broad_or_unsupported_write_grants(
    tmp_path: Path, grant: str
) -> None:
    config = _writer_config(
        tmp_path,
        writes="""
        [writes]
        max_affected_rows = 10
        insert_columns = { "appdb.orders" = ["label"] }
        update_columns = { "appdb.orders" = ["label"] }
        delete_tables = ["appdb.orders"]
        """,
    )
    connection = _grant_connection([(grant,)])

    with pytest.raises(MCPAppError):
        with connection_scope(config, driver=FakeDriver(connection)):
            pytest.fail("an unscoped or unsupported grant passed preflight")

    assert connection.closed is True


def test_combined_grant_is_rejected_if_any_privilege_exceeds_policy(
    tmp_path: Path,
) -> None:
    config = _writer_config(
        tmp_path,
        writes="""
        [writes]
        max_affected_rows = 10
        insert_columns = { "appdb.orders" = ["label"] }
        """,
    )
    grant = (
        "GRANT INSERT (`label`), UPDATE (`label`) ON `appdb`.`orders` "
        "TO `mcp_rw`@`localhost`"
    )

    with pytest.raises(MCPAppError):
        with connection_scope(config, driver=FakeDriver(_grant_connection([(grant,)]))):
            pytest.fail(
                "an unconfigured privilege in a combined grant passed preflight"
            )


def test_write_grants_are_rejected_when_write_policy_is_disabled(
    tmp_path: Path,
) -> None:
    config = load_config(
        "tests/fixtures/local.toml",
        environ={"MARIADB_MCP_PASSWORD": "secret"},
    )
    grants = [("GRANT INSERT ON `appdb`.`orders` TO `mcp_ro`@`localhost`",)]

    with pytest.raises(MCPAppError):
        with connection_scope(
            config,
            driver=FakeDriver(_grant_connection(grants, identity="mcp_ro@localhost")),
        ):
            pytest.fail("write grants were accepted without explicit policy")


def test_connection_rejects_identity_different_from_configured_username() -> None:
    config = load_config(
        "tests/fixtures/local.toml",
        environ={"MARIADB_MCP_PASSWORD": "secret"},
    )
    grants = [("GRANT SELECT ON `appdb`.* TO `mcp_ro`@`localhost`",)]

    with pytest.raises(MCPAppError):
        with connection_scope(
            config,
            driver=FakeDriver(
                _grant_connection(grants, identity="mcp_other@localhost")
            ),
        ):
            pytest.fail(
                "a connection identity different from the configured user passed"
            )
