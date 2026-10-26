# Secure setup and operation

MariaDB MCP Server exposes a local MCP STDIO process for metadata discovery, bounded read-only queries, query plans, and connection diagnostics. Insert, update, and delete tools are available only when each operation is explicitly configured and backed by narrowly scoped MariaDB grants. The server does not accept raw write SQL and does not provide HTTP transport, DDL, administration, views, routines, or stored-function calls. The SQL validator deliberately supports a subset and rejects unsupported or ambiguous SQL.

## Requirements

- Python 3.11–3.14 (the supported range is set in `pyproject.toml`).
- MariaDB Connector/Python 1.1 GA and MariaDB Connector/C 3.3.1 or newer.
- A MariaDB server reachable locally or remotely.
- A dedicated, non-root MariaDB account with only the required grants. Without write configuration, it must remain read-only; write-enabled deployments require direct, narrowly scoped operation grants.
- An MCP client that launches a local process over STDIO.

Docker is not required for installation, runtime, or unit tests. Connector/Python 1.1 uses a native Connector/C library, so install Connector/C before installing the Python package.

## Install natively

Install Connector/C using the vendor instructions for your operating system:

- **Debian/Ubuntu**: install the development package and pkg-config, for example `sudo apt-get install libmariadb-dev pkg-config`.
- **Fedora/RHEL**: install the Connector/C development package, commonly `mariadb-connector-c-devel`.
- **macOS**: use the official Homebrew formula, for example `brew install mariadb-connector-c pkg-config`.
- **Windows**: download the 64-bit or 32-bit MariaDB Connector/C MSI matching Python's architecture from the [official Connector/C download page](https://mariadb.com/downloads/connectors/connectors-data-access/c-connector/). Run the MSI and ensure its library directory is available to the Python process. Do not mix 32-bit and 64-bit Python/Connector/C installations.

Then install the package and development extras:

```sh
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Windows PowerShell equivalents:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

The package pins the official MCP Python SDK, MariaDB Connector/Python, and SQLGlot. Dependency upgrades must be exact tested pins; verify the Python/OS/architecture matrix before claiming support for a new combination.

## Configure a dedicated database account

Create a separate account for the MCP process. Have a DBA substitute the deployment host, database, and secret. The runtime account must not be root or a fixture-setup account. The read-only setup remains the default:

```sql
CREATE USER 'mcp_ro'@'trusted-client-host' IDENTIFIED BY 'use-a-secret-manager-value';
GRANT SELECT ON appdb.* TO 'mcp_ro'@'trusted-client-host';
```

For remote connections, require TLS at the account/server and configure the server certificate CA. Connector/Python 1.1's C extension does not enable certificate verification by default, so the application explicitly requires verification for remote hosts. Grant table- or column-level `SELECT` instead of database-wide `SELECT` when narrower access is needed.

To enable writes, use a **separate** non-admin account with direct grants matching the configured operations. For example, if the write policy allows inserting `customer_id` and `label`, updating `label`, deleting rows, and internally reading `id`/`customer_id`/`label` on `appdb.orders`:

```sql
CREATE USER 'mcp_rw'@'trusted-client-host' IDENTIFIED BY 'use-a-secret-manager-value';
GRANT SELECT (id, customer_id, label) ON appdb.orders TO 'mcp_rw'@'trusted-client-host';
GRANT INSERT (customer_id, label) ON appdb.orders TO 'mcp_rw'@'trusted-client-host';
GRANT UPDATE (label) ON appdb.orders TO 'mcp_rw'@'trusted-client-host';
GRANT DELETE ON appdb.orders TO 'mcp_rw'@'trusted-client-host';
```

Use direct table/column grants; do not grant roles, `PUBLIC`, global/schema-wide DML, `ALL`, or `GRANT OPTION`. Keep the runtime username unique across host entries because MariaDB's grant display may not show every matching-host grant. The server's grant preflight is conservative evidence, not a replacement for MariaDB's own permission enforcement.

Do **not** grant `FILE`, `EXECUTE`, `PROCESS`, `SUPER`, `READ_ONLY ADMIN`, `CONNECTION ADMIN`, `GRANT OPTION`, or global `SHOW DATABASES` for convenience. The server's configured object allowlist is an additional boundary, not a replacement for MariaDB grants. Metadata queries may return partial results if the account cannot see indexes or relationship metadata; add only the narrowly required read grants after testing.

Before database operations, the server inspects the connected identity, active role, and grant statements. It fails closed for root/admin accounts, any active or granted role, global or out-of-allowlist grants, privileges outside configured write policy, and grant syntax it cannot safely interpret. Role-based grants are intentionally unsupported; use direct, narrowly scoped grants for the runtime account. Read-only deployments must not grant DML privileges.

## Configure the server

Create an access-restricted local `mcp.toml`; keep it out of source control. The password is supplied separately via `MARIADB_MCP_PASSWORD`.

```toml
[database]
host = "127.0.0.1"
port = 3306
default_database = "appdb"
username = "mcp_ro"
tls_verify = true
# ca_file = "/absolute/path/to/approved-ca.pem"

