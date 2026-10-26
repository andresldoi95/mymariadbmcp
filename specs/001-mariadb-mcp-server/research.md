# Phase 0 Research: MariaDB MCP Server

**Research snapshot**: 2026-10-25
**Inputs**: [MariaDB Connector/Python research](../../research_notes/MariaDB%20MCP%20planning/mariadb_connector.md), [MCP SDK research](../../research_notes/MariaDB%20MCP%20planning/mcp_sdk.md), [SQL security research](../../research_notes/MariaDB%20MCP%20planning/sql_security.md), [feature specification](spec.md), and [project constitution](../../.specify/memory/constitution.md).

This consolidation resolves the plan's technical-context choices where the research supports a decision. Statements labeled **Decision** are recommendations for the plan; cited documentation facts are distinguished from recommendations. Numeric performance defaults and exact metadata grants remain explicit open items because the research does not establish workload requirements or a canonical grant set for every metadata query.

## Technical baseline decisions

### Decision: Use Python 3.11+ and official MCP Python SDK v2

**Decision.** Set `requires-python = ">=3.11"`, use the official `mcp` package's v2 `MCPServer` API, and pin an exact SDK version selected and verified in CI; `mcp==2.3.0` is the research-date candidate, not an untested floating dependency. Test Python 3.11–3.14. Do not advertise Python 3.15 support until SDK support is established.

