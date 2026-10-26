# Quickstart Validation: MariaDB MCP Server

This guide defines the planned end-to-end checks for the implementation. Commands assume the package entry point and development extras described in the plan have been implemented. Local validation uses no Docker. Do not use a production database or credentials for these checks.

## Prerequisites

- Python 3.11 or newer within the project's declared/tested version range.
- MariaDB Connector/C 3.3.1+ installed for the selected Connector/Python 1.1 GA line, using the platform-specific installation instructions.
- For integration checks only: a disposable or pre-provisioned MariaDB database reachable from the machine.
- A dedicated non-root account with only the documented required `SELECT` grants. Use a distinct setup identity for creating test fixtures; never grant fixture setup privileges to the server account.
- An MCP client that supports local STDIO subprocesses for host smoke testing.

## Configure a local test connection

Create a local, access-restricted `mcp.toml` (do not commit secrets):

```toml
[database]
host = "127.0.0.1"
port = 3306
default_database = "mcp_test"
username = "mcp_ro"
tls_verify = true

[access]
allowed_databases = ["mcp_test"]
allowed_tables = ["mcp_test.sample_records"]
# Optional per-table column restrictions:
# allowed_columns = { "mcp_test.sample_records" = ["id", "label"] }

[limits]
connect_timeout_seconds = 5
query_timeout_seconds = 10
default_page_size = 100
max_rows = 1000
max_result_bytes = 2097152
max_concurrent_queries = 4
```

Provide the secret through the process environment, not the TOML file:

```sh
export MARIADB_MCP_CONFIG="/absolute/path/to/mcp.toml"
export MARIADB_MCP_PASSWORD="<test-only-secret>"
```

On Windows PowerShell, use `$env:MARIADB_MCP_CONFIG = 'C:\absolute\path\mcp.toml'` and set the password from a protected local secret source. Do not paste real secrets into shell history or client configuration. Remote database connections must use TLS with certificate verification; configure the approved CA path when required.

The first implementation must document the definitive key names, validation ranges, and host-specific secret-injection behavior. An empty or missing allowlist must deny access.

## Install and run offline checks

From the repository root, install the editable project and development tools:

```sh
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest -m "not integration"
python -m ruff check src tests
python -m ruff format --check src tests
```

Expected outcome: all unit and MCP contract tests pass without connecting to MariaDB; Ruff reports no lint or formatting issues. Offline tests must cover allowed/denied ASTs, nested authorization, configured bounds, sanitized errors, diagnostics, and MCP tool schemas/results.

## Verify local STDIO startup and client discovery

Start the native module directly for a smoke check:

```sh
python -m mariadb_mcp
```

An idle server may appear silent because stdout is reserved for MCP protocol messages. It must not print banners or debug output to stdout and must exit when the client closes stdin. Operational logs, if any, go to stderr and must be redacted.

Configure the client's local MCP server using its documented STDIO format. The generic launch fields are an absolute Python executable path, arguments `-m mariadb_mcp`, and the config/password environment entries. Client configuration formats differ; do not assume a generic environment interpolation syntax. Restart the client after configuration changes.

Expected host smoke checks:

1. Standard MCP tool discovery lists the stable tools defined in [contracts/mcp-tools.md](contracts/mcp-tools.md).
2. `list_databases` returns only allowlisted, account-visible names; `list_tables` and `describe_table` reveal only permitted metadata.
3. `diagnose_connection` reports success or a sanitized category without host, username, database name, or secret values.

When the configuration file is missing or invalid, the process remains available over STDIO with only `diagnose_connection` registered. It reports `status: misconfigured`; metadata and query tools are not registered.

## Validate read-only query and analysis

Using a disposable fixture table such as `mcp_test.sample_records(id, label)`:

