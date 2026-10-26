# Tasks: MariaDB MCP Server

**Input**: Design documents from `specs/001-mariadb-mcp-server/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/mcp-tools.md`, and `quickstart.md`

**Tests**: Included because the feature specification explicitly requires automated unit, security, MCP contract, and optional database integration tests.

**Organization**: Tasks are grouped by the four prioritized user stories. Every task has a sequential ID and exact target path. `[P]` means independent files/no dependency on an incomplete task; `[US#]` traces story-specific work to `spec.md`.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the installable Python package and baseline project automation.

- [X] T001 Define package metadata, Python `>=3.11`, exact tested runtime/dev dependency pins, CLI entry point, pytest markers, and Ruff settings in `pyproject.toml`.
- [X] T002 [P] Ignore virtual environments, Python/test/lint caches, local TOML configuration, and secret files in `.gitignore`.
- [X] T003 Configure baseline install, pytest, and Ruff checks in `.github/workflows/ci.yml`.
- [X] T004 Create the package and test directory skeleton in `src/mariadb_mcp/__init__.py`, `src/mariadb_mcp/tools/__init__.py`, `tests/unit/`, `tests/contract/`, and `tests/integration/`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Implement configuration, connection lifecycle, safe errors, and the shared STDIO server before feature tools.

**Checkpoint**: Configuration and database access fail closed, secrets are not exposed, and a native MCP process can start without contaminating STDOUT.

- [X] T005 [P] Specify TOML/environment parsing, invalid-value, default-deny allowlist, TLS, and limit-validation cases in `tests/unit/test_config.py`.
- [X] T006 [P] Specify mocked connection creation, timeout/TLS settings, cursor/connection cleanup, and failure cleanup cases in `tests/unit/test_connection.py`.
- [X] T007 [P] Specify sanitized error categories and sentinel-secret redaction cases in `tests/unit/test_errors.py`.
- [X] T008 [P] Specify MCP STDIO startup, deterministic `tools/list`, EOF shutdown, and stdout-only-protocol behavior in `tests/contract/test_server_protocol.py`.
- [X] T009 Implement typed TOML/environment configuration and validation in `src/mariadb_mcp/config.py`; preserve the data-model rules `host = non-empty string`, `port = integer, 1–65535`, `default_database = optional configured identifier`, `username = non-empty string`, `password = secret input`, `tls_mode = required for remote connections`, `ca_file = optional path`, and `connect_timeout = positive bounded duration`. Require `allowed_databases` to be a non-empty list (omitted/empty grants no access), keep `allowed_tables` optional but base-table-only, keep `allowed_columns` optional with unlisted columns denied, deny system schemas by default, intersect policy with database visibility, and reject invalid or over-maximum limits.
- [X] T010 Implement MariaDB Connector/Python connection creation and resource lifecycle in `src/mariadb_mcp/connection.py`; apply the positive bounded connect/query deadlines, require certificate verification for remote TLS, and close/discard resources on every failure path.
- [X] T011 [P] Implement sanitized internal error categories and redacted stderr logging helpers in `src/mariadb_mcp/errors.py`; never include credentials, raw DSNs, raw SQL literals, or unfiltered connector messages in client errors/logs.
- [X] T012 Implement the shared static MCP server and native STDIO module entry point in `src/mariadb_mcp/server.py` and `src/mariadb_mcp/__main__.py`; keep STDOUT exclusively for protocol messages and use shared connection/config/error services.

---

## Phase 3: User Story 1 - Discover an authorized database (Priority: P1) 🎯 MVP

**Goal**: Let an MCP client list only permitted databases/schemas/tables and inspect authorized table structure.

**Independent Test**: With a mocked or configured test database, discover MCP tools and verify the database/table listings and table columns, keys, indexes, and foreign keys are intersected with application allowlists and runtime-account visibility; verify an out-of-scope object is not disclosed.

### Tests for User Story 1

- [X] T013 [P] [US1] Define MCP contract tests for `list_databases`, `list_tables`, and `describe_table`, including structured outputs and denied-object behavior, in `tests/contract/test_metadata_tools.py`.
- [X] T014 [P] [US1] Define metadata service unit tests for columns, primary keys, indexes, foreign keys, pagination, inaccessible objects, and partial metadata in `tests/unit/test_metadata.py`.
- [X] T015 [P] [US1] Define opt-in live metadata visibility and least-privilege integration tests in `tests/integration/test_metadata_access.py`; tests must skip clearly when integration settings are absent.

### Implementation for User Story 1

- [X] T016 [P] [US1] Implement authorized database/schema/table listing and table description in `src/mariadb_mcp/tools/metadata.py`; return ordered column names/types and available nullability, ordered primary-key/index columns, and authorized foreign-key references, omit views and unauthorized objects, and set metadata completeness to `complete` or `partial` without implying completeness after metadata permission/error gaps.
- [X] T017 [US1] Register `list_databases`, `list_tables`, and `describe_table` with stable schemas and bounded pagination in `src/mariadb_mcp/server.py`.

