# Implementation Plan: Database Write Operations

**Branch**: `002-database-write-operations` | **Date**: 2026-10-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-database-write-operations/spec.md`

## Summary

Add three structured MCP write capabilities while preserving the existing read-only default. Operators separately allowlist insert columns, update columns, and delete tables and configure a required affected-row cap. A write policy validates every structured request against configuration and live metadata; the write service compiles one parameterized, single-table operation and uses a transaction. Update/delete first lock a bounded set of matching primary keys and reject with rollback if the configured cap would be exceeded. Runtime grant preflight remains deny-by-default and permits only direct scoped grants justified by write policy. See [research decisions](research.md) and [primary-source findings](research-sources.md).

## Technical Context

**Language/Version**: Python 3.11–3.14 (existing `pyproject.toml` constraint)

**Primary Dependencies**: Existing MCP Python SDK 2.3.0, MariaDB Connector/Python 1.1.14, SQLGlot 30.24.0; no new runtime dependencies

**Storage**: External MariaDB; write targets must support transactions (InnoDB in the supported deployment); update/delete targets must expose a primary key

**Testing**: pytest 9.1.1 unit and MCP contract suites without a database; opt-in integration suite against disposable MariaDB; Ruff check and format

**Target Platform**: Native Windows, Linux, and macOS; local MCP STDIO transport

**Project Type**: Python MCP server

**Performance Goals**: Keep each connection/query within the existing configured timeout (10-second query default); candidate selection is bounded to the configured row cap plus one; no separate throughput target is specified

**Constraints**: Writes remain disabled unless operation/table/field permissions are explicitly configured. The maximum affected-row count is required when writes are enabled, has a 10,000-row hard ceiling, and cannot be overridden by a tool caller. One operation targets one table; inserts add one row. Update/delete require a non-empty AND-combined equality filter and primary key; filter and key columns must be authorized for the internal read needed to target rows. Values are parameter-bound; identifiers are resolved from live schema metadata. No raw SQL DML, role grants, broad DML grants, DDL, or administrative operations. Preserve read-only connection behavior when writes are disabled.

**Scale/Scope**: Three write tools registered only for configured operations; a single write call affects at most the configured number of existing rows or inserts one row. Existing connection and statement timeouts apply; no separate write-concurrency setting or throughput target is introduced.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle/gate | Status | Evidence and controls |
|---|---|---|
| I. Portable Official Stack | PASS | Uses the existing supported Python, official MCP SDK, and MariaDB Connector/Python stack; adds no mandatory dependency or Docker runtime requirement. |
| II. Least Privilege and Layered Authorization | PASS WITH CONTROLS | Writes stay disabled by default. Configuration and MariaDB grants are operation/object/column-scoped; structured requests are authorized from metadata; broad scopes, roles, unknown grant syntax, and ambiguous requests fail closed. |
| III. Safe and Bounded Data Access | PASS WITH CONTROLS | Reuses configured timeouts and sanitized errors; bounds update/delete candidate selection; uses transactions only on transactional tables; rolls back on rejection/failure and closes resources. |
| IV. Modular Design and Simplicity | PASS | Write request validation, execution, MCP registration, connection authorization, and configuration have separate responsibilities; no new dependency is proposed. |
| V. Verifiable Quality and Specification-Driven Development | PASS | Requirements trace to offline policy/service/contract tests, optional disposable-DB integration tests, documentation, and Ruff. Security negatives are included. |
| MCP and Platform Compatibility | PASS | Adds local structured MCP tools and advisory non-read-only/destructive annotations; preserves STDIO and native platform support. |
| Development, Testing, and Documentation | PASS | Design includes tests, least-privilege grant guidance, opt-in configuration, and updates to security/setup documentation. |

**Pre-research gate**: PASS. No constitution violation or new infrastructure dependency identified.

## Project Structure

### Documentation (this feature)

```text
specs/002-database-write-operations/
├── plan.md
├── research.md
├── research-sources.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── mcp-tools.md
└── tasks.md                 # Created by /speckit.tasks, not by this plan
```

### Source Code (repository root)

```text
src/mariadb_mcp/
├── config.py                 # Extend write policy and cap configuration
├── connection.py             # Preserve read-only preflight; validate scoped write grants
├── errors.py                 # Reuse/extend sanitized error categories if needed
├── server.py                 # Register only configured write tools after preflight
├── write_policy.py           # Validate structured requests and authorize identifiers
├── write_service.py          # Bounded transactional execution and result shaping
└── tools/
    └── write.py              # insert_record, update_records, delete_records

tests/
├── unit/
│   ├── test_write_policy.py
│   ├── test_write_service.py
│   ├── test_config.py         # Extend default/invalid-write-policy coverage
│   └── test_connection.py     # Extend grant parser/preflight coverage
├── contract/
│   └── test_write_tools.py
└── integration/
    ├── test_write_operations.py
    └── test_least_privilege.py # Verify write-grant opt-in and read-only default

docs/
└── security-and-setup.md     # Explain opt-in writes, grants, limits, and test setup
```

**Structure Decision**: Retain the existing single Python project and add cohesive write-policy, write-service, and MCP-tool modules alongside the current query, connection, and metadata modules. Tests follow the repository's existing unit/contract/integration split.

## Phase 1 Constitution Re-check

**Post-design gate**: PASS. The contracts expose only structured, single-operation changes; disabled operations are not registered; execution is bounded and transactional; grant preflight and MariaDB permissions remain independent controls. No new dependency, transport, platform limitation, or unrelated project area is introduced. Security verification is explicitly covered by the validation guide and test structure above.
