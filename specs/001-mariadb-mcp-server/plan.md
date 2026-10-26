# Implementation Plan: MariaDB MCP Server

**Branch**: `001-mariadb-mcp-server` (planning identifier; no Git branch was created) | **Date**: 2026-10-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification at `specs/001-mariadb-mcp-server/spec.md`

## Summary

Build a native Python MCP subprocess using the official MCP Python SDK and MariaDB Connector/Python. V1 uses STDIO only and exposes a small, deterministic set of metadata, read-only query, query-plan, and connection-diagnostic tools. Every request is bounded and checked against a default-deny application allowlist, while a dedicated MariaDB account provides an independent permission boundary. A pinned SQLGlot MySQL-dialect parser is a structural parsing component, not a safety proof: the server authorizes every resolved reference and rejects unrecognized or ambiguous syntax. See [research.md](research.md) for evidence, alternatives, and compatibility caveats.

## Technical Context

**Language/Version**: Python 3.11+; target Python 3.11–3.14 for initial CI validation.

**Primary Dependencies**: Official `mcp` Python SDK v2 (exact tested version pin; research-date candidate `2.3.0`); MariaDB Connector/Python 1.1 GA (research-date candidate `1.1.14`) with MariaDB Connector/C 3.3.1+; SQLGlot pinned and configured for its explicit MySQL dialect; pytest; Ruff. Revalidate versions and native support before implementation pins are finalized.

**Storage**: No application database or persistent query data. Non-secret settings and access policy use a local TOML configuration file; credentials are supplied through environment variables or a protected host secret mechanism.

**Testing**: pytest offline unit and MCP contract tests; opt-in integration tests against a disposable or pre-provisioned MariaDB service; Ruff lint and format checks; native install/startup smoke tests on supported OSes.

**Target Platform**: Native Windows, Linux, and macOS local child process over MCP STDIO; no Docker requirement and no remote HTTP transport in v1.

**Project Type**: Single Python package with a module/CLI entry point and separated configuration, database, SQL-policy, MCP-tool, and transport responsibilities.

**Performance Goals**: Every query and response is bounded by configurable execution-time, row, serialized-byte, and concurrency limits. The feature specifies no workload-derived latency or throughput SLO; do not claim one without measurement.

**Constraints**: Fail closed on parse, metadata, or authorization uncertainty; query and plan operations accept only an explicitly supported read-only SELECT form; default-deny database/schema/table/column scope; no writes, DDL, admin, stored routine, or view access in v1; bind values; redact secrets and raw SQL from logs/errors; release resources on every path; no global/admin database grants.

**Scale/Scope**: One local process per MCP client, static tool registry, configured object scope, request-scoped connections initially; no pooling or application persistence until measurements justify either.

## Constitution Check

### Pre-Phase 0 Gate

- **Portable Official Stack — PASS**: Plan uses Python, the official MCP Python SDK, MariaDB Connector/Python, and native execution on all three required desktop OSes. Connector/C is a documented native prerequisite for the selected GA connector line; Docker is not required.
- **Least Privilege and Layered Authorization — PASS**: Dedicated non-root read-only account plus application-level full-query authorization and explicit object scope; deny on uncertainty. No reliance on regex or MCP hints as security controls.
- **Safe and Bounded Data Access — PASS**: Configure nonzero timeouts and row/byte limits, bound in-flight work, close/discard resources on success and failure, and keep secrets external and redacted.
- **Modular Design and Simplicity — PASS**: Separate configuration, connector lifecycle, SQL policy, tools, and STDIO entry point. SQLGlot is justified by structural whole-query validation needs; no remote service or unrelated product capability is added.
- **Verifiable Quality and Specification-Driven Development — PASS**: pytest offline unit tests, optional live integration tests, Ruff, acceptance evidence, and documentation are in scope.
- **MCP and platform requirements — PASS**: Standard MCP tool discovery and STDIO behavior; host-specific client configuration is documented without promising a universal client format.

No pre-design constitution violations identified.

## Phase 0 and Phase 1 Design Decisions

Research decisions and citations are in [research.md](research.md). Key implementation constraints:

