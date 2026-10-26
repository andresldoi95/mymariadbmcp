"""Fail-closed TOML and environment configuration."""

from __future__ import annotations

import ipaddress
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType


class ConfigurationError(ValueError):
    """A safe, client-independent configuration failure."""


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    host: str
    username: str
    password: str = field(repr=False)
    port: int = 3306
    default_database: str | None = None
    tls_verify: bool = True
    ca_file: str | None = None


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    allowed_databases: tuple[str, ...] = ()
    allowed_tables: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    table_allowlist_configured: bool = False
    allowed_columns: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def database_allowed(self, database: str) -> bool:
        return database in self.allowed_databases

    def table_allowed(self, database: str, table: str) -> bool:
        if not self.database_allowed(database):
            return False
        if self.table_allowlist_configured:
            allowed = self.allowed_tables.get(database, ())
            return table in allowed
        allowed = self.allowed_tables.get(database)
        return allowed is None or table in allowed

    def column_allowed(self, database: str, table: str, column: str) -> bool:
        if not self.table_allowed(database, table):
            return False
        allowed = self.allowed_columns.get(f"{database}.{table}")
        return allowed is None or column in allowed


@dataclass(frozen=True, slots=True)
class QueryLimits:
    connect_timeout_seconds: int = 5
    query_timeout_seconds: int = 10
    default_page_size: int = 100
    max_page_size: int = 1000
    max_rows: int = 1000
    max_result_bytes: int = 2 * 1024 * 1024
    max_concurrent_queries: int = 4


@dataclass(frozen=True, slots=True)
class WritePolicy:
    insert_columns: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    update_columns: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    delete_tables: tuple[str, ...] = ()
    max_affected_rows: int | None = None

    @property
    def enabled(self) -> bool:
        return (
            any(self.insert_columns.values())
            or any(self.update_columns.values())
            or bool(self.delete_tables)
        )

    def insert_columns_for(self, database: str, table: str) -> tuple[str, ...]:
        return self.insert_columns.get(f"{database}.{table}", ())

    def update_columns_for(self, database: str, table: str) -> tuple[str, ...]:
        return self.update_columns.get(f"{database}.{table}", ())

    def delete_allowed(self, database: str, table: str) -> bool:
        return f"{database}.{table}" in self.delete_tables


@dataclass(frozen=True, slots=True)
class AppConfig:
    database: DatabaseSettings
    access: AccessPolicy
    limits: QueryLimits
    writes: WritePolicy


_LIMIT_CEILINGS = {
    "connect_timeout_seconds": 60,
    "query_timeout_seconds": 60,
    "default_page_size": 1000,
    "max_page_size": 1000,
    "max_rows": 10_000,
    "max_result_bytes": 8 * 1024 * 1024,
    "max_concurrent_queries": 16,
}


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"Configuration section '{field_name}' is invalid.")
    return value


def _required_string(section: Mapping[str, object], name: str) -> str:
    value = section.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(
            f"Configuration value '{name}' must be a non-empty string."
        )
    return value.strip()


def _optional_string(section: Mapping[str, object], name: str) -> str | None:
    value = section.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(
            f"Configuration value '{name}' must be a non-empty string."
        )
    return value.strip()


def _integer(
    section: Mapping[str, object],
    name: str,
    default: int,
    *,
    maximum: int,
) -> int:
    value = section.get(name, default)
    if type(value) is not int or value < 1 or value > maximum:
        raise ConfigurationError(
            f"Configuration value '{name}' must be an integer from 1 to {maximum}."
        )
    return value


