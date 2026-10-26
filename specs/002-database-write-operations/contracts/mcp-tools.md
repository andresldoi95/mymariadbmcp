# MCP Tool Contracts: Database Write Operations

All write tools use structured arguments. They do not accept SQL text. Database and table names, field names, and values are validated against configured policy and live table metadata. The caller cannot override the configured affected-row cap.

## Shared data types

- `Scalar`: JSON string, number, boolean, or null. Nested arrays/objects are not accepted as values.
- `Values`: non-empty object mapping column names to scalar values.
- `Filters`: non-empty object mapping column names to scalar values. Filters are combined using AND; null denotes `IS NULL`. No condition means the request is invalid.
- Identifiers are resolved to canonical metadata names and safely quoted by the server. Values are parameter-bound.

## `insert_record`

Registered only when insert permissions are configured.

**Arguments**

| Name | Type | Required | Meaning |
|---|---|---:|---|
| `database` | string | yes | Configured, authorized database. |
| `table` | string | yes | Authorized base table in that database. |
| `values` | Values | yes | One record's permitted insert fields and values. |

**Success result**: `{ "operation": "insert", "status": "success", "affected_rows": 1 }`.

## `update_records`

Registered only when update permissions are configured.

**Arguments**

| Name | Type | Required | Meaning |
|---|---|---:|---|
| `database` | string | yes | Configured, authorized database. |
| `table` | string | yes | Authorized transactional base table with a primary key. |
| `values` | Values | yes | Permitted fields and replacement values. |
| `filters` | Filters | yes | Non-empty, AND-combined conditions identifying rows to update. |

**Success result**: `{ "operation": "update", "status": "success", "affected_rows": 0 }` (count reflects records changed; a valid no-match condition returns zero).

## `delete_records`

Registered only when delete permissions are configured.

**Arguments**

| Name | Type | Required | Meaning |
|---|---|---:|---|
| `database` | string | yes | Configured, authorized database. |
| `table` | string | yes | Authorized transactional base table with a primary key. |
| `filters` | Filters | yes | Non-empty, AND-combined conditions identifying rows to delete. |

**Success result**: `{ "operation": "delete", "status": "success", "affected_rows": 0 }` (a valid no-match condition returns zero).

## Authorization and safety behavior

- Each tool requires its separate operation-specific opt-in, object/field policy, and matching MariaDB grants. Configuration without write opt-in does not register write tools.
- Insert/update fields must be permitted for that operation. Update/delete filter fields must also be readable under the existing access policy.
- All writes reject targets without transactional behavior. Update/delete additionally reject empty filters, tables without a stable primary key, primary-key/filter columns that are not authorized for the internal read needed to target rows, unsupported values, unknown/restricted columns, and requests exceeding the configured cap. No subset is committed when the cap is exceeded.
- Every write MCP tool is annotated as non-read-only and destructive. An annotation is a client hint, not an authorization control.
- Errors use the existing sanitized tool-error contract. Raw SQL, values, grant statements, and connector exception text are not returned. Commit outcome may be `unknown` if connectivity is lost after the commit request.