**Checkpoint**: User Story 1 works independently using the shared configuration/connection layer and exposes no metadata outside the configured/database-granted scope.

---

## Phase 4: User Story 2 - Retrieve authorized data safely (Priority: P1)

**Goal**: Execute a narrow read-only query subset with recursive object authorization, value binding, bounded results, and filtering/sorting/pagination through SQL clauses.

**Independent Test**: Run allowed and denied requests against fake connector objects; verify the query result schema and caps without MariaDB. In opt-in integration tests, confirm the runtime account can read permitted objects but cannot modify data.

### Tests for User Story 2

- [X] T018 [P] [US2] Define `query_read_only` contract tests for input limits, bound parameters, structured result fields, truncation, and sanitized rejections in `tests/contract/test_query_tools.py`.
- [X] T019 [P] [US2] Define adversarial AST/policy tests for writes, multiple statements, comments, joins, nested queries, CTEs, UNIONs, aliases, wildcard columns, unauthorized predicates, and unknown functions in `tests/unit/test_sql_policy.py`.
- [X] T020 [P] [US2] Define query execution tests for parameter binding, row/byte caps, truncation metadata, timeouts, concurrency bounds, and cleanup in `tests/unit/test_query_service.py`.
- [X] T021 [P] [US2] Define opt-in MariaDB tests for authorized reads, rejected writes, unchanged fixture data, and query pagination in `tests/integration/test_read_only_queries.py`.

### Implementation for User Story 2

- [X] T022 [US2] Implement SQLGlot MySQL-dialect parsing, single-scope SELECT acceptance, MariaDB-aware token-based comment rejection (not regex-only), resolution/authorization of every reference in the accepted scope, and default-deny database/table/column authorization in `src/mariadb_mcp/sql_policy.py`; validate and execute the same SQL text. Reject nested SELECTs, CTEs, set operations, `USING`/`NATURAL` joins, and derived sources. Enforce `allowed_tables = optional per-database allowlist` (listed base tables only; views denied) and `allowed_columns = optional per-table allowlist` (unlisted columns denied; reject `*` unless fully expanded and authorized); deny system schemas and reject unknown AST nodes, ambiguous names, routines, and functions outside the plan's explicit allowlist.
- [X] T023 [US2] Implement query execution and results in `src/mariadb_mcp/query_service.py`; require `sql = non-empty, size-bounded string; exactly one supported SELECT`, accept `parameters = optional ordered JSON-compatible values` bound to values only, enforce a `deadline = server-controlled positive duration` that clients cannot extend, and return columns, positional JSON-safe rows aligned to columns, row count, non-negative execution time, a truncation boolean/reason when a bound prevents complete output, and `has_more` only when reliably detected.
- [X] T024 [US2] Implement `query_read_only` input validation and structured result/error mapping in `src/mariadb_mcp/tools/query.py`; enforce the contract's non-empty SQL and 16 KiB maximum, accept filtering/sorting/pagination only as SQL `WHERE`/`ORDER BY`/`LIMIT`/`OFFSET`, and never rewrite caller SQL or allow client inputs to increase server limits.
- [X] T025 [US2] Register `query_read_only` with its declared input/output schema and bounded response behavior in `src/mariadb_mcp/server.py`.

**Checkpoint**: User Story 2 can execute authorized SELECTs, rejects every tested unsafe/unauthorized form, and never returns more than configured bounds.

---

## Phase 5: User Story 3 - Analyze a query and check connectivity (Priority: P2)

**Goal**: Provide safe EXPLAIN analysis for the same authorized SELECT subset and sanitized connectivity diagnostics.

**Independent Test**: Verify authorized EXPLAIN requests return bounded plans, unsupported plans are rejected by the same authorization path as query execution, and valid/invalid connection states yield useful diagnostics without secrets.

### Tests for User Story 3

- [X] T026 [P] [US3] Define MCP contract tests for `explain_read_only` and `diagnose_connection` schemas, outputs, and safe error categories in `tests/contract/test_analysis_diagnostics.py`.
- [X] T027 [P] [US3] Define unit tests proving EXPLAIN validates the inner SELECT and rejects write plans, ANALYZE, EXPLAIN FOR CONNECTION, and unbounded plan output in `tests/unit/test_explain.py`.
- [X] T028 [P] [US3] Define diagnostics unit tests for successful, unreachable, invalid-credential, malformed-config, and secret-sentinel cases in `tests/unit/test_diagnostics.py`.
- [X] T029 [P] [US3] Define opt-in live tests for authorized EXPLAIN behavior and safe connection diagnostics in `tests/integration/test_explain_diagnostics.py`.

