# Feature Specification: Database Write Operations

**Feature Branch**: `[Not created]`

**Created**: 2026-10-26

**Status**: Draft

**Input**: User description: "we need to support insert, update and delete operations on this mcp as well"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Insert authorized records (Priority: P1)

A user asks an AI assistant to add a record to an approved database table. The assistant submits the requested field values, and the server reports whether the record was added without exposing unrelated data.

**Why this priority**: Creating records is one of the three requested write capabilities and enables users to add data through the existing MCP service.

**Independent Test**: With writes explicitly enabled for a test table, insert a valid record and verify its values and the operation result; repeat with writes disabled and with an unauthorized table and verify no record is added.

**Acceptance Scenarios**:

1. **Given** writes are enabled for an authorized table and valid permitted values are provided, **When** a user requests an insert, **Then** exactly the requested record is added and the result confirms the outcome.
2. **Given** writes are disabled, the table is not authorized, or a field is outside the permitted scope, **When** an insert is requested, **Then** the request is rejected and database contents remain unchanged.
3. **Given** required values are missing or values violate table constraints, **When** an insert is requested, **Then** the operation fails safely, reports a sanitized reason, and does not leave a partial record.

---

### User Story 2 - Update authorized records (Priority: P1)

A user asks an AI assistant to change values on records in an approved table. The assistant identifies the records with explicit conditions and provides the permitted field changes; the server reports how many records were changed.

**Why this priority**: Updating existing records is essential to maintaining current data and is one of the three requested write capabilities.

**Independent Test**: Enable updates for a test table, update records using a valid condition, and verify only matching rows and permitted fields change; verify missing conditions and unauthorized changes leave data unchanged.

**Acceptance Scenarios**:

1. **Given** updates are enabled for an authorized table, permitted fields and values are supplied, and at least one supported condition is provided, **When** an update is requested, **Then** only matching records are changed and the result reports the affected-record count.
2. **Given** no condition is provided, the table or field is unauthorized, or the request exceeds the configured affected-record limit, **When** an update is requested, **Then** the request is rejected without changing records.
3. **Given** values violate a table constraint or the target records cannot be updated, **When** an update is requested, **Then** the operation fails safely and reports a sanitized reason.
4. **Given** a valid update condition matches no records, **When** the update is requested, **Then** no records are changed and the result reports zero affected records.
5. **Given** the target table cannot support an atomic update or has no stable unique row identifier, **When** an update is requested, **Then** the request is rejected without changing records.

---

### User Story 3 - Delete authorized records (Priority: P1)

A user asks an AI assistant to remove records from an approved table. The assistant supplies explicit conditions identifying the records, and the server reports how many records were deleted.

**Why this priority**: Deleting records is explicitly requested and necessary for users to manage data through the MCP service, while its destructive nature requires strict safeguards.

**Independent Test**: Enable deletes for a test table, delete records selected by a valid condition, and verify only matching records are removed; verify missing conditions, unauthorized targets, and over-limit requests leave data unchanged.

**Acceptance Scenarios**:

1. **Given** deletes are enabled for an authorized table and at least one supported condition is provided, **When** a delete is requested, **Then** only matching records are removed and the result reports the affected-record count.
2. **Given** no condition is provided, the table is unauthorized, or the request exceeds the configured affected-record limit, **When** a delete is requested, **Then** the request is rejected without removing records.
3. **Given** the database refuses a deletion or the request is invalid, **When** a delete is requested, **Then** the operation fails safely and reports a sanitized reason.
4. **Given** a valid delete condition matches no records, **When** the delete is requested, **Then** no records are removed and the result reports zero affected records.
5. **Given** the target table cannot support an atomic delete or has no stable unique row identifier, **When** a delete is requested, **Then** the request is rejected without removing records.

---

### User Story 4 - Enable and constrain write access (Priority: P1)

A database owner deliberately enables only the write operations and tables needed for their use case, grants matching database permissions, and retains read-only behavior everywhere else.

**Why this priority**: Separate opt-in and least-privilege authorization are necessary to add writes without weakening the server's existing read-only defaults or database-enforced security boundary.

**Independent Test**: Configure one operation on one table, then verify it succeeds only for that scope; verify other operations, tables, fields, and configurations without write opt-in are denied.

**Acceptance Scenarios**:

1. **Given** no write permissions are explicitly configured, **When** a client attempts any insert, update, or delete, **Then** the server denies the request and makes no data changes.
2. **Given** only selected operations and objects are enabled and the database account has corresponding limited permissions, **When** a request falls within that scope, **Then** it may proceed only if both the server policy and database permissions allow it.
3. **Given** server policy or database permissions cannot be verified, **When** a write is requested, **Then** the server denies it without disclosing protected data or sensitive connection details.
4. **Given** an operator follows the write setup documentation, **When** they configure, use, and disable a permitted write operation, **Then** the documented steps let them complete each task without granting unrelated database privileges.

### Edge Cases