[access]
allowed_databases = ["appdb"]
allowed_tables = ["appdb.orders", "appdb.customers"]
allowed_columns = { "appdb.orders" = ["id", "customer_id", "label"] }

[limits]
connect_timeout_seconds = 5
query_timeout_seconds = 10
default_page_size = 100
max_page_size = 1000
max_rows = 1000
max_result_bytes = 2097152
max_concurrent_queries = 4
```

The example above is read-only because it has no `[writes]` section. To opt in to writes, configure only the operations and fields required, using an account whose direct MariaDB grants match. In the write-enabled file, set `[database].username` to that dedicated write account (for example, `mcp_rw`), and supply that account's secret through `MARIADB_MCP_PASSWORD`; do not reuse the read-only account. For example:

```toml
[writes]
max_affected_rows = 100
insert_columns = { "appdb.orders" = ["customer_id", "label"] }
update_columns = { "appdb.orders" = ["label"] }
delete_tables = ["appdb.orders"]
```

An empty or missing write section or operation list/map leaves writes disabled. A non-empty write policy requires `max_affected_rows` from 1 through 10,000; MCP callers cannot raise it. Insert accepts one row per call. Update/delete require non-empty equality filters (combined with AND; a null value means `IS NULL`) and target only transactional tables with a primary key. The primary-key and filter columns must also be allowed for internal reads under `allowed_columns` and the database account's `SELECT` grants. Tables without the required transactional behavior or primary key are rejected.

Set configuration and secret through the process environment:

```sh
export MARIADB_MCP_CONFIG="/absolute/path/to/mcp.toml"
export MARIADB_MCP_PASSWORD="<secret-from-your-secret-manager>"
```

Do not put the password in TOML, command-line arguments, SQL tool arguments, source control, logs, or MCP responses. MCP host environment-variable injection differs by client; configure its secret mechanism explicitly. An empty/missing database allowlist grants no access. A configured default database must itself be allowlisted.

Limits are validated and tool callers cannot raise them. Defaults are 5-second connect timeout, 10-second query timeout, 100-row default page, 1,000 returned rows, 2 MiB serialized query result, and four concurrent queries. Hard maxima are 60 seconds, 10,000 rows, 8 MiB, and 16 concurrent queries. These are safety starting points, not workload performance promises. Connector/server timeout cancellation behavior varies; the server closes/discards uncertain connections and does not claim that every timeout immediately stops server-side work.

## Run and connect an MCP client

Start the local STDIO process directly:

```sh
python -m mariadb_mcp
```

An idle STDIO process is normally silent. STDOUT is reserved for MCP protocol messages; operational logging goes to STDERR. A client launches the process and communicates over its stdin/stdout. Use absolute interpreter paths in host configuration and restart the host after editing its configuration.

The client-specific JSON shape differs by host. The stable launch fields are an absolute Python executable, arguments `-m mariadb_mcp`, and environment values for `MARIADB_MCP_CONFIG` and `MARIADB_MCP_PASSWORD`. Do not assume that a host interpolates secret placeholders or inherits the shell environment. Verify the exact configuration format in the selected client's documentation.

Standard MCP `tools/list` discovery exposes read tools and diagnostics; write tools are listed only when their separate operation policy is configured:

| Tool | Purpose |
|---|---|
| `list_databases` | List only allowlisted, account-visible database/schema names. |
| `list_tables` | List authorized base tables with bounded pagination. |
| `describe_table` | Return permitted columns/types, primary keys, indexes, and visible foreign keys. |
| `query_read_only` | Execute one authorized SELECT with bound values and bounded structured rows. |
| `explain_read_only` | Return a bounded plan for the same authorized SELECT subset without executing that SELECT. |
| `insert_record` | Insert one record using configured fields and bound values; present only when insert is enabled. |
| `update_records` | Update configured fields on records matching non-empty filters; present only when update is enabled. |
| `delete_records` | Delete records matching non-empty filters; present only when delete is enabled. |
| `diagnose_connection` | Report a safe connection status and category without secret connection details. |

Query filters, sorting, and pagination are expressed in SQL with `WHERE`, `ORDER BY`, `LIMIT`, and `OFFSET`; the server does not rewrite query text. A server-enforced row/byte cap still applies. Query results contain column names/types, positional rows, row count, execution time, truncation status/reason, and `has_more` when reliably detected.

## SQL safety boundary

V1 accepts a single parser-recognized SELECT and a constrained EXPLAIN wrapper around that SELECT. It binds values with positional `?` placeholders; identifiers are resolved against metadata and the configured allowlist. It checks every table and column referenced in the supported query scope, including joins, filters, ordering, grouping, and expressions. MariaDB permissions remain an independent layer.

The server rejects multi-statements, SQL comments (including executable comments), nested queries, CTEs, set operations, derived sources, `JOIN ... USING`, `NATURAL JOIN`, views, stored routines/UDFs, unknown functions, system schemas, writes/DDL/admin/session statements, variables/assignments, file access, locking clauses, and ambiguous or unresolved references. The initial built-in allowlist is `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, `COALESCE`, `NULLIF`, `ABS`, `LOWER`, `UPPER`, and `ROUND`. It rejects wildcard projections when a column allowlist is configured. MCP `readOnlyHint` annotations are advisory only; they do not enforce security.