1. Run a parameterized SELECT with an allowed projection, filter, explicit stable ordering, and a small `LIMIT`/`OFFSET`. Confirm column metadata, positional rows, execution metadata, and `truncated: false`.
2. Run a query exceeding the configured row or serialized-byte cap. Confirm the response stays within the cap and indicates truncation accurately.
3. Request an execution plan for the same supported SELECT. Confirm the plan is returned without executing the data query.
4. Submit a write, two statements, restricted table/column, unauthorized join/subquery/CTE/UNION reference, executable comment, view, locking clause, or unsupported function. Confirm the server rejects the request before returning protected data and the fixture contents remain unchanged.
5. Use an invalid credential and an unreachable test host in separate checks. Confirm safe diagnostics and no sentinel password, raw DSN, or raw connector exception in logs or client output.
6. Exercise a deliberate timeout on the disposable database. Confirm a bounded timeout outcome, resource cleanup/connection discard where state is uncertain, and no claim that the server query was interrupted unless that behavior was verified for the exact driver/server combination.

## Optional MariaDB integration checks

Only enable integration tests against a disposable/pre-provisioned instance. Store test connection values in environment variables and keep setup credentials separate from runtime read-only credentials.

```sh
export MARIADB_MCP_INTEGRATION=1
export MARIADB_MCP_CONFIG="/absolute/path/to/test-mcp.toml"
export MARIADB_MCP_PASSWORD="<test-only-secret>"
export MARIADB_MCP_TEST_WRITE_PROBE_TABLE="mcp_test.sample_records"
# Optional: a separate disposable identity with an unsafe privilege or role.
export MARIADB_MCP_TEST_PRIVILEGED_CONFIG="/absolute/path/to/unsafe-test-mcp.toml"
python -m pytest -m integration
```

Expected outcome: tests are skipped with an explicit reason when opt-in settings are absent; when enabled, tests prove least-privilege discovery/query behavior against the actual supported MariaDB version, reject the separately configured privileged/role identity before use, and verify fixture teardown. Integration tests are optional and must not make ordinary unit tests depend on Docker or any live database. The privileged-account check performs only identity/grant inspection and must use a disposable test account/database.

Alternatively, run the disposable Docker-backed database and isolated Connector/C test runner without preparing a host database:

```sh
bash scripts/test-integration-docker.sh
```

The script generates short-lived test TLS certificates and credentials, then removes its containers and volumes when the run ends. It is test-only; do not use it with production data.

## Platform release smoke matrix

Before claiming support, repeat native install, import, STDIO launch, MCP tool discovery, and a harmless authorized read against a test database on Windows, Linux, and macOS for each declared Python version/architecture. Record Connector/C installation and TLS behavior. The Connector/Python 1.1 native dependency makes this a release gate, not an assumption based solely on the MCP SDK's portability.

## Local verification record

Verified in this Linux workspace with Python 3.14.4, pytest 9.1.1, and Ruff 0.17.2:

| Command | Outcome |
|---|---|
| `.venv/bin/python -m pytest -m 'not integration'` | 90 passed; includes MCP schemas/discovery, STDIO EOF and misconfiguration behavior, query authorization/result bounds, diagnostics, secret redaction, runtime-grant preflight, and metadata/result type checks. |
| `.venv/bin/python -m pytest -m integration` | 7 skipped with explicit reasons because host integration settings were not provided. |
| `.venv/bin/python -m ruff check src tests` | Passed. |
| `.venv/bin/python -m ruff format --check src tests` | Passed. |
| `bash scripts/test-integration-docker.sh` | 7 passed against MariaDB 11.4 from an isolated Python 3.12.15 runner with Connector/Python 1.1.14 and Connector/C installed. Covered TLS, safe/unsafe grants, tool registration, metadata, query rejection, EXPLAIN/diagnostics, and the MariaDB statement deadline (error 1969). |
| GitHub Actions CI matrix | Passed native install, package imports, STDIO/offline tests on Linux, macOS, and Windows for Python 3.11–3.14. |

The Docker harness verifies the live connector/database path in a Linux container. CI separately verifies native installation and STDIO/offline behavior across the OS/Python matrix; live database connections and authorized reads have not been exercised on every host OS.
