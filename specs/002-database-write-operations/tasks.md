---
description: "Implementation tasks for scoped MariaDB write operations"
---

# Tasks: Database Write Operations

**Input**: Design documents from `specs/002-database-write-operations/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/mcp-tools.md`, and `quickstart.md`

**Tests**: Included because FR-013 in `spec.md` requires automated coverage. Tests are listed before implementation tasks within each user-story phase.

**Organization**: Tasks are grouped by the four P1 user stories to support independently testable increments.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare disposable integration fixtures without adding runtime dependencies.

- [x] T001 Add an InnoDB `sample_records` write fixture, a unique non-admin account with scoped grants, and its write-policy config/environment in `docker/integration/init.sql`, `docker/integration/write.toml`, and `docker-compose.integration.yml`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add fail-closed write configuration, authorization, metadata validation, and transaction primitives required by every write story.

**⚠️ CRITICAL**: Complete this phase before implementing any write tool.

- [x] T002 [P] Add config tests in `tests/unit/test_config.py` proving missing/empty write permissions disable writes, a non-empty write policy requires `max_affected_rows`, and the cap is a positive integer no greater than 10,000.
- [x] T003 Parse the `writes.insert_columns`, `writes.update_columns`, `writes.delete_tables`, and `writes.max_affected_rows` settings in `src/mariadb_mcp/config.py`; preserve the exact data-model rules: “Missing permission lists/maps default to empty,” “A non-empty permission setting without `max_affected_rows` makes configuration invalid,” “Positive integer,” and “maximum 10,000.”
- [x] T004 [P] Add `SHOW GRANTS` policy tests in `tests/unit/test_connection.py` for exact table/column DML grants, recognized MariaDB-combined privileges, and denial of global/schema DML, roles, PUBLIC, grant options, unknown syntax, and grants outside configured policy.
- [x] T005 Extend runtime identity and grant validation in `src/mariadb_mcp/connection.py` to allow only directly scoped privileges supported by configured write policy; preserve read-only behavior and reject active/inherited roles, broad grants, unknown output, and unverifiable authorization.
- [x] T006 [P] Add write target and request validation tests in `tests/unit/test_write_policy.py` for allowlisted base tables, transactional-engine metadata, actual columns, primary keys, permitted fields, non-empty filters, scalar values, and fail-closed incomplete metadata.
- [x] T007 Implement `WriteTargetSchema` resolution and structured-request authorization in `src/mariadb_mcp/write_policy.py`; enforce “Missing or incomplete metadata denies the write,” “A primary key is required for bounded update/delete targeting; inserts do not require a primary key,” and “predicate and primary-key columns are authorized for the internal read needed to target rows.”
- [x] T008 [P] Add transaction lifecycle tests in `tests/unit/test_write_service.py` for explicit begin/commit, rollback on validation/database errors, cursor/connection cleanup, and an unknown outcome when commit connectivity is lost.
- [x] T009 Implement shared transaction and sanitized-result handling in `src/mariadb_mcp/write_service.py`; explicitly begin/commit/rollback writes while preserving the existing read connection behavior; support the result status “Completed success, rejected/failed, or unknown when a connection is lost at commit and the outcome cannot be established”; enforce “The result never contains affected row contents, submitted values, SQL text, credentials, or raw connector errors.”

**Checkpoint**: Shared policy, live-schema validation, grant checks, and transaction handling are ready for independent write operations.

---

## Phase 3: User Story 1 - Insert Authorized Records (Priority: P1) 🎯 MVP

**Goal**: Allow one configured insert operation to add one permitted record and report its outcome.

**Independent Test**: With insert enabled for a disposable table, insert a valid record and verify its contents/result; with insert disabled or a field/table unauthorized, verify rejection and unchanged data.

### Tests for User Story 1

> Write these tests first and confirm they fail before implementing insert behavior.

- [x] T010 [P] [US1] Add offline insert service tests in `tests/unit/test_insert.py` for “Scalar: JSON string, number, boolean, or null. Nested arrays/objects are not accepted as values,” one valid row, unapproved table/field, database constraint failure, sanitized errors, and rollback.
- [x] T011 [P] [US1] Add MCP contract tests in `tests/contract/test_insert_tool.py` for structured `database`/`table`/`values` arguments, the `{operation, status, affected_rows}` result, insert-only registration, and non-read-only/destructive annotations.
- [x] T012 [P] [US1] Add an opt-in disposable-database insert scenario in `tests/integration/test_write_operations.py` verifying one row is committed and a constraint failure leaves no partial row.

### Implementation for User Story 1

- [x] T013 [P] [US1] Implement `WriteService.insert` in `src/mariadb_mcp/write_service.py`; enforce “Values: a non-empty mapping from permitted column names to JSON scalar values; exactly one record per request,” bind values, and return one affected row on success.
- [x] T014 [P] [US1] Register `insert_record` in `src/mariadb_mcp/tools/write.py` and wire it through `src/mariadb_mcp/server.py` only when insert permissions are configured; map safe failures through the existing MCP error handler.

