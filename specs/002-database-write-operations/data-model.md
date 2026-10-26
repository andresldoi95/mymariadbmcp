# Data Model: Database Write Operations

## Configuration entities

### WritePolicy

Represents the operator's explicit write authorization. It is separate from the existing read access policy.

| Field | Type | Rules |
|---|---|---|
| Insert permissions | Mapping of qualified table to permitted columns | Missing/empty means inserts are disabled for that table. |
| Update permissions | Mapping of qualified table to permitted columns | Missing/empty means updates are disabled for that table. |
| Delete permissions | Set of qualified tables | Missing/empty means deletes are disabled for that table. |
| Maximum affected rows | Positive integer | Required when any write operation is enabled; maximum 10,000. |

The planned TOML settings are `writes.insert_columns`, `writes.update_columns`, `writes.delete_tables`, and `writes.max_affected_rows`. Missing permission lists/maps default to empty. A non-empty permission setting without `max_affected_rows` makes configuration invalid.

An operation is authorized only when the operation-specific policy allows it, the existing database/table policy allows the target, and MariaDB grants the connected account the corresponding privilege. Insert/update fields must also be in the operation-specific writable-column list. Predicate columns remain subject to the existing readable-column policy.

## Request entities

### InsertRequest

- Target: one allowlisted database and base table.
- Values: a non-empty mapping from permitted column names to JSON scalar values; exactly one record per request.
- Validation: all names resolve to actual table columns and all names are authorized for insert; values are bound, not interpolated into SQL. MariaDB constraints remain authoritative for required, generated, unique, and foreign-key values.

### UpdateRequest

- Target: one allowlisted database and base table.
- Values: a non-empty mapping of authorized update columns to JSON scalar values.
- Filters: a non-empty mapping of readable columns to scalar equality conditions; all conditions are combined with AND, and null values mean `IS NULL`.
- Validation: target table supports transactions and exposes a stable primary key; predicate and primary-key columns are authorized for the internal read needed to target rows, and filter values are validated before execution. The server applies only to the selected matching row identifiers and rejects when the candidate count exceeds the configured cap.

### DeleteRequest

- Target: one allowlisted database and base table.
- Filters: same non-empty equality-filter mapping as `UpdateRequest`.
- Validation: target table supports transactions and exposes a stable primary key; predicate and primary-key columns are authorized for the internal read needed to target rows. The server rejects when matching candidates exceed the configured cap.

Raw SQL, arbitrary operators/expressions, joins, multi-table writes, multi-row inserts, upserts, and multiple operations per request are not part of the request model.

## Execution entities

### WriteTargetSchema

The metadata needed to prove that the request can be safely executed: database and table identity, base-table status, transactional engine status, actual columns, and primary-key columns. Missing or incomplete metadata denies the write. A primary key is required for bounded update/delete targeting; inserts do not require a primary key.

### WriteResult

| Field | Meaning |
|---|---|
| `operation` | `insert`, `update`, or `delete`. |
| `status` | Completed success, rejected/failed, or unknown when a connection is lost at commit and the outcome cannot be established. |
| `affected_rows` | One for a successful single-record insert; changed/deleted records for update/delete; zero for a valid condition matching no records. |

The result never contains affected row contents, submitted values, SQL text, credentials, or raw connector errors. Rejected requests and known failures use the existing sanitized MCP error mechanism.

## Relationships and lifecycle

- A `WritePolicy` authorizes request entities by operation, target, and writable fields.
- Each request resolves to one `WriteTargetSchema` before any change is executed.
- Update/delete candidates are locked within a transaction, counted up to `maximum affected rows + 1`, then either rejected with rollback or changed by their locked identifiers and committed.
- Every failure before commit rolls back and releases cursor/connection resources. A lost connection during commit is reported as an unknown outcome and is never automatically retried.
