# Quickstart: Validate Database Write Operations

This guide describes validation scenarios for the implementation. Use only a disposable MariaDB database and a dedicated test account. Never run write tests against production data.

## Prerequisites

- Python and the repository's development dependencies are installed.
- A disposable MariaDB instance and test schema are available for optional integration checks.
- The test account is non-root and has only the directly scoped grants needed for the configured test operations.
- Test tables use a transactional engine; tables used for update/delete have primary keys.

## Offline validation

Run the normal unit and contract suites without a live MariaDB instance:

```sh
python -m pytest -m "not integration"
python -m ruff check src tests
python -m ruff format --check src tests
```

Expected outcomes include:

- Write tools are absent when write configuration is omitted.
- Valid structured insert/update/delete requests generate one operation and bind all values.
- Unauthorized operations, tables, fields, empty filters, invalid values, incomplete metadata, and over-cap requests are denied.
- Update/delete roll back when the locked candidate set exceeds the configured cap.
- Failed operations return sanitized errors and close their cursor/connection; no test requires a live database.
- Existing read-only tests and tool discovery behavior remain unchanged with writes disabled.

## Disposable-database validation

Configure only test objects and the operation(s) being checked. Grant only the corresponding table/column privileges to a dedicated non-admin test account. Keep the account username unique to avoid ambiguous host-matched grant entries.

An illustrative configuration (replace the table and columns with disposable test objects) is:

```toml
[access]
allowed_databases = ["appdb"]
allowed_tables = ["appdb.sample_records"]
allowed_columns = { "appdb.sample_records" = ["id", "label"] }

[writes]
max_affected_rows = 100
insert_columns = { "appdb.sample_records" = ["label"] }
update_columns = { "appdb.sample_records" = ["label"] }
delete_tables = ["appdb.sample_records"]
```

The columns used by update/delete filters and internal primary-key targeting must also be allowed for reads and covered by the database account's `SELECT` grants.

1. Start the disposable MariaDB service and create an InnoDB test table with a primary key and fixture rows.
2. Start the server using the test-only configuration and secret environment variable.
3. Connect an MCP client and verify that only configured write tools are listed.
4. Insert one valid row; verify the response reports one and the fixture contains the submitted row.
5. Update records with a non-empty equality filter; verify only the selected row(s) changed and the affected count is accurate.
6. Delete records with a non-empty equality filter; verify only selected rows are removed.
7. Attempt an empty-filter update/delete and a change that would exceed the configured cap; verify denial and that the original fixture remains unchanged.
8. Remove the corresponding database grant while leaving app policy enabled; verify MariaDB denies the operation and the MCP response is sanitized.
9. Restart without write policy; verify write tools are absent, direct write attempts are impossible through the MCP service, and read-only tools still work.

Integration tests must opt in explicitly, use disposable accounts and fixtures, and document the exact test configuration variables alongside the test harness. Do not test a denied write by issuing unsafe DML against a real database.

See [the MCP contracts](contracts/mcp-tools.md) for argument/result shapes and [the data model](data-model.md) for policy and validation rules.
