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
        if username != config.database.username.casefold():
            raise ValueError("unexpected identity")
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
            "The database account does not meet the required access policy.",
        ) from None
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                # The connection is discarded by connection_scope on failure.
                pass


def _grant_is_within_policy(grant: str, config: AppConfig) -> bool:
    """Accept only explicit SELECT and configured table/column DML grants."""

    match = re.fullmatch(
        r"\s*GRANT\s+(.+?)\s+ON\s+(.+?)\s+TO\s+(.+?)\s*;?\s*",
        grant,
        flags=re.IGNORECASE,
    )
    if match is None or re.search(
        r"\bWITH\s+(?:GRANT|ADMIN)\s+OPTION\b", grant, flags=re.IGNORECASE
    ):
        return False
    privilege_clause, scope_clause, grantee = match.groups()
    parsed_grantee = _parse_grantee(grantee)
    if parsed_grantee is None:
        return False
    grantee_username, grantee_options = parsed_grantee
    if (
        grantee_username is None
        or grantee_username.casefold() != config.database.username.casefold()
        or not _allowed_grantee_options(grantee_options)
    ):
        return False

    privileges = _split_grant_privileges(privilege_clause)
    if not privileges:
        return False
    scope = _parse_grant_scope(scope_clause)
    if scope is None:
        return False
    if any(privilege == "USAGE" for privilege, _ in privileges):
        return (
            len(privileges) == 1
            and privileges[0][0] == "USAGE"
            and privileges[0][1] is None
            and scope == ("*", "*")
        )
    return all(
        _privilege_is_within_policy(privilege, columns, scope, config)
        for privilege, columns in privileges
    )


def _privilege_is_within_policy(
    privilege: str,
    granted_columns: tuple[str, ...] | None,
    scope: tuple[str, str],
    config: AppConfig,
) -> bool:
    database, table = scope
    if database not in config.access.allowed_databases:
        return False

    if privilege == "SELECT":
        if table == "*":
            if config.access.table_allowlist_configured:
                return False
            if granted_columns is not None and config.access.allowed_columns:
                return False
            return True
        if not config.access.table_allowed(database, table):
            return False
        if granted_columns is None:
            return config.access.allowed_columns.get(f"{database}.{table}") is None
        return all(
            config.access.column_allowed(database, table, column)
            for column in granted_columns
        )

    if not config.writes.enabled or table == "*":
        return False
    if not config.access.table_allowed(database, table):
        return False
    if privilege == "INSERT":
        allowed_columns = config.writes.insert_columns_for(database, table)
    elif privilege == "UPDATE":
        allowed_columns = config.writes.update_columns_for(database, table)
    else:
        return (
            privilege == "DELETE"
            and granted_columns is None
            and config.writes.delete_allowed(database, table)
        )

    # Table-wide INSERT/UPDATE grants exceed the operation's explicit writable
    # column policy, so only direct column grants are accepted.
    return (
        granted_columns is not None
        and bool(granted_columns)
        and bool(allowed_columns)
        and all(column in allowed_columns for column in granted_columns)
    )


def _parse_grantee(grantee: str) -> tuple[str, str] | None:
    account_part = r"(?:`(?:``|[^`])+`|'(?:''|[^'])+'|[A-Za-z0-9_$]+)"
    host_part = r"(?:`(?:``|[^`])+`|'(?:''|[^'])+'|[A-Za-z0-9_%.-]+)"
    match = re.match(
        rf"\s*({account_part})\s*@\s*({host_part})(?P<options>.*)$",
        grantee,
    )
    if match is None:
        return None
    username = match.group(1)
    if username.startswith("`"):
        parsed_username = username[1:-1].replace("``", "`")
    elif username.startswith("'"):
        parsed_username = username[1:-1].replace("''", "'")
    else:
        parsed_username = username
    options = match.group("options").strip().removesuffix(";").strip()
    return parsed_username, options


def _allowed_grantee_options(options: str) -> bool:
    if not options or re.fullmatch(r"REQUIRE\s+SSL", options, re.IGNORECASE):
        return True
    return (
        re.fullmatch(
            r"IDENTIFIED\s+BY\s+PASSWORD\s+'(?:''|[^'])*'"
            r"(?:\s+REQUIRE\s+SSL)?",
            options,
            re.IGNORECASE,
        )
        is not None
    )


def _split_grant_privileges(
    value: str,
) -> tuple[tuple[str, tuple[str, ...] | None], ...]:
    clauses: list[str] = []
    start = 0
    parentheses = 0
    in_backtick = False
    index = 0
    while index < len(value):
        char = value[index]
        if char == "`":
            if in_backtick and index + 1 < len(value) and value[index + 1] == "`":
                index += 2
                continue
            in_backtick = not in_backtick
        elif not in_backtick:
            if char == "(":
                parentheses += 1
            elif char == ")":
                parentheses -= 1
                if parentheses < 0:
                    return ()
            elif char == "," and parentheses == 0:
                clauses.append(value[start:index].strip())
                start = index + 1
        index += 1
    if in_backtick or parentheses != 0:
        return ()
    clauses.append(value[start:].strip())
    if any(not clause for clause in clauses):
        return ()

    parsed: list[tuple[str, tuple[str, ...] | None]] = []
    for clause in clauses:
        match = re.fullmatch(
            r"(?P<privilege>USAGE|SELECT|INSERT|UPDATE|DELETE)"
            r"(?:\s*\((?P<columns>.*)\))?",
            clause,
            flags=re.IGNORECASE,
        )
        if match is None:
            return ()
        privilege = match.group("privilege").upper()
        raw_columns = match.group("columns")
        columns = _parse_grant_columns(raw_columns) if raw_columns is not None else None
        if raw_columns is not None and columns is None:
            return ()
        if privilege == "USAGE" and columns is not None:
            return ()
        parsed.append((privilege, columns))
    return tuple(parsed)


def _read_grant_identifier(value: str, offset: int) -> tuple[str, int] | None:
    while offset < len(value) and value[offset].isspace():
        offset += 1
    if offset >= len(value):
        return None
    if value[offset] == "`":
        offset += 1
        characters: list[str] = []
        while offset < len(value):
            if value[offset] != "`":
                characters.append(value[offset])
                offset += 1
                continue
            if offset + 1 < len(value) and value[offset + 1] == "`":
                characters.append("`")
                offset += 2
                continue
            if not characters:
                return None
            return "".join(characters), offset + 1
        return None
    match = re.match(r"[A-Za-z0-9_$*]+", value[offset:])
    if match is None:
        return None
    return match.group(0), offset + len(match.group(0))


def _parse_grant_scope(scope: str) -> tuple[str, str] | None:
    first = _read_grant_identifier(scope, 0)
    if first is None:
        return None
    database, offset = first
    while offset < len(scope) and scope[offset].isspace():
        offset += 1
    if offset >= len(scope) or scope[offset] != ".":
        return None
    second = _read_grant_identifier(scope, offset + 1)
    if second is None:
        return None
    table, offset = second
    if scope[offset:].strip():
        return None
    return database, table


def _parse_grant_columns(value: str) -> tuple[str, ...] | None:
    columns: list[str] = []
    offset = 0
    while True:
        parsed = _read_grant_identifier(value, offset)
        if parsed is None:
            return None
        column, offset = parsed
        columns.append(column)
        while offset < len(value) and value[offset].isspace():
            offset += 1
        if offset == len(value):
            return tuple(columns) if len(columns) == len(set(columns)) else None
        if value[offset] != ",":
            return None
        offset += 1


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
