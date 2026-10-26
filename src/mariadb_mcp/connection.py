"""MariaDB Connector/Python connection lifecycle."""

from __future__ import annotations

import importlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from mariadb_mcp.config import AppConfig
from mariadb_mcp.errors import ErrorCode, MCPAppError, log_database_failure


def _driver_or_raise() -> Any:
    try:
        return importlib.import_module("mariadb")
    except ImportError:
        raise MCPAppError(
            ErrorCode.CONNECTION_FAILED,
            "The MariaDB database connector is not installed.",
        ) from None


def _connection_arguments(config: AppConfig) -> dict[str, Any]:
    settings = config.database
    kwargs: dict[str, Any] = {
        "host": settings.host,
        "port": settings.port,
        "user": settings.username,
        "password": settings.password,
        "connect_timeout": config.limits.connect_timeout_seconds,
        "read_timeout": config.limits.query_timeout_seconds,
        "write_timeout": config.limits.query_timeout_seconds,
        "autocommit": True,
    }
    if settings.default_database is not None:
        kwargs["database"] = settings.default_database
    if not _is_local(settings.host):
        kwargs["ssl"] = True
        kwargs["ssl_verify_cert"] = True
        if settings.ca_file is not None:
            kwargs["ssl_ca"] = settings.ca_file
    return kwargs


def _is_local(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    return normalized == "localhost" or normalized == "127.0.0.1" or normalized == "::1"


def _verify_runtime_identity(connection: Any, config: AppConfig) -> None:
    """Reject identities whose effective grants exceed the configured read scope."""

    cursor = None
    try:
        cursor = connection.cursor(buffered=True)
        cursor.execute(
            f"SET SESSION max_statement_time = {config.limits.query_timeout_seconds}"
        )
        cursor.execute("SELECT CURRENT_USER(), CURRENT_ROLE()")
        identity = cursor.fetchone()
        if not identity or len(identity) < 2:
            raise ValueError("missing identity result")
        username = str(identity[0]).split("@", 1)[0].strip("`'\" ").casefold()
        active_role = identity[1]
        if username in {"root", "admin", "administrator"}:
            raise ValueError("administrative identity")
        if active_role is not None and str(active_role).casefold() not in {
            "",
            "none",
            "null",
        }:
            raise ValueError("active role")

        cursor.execute("SHOW GRANTS")
        grant_rows = cursor.fetchall()
        if not grant_rows:
            raise ValueError("missing grant evidence")
        for row in grant_rows:
            if not row or not _grant_is_within_policy(str(row[0]), config):
                raise ValueError("excessive or unverifiable grant")
    except Exception:
        raise MCPAppError(
            ErrorCode.AUTHORIZATION_DENIED,
            "The database account does not meet the required read-only policy.",
        ) from None
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                # The connection is discarded by connection_scope on failure.
                pass


def _grant_is_within_policy(grant: str, config: AppConfig) -> bool:
    """Accept only scoped SELECT grants; role grants and unknown syntax fail closed."""

    match = re.fullmatch(
        r"\s*GRANT\s+(.+?)\s+ON\s+(.+?)\s+TO\s+.+?\s*;?\s*",
        grant,
        flags=re.IGNORECASE,
    )
    if match is None:
        # This also rejects grants of roles to users or roles to other roles.
        return False
    privilege_clause, scope_clause = match.groups()
    if re.search(r"\bWITH\s+GRANT\s+OPTION\b", grant, flags=re.IGNORECASE):
        return False
    if re.fullmatch(r"USAGE", privilege_clause.strip(), flags=re.IGNORECASE):
        return scope_clause.strip().replace("`", "") == "*.*"

    privilege_match = re.fullmatch(
        r"SELECT(?:\s*\(([^)]*)\))?", privilege_clause.strip(), re.IGNORECASE
    )
    if privilege_match is None:
        return False
    scope = re.fullmatch(
        r"\s*`?([^`.]+)`?\s*\.\s*(\*|`?([^`.]+)`?)\s*",
        scope_clause,
    )
    if scope is None:
        return False
    database, table = scope.group(1).strip("`"), scope.group(3)
    if database not in config.access.allowed_databases:
        return False

    if table is None:
        if config.access.table_allowlist_configured:
            return False
        if privilege_match.group(1) and config.access.allowed_columns:
            return False
        return True
    if not config.access.table_allowed(database, table):
        return False

    granted_columns = privilege_match.group(1)
    if granted_columns is None:
        return config.access.allowed_columns.get(f"{database}.{table}") is None
    columns = [part.strip().strip("`") for part in granted_columns.split(",")]
    if not columns or any(not column for column in columns):
        return False
    allowed_columns = config.access.allowed_columns.get(f"{database}.{table}")
    return allowed_columns is None or all(
        column in allowed_columns for column in columns
    )


@contextmanager
def connection_scope(config: AppConfig, *, driver: Any | None = None) -> Iterator[Any]:
    """Open one request-scoped connection and always release it."""

    connector = _driver_or_raise() if driver is None else driver
    connection: Any | None = None
    try:
        connection = connector.connect(**_connection_arguments(config))
        _verify_runtime_identity(connection, config)
    except MCPAppError:
        if connection is not None:
            try:
                connection.close()
            except Exception as error:
                log_database_failure(error)
        raise
    except Exception as error:
        if connection is not None:
            try:
                connection.close()
            except Exception as close_error:
                log_database_failure(close_error)
        log_database_failure(error)
        raise MCPAppError(
            ErrorCode.CONNECTION_FAILED,
            "The database connection is unavailable.",
        ) from None
    try:
        yield connection
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception as error:
                log_database_failure(error)
