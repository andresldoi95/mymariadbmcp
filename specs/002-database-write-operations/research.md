# Research: Database Write Operations

**Date**: 2026-10-26

## Decisions

### Use structured, single-operation requests instead of accepting DML SQL

- **Decision**: Expose separate insert, update, and delete tools with structured identifiers, values, and equality filters. Build one single-table statement from canonical metadata identifiers and bind all values. Support one inserted record per call; do not expose arbitrary SQL, `INSERT ... SELECT`, upserts, multi-table DML, or multiple statements.
- **Rationale**: The current read path validates parsed structure and resolves every referenced object. Reusing raw caller-supplied DML would require a new parser/authorization surface and would be unsafe if validation were based only on textual checks. Structured requests permit explicit operation, object, column, and filter authorization.
- **Alternatives considered**: Accept arbitrary `INSERT`/`UPDATE`/`DELETE` SQL and extend the current SELECT parser; rejected because the feature does not need general SQL and ambiguous or unsupported constructs must fail closed. Multi-row inserts were deferred to keep one request atomic and easy to bound.

### Bound update/delete by locking candidate primary keys in a transaction

- **Decision**: Start an explicit transaction for each write on a request-scoped connection. For update/delete, select matching primary-key values in deterministic order with `FOR UPDATE` and a `maximum affected rows + 1` limit. Roll back and reject if the extra candidate exists; otherwise apply the operation only to the locked primary-key set and commit. Require transactional tables for all writes and a primary key for update/delete. Preserve the existing autocommit read path.
- **Rationale**: MariaDB documents that `FOR UPDATE` locks rows only inside a transaction and that rollback depends on a transactional engine. A primary-key target set prevents the later mutation from widening beyond the rows counted and locked. An unlocked `COUNT(*)` followed by a write has a race. The repository currently enables autocommit for every connection, so writes explicitly begin, commit, or roll back their transaction without changing read behavior.
- **Alternatives considered**: Rely on `UPDATE/DELETE ... LIMIT cap`; rejected as the sole guard because MariaDB's `UPDATE` count is changed rows by default rather than all matched rows, and its `LIMIT` behavior has a statement-based replication caveat. A plain pre-count followed by an unrestricted DML statement is also rejected as race-prone. Tables without transaction support or stable primary keys are denied.
- **Semantics**: The limit bounds the direct target rows selected for this operation. Trigger and foreign-key side effects remain governed by the database schema; the result count is the direct statement's count and does not claim to count cascaded changes.

### Keep opt-in and MariaDB grants operation-specific

- **Decision**: Empty/missing write policy means no write tools. Configuration separately authorizes insert columns, update columns, and delete tables, plus a required maximum affected-row count when writes are enabled. Continue enforcing the existing table/readable-column policy. Extend runtime grant validation only for explicitly authorized, narrowly scoped DML grants; reject broad scopes, roles, grant options, unknown syntax, and any privileges outside configured policy. MariaDB remains the final independent permission boundary.
- **Rationale**: The current connection preflight deliberately accepts scoped SELECT/USAGE grants and denies write privileges, roles, and ambiguous grant syntax. MariaDB supports table- and column-level grants, but INSERT/UPDATE/DELETE have distinct privileges; UPDATE/DELETE predicates can also require SELECT. Grant output is not a complete effective-privilege inventory in every account-host configuration, so the application parser must be conservative and documentation must require a dedicated account with a unique username and direct grants.
- **Observed `SHOW GRANTS` normalization**: MariaDB may combine separately issued column privileges into one row and append account authentication/TLS clauses (for example, `IDENTIFIED BY PASSWORD ... REQUIRE SSL`). The preflight parser accepts only recognized combinations when every privilege is independently within policy, and only known authentication/SSL suffixes; it rejects the whole row when any operation is unconfigured or any syntax is unknown.
- **Alternatives considered**: Permit all DML once any write is enabled; rejected because it weakens least privilege. Treat `SHOW GRANTS` as the only enforcement layer; rejected because MariaDB documents host-matched grant and role/PUBLIC/version caveats. Automatically expand role grants; deferred because the current constitution and implementation reject roles and expansion increases the authorization surface.

### Preserve timeouts, resource cleanup, and no-dependency scope

- **Decision**: Reuse configured connection/query timeouts, sanitized error mapping, request-scoped connections, and pytest/Ruff. Add no runtime dependency. Tests cover policy, transaction rollback and resource lifecycle offline, plus opt-in integration tests against disposable transactional MariaDB tables and narrow test accounts.
- **Rationale**: These patterns already exist and are constitution requirements. Connector/Python exposes transaction begin/commit/rollback and DML row counts; exact behavior must be tested against the pinned 1.1.14 connector and supported MariaDB versions.
- **Alternatives considered**: Add a new query builder or grant-parser dependency; not justified for the limited structured request grammar.

## Source notes

Primary-source findings and the distinction between documented behavior and design recommendations are recorded in [research-sources.md](research-sources.md). Key documentation:

- [MariaDB `FOR UPDATE`](https://mariadb.com/docs/server/reference/sql-statements/data-manipulation/selecting-data/for-update.md) and [transaction start](https://mariadb.com/docs/server/reference/sql-statements/transactions/start-transaction.md)
- [MariaDB `UPDATE`](https://mariadb.com/docs/server/reference/sql-statements/data-manipulation/changing-deleting-data/update.md), [DELETE](https://mariadb.com/docs/server/reference/sql-statements/data-manipulation/changing-deleting-data/delete.md), and [ROW_COUNT()](https://mariadb.com/docs/server/reference/sql-functions/secondary-functions/information-functions/row_count.md)
- [MariaDB Connector/Python transactions](https://mariadb.com/docs/connectors/mariadb-connector-python/transactions-with-mariadb-connector-python.md) and [cursor API](https://mariadb.com/docs/connectors/mariadb-connector-python/api/cursor.md)
- [MariaDB `GRANT`](https://mariadb.com/docs/server/reference/sql-statements/account-management-sql-statements/grant.md) and [`SHOW GRANTS`](https://mariadb.com/docs/server/reference/sql-statements/administrative-sql-statements/show/show-grants.md)

## Resolved unknowns

- **Write interface**: structured tool arguments, no arbitrary DML SQL.
- **Write scope**: one table and one operation per request; one inserted row per request.
- **Update/delete selection**: non-empty AND-combined equality filters; null means `IS NULL`.
- **Affected-row safety**: required operator cap, locked primary-key candidate set, transactional rollback on cap overflow.
- **Table requirements**: transactional target; update/delete require a primary key.
- **Grant model**: separate policy opt-in plus corresponding direct MariaDB grants; roles and broad grants remain unsupported.
- **Verification**: offline pytest and Ruff, plus opt-in integration tests on disposable MariaDB.