### Implementation for User Story 3

- [X] T030 [US3] Implement `explain_read_only` in `src/mariadb_mcp/tools/query.py` using the shared SELECT validator/authorizer; return a bounded plan object/text, non-negative `execution_time_ms`, and `truncated` boolean without executing the inner query, and reject unsupported plan forms.
- [X] T031 [P] [US3] Implement `diagnose_connection` in `src/mariadb_mcp/tools/diagnostics.py` with `status` restricted to `ok`, `unavailable`, or `misconfigured`, a safe category, and short sanitized guidance; never include passwords, DSNs, raw exception text, usernames, host names, local paths, or unauthorized database names.
- [X] T032 [US3] Register `explain_read_only` and `diagnose_connection` with stable structured schemas in `src/mariadb_mcp/server.py`.

**Checkpoint**: User Story 3 provides useful plan/connection outcomes while sharing the query security boundary and withholding sensitive connection details.

---

## Phase 6: User Story 4 - Configure and operate the server securely (Priority: P2)

**Goal**: Make native installation, least-privilege database setup, MCP client configuration, testing, and troubleshooting reproducible across supported desktop platforms.

**Independent Test**: Follow the installation guide on Windows, Linux, and macOS, launch via a local STDIO client, run offline tests without MariaDB, and verify a dedicated read-only account can read only permitted data and cannot write.

### Tests for User Story 4

- [X] T033 [P] [US4] Define an opt-in least-privilege integration test using a separate fixture setup identity and runtime read-only identity in `tests/integration/test_least_privilege.py`; verify unauthorized objects and data modifications remain inaccessible.

### Implementation for User Story 4

- [X] T034 [P] [US4] Document native Windows/Linux/macOS installation, Connector/C prerequisites, configuration keys, TLS, minimum MariaDB grants, available tools, client integration, testing, and troubleshooting in `docs/security-and-setup.md`.
- [X] T035 [P] [US4] Add the user-facing native install/run quickstart and links to security/client/test documentation in `README.md`.
- [X] T036 [P] [US4] Expand `.github/workflows/ci.yml` to validate declared Python versions on Windows, Linux, and macOS, including Connector/C installation and native package/startup smoke checks.

**Checkpoint**: An operator can follow the documented native workflow on each claimed platform; no runtime, unit-test, or development step requires Docker.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Prove the shared security promises and the complete validation path before release.

- [X] T037 [P] Add cross-tool sentinel-secret tests for stderr logs, MCP errors, diagnostics, and query failures in `tests/unit/test_secret_redaction.py`.
- [X] T038 Run the full offline pytest suite and Ruff lint/format checks, then fix any failures in `pyproject.toml`, `src/`, and `tests/`.
- [X] T039 Execute the offline quickstart checks and the Docker-backed setup, tool-discovery, query, rejection, limit, diagnostic, and optional integration scenarios; record verified commands/outcomes in `specs/001-mariadb-mcp-server/quickstart.md`.

**Execution note**: Offline tests passed, Ruff passed, and `bash scripts/test-integration-docker.sh` built the Connector/C test runner and passed the live MariaDB integration suite. The host-only integration command skips when its optional settings are absent. Native Windows/macOS validation remains tracked by T043.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No feature dependencies. `T001` precedes package/CI tasks; `T002` can run independently.
- **Foundational (Phase 2)**: Depends on Setup. Configuration, connector lifecycle, safe errors, and MCP STDIO startup block tool work.
- **User Stories (Phases 3–6)**: Depend on Foundational completion. Each phase starts with its tests; implementation follows those tests.
- **Polish (Phase 7)**: Requires all intended stories and integration points to be implemented.

### User Story Dependencies

```text
Setup → Foundation → US1 ──────────┐
                     └→ US2 core ──┴→ US2 registration → US3 → US4 → Polish
```

- **US1 (P1)**: Starts after Foundation; independently testable. It registers metadata tools in `server.py`.
- **US2 (P1)**: Core parser/query work can proceed after Foundation; its final `server.py` registration follows US1's registration to avoid conflicting edits. It does not depend on metadata query results.
- **US3 (P2)**: Depends on US2's shared validator/query service for safe EXPLAIN; diagnostics can be developed in parallel with EXPLAIN work.
- **US4 (P2)**: Documentation and platform CI can be drafted independently, but full acceptance depends on the tools and shared security behavior being available.

### Parallel Opportunities