def _string_list(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ConfigurationError(
            f"Configuration value '{field_name}' must be a list of names."
        )
    result = tuple(item.strip() for item in value)
    if len(result) != len(set(result)):
        raise ConfigurationError(
            f"Configuration value '{field_name}' contains duplicates."
        )
    return result


def _parse_tables(value: object) -> Mapping[str, tuple[str, ...]]:
    if value is None:
        return MappingProxyType({})
    names = _string_list(value, "allowed_tables")
    if not names:
        raise ConfigurationError("An explicit allowed_tables list cannot be empty.")
    result: dict[str, list[str]] = {}
    for qualified_name in names:
        if qualified_name.count(".") != 1:
            raise ConfigurationError(
                "Each allowed table must use database.table notation."
            )
        database, table = qualified_name.split(".", 1)
        if not database or not table:
            raise ConfigurationError(
                "Each allowed table must use database.table notation."
            )
        result.setdefault(database, []).append(table)
    return MappingProxyType({key: tuple(items) for key, items in result.items()})


def _parse_columns(value: object) -> Mapping[str, tuple[str, ...]]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, dict):
        raise ConfigurationError(
            "Configuration value 'allowed_columns' must be a table."
        )
    parsed: dict[str, tuple[str, ...]] = {}
    for qualified_name, columns in value.items():
        if not isinstance(qualified_name, str) or qualified_name.count(".") != 1:
            raise ConfigurationError(
                "Each column policy must use database.table notation."
            )
        database, table = qualified_name.split(".", 1)
        if not database or not table:
            raise ConfigurationError(
                "Each column policy must use database.table notation."
            )
        parsed[qualified_name] = _string_list(columns, "allowed_columns entry")
    return MappingProxyType(parsed)


def _qualified_table(value: object, field_name: str) -> tuple[str, str]:
    if not isinstance(value, str) or value != value.strip() or value.count(".") != 1:
        raise ConfigurationError(
            f"Each {field_name} entry must use database.table notation."
        )
    database, table = value.split(".", 1)
    if not database or not table:
        raise ConfigurationError(
            f"Each {field_name} entry must use database.table notation."
        )
    return database, table


def _parse_write_columns(
    value: object,
    field_name: str,
    access: AccessPolicy,
) -> Mapping[str, tuple[str, ...]]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, dict):
        raise ConfigurationError(f"Configuration value '{field_name}' must be a table.")
    parsed: dict[str, tuple[str, ...]] = {}
    for qualified_name, columns in value.items():
        database, table = _qualified_table(qualified_name, field_name)
        if not access.table_allowed(database, table):
            raise ConfigurationError(
                f"A {field_name} entry references a table outside the access policy."
            )
        parsed[qualified_name] = _string_list(columns, f"{field_name} entry")
    return MappingProxyType(parsed)


def _parse_write_tables(value: object, access: AccessPolicy) -> tuple[str, ...]:
    if value is None:
        return ()
    names = _string_list(value, "delete_tables")
    for qualified_name in names:
        database, table = _qualified_table(qualified_name, "delete_tables")
        if not access.table_allowed(database, table):
            raise ConfigurationError(
                "A delete_tables entry references a table outside the access policy."
            )
    return names