- An insert omits a required value, supplies an unknown or restricted field, or conflicts with a uniqueness or other table constraint; no partial record is left behind.
- An update or delete has no condition, has an invalid or unsupported condition, matches no records, or would exceed the configured affected-record limit; the server rejects unsafe requests and reports zero matches distinctly from failure where applicable.
- A condition refers to an unauthorized object or field, or attempts to bypass scope through ambiguous input; the server denies the request.
- The database connection fails, times out, or loses connectivity during a write; the response does not claim success unless the outcome is known, and errors remain sanitized.
- A write is denied by the database account even though server policy allows it; the server fails closed and does not expose internal database details.
- Two users change the same record concurrently; the server reports the result based on the database outcome and does not claim an update that did not occur.
- A write request attempts schema changes, administrative actions, multiple operations, or arbitrary statement execution; the server rejects it.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The server MUST provide distinct capabilities for inserting, updating, and deleting records through the MCP service.
- **FR-002**: Write capabilities MUST be disabled by default; operators MUST explicitly enable each operation and configure the database objects and writable fields on which it is allowed.
- **FR-003**: Before each write, the server MUST validate the requested operation, target table, fields, values, and conditions against configured access restrictions and deny requests that are unauthorized, malformed, unsupported, or ambiguous.
- **FR-004**: An insert MUST accept values only for fields authorized for writing on the selected table and MUST report whether the record was added.
- **FR-005**: An update MUST require at least one supported condition, accept changes only to authorized fields, and MUST NOT change records beyond the configured affected-record limit.
- **FR-006**: A delete MUST require at least one supported condition and MUST NOT remove records beyond the configured affected-record limit.
- **FR-007**: Operators MUST be able to configure a maximum number of records affected by an update or delete; requests that could exceed that limit MUST be rejected without partial changes.
- **FR-008**: Each operation MUST report its outcome and affected-record count without returning unrelated records or sensitive connection information.
- **FR-009**: Write authorization MUST be enforced both by server-side policy and by the database account's permissions. A denial or inability to establish either authorization MUST fail closed.
- **FR-010**: Write capabilities MUST NOT permit schema changes, administrative actions, arbitrary statement execution, or multiple operations in a single request.
- **FR-011**: Existing read-only behavior MUST remain available and unchanged when write capabilities are disabled.
- **FR-012**: Invalid inputs, authorization failures, database errors, and timeouts MUST produce predictable, sanitized responses that do not expose credentials or sensitive database information.
- **FR-013**: Automated tests MUST verify successful insert, update, and delete behavior, disabled-by-default behavior, object and field restrictions, required update/delete conditions, affected-record limits, database permission denials, and safe errors. Unit tests MUST run without a live MariaDB instance; optional integration tests MAY use a disposable database.
- **FR-014**: Documentation MUST explain how to opt in to writes, scope permissions by operation and object, grant corresponding least-privilege database permissions, use the write capabilities, understand their limits, and disable them.
- **FR-015**: The server MUST reject writes when it cannot establish atomic execution for the target table; update and delete MUST also be rejected when records cannot be identified deterministically.

### Key Entities *(include if feature involves data)*

- **Write Policy**: Operator-defined permissions for specific write operations, tables, and fields, with write access disabled unless explicitly granted.
- **Write Request**: A request to insert a record, update authorized fields on condition-matched records, or delete condition-matched records.
- **Write Result**: A safe outcome, affected-record count, and sanitized failure information for a write request.
- **Affected-Record Limit**: The maximum number of existing records an update or delete may change in one request.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In acceptance testing, authorized insert, update, and delete scenarios each complete successfully in 100% of valid cases.
- **SC-002**: In acceptance testing, 100% of write attempts made without explicit opt-in, outside configured scope, without required update/delete conditions, or above the configured affected-record limit are denied without unintended data changes.
- **SC-003**: In acceptance testing, 100% of database-permission denials and write failures produce a safe outcome that does not expose credentials or sensitive connection details.
- **SC-004**: Every completed write response lets users identify whether it succeeded and how many records it created, updated, or deleted.
- **SC-005**: With write capabilities disabled, all existing read-only scenarios continue to pass without behavior changes.

## Assumptions

- Write access is an explicit operator opt-in, configured separately for insert, update, and delete; existing installations remain read-only unless changed.
- Operators use a dedicated non-administrative database account whose grants are limited to the same operations and objects enabled in server policy.
- Each request performs one operation on one table; schema changes, administrative actions, arbitrary SQL writes, and multi-operation transactions are out of scope.
- Updates and deletes require explicit supported conditions. Operators configure an affected-record limit; requests that could exceed it are rejected rather than partially applied.
- Write targets must support atomic transactions; update and delete targets must also expose a stable unique row identifier. Unsupported tables are denied rather than written without the required safety guarantees.
- Insert, update, and delete responses report outcomes and counts, not the full contents of affected records.
- The existing connection configuration, access restrictions, query safety controls, timeout behavior, and sanitized error practices continue to apply to write requests.
- Optional integration tests may use a disposable MariaDB instance; normal unit tests do not require a live database.