- Setup: `T002` can run alongside `T001`; `T003` and `T004` follow project metadata creation.
- Foundation: `T005`–`T008` are separate test files and can be authored in parallel; `T011` is independent of configuration and connector implementation.
- US1: `T013`–`T015` can run in parallel; metadata implementation `T016` is separate from SQL/query implementation after its tests are specified.
- US2: `T018`–`T021` can run in parallel. `T022` must precede `T023`, then `T024` and `T025`.
- US3: `T026`–`T029` can run in parallel. `T030` and `T031` touch separate tool modules; `T032` waits for both.
- US4: `T033`–`T036` use separate files and can run in parallel once the integration contract and platform targets are stable.
- Cross-story parallelism: US1 metadata code and US2 parser/query code may proceed concurrently after Foundation, except their edits to `src/mariadb_mcp/server.py` must be serialized.

### Parallel Execution Examples

**User Story 1**

```text
Run T013: tests/contract/test_metadata_tools.py
Run T014: tests/unit/test_metadata.py
Run T015: tests/integration/test_metadata_access.py
Then T016: src/mariadb_mcp/tools/metadata.py
Then T017: src/mariadb_mcp/server.py
```

**User Story 2**

```text
Run T018: tests/contract/test_query_tools.py
Run T019: tests/unit/test_sql_policy.py
Run T020: tests/unit/test_query_service.py
Run T021: tests/integration/test_read_only_queries.py
Then T022 → T023 → T024 → T025
```

**User Story 3**

```text
Run T026: tests/contract/test_analysis_diagnostics.py
Run T027: tests/unit/test_explain.py
Run T028: tests/unit/test_diagnostics.py
Run T029: tests/integration/test_explain_diagnostics.py
Then run T030 and T031 in parallel; finish with T032
```

**User Story 4**

```text
Run T033: tests/integration/test_least_privilege.py
Run T034: docs/security-and-setup.md
Run T035: README.md
Run T036: .github/workflows/ci.yml
```

## Implementation Strategy

### MVP First (User Story 1)

1. Complete Setup and Foundation.
2. Complete User Story 1 metadata discovery and its isolated tests.
3. Stop and validate that MCP clients can discover tools and inspect only authorized metadata.
4. Continue to US2 before describing the result as the complete initial release; query execution and analysis remain required release scope.

### Incremental Delivery

1. Setup + Foundation: installable, offline-testable STDIO host with safe shared services.
2. US1: useful, permission-aware metadata discovery.
3. US2: authorized, read-only, bounded query capability.
4. US3: safe EXPLAIN and diagnostics.
5. US4 + Polish: native operation, least-privilege docs, platform evidence, and end-to-end validation.

Each story must pass its independent test criteria before being considered complete. Integration tests remain optional; unit and contract tests must work without MariaDB.

## Phase 8: Convergence

- [X] T040 CRITICAL: Add a fail-closed runtime identity/effective-grant preflight before registering metadata/query tools and before every database operation in `src/mariadb_mcp/connection.py` and `src/mariadb_mcp/server.py`; reject root/admin identities and write, administrative, file, execute, broad, role-based, or otherwise unverifiable privileges, with unit and opt-in disposable-database coverage in `tests/unit/test_connection.py` and `tests/integration/test_least_privilege.py` per Constitution II / FR-012 (contradicts).
- [X] T041 Keep a diagnostic-only STDIO server available when connection configuration is missing, malformed, or invalid; return `status: misconfigured` with sanitized details while data tools remain unavailable, with coverage in `src/mariadb_mcp/__main__.py`, `src/mariadb_mcp/server.py`, `src/mariadb_mcp/tools/diagnostics.py`, `tests/unit/test_diagnostics.py`, and `tests/contract/test_server_protocol.py` per FR-008 / US3-AC3 (partial).
- [X] T042 Return complete, meaningful MariaDB result types: use `COLUMN_TYPE` for table metadata and map Connector/Python result type codes to readable types, with tests for length/precision/unsigned column metadata and query expressions in `src/mariadb_mcp/tools/metadata.py`, `src/mariadb_mcp/query_service.py`, `tests/unit/test_metadata.py`, and `tests/unit/test_query_service.py` per FR-004 / FR-006 / US1-AC2 / US2-AC1 (partial).
- [ ] T043 Execute the declared Python/Windows/Linux/macOS native install and STDIO smoke matrix with Connector/C, plus opt-in disposable-MariaDB least-privilege/query/timeout scenarios when a test instance is available; record only verified platform combinations and outcomes in `.github/workflows/ci.yml`, `tests/integration/`, `docs/security-and-setup.md`, and `specs/001-mariadb-mcp-server/quickstart.md` per SC-006 / FR-016 / US4-AC1 (partial).

**Execution note**: CI passed native install, package import, and STDIO/offline checks on Linux, macOS, and Windows for Python 3.11–3.14. Docker-backed live checks also pass on Linux with Python 3.12 and MariaDB 11.4, including the configured statement deadline. Live database connection/read checks have not been exercised on every host OS, so T043 remains open for that matrix evidence.