Write tools do not relax this read-only SQL-query boundary: they accept only structured table/field/value/filter arguments, never DML text. Update/delete lock matching primary keys in a transaction and reject if the candidate set exceeds the configured cap; they do not partially apply an over-cap request. Results report direct rows changed/deleted (not trigger or foreign-key cascade side effects). If the connection is lost during commit, the outcome is reported as unknown; do not automatically retry that operation.

## Testing

Offline tests require no live MariaDB server:

```sh
python -m pytest -m "not integration"
python -m ruff check src tests
python -m ruff format --check src tests
```

Optional integration tests use a disposable/pre-provisioned database and are skipped unless explicitly enabled:

```sh
export MARIADB_MCP_INTEGRATION=1
export MARIADB_MCP_CONFIG="/absolute/path/to/test-mcp.toml"
export MARIADB_MCP_WRITE_CONFIG="/absolute/path/to/write-test-mcp.toml"
export MARIADB_MCP_PASSWORD="<test-only-secret>"
export MARIADB_MCP_TEST_WRITE_PROBE_TABLE="appdb.orders"
# Optional: a separate disposable identity with a write privilege or assigned role.
export MARIADB_MCP_TEST_PRIVILEGED_CONFIG="/absolute/path/to/unsafe-test-mcp.toml"
python -m pytest -m integration
```

Use separate disposable identities for fixture setup, read-only checks, and write-enabled tests. The write-enabled test config must use only the test account and fixture objects; the write-permission test verifies a matching direct grant succeeds and that a read-only account's missing DML grant is denied. Role/privilege preflight tests must use disposable accounts. Never point integration tests at production.

To run the full integration suite without installing Connector/C or configuring a local MariaDB server, use the optional Docker harness:

```sh
bash scripts/test-integration-docker.sh
```

It builds an isolated Python runner with Connector/C, starts a TLS-enabled MariaDB 11.4 container with disposable read-only, narrowly write-enabled, and role test accounts, runs the opt-in tests, then removes its containers, network, and test volumes. The harness uses test-only credentials and must never be repointed at real data. Docker remains unnecessary for normal development, unit tests, or native server use.

## Troubleshooting

- **Connector import/build failure**: install matching-architecture Connector/C first; on Linux/macOS verify development headers and pkg-config; on Windows verify the MSI library path is visible to the Python process.
- **Configuration is missing or invalid**: the server remains available over STDIO with only `diagnose_connection`; it reports `misconfigured` without exposing local paths or values. Check the absolute `MARIADB_MCP_CONFIG` path and required settings.
- **Data tools report an authorization failure at startup/use**: verify the connected account is non-admin, has no active/granted roles, and has only direct grants inside the configured object scope. For writes, verify each operation's table/column allowlist and matching direct DML grants; keep `SELECT` grants for filter and primary-key columns.
- **Connection diagnostic says unavailable**: verify host/port reachability, account host restrictions and grants, secret injection, TLS certificate/CA configuration, and remote certificate verification.
- **A database/table is absent from discovery**: confirm it is explicitly allowlisted and visible to the runtime account; the server intentionally does not disclose global catalog names.
- **A query is rejected**: v1 supports a conservative SQL subset. Simplify unsupported nested/CTE/set-operation syntax, remove comments/locking/session/file features, qualify ambiguous columns, and use only the documented function allowlist.
- **STDIO appears silent**: this is expected while waiting for MCP input. Do not print debug output to stdout; inspect the host's stderr/log view and verify the absolute process command and environment configuration.
- **Tests skip**: integration tests need explicit opt-in and test configuration; the ordinary offline unit suite should not require a live database.
