# MCP Tool Contract

This contract describes the initial stable tool surface. Standard MCP `tools/list` provides tool discovery; it is not duplicated as an application tool. All tools are local STDIO tools, have deterministic names/order, and return structured JSON content within configured response bounds. Read-only annotations are descriptive hints only, never authorization controls.

## Common rules

- Identifiers are resolved against configured scope and current database metadata. Database/schema names are synonymous in MariaDB.
- Inputs that exceed configured size/page limits or cannot be validated are rejected before database execution.
- Expected failures use sanitized tool errors with one of: `invalid_input`, `authorization_denied`, `unsupported_query`, `connection_failed`, `query_timeout`, `result_limit`, or `database_error`. Error text must not disclose secret values, raw connector errors, SQL literals, or unauthorized object names.
- Database/metadata responses include only objects visible to both the application allowlist and runtime database account.
- No tool supports DML, DDL, transaction/session control, administrative operations, stored routine execution, or arbitrary connection selection.

## `list_databases`

Lists only explicitly allowed databases/schemas that the runtime account can discover. It does not expose a global catalog.

**Input**: `{}`

**Structured output**:

```json
{
  "databases": ["appdb"],
  "partial": false
}
```

`partial` is true if a safe metadata query could not establish complete visibility; do not report inaccessible names.

## `list_tables`

Lists authorized base tables in one allowed database/schema. Results are sorted by name and paginated.

**Input**:

| Field | Type | Constraint |
|---|---|---|
| database | string | Required; must be allowlisted |
| page_size | integer | Optional; default 100; 1 through configured maximum (initially 1000) |
| offset | integer | Optional; non-negative and bounded |

**Structured output**: `database`, `tables` (array of names), `has_more`, `next_offset` (nullable), `partial`.

Views are omitted in v1. Unauthorized database requests do not reveal whether a database exists.

## `describe_table`

Returns authorized structure for one allowlisted base table.

**Input**: `{ "database": "appdb", "table": "orders" }`; both identifiers are required and must be allowlisted.

**Structured output**: `database`, `table`, `columns` (ordered objects with `name`, `type`, `nullable` when available), `primary_key` (ordered names), `indexes` (name, uniqueness, ordered column names), `foreign_keys` (name and local/referenced table and columns when visible), and `partial`.

Do not disclose restricted column names or unauthorized referenced objects. If policy or grants prevent full metadata retrieval, set `partial` and return only safe available fields.

## `query_read_only`

Executes one validated, authorized SELECT and returns a bounded result. The assistant expresses filters with `WHERE`, sort order with `ORDER BY`, and pages with `LIMIT`/`OFFSET` in the submitted SQL. The server does not rewrite arbitrary query text to add pagination; server row and byte caps remain authoritative.

**Input**:

| Field | Type | Constraint |
|---|---|---|
| sql | string | Required; non-empty; maximum 16 KiB; exactly one supported SELECT |
| parameters | array | Optional; JSON-compatible bind values corresponding to positional `?` placeholders; maximum count/size set by configuration |

No client input can raise the configured execution deadline, row cap, byte cap, or concurrency cap.

**Structured output**:

```json
{
  "columns": [{"name": "id", "type": "BIGINT"}],
  "rows": [[42]],
  "row_count": 1,
  "execution_time_ms": 3,
  "truncated": false,
  "truncation_reason": null,
  "has_more": false
}
```

Rows are positional arrays aligned with `columns`, avoiding duplicate-name ambiguity. `truncated` is true if any configured output or execution bound prevents full results. `has_more` is supplied only when reliably detected.

## `explain_read_only`

Returns a bounded execution plan for one supported SELECT without executing that SELECT. The server validates and authorizes the inner SELECT exactly as for `query_read_only`, then applies the one supported EXPLAIN form.

**Input**: Same `sql` and `parameters` fields and limits as `query_read_only`.

**Structured output**: `plan` (bounded JSON object or text summary), `execution_time_ms`, `truncated`.

Reject EXPLAIN of writes, EXPLAIN FOR CONNECTION, ANALYZE, and unsupported plan syntax.

## `diagnose_connection`

Checks whether configured connectivity is usable; it does not return credentials or connection configuration.

**Input**: `{}`

**Structured output**:

```json
{
  "status": "ok",
  "category": "connected",
  "message": "Database connection is available."
}
```

Allowed status values: `ok`, `unavailable`, `misconfigured`. Messages/categories are curated; omit host, port, username, database names, DSN, secret, local path, and raw exception detail.

If configuration cannot be loaded or the runtime grant preflight fails, STDIO remains available with only this diagnostic tool registered. Invalid/missing configuration returns `status: misconfigured`; data tools are not exposed until a valid configuration and safe runtime identity pass startup preflight.

## SQL acceptance boundary

The supported form is one parser-recognized single-scope SELECT with every relation and column resolved and authorized. Explicit `JOIN ... ON` is supported; nested SELECTs, CTEs, set operations, derived sources, `JOIN ... USING`, and `NATURAL JOIN` are rejected in v1. Parameter markers bind values only. The initial built-in function allowlist is `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, `COALESCE`, `NULLIF`, `ABS`, `LOWER`, `UPPER`, and `ROUND`; qualified function calls and other functions are rejected. Reject parse errors, multiple statements, comments/executable comments, unmodeled AST nodes, unresolved/ambiguous identifiers, system schemas, unauthorized references, `SELECT ... INTO`, file access, variables/assignments, locking clauses, stored routines/UDFs, views, and any non-SELECT operation. Any change to this subset requires adversarial contract tests and a constitution review.