**Rationale.** The constitution mandates Python and the official SDK. The SDK repository describes Python 3.11+ while PyPI metadata permits 3.10+, and Python 3.10 reached EOL on 2026-10-01. Choosing 3.11 is the conservative overlap that excludes an EOL interpreter. SDK v2 is a breaking API transition from v1, so an exact tested dependency prevents installations from silently switching API generations. PyPI listed 2.3.0 as latest on the research date; this version should be refreshed/revalidated when the plan is implemented. ([SDK repository](https://github.com/modelcontextprotocol/python-sdk); [SDK PyPI metadata](https://pypi.org/project/mcp/); [SDK migration guide](https://py.sdk.modelcontextprotocol.io/migration/); [Python version status](https://devguide.python.org/versions/))

**Alternatives considered.** Python 3.10 is installable per PyPI metadata but is already EOL and conflicts with SDK repository guidance. SDK v1 is rejected because v2 is the current official documented API and the migration is breaking. Python 3.15 is not included because the cited SDK classifiers stop at 3.14 and explicit SDK test support was not established. Pinning `mcp==2.3.0` is the evidence-backed snapshot choice; a later exact v2 release is acceptable only after compatibility testing.

**Technical Context resolved.** Language/version = Python 3.11+; SDK = official MCP Python SDK v2, exact tested pin; platform compatibility = test 3.11–3.14 across Windows, Linux, and macOS rather than assert undocumented universal support.

### Decision: Prefer Connector/Python 1.1 GA and disclose the native dependency

**Decision.** Use an exact Connector/Python 1.1 GA release; the research-date choice is `mariadb==1.1.14`. Document and test MariaDB Connector/C 3.3.1+ on each native OS. Keep Connector/Python 2.0 evaluation separate until GA and verify the actual wheel/ABI matrix before considering a switch.

**Rationale.** The official guide identifies 1.1.14 as current stable/GA; 1.1 always uses the C extension and requires preinstalled Connector/C. Version 2.0.0rc2 offers pure-Python and bundled-wheel installation options but is still an RC in the cited official docs, which advise against production use of non-GA versions. The stable choice resolves the production-readiness uncertainty at the cost of installer complexity. ([Connector/Python guide](https://mariadb.com/docs/connectors/mariadb-connector-python/mariadb-connector-python-guide); [installation](https://mariadb.com/docs/connectors/mariadb-connector-python/install))

**Alternatives considered.** Connector/Python 2.0 pure Python or `mariadb[binary]` could reduce system dependency burden, but must not be selected as production baseline while RC and platform matrix uncertainties remain. A plain `pip install mariadb` selects stable 1.1, consistent with the decision. Connection pooling is available in 1.1 but is not adopted initially; it adds lifecycle/concurrency complexity without evidenced need.

**Compatibility caveats and risk.** Official 1.1 Python minimum statements differ: the guide lists CPython 3.9–3.14, while install prerequisites say Python 3.8. Confirm exact 1.1.14 package metadata, wheel availability, OS versions, and architecture on CI before declaring the final matrix. 2.0's docs do not enumerate all binary wheel OS/architecture/Python ABI combinations. ([Connector/Python guide requirements](https://mariadb.com/docs/connectors/mariadb-connector-python/mariadb-connector-python-guide#requirements); [C-extension prerequisites](https://mariadb.com/docs/connectors/mariadb-connector-python/install#c-extension-build-prerequisites); [2.0 installation options](https://mariadb.com/docs/connectors/mariadb-connector-python/install#installation-options))

**Technical Context resolved.** Primary dependencies = official `mcp` v2, MariaDB Connector/Python 1.1, Connector/C prerequisite, SQLGlot parser, pytest and Ruff. Native platform support requires actual per-OS packaging/connectivity checks, not only pure-Python protocol portability.

### Decision: STDIO-only local subprocess; standard MCP tool discovery

**Decision.** Run the server as a native local child process through `mcp.run()`'s default STDIO transport. Use deterministic, statically registered tools. Rely on protocol `tools/list` for MCP tool discovery; expose separate tools for permitted database/schema/table metadata. Reserve stdout for newline-delimited UTF-8 JSON-RPC, log to stderr, and exit cleanly on stdin EOF.

**Rationale.** The feature assumes local STDIO, and the MCP SDK specifies default `mcp.run()` as STDIO. STDIO requires no listening port and keeps the v1 attack surface local to the host-launched subprocess. The MCP tools specification expects deterministic tool listings; annotations such as `readOnlyHint` are explicitly not security controls. ([SDK real-host guide](https://py.sdk.modelcontextprotocol.io/get-started/real-host/); [STDIO transport specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio); [tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools))

**Alternatives considered.** Streamable HTTP/SSE and a custom `list_tools` tool are not needed for v1: HTTP expands network exposure, while MCP already provides tools/list. Dynamic tool registration based on last-used database or connection state is rejected because it complicates client caching and authorization reasoning.

**Compatibility caveat.** Host config locations and environment inheritance differ among clients. Documentation should provide verified examples per named host, absolute executable/script paths, and restart instructions; there is no universal client config format. ([SDK real-host guide](https://py.sdk.modelcontextprotocol.io/get-started/real-host/); [MCP debugging guide](https://modelcontextprotocol.io/docs/2026-07-28/tools/debugging))

**Technical Context resolved.** Target platform = native Windows/Linux/macOS; project type = local Python MCP subprocess/CLI package; transport = STDIO only in v1; no server-side web endpoint.

### Decision: No application data store; externalize secrets and configuration

**Decision.** Use environment variables or another documented protected local configuration mechanism for connection settings and credentials. Do not commit credentials, put them in tool arguments, command-line arguments, logs, or responses. No persistent application database/storage is required by v1; connection profiles and access policy are local configuration, not a new data store.

**Rationale.** The spec defines connection profile and access scope entities but requires credentials to remain outside source control and responses. MCP host configuration can pass environment values, but host secret handling is client-specific and not standardized. The application should state exact environment keys and host behavior, and avoid claiming host-level secret protection it has not verified. ([Spec](spec.md); [SDK real-host guide](https://py.sdk.modelcontextprotocol.io/get-started/real-host/); [MCP debugging guide](https://modelcontextprotocol.io/docs/2026-07-28/tools/debugging))

**Alternatives considered.** A checked-in `.env`, password in command arguments, or credentials in tool schemas/results is rejected. A platform keychain may be considered later if it fits a documented cross-platform abstraction; it is not necessary to resolve v1 requirements and would add dependencies and platform-specific behavior.

**Technical Context resolved.** Storage = N/A for application data; configuration/secrets are external local inputs and must be handled with redaction and safe diagnostics.

## Security architecture decisions

### Decision: Combine database least privilege with default-deny object policy

**Decision.** Use a dedicated non-root MariaDB principal with the minimum `SELECT` grants for configured objects, host-scoped where possible. Application policy independently restricts databases/schemas/tables/columns and denies omitted or ambiguous scope. Do not grant `FILE`, `EXECUTE`, `PROCESS`, `SUPER`, `READ_ONLY ADMIN`, `GRANT OPTION`, or global `SHOW DATABASES` unless an independently approved feature demonstrates a need. Require TLS and certificate verification for remote connections; for Connector/Python 1.1 explicitly configure it because its C extension defaults TLS and certificate verification off.

**Rationale.** MariaDB supports `SELECT` at database, table, and column levels. Privilege-filtered `SHOW TABLES` and information schema permit scoped discovery; global `SHOW DATABASES` reveals broader catalog names. `FILE` grants server file access; `EXECUTE` permits routines; administrative privileges exceed the feature. The constitution requires a dedicated non-root account and layered authorization. ([MariaDB GRANT](https://mariadb.com/docs/server/reference/sql-statements/account-management-sql-statements/grant); [SHOW TABLES](https://mariadb.com/docs/server/reference/sql-statements/administrative-sql-statements/show/show-tables); [SHOW DATABASES](https://mariadb.com/docs/server/reference/sql-statements/administrative-sql-statements/show/show-databases); [CREATE USER](https://mariadb.com/docs/server/reference/sql-statements/account-management-sql-statements/create-user); [Connector TLS parameters](https://mariadb.com/docs/connectors/mariadb-connector-python/api/connection#ssltls-parameters))

**Alternatives considered.** Global read grants or global `SHOW DATABASES` would simplify broad discovery but expose unrelated objects and violate least privilege. MariaDB `read_only` and driver `read_only=True` are supplemental behavior, not the authorization boundary. Admin credentials are not used by the runtime server.

**Metadata caveat/risk.** Research documents table and column visibility, but not a canonical minimum grant recipe for every index, key, foreign-key, view, or version-specific metadata query. Add privileges narrowly only after testing the implemented queries; report partial metadata rather than treating it as complete. ([Connector research notes](../../research_notes/MariaDB%20MCP%20planning/mariadb_connector.md))

**Technical Context resolved.** Security constraint = layered account grants plus application allowlist; secure discovery = only authorized metadata; no privilege expansion for convenience.

### Decision: Use SQLGlot MySQL AST parsing, but fail closed on unmodeled SQL

**Decision.** Use a pinned SQLGlot release with its explicit MySQL dialect as a parser component, not a security engine. Build a narrow adapter for positively recognized statement/AST forms. Maintain a MariaDB-versioned regression corpus and reject parser errors, unknown node kinds, unresolved identifiers, unsupported syntax, and incomplete/stale metadata. Pinning/version is selected and upgraded only with adversarial tests.

**Rationale.** SQLGlot's official repository documents a maintained MySQL dialect and AST traversal. It also says parsing is intentionally lenient and that it is a transpiler rather than a validator. No source establishes SQLGlot or TiDB as an exact MariaDB grammar validator or authorization engine. ([SQLGlot repository](https://github.com/tobymao/sqlglot); [SQLGlot MySQL dialect](https://sqlglot.com/sqlglot/dialects/mysql.html); [TiDB parser README](https://github.com/pingcap/tidb/blob/master/pkg/parser/README.md))

**Alternatives considered.** Keyword/regex filters and prefix checks are explicitly rejected by the constitution and cannot authorize nested/indirect references. TiDB's parser is credible for Go but conflicts with the Python constitution. Generic permissive dialect parsing is rejected in favor of explicit MySQL mode plus differential tests.

**Technical Context resolved.** Primary validation approach = AST-based structural validation and semantic object resolution; exact MariaDB compatibility remains a test obligation rather than an unsupported parser claim.

### Decision: Restrict v1 to one SELECT and safe EXPLAIN of that SELECT

**Decision.** V1 query execution accepts exactly one AST-identified `SELECT` with every relation and column authorized; query analysis accepts only an explicit supported form such as `EXPLAIN [FORMAT=JSON] <authorized SELECT>`. Use bound parameters for values; never interpolate values or accept parameter markers as identifiers. Fixed database context; no `USE`. Deny system schemas by default. Reject all unsupported/ambiguous constructs.

**Rationale.** MariaDB `SELECT` syntax itself includes cross-database references, locking clauses, `INTO OUTFILE`/`DUMPFILE`, variable assignments, and procedure clauses. `EXPLAIN` can analyze UPDATE/DELETE, while `ANALYZE` executes the query. Parameter markers bind values, not identifiers. Thus “read-only SELECT” must mean AST-validated and policy-checked, not merely a query beginning with SELECT. ([MariaDB SELECT](https://mariadb.com/docs/server/reference/sql-statements/data-manipulation/selecting-data/select); [PREPARE](https://mariadb.com/docs/server/reference/sql-statements/prepared-statements/prepare-statement); [EXPLAIN](https://mariadb.com/docs/server/reference/sql-statements/administrative-sql-statements/analyze-and-explain-statements/explain))

**Alternatives considered.** General-purpose SQL passthrough is rejected. EXPLAIN for writes, `EXPLAIN FOR CONNECTION`, `ANALYZE`, arbitrary execution-plan commands, multiple statements, and session/admin commands are out of scope. Views and stored routines/functions are excluded initially because views can run with definer privileges and functions may contain writes despite declared characteristics; adding them requires recursive dependency and routine-security analysis. ([MariaDB CREATE VIEW](https://mariadb.com/docs/server/server-usage/views/create-view); [CREATE FUNCTION](https://mariadb.com/docs/server/reference/sql-statements/data-definition/create/create-function); [stored routine privileges](https://mariadb.com/docs/server/server-usage/stored-routines/stored-functions/stored-routine-privileges))

**Compatibility caveat/risk.** SQLGlot's MySQL dialect does not promise MariaDB-specific syntax coverage. MariaDB executable comments (`/*!...*/`, `/*M!...*/`) can contain executable SQL. Reject comments using MariaDB-aware lexical handling, not a keyword blacklist or naïve comment stripping; validate and execute the same SQL text. Add tests for quote/comment edge cases, SQL modes, and parser behavior. Research does not certify a complete safe built-in function allowlist; the plan chooses a narrow initial set (`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, `COALESCE`, `NULLIF`, `ABS`, `LOWER`, `UPPER`, `ROUND`) and rejects all other functions, including stored/UDF calls, `LOAD_FILE`, locking/sleep/resource functions. ([MariaDB comment syntax](https://mariadb.com/docs/server/reference/sql-statements/comment-syntax); [SQLGlot README](https://github.com/tobymao/sqlglot))

**Authorization detail.** The research recommendation was recursive authorization across every scope and branch. The implementation plan deliberately narrows v1 further: accept one SELECT scope with base tables and resolvable joins, but reject nested SELECTs, CTEs, correlated references, set operations, and derived sources until their scope-resolution rules are implemented and tested. Within the accepted scope, authorize every source and column in projections, predicates, joins, grouping, ordering, and expressions; reject unresolved or ambiguous identifiers. Reject `USING`/`NATURAL` joins because the parser's scope column list does not expose their implicit join references. If column scope is configured, reject `*` unless it can be expanded from complete authoritative metadata and each resulting column authorized. Any future expansion to nested scopes must add recursive authorization tests before enabling those forms. ([MariaDB CTEs](https://mariadb.com/docs/server/reference/sql-statements/data-manipulation/selecting-data/common-table-expressions); [MariaDB GRANT column privileges](https://mariadb.com/docs/server/reference/sql-statements/account-management-sql-statements/grant))

### Decision: Apply explicit execution and output budgets; don't promise hard cancellation yet

**Decision.** Configure nonzero connection/query deadlines, hard row and serialized-byte limits, and request-level concurrency bounds. Use server-side statement time limit as an additional guard where supported, plus connector/socket bounds; ensure cursor/connection cleanup in `finally`/context-managed paths. Use explicit `buffered` mode. Do not grant `SUPER`/`CONNECTION ADMIN` for killing queries. Do not claim prompt cancellation until the chosen connector/server combination is tested.

**Rationale.** Connector/Python documents connection/socket/query timeout settings and buffered or streaming cursors, but connector docs do not establish identical `query_timeout` support or cancellation semantics across backends. `Connection.kill()` needs elevated privileges. MariaDB `max_statement_time` provides a server-side limit but is checked at execution checkpoints and may exceed its nominal bound. The constitution requires bounded queries and cleanup, so limits must be enforced at more than one layer and described honestly. ([Connector timeout parameters](https://mariadb.com/docs/connectors/mariadb-connector-python/api/connection#timeout-parameters); [connection kill](https://mariadb.com/docs/connectors/mariadb-connector-python/api/connection#connectionkillconnection_id-int-none); [MariaDB query limits](https://mariadb.com/docs/server/ha-and-performance/optimization-and-tuning/query-optimizations/query-limits-and-timeouts); [cursor buffering](https://mariadb.com/docs/connectors/mariadb-connector-python/api/cursor#cursorbuffered-bool))

**Alternatives considered.** Client socket timeout alone is not proof of server cancellation. Elevated kill privileges would violate the least-privilege architecture. Blindly rewriting arbitrary SQL with `LIMIT` is rejected because it can change semantics across UNIONs, ordering, and nested queries. Start with request-scoped connections; add pooling only after measurements justify it.

**Open risk.** Define row/byte/time/concurrency defaults from explicit product workload and test connector timeout behavior for 1.1.14 and supported MariaDB versions. If bounded cleanup cannot be demonstrated for an in-flight operation, close/discard the connection conservatively and keep the limitation explicit. ([Connector research notes](../../research_notes/MariaDB%20MCP%20planning/mariadb_connector.md); [SQL security research notes](../../research_notes/MariaDB%20MCP%20planning/sql_security.md))

**Technical Context resolved.** Constraints = bounded query execution and bounded serialized results; no numeric latency/memory SLO can be responsibly selected from current evidence. Query timeout is mandatory, but prompt cancellation is not an established guarantee.

### Decision: Sanitize every protocol and log boundary

**Decision.** Use typed/constrained MCP inputs and bounded structured outputs; return actionable sanitized `ToolError` messages for expected failures. Keep details in protected stderr logs only after redaction; avoid logging raw SQL literals, credentials, DSNs, or exception text that may contain secrets. Keep tool set stable and return no sensitive connection fields from diagnostics. Treat `readOnlyHint` and other annotations as advisory metadata.

**Rationale.** MCP's tool protocol requires access control, input validation, rate-limiting, and sanitized output. The SDK distinguishes tool execution errors from protocol errors and may log unexpected tracebacks; forwarded MCP error messages are exposed. STDIO reserves stdout for protocol messages, and the SDK warns that `print()` corrupts the channel. ([MCP tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools); [SDK error handling](https://py.sdk.modelcontextprotocol.io/servers/handling-errors/); [STDIO specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio); [SDK logging](https://py.sdk.modelcontextprotocol.io/handlers/logging/))

**Alternatives considered.** Raw connector errors/tracebacks to clients, raw SQL in logs, and logging to stdout are rejected. Tool annotations alone are rejected as authorization controls.

**Technical Context resolved.** Error handling and diagnostics = predictable sanitized categories; protocol/logging boundary = stdout protocol only, stderr redacted operational logging.

## Quality, scope, and project decisions

### Decision: Use pytest offline-first, optional integration tests, and Ruff

**Decision.** Use pytest for security, SQL validation, authorization, error handling, and MCP behavior tests; unit tests must not require a running MariaDB service. Keep live tests in an opt-in/environment-gated integration tier using a disposable or pre-provisioned database. Use Ruff for lint and formatting. CI should exercise supported Python/OS installation and launch matrices.

**Rationale.** The constitution explicitly requires pytest, offline unit tests, optional disposable DB integration tests, Ruff, and native documentation/testing. pytest supports skipping external-resource tests and yield-fixture cleanup; those mechanisms support the recommended opt-in integration tier without making Docker mandatory. ([constitution](../../.specify/memory/constitution.md); [pytest skip/xfail](https://docs.pytest.org/en/stable/how-to/skipping.html); [pytest fixture teardown](https://docs.pytest.org/en/stable/how-to/fixtures.html#teardown-cleanup-aka-fixture-finalization); [pytest monkeypatch](https://docs.pytest.org/en/stable/how-to/monkeypatch.html))

**Alternatives considered.** Requiring Docker or a live DB for ordinary tests is rejected. Integration fixtures should use a separate setup identity for creating test state and the runtime read-only account for the behavior under test; do not reuse production credentials. Exact database test provisioning is an implementation choice (local service, CI service, or disposable instance), not a Docker requirement.

**Technical Context resolved.** Testing = pytest offline-first plus optional live integration; quality tools = Ruff; target OS support requires measured native CI evidence.

### Decision: Keep v1 limited to discovery, read-only SELECT, and query analysis

**Decision.** Deliver only secure metadata discovery, bounded authorized read-only queries, and safe non-executing query analysis (`EXPLAIN` on a validated SELECT), plus connectivity diagnostics required by the spec. Exclude modifications, schema changes, administration, remote HTTP, arbitrary routine execution, views (unless dependency analysis is added), and broad catalog enumeration.

**Rationale.** This is the explicit feature scope and FR-018/constitution scope. It reduces the security claim to functions that can be given testable authorization and output bounds. MCP can expose more transports/tools, but neither implies database access safety. ([Spec](spec.md); [constitution](../../.specify/memory/constitution.md); [MCP tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools))

**Alternatives considered.** Admin utilities, writes, schema mutation, HTTP transport, arbitrary SQL, `ANALYZE`, and general routine/view support are deferred rather than hidden behind prompts or hints.

**Technical Context resolved.** Scale/scope = one local STDIO process exposing a small stable tool set for configured database objects, with bounded query/result budgets; performance SLO = not specified by evidence and must be set before numeric defaults are finalized.

## Technical Context resolution crosswalk

| Plan field | Resolution from research | Remaining uncertainty |
|---|---|---|
| Language/version | Python 3.11+; CI target 3.11–3.14 | SDK PyPI metadata and repository README disagree on Python 3.10; do not claim 3.15 support. |
| Primary dependencies | Official `mcp` v2 exact tested pin; MariaDB Connector/Python 1.1.14 snapshot candidate; Connector/C 3.3.1+; SQLGlot pinned; pytest; Ruff | Revalidate latest versions and package/platform matrix at implementation time; Connector/C native packaging is OS-specific. |
| Storage | N/A for application persistence; external local config/secrets | Host-specific environment/secret handling and protection must be documented per client. |
| Testing | pytest; fully offline unit tier; optional environment-gated integration tier | Exact MariaDB supported-version matrix and fixture provisioning must be selected. |
| Target platform | Native Windows, Linux, macOS; no Docker requirement; STDIO subprocess | Exact OS releases/architectures not in research; prove native installs in CI. |
| Project type | Single Python MCP server package/CLI subprocess | Package name and source tree are implementation details; retain separate config, DB, SQL policy, tools, and transport responsibilities. |
| Performance goals | Configurable connect/query/row/byte/concurrency bounds; no evidence-based p95 or memory target | Product must set numeric defaults/SLO from workload and acceptance needs. |
| Constraints | Least privilege; full-query authorization; fail-closed SQL subset; secrets external; sanitized errors; bounded results; no remote transport | Query cancellation and complete metadata-query grants require verification. |
| Scale/scope | Small static tool surface; configured objects; request-scoped connections initially | Concurrency capacity and pool need should follow measurement, not assumption. |

## Constitution check and risks

The recommended baseline conforms to the constitution's required official Python/MCP/Connector stack, native platform support, least-privilege layered authorization, bounded and cleaned-up query access, secure configuration, modular responsibility boundaries, pytest/Ruff quality, and v1 focus. Preserve the mandatory full-statement validation rule: an AST parser alone is insufficient; every referenced table and column must resolve and authorize, otherwise deny. MCP annotations are not security controls.

| Remaining risk | Why unresolved | Required plan/implementation response |
|---|---|---|
| Parser/server semantic mismatch | SQLGlot's MySQL parser is lenient and not a MariaDB-version validator; MariaDB comments/extensions and name-resolution rules differ. | Pin parser; define supported MariaDB versions; deny unknown syntax; build adversarial parser-to-server tests for comments, SQL modes, identifiers, CTEs, UNIONs, and nested scopes. |
| Metadata privileges/completeness | No single canonical grant recipe covers all metadata (indexes, constraints, foreign keys, views) across versions. | Test each implemented catalog query with least-privilege accounts; add grants narrowly; surface partial metadata and avoid broad visibility grants. |
| Query cancellation and timeout behavior | Driver `query_timeout` parity and in-flight cancellation are undocumented; MariaDB statement limit may overrun checkpoint intervals. | Test real driver/server behavior; enforce layered server and client limits; discard uncertain connections; don't claim prompt cancellation or add admin kill privileges. |
| Numeric performance budgets absent | No workload or resource SLO is specified. | Set configurable conservative defaults and acceptance bounds as an explicit plan decision, then document measured limits; do not invent latency claims. |
| Python/connector platform packaging | Published version requirements conflict and 2.0 wheel matrix is incomplete. | Test exact 1.1.14/Connector-C installation and connectivity on declared OS/Python/architecture matrix; only document proven combinations. |
| Remote TLS configuration and secrets | 1.1 C extension defaults TLS/verification off; MCP clients handle env secrets differently. | Explicitly configure TLS verification for remote DB, document CA handling and host-specific secret injection, and include secret-sentinel tests for logs/errors. |
| Views/functions and row cost | Definer views and stored functions can obscure transitive access or side effects; row limits do not necessarily bound scan cost. | Exclude views/routines/unreviewed functions in v1; use statement time and output budgets; review any later expansion separately. |