**Checkpoint**: The insert journey works independently while update/delete tools remain unavailable unless separately implemented and configured.

---

## Phase 4: User Story 2 - Update Authorized Records (Priority: P1)

**Goal**: Update only authorized fields on a bounded set of records identified by explicit filters.

**Independent Test**: Update matching fixture records and verify only selected rows change; verify no-filter, unauthorized, and over-cap requests make no changes, while a valid no-match returns zero.

### Tests for User Story 2

> Write these tests first and confirm they fail before implementing update behavior.

- [x] T015 [P] [US2] Add offline update service tests in `tests/unit/test_update.py` for “Filters: a non-empty mapping of readable columns to scalar equality conditions; all conditions are combined with AND, and null values mean `IS NULL`,” “Values: a non-empty mapping of authorized update columns to JSON scalar values,” writable-field restrictions, candidate cap boundaries, composite primary keys, same-value updates, no matches, and rollback.
- [x] T016 [P] [US2] Add MCP contract tests in `tests/contract/test_update_tool.py` for required non-empty `filters`, replacement `values`, update-only registration, bounded affected counts, and safe errors.
- [x] T017 [P] [US2] Extend the disposable-database scenarios in `tests/integration/test_write_operations.py` for a successful filtered update, zero matches, and cap-plus-one rejection with the fixture unchanged.

### Implementation for User Story 2

- [x] T018 [P] [US2] Implement bounded update selection and execution in `src/mariadb_mcp/write_service.py`: lock matching primary keys in deterministic order with `FOR UPDATE` up to `max_affected_rows + 1`, roll back/reject over-cap candidates, then update only the locked keys and commit.
- [x] T019 [P] [US2] Register `update_records` in `src/mariadb_mcp/tools/write.py` and `src/mariadb_mcp/server.py` only when update permissions are configured; enforce filter and writable-column policy and report changed-row counts.

**Checkpoint**: Insert and update operate independently; update cannot modify more than the configured candidate cap.

---

## Phase 5: User Story 3 - Delete Authorized Records (Priority: P1)

**Goal**: Delete only authorized records identified by explicit filters and report the direct affected-row count.

**Independent Test**: Delete filtered fixture records and verify only those records are removed; verify empty filters, unauthorized targets, and over-cap requests leave data unchanged.

### Tests for User Story 3

> Write these tests first and confirm they fail before implementing delete behavior.

- [x] T020 [P] [US3] Add offline delete service tests in `tests/unit/test_delete.py` for “Filters: a non-empty mapping of readable columns to scalar equality conditions; all conditions are combined with AND, and null values mean `IS NULL`,” no-match results, transactional rollback, and cap boundaries.
- [x] T021 [P] [US3] Add MCP contract tests in `tests/contract/test_delete_tool.py` for required filters, delete-only registration, direct affected-row counts, and sanitized failures.
- [x] T022 [P] [US3] Extend disposable-database scenarios in `tests/integration/test_write_operations.py` for a successful filtered delete, no matches, and cap-plus-one rejection without data changes.

### Implementation for User Story 3

- [x] T023 [P] [US3] Implement bounded delete selection and execution in `src/mariadb_mcp/write_service.py`: lock matching primary keys with `FOR UPDATE`, reject/rollback when candidate count exceeds the configured cap, then delete only the locked keys and commit.
- [x] T024 [P] [US3] Register `delete_records` in `src/mariadb_mcp/tools/write.py` and `src/mariadb_mcp/server.py` only when delete permissions are configured; reject empty filters and return the direct deleted-row count.

**Checkpoint**: Insert, update, and delete are independently testable and each remains separately opt-in.

---

## Phase 6: User Story 4 - Enable and Constrain Write Access (Priority: P1)

**Goal**: Prove operators can configure only the required operations and objects, while the database account independently restricts writes.

**Independent Test**: Configure one operation on one table, verify only that tool is available and succeeds with matching grants, then verify an ungranted operation and a no-write configuration are denied without changing data.

### Tests for User Story 4

> Write these tests first and confirm they fail before finalizing the authorization and setup behavior.

- [x] T025 [P] [US4] Add policy tests in `tests/unit/test_write_authorization.py` proving insert/update/delete allowlists do not enable one another and a write operation absent from policy is denied even if another operation is enabled.
- [x] T026 [P] [US4] Add MCP registration tests in `tests/contract/test_write_registration.py` proving an unconfigured server exposes no write tools, a one-operation policy exposes only its tool, and existing read-only tools remain available.
- [x] T027 [P] [US4] Add an opt-in MariaDB privilege test in `tests/integration/test_write_permissions.py` proving matching direct grants allow a configured write and a read-only account's missing DML grant denies the write without leaking database details or changing data.