def _is_local_host(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def load_config(
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> AppConfig:
    """Load configuration, keeping secrets out of disk-backed settings and errors."""

    environment = os.environ if environ is None else environ
    config_path = Path(
        path or environment.get("MARIADB_MCP_CONFIG", "mcp.toml")
    ).expanduser()
    try:
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        raise ConfigurationError("Configuration file is missing or invalid.") from None

    database = _mapping(raw.get("database", {}), "database")
    access = _mapping(raw.get("access", {}), "access")
    limits_raw = _mapping(raw.get("limits", {}), "limits")
    writes_raw = _mapping(raw.get("writes", {}), "writes")

    host = _required_string(database, "host")
    username = _required_string(database, "username")
    password = environment.get("MARIADB_MCP_PASSWORD")
    if not isinstance(password, str) or not password:
        raise ConfigurationError(
            "Environment variable MARIADB_MCP_PASSWORD is required."
        )

    port = database.get("port", 3306)
    if type(port) is not int or not 1 <= port <= 65_535:
        raise ConfigurationError(
            "Configuration value 'port' must be an integer from 1 to 65535."
        )
    tls_verify = database.get("tls_verify", True)
    if type(tls_verify) is not bool:
        raise ConfigurationError("Configuration value 'tls_verify' must be boolean.")
    if not _is_local_host(host) and not tls_verify:
        raise ConfigurationError(
            "TLS certificate verification is required for remote databases."
        )

    default_database = _optional_string(database, "default_database")
    ca_file = _optional_string(database, "ca_file")

    allowed_databases = _string_list(
        access.get("allowed_databases", []), "allowed_databases"
    )
    if default_database is not None and default_database not in allowed_databases:
        raise ConfigurationError(
            "The default database must be included in allowed_databases."
        )

    table_allowlist_configured = "allowed_tables" in access
    allowed_tables = _parse_tables(access.get("allowed_tables"))
    allowed_columns = _parse_columns(access.get("allowed_columns"))
    if any(database_name not in allowed_databases for database_name in allowed_tables):
        raise ConfigurationError(
            "A table policy references a database outside the allowlist."
        )
    for database_name, tables in allowed_tables.items():
        for qualified_table in allowed_columns:
            column_database, column_table = qualified_table.split(".", 1)
            if (
                column_database == database_name
                and tables
                and column_table not in tables
            ):
                raise ConfigurationError(
                    "A column policy references a table outside the allowlist."
                )
    if any(key.split(".", 1)[0] not in allowed_databases for key in allowed_columns):
        raise ConfigurationError(
            "A column policy references a database outside the allowlist."
        )

    limits = QueryLimits(
        connect_timeout_seconds=_integer(
            limits_raw,
            "connect_timeout_seconds",
            5,
            maximum=_LIMIT_CEILINGS["connect_timeout_seconds"],
        ),
        query_timeout_seconds=_integer(
            limits_raw,
            "query_timeout_seconds",
            10,
            maximum=_LIMIT_CEILINGS["query_timeout_seconds"],
        ),
        default_page_size=_integer(
            limits_raw,
            "default_page_size",
            100,
            maximum=_LIMIT_CEILINGS["default_page_size"],
        ),
        max_page_size=_integer(
            limits_raw,
            "max_page_size",
            1000,
            maximum=_LIMIT_CEILINGS["max_page_size"],
        ),
        max_rows=_integer(
            limits_raw,
            "max_rows",
            1000,
            maximum=_LIMIT_CEILINGS["max_rows"],
        ),
        max_result_bytes=_integer(
            limits_raw,
            "max_result_bytes",
            2 * 1024 * 1024,
            maximum=_LIMIT_CEILINGS["max_result_bytes"],
        ),
        max_concurrent_queries=_integer(
            limits_raw,
            "max_concurrent_queries",
            4,
            maximum=_LIMIT_CEILINGS["max_concurrent_queries"],
        ),
    )
    if limits.default_page_size > limits.max_page_size:
        raise ConfigurationError("default_page_size cannot exceed max_page_size.")

    access_policy = AccessPolicy(
        allowed_databases=allowed_databases,
        allowed_tables=allowed_tables,
        table_allowlist_configured=table_allowlist_configured,
        allowed_columns=allowed_columns,
    )
    insert_columns = _parse_write_columns(
        writes_raw.get("insert_columns"), "insert_columns", access_policy
    )
    update_columns = _parse_write_columns(
        writes_raw.get("update_columns"), "update_columns", access_policy
    )
    delete_tables = _parse_write_tables(writes_raw.get("delete_tables"), access_policy)
    has_write_permissions = (
        any(insert_columns.values())
        or any(update_columns.values())
        or bool(delete_tables)
    )
    if has_write_permissions and "max_affected_rows" not in writes_raw:
        raise ConfigurationError(
            "Configuration value 'max_affected_rows' is required when writes "
            "are enabled."
        )
    max_affected_rows = (
        _integer(
            writes_raw,
            "max_affected_rows",
            1,
            maximum=10_000,
        )
        if "max_affected_rows" in writes_raw
        else None
    )
    write_policy = WritePolicy(
        insert_columns=insert_columns,
        update_columns=update_columns,
        delete_tables=delete_tables,
        max_affected_rows=max_affected_rows,
    )

    return AppConfig(
        database=DatabaseSettings(
            host=host,
            port=port,
            default_database=default_database,
            username=username,
            password=password,
            tls_verify=tls_verify,
            ca_file=ca_file,
        ),
        access=access_policy,
        limits=limits,
        writes=write_policy,
    )
