# Data Model: MariaDB MCP Server

The server has no application database or durable query-result store. The following are request/configuration-time concepts; sensitive values must not be copied into tool results or logs.

## Entities

### Connection Profile

Represents settings for one MariaDB connection.

| Field | Type / rule | Notes |
|---|---|---|
| host | non-empty string | Local or remote hostname/address; never returned by diagnostics |
| port | integer, 1–65535 | MariaDB listener port |
| default_database | optional configured identifier | Fixed execution context; never selected by submitted SQL |
| username | non-empty string | Dedicated non-root account |
| password | secret input | Read from protected environment/host secret source; never persisted in project files or logged |
| tls_mode | required for remote connections | Certificate verification must be enabled; local transport policy is explicit |
| ca_file | optional path | Used only when a configured CA is needed; path excluded from tool responses |
| connect_timeout | positive bounded duration | Has a conservative default and operator maximum |

### Access Policy

Defines the server-side maximum object scope. Database privileges independently constrain this policy.

| Field | Type / rule | Notes |
|---|---|---|
| allowed_databases | non-empty list of identifiers | Omitted/empty policy grants no database access |
| allowed_tables | optional per-database allowlist | If configured, only listed base tables are exposed; views denied in v1 |
| allowed_columns | optional per-table allowlist | Columns not listed are denied; wildcard projection is rejected unless fully expanded and authorized |
| denied_system_schemas | list | System schemas denied by default |
| metadata_visibility | intersection | Result is the intersection of policy and object visibility for the runtime database account |

Identifiers are normalized/resolved using actual server metadata and SQL name-resolution rules, not string-prefix checks. Unknown or ambiguous names fail closed.

### Database Object Metadata

Represents only information discoverable under both the configured access policy and database grants.

| Field | Type / rule |
|---|---|
| database_name | authorized identifier |
| schema_name | MariaDB schema/database name; terms are synonymous |
| table_name | authorized base-table identifier |
| columns | ordered list of name, database type, and available nullability |
| primary_key | ordered authorized column references |
| indexes | names, uniqueness, and ordered column references available to the account |
| foreign_keys | constraint name and local/referenced columns and table when available and authorized |
| completeness | complete or partial; never imply completeness after metadata permission/error gaps |

Views, routines, system schemas, and their metadata are excluded unless a later feature adds transitive dependency authorization.

### Read Query Request

Represents one tool request for data retrieval.

| Field | Type / rule |
|---|---|
| sql | non-empty, size-bounded string; exactly one supported SELECT |
| parameters | optional ordered JSON-compatible values | Bound to value placeholders; never interpolated into SQL text |
| filter/sort/page | SQL WHERE/ORDER BY/LIMIT/OFFSET clauses | Pagination is supplied by the caller's query and does not override server caps |
| resolved_objects | derived authorized database/table/column references | Includes every nested scope and expression reference |
| deadline | server-controlled positive duration | Client cannot extend the configured maximum |

Validation states: `received → parsed → resolved_and_authorized → executing → completed`. Any parse, scope, permission, timeout, or bounds failure ends in a sanitized rejection/error; no state-changing request is executed.

### Query Result

| Field | Type / rule |
|---|---|
| columns | ordered list of result-column name and database type |
| rows | ordered arrays aligned to `columns`; values JSON-safe and bounded |
| row_count | number of returned rows |
| execution_time_ms | non-negative elapsed duration |
| truncated | boolean; true when row, byte, or time bound prevents complete output |
| truncation_reason | optional enum: `row_limit`, `byte_limit`, `timeout` |
| has_more | optional boolean when reliably detected by bounded extra fetch |

### Execution Plan

Represents bounded analysis of an authorized SELECT, not execution of the SELECT itself.

| Field | Type / rule |
|---|---|
| plan | structured plan object or bounded text summary |
| execution_time_ms | non-negative elapsed duration |
| truncated | boolean if plan output is bounded |

Only the constrained EXPLAIN form is supported. ANALYZE and EXPLAIN forms that inspect other connections or non-SELECT statements are rejected.

### Diagnostic Result

| Field | Type / rule |
|---|---|
| status | `ok`, `unavailable`, or `misconfigured` |
| category | safe category such as `connection_failed`, `authentication_failed`, or `configuration_invalid` |
| message | short sanitized guidance |
| sensitive_details | never included |

Diagnostics must not include passwords, DSNs, raw exception text, usernames, host names, local paths, or unauthorized database names.

## Relationships

- A Connection Profile is evaluated with one Access Policy and one runtime database identity.
- An Access Policy scopes Database Object Metadata; effective metadata visibility is the intersection of policy and database grants.
- A Read Query Request resolves to zero or more Database Object Metadata references; all references must be authorized before execution.
- An authorized Read Query Request produces one bounded Query Result.
- An authorized SELECT may produce one Execution Plan through the same validation and authorization path.
- A connection attempt produces a Diagnostic Result with no secret-bearing relationship data.