### Implementation for User Story 4

- [x] T028 [US4] Document write opt-in, the `writes.*` settings, operation-specific least-privilege GRANT examples, unique-account/role restrictions, InnoDB and primary-key requirements, affected-row limits, tool arguments, disabling writes, and disposable testing in `docs/security-and-setup.md`.

**Checkpoint**: Operators can enable only the intended write surface and verify the application policy and MariaDB grants remain independent controls.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Align top-level project guidance and run the complete available verification.

- [x] T029 Update the project summary, read-only-default wording, and link to write configuration guidance in `README.md`.
- [x] T030 [P] Run the offline unit/contract suite with `python -m pytest -m "not integration"` for `tests/` and resolve failures.
- [x] T031 [P] Run `python -m ruff check src tests` and `python -m ruff format --check src tests` for `src/` and `tests/`; resolve all reported issues.
- [x] T032 Run the disposable-database validation in `specs/002-database-write-operations/quickstart.md` using `tests/integration/` and `docker-compose.integration.yml`; confirm integration tests remain explicitly opt-in and never target production.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 prepares the disposable database fixture; no runtime project changes depend on it, but integration tests do.
- **Foundational (Phase 2)**: T002/T004/T006/T008 tests can be authored in parallel. T003 follows T002, T005 follows T003 and T004, T007 follows T003 and T006, and T009 follows T007 and T008. All foundational tasks block user-story implementation.
- **User Stories (Phases 3–6)**: Each story depends on the foundation. The operation stories proceed in spec order because they extend the same `write_service.py`, `tools/write.py`, `server.py`, and integration test module. Within each story, its independent tests can be authored in parallel before implementation.
- **Polish (Phase 7)**: T029 follows documentation implementation in T028. T030 and T031 can run in parallel after all stories; T032 requires the disposable fixture and completed write flows.

### User Story Dependencies

- **US1 Insert (P1)**: Starts after Phase 2; no dependency on update or delete. It is the MVP write operation.
- **US2 Update (P1)**: Starts after Phase 2 and US1 because service/tool files are extended incrementally; no semantic dependency on insert behavior.
- **US3 Delete (P1)**: Starts after Phase 2 and US2 because the same service/tool files are extended; no semantic dependency on update behavior.
- **US4 Enable and constrain access (P1)**: Shared policy primitives are foundational; end-to-end registration, grant, documentation, and regression validation follows all three tool increments.

### Parallel Opportunities

- Foundation tests T002, T004, T006, and T008 touch separate files and can be authored in parallel.
- Within US1, tests T010–T012 can proceed in parallel; after they are written, service work T013 and MCP wiring T014 touch separate modules and can proceed in parallel.
- Within US2, tests T015–T017 can proceed in parallel; service work T018 and MCP wiring T019 can proceed in parallel after tests.
- Within US3, tests T020–T022 can proceed in parallel; service work T023 and MCP wiring T024 can proceed in parallel after tests.
- US4 tests T025–T027 touch separate files and can proceed in parallel. The offline test suite and Ruff checks (T030–T031) can also run in parallel.
- The operation phases themselves should remain sequential because their implementation tasks touch shared service, registration, and integration-test files.

## Parallel Example: User Story 1

```text
Run T010, T011, and T012 in parallel (unit, contract, and opt-in integration tests use separate files).
After those tests are written, run T013 and T014 in parallel (service and MCP wiring use separate modules).
```

## Parallel Example: User Story 2

```text
Run T015, T016, and T017 in parallel (unit, contract, and integration tests).
After those tests are written, run T018 and T019 in parallel (service and MCP wiring).
```

## Parallel Example: User Story 3

```text
Run T020, T021, and T022 in parallel (unit, contract, and integration tests).
After those tests are written, run T023 and T024 in parallel (service and MCP wiring).
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 and Phase 2 so insert is protected by the same fail-closed configuration, grant, metadata, transaction, and error controls as later operations.
2. Complete Phase 3 and verify insert unit, MCP contract, and optional disposable-database scenarios independently.
3. Stop and validate the insert-only configuration; update/delete must remain unavailable unless separately enabled and implemented.

### Incremental Delivery

1. Complete shared setup and foundation.
2. Deliver insert (US1), verify independently, then update (US2), then delete (US3).
3. Verify the complete least-privilege setup journey and documentation (US4).
4. Run offline tests and Ruff; run disposable-database validation only with its explicit opt-in and test account.

### Notes

- Every task is listed as an unchecked checkbox with a sequential ID; story-phase tasks carry the matching `[US#]` label.
- `[P]` is used only where tasks touch different files and have no dependency on unfinished work.
- Test tasks precede their corresponding implementation tasks, per the task template's red-before-green guidance.
