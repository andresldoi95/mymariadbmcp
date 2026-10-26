from __future__ import annotations

from dataclasses import dataclass
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