1. Pin an exact compatible MCP SDK v2, Connector/Python 1.1 GA release, and SQLGlot release; upgrade only with CI compatibility and adversarial regression tests. Declare and test only proven Python/OS/architecture combinations.
2. Use static, deterministically ordered MCP tools. Reserve stdout for STDIO protocol traffic; send only redacted operational logs to stderr. Keep structured results bounded and conformant to declared output schemas.
3. Use a default-deny allowlist and a narrowly scoped MariaDB account. Never use a global catalog grant merely to simplify listing. Verify each metadata query under the runtime account and report incomplete metadata safely.
4. Accept one positively identified, single-scope SELECT for data access and one constrained EXPLAIN form over that same validated SELECT. Resolve every source and column in the accepted scope, including joins and predicates. Reject nested queries, CTEs, set operations, `USING`/`NATURAL` joins, unsupported comments, locking, writes, file access, variables, views, routines, unresolved identifiers, and multi-statements rather than passing them through. Allow only explicitly reviewed, deterministic built-ins (initially `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, `COALESCE`, `NULLIF`, `ABS`, `LOWER`, `UPPER`, and `ROUND`); deny qualified functions and all other calls. Validate the exact statement that will execute.
5. Use bound parameters for values; do not bind or interpolate identifiers. Treat query-supplied WHERE/ORDER BY/LIMIT/OFFSET as filtering, sorting, and pagination; do not rewrite arbitrary SQL to inject a limit. Enforce a separate server-side hard result cap and serialized-byte cap.
6. Begin with request-scoped DB connections/cursors and explicitly select buffered or streaming behavior. Stream potentially large results row-by-row under row/byte caps; close or discard resources when a cap or timeout leaves protocol state uncertain. Configure connection/query deadlines and test their actual behavior. Do not claim a client timeout cancels server work; do not grant elevated kill privileges.
7. Use pytest without a live DB for ordinary tests; make integration tests opt-in and use a separate setup identity if they create fixture state. Require no Docker in unit-test or native-run workflows.

### Proposed Initial Safety Defaults

These are configurable starting values, not performance guarantees; validate and adjust against representative data before release:

| Setting | Initial default | Enforced behavior |
|---|---:|---|
| Connection timeout | 5 seconds | Fail with sanitized connection category |
| Query timeout | 10 seconds (hard maximum 60 seconds) | Nonzero driver/server deadline; discard connection when state is uncertain |
| Default page size | 100 rows | Applies to tool guidance and table listings; query pagination is expressed in SQL |
| Maximum returned rows | 1,000 rows (hard maximum 10,000) | Fetch at most the cap plus one row when supported to detect truncation |
| Maximum serialized result | 2 MiB (hard maximum 8 MiB) | Stop materialization before exceeding the configured response bound |
| Maximum concurrent queries | 4 per process (hard maximum 16) | Reject or queue excess requests with bounded behavior |

All values must be validated as positive and may be lowered by operators, but cannot exceed the stated built-in hard maxima; tool callers cannot raise them. A timeout is a required bound, but prompt interruption of every MariaDB operation is not guaranteed until verified against the selected connector/server pair.

## Project Structure

### Documentation (this feature)

```text
specs/001-mariadb-mcp-server/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── mcp-tools.md
└── tasks.md                 # Produced by /speckit.tasks, not this plan
```

### Source Code (repository root)

```text
pyproject.toml
src/
└── mariadb_mcp/
    ├── __init__.py
    ├── __main__.py          # Native module entry point and STDIO lifecycle
    ├── config.py            # TOML/env parsing and fail-closed policy validation
    ├── connection.py        # Connector factory and resource lifecycle
    ├── errors.py            # Safe internal categories and MCP-facing errors
    ├── sql_policy.py        # Parsing, scope resolution, and object authorization
    ├── query_service.py     # Bounded query/EXPLAIN execution and result shaping
    ├── server.py            # Stable MCP registration and transport setup
    └── tools/
        ├── metadata.py      # Database/schema/table listing and table description
        ├── query.py         # Read-only query and execution-plan tools
        └── diagnostics.py   # Sanitized connection diagnostics
tests/
├── unit/                    # No MariaDB dependency
├── contract/                # MCP schemas, tool behavior, and error contracts
└── integration/             # Explicitly enabled MariaDB verification
docs/
└── security-and-setup.md    # Installation, grants, host configuration, troubleshooting
```

**Structure Decision**: One installable Python package is sufficient for the local MCP server. Keep shared connection, validation, authorization, limits, and sanitization below the tool handlers so additional tools cannot bypass policy. Tests mirror unit, contract, and opt-in integration boundaries. No frontend, HTTP service, or second deployable project is justified.

## Constitution Check (Post-Design)

- **Portable Official Stack — PASS WITH RELEASE GATE**: Runtime is native Python and official SDK/connector. The selected Connector/Python 1.1 GA line requires Connector/C, so each OS installation and supported interpreter combination must be proven in CI and documented; do not silently switch to a release candidate to simplify packaging.
- **Least Privilege and Layered Authorization — PASS WITH SECURITY GATE**: AST parsing alone is insufficient. Release requires tests proving recursive authorization for joins, subqueries, CTEs, unions, aliases, predicates, and columns; unresolved/unsupported forms fail closed. Account grants independently deny modifications.
- **Safe and Bounded Data Access — PASS WITH VERIFICATION GATE**: Ensure limits are enforced and connections are cleaned up. Test real connector/server timeout behavior; do not claim prompt cancellation or use elevated connection-kill grants.
- **Modular Design and Simplicity — PASS**: Single package and one justified SQL parser dependency; no pool/HTTP/authentication subsystem added without evidence.
- **Verifiable Quality and Specification-Driven Development — PASS**: Offline pytest, optional integration tests, Ruff, user documentation, and release evidence are included.

**Gate result**: PASS. Open risks are explicit test/release gates rather than unresolved specification choices: MariaDB/parser semantic mismatch, complete least-privilege metadata grants, connector timeout/cancellation behavior, and exact native package matrix. No constitution exception is required.

## Complexity Tracking

No constitution violations. SQLGlot is the one additional security-relevant dependency, justified because whole-query structural validation is required and the constitution explicitly rejects regex/keyword-only validation. It remains a parser component, not an authorization oracle.
