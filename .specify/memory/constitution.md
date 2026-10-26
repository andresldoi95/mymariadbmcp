<!--
Sync Impact Report
- Version change: Unratified scaffold → 1.0.0
- Modified principles: Template placeholders → Portable Official Stack; Least Privilege and Layered Authorization; Safe and Bounded Data Access; Modular Design and Simplicity; Verifiable Quality and Specification-Driven Development
- Added sections: MCP and Platform Compatibility; Development, Testing, and Documentation
- Removed sections: None
- Follow-up TODOs: None
-->
# MariaDB MCP Server Constitution

## Core Principles

### I. Portable Official Stack
The server MUST be implemented in Python using the official MCP Python SDK and MariaDB
Connector/Python for database connectivity. It MUST run natively on Windows, Linux, and macOS
without Docker. Docker MAY be provided as an optional aid for development, testing, or deployment,
but MUST NOT be a required runtime or development dependency.

### II. Least Privilege and Layered Authorization
The server MUST connect with a dedicated, non-root MariaDB account and default to read-only access.
Any write capability MUST be explicitly specified, separately authorized, and limited by narrowly
scoped database grants. Before execution, every query MUST pass application-level safety validation
and authorization against the configured databases, schemas, tables, and columns. Validation MUST
NOT rely solely on regular expressions, keyword blacklists, or string-prefix checks. The server
MUST combine application controls with MariaDB permissions and fail closed whenever query safety
or authorization cannot be established.

### III. Safe and Bounded Data Access
Every query MUST have a timeout and bounded result size. Results MUST support pagination where
needed to enforce those bounds. Database connections, cursors, and other resources MUST be released
on success and failure. Credentials MUST come from environment variables or another secure
configuration mechanism; secrets MUST NOT be hard-coded or committed. Logs, errors, and MCP tool
responses MUST NOT expose credentials or sensitive database information. If an error cannot be
reported safely, the server MUST return a sanitized error without leaking underlying details.

### IV. Modular Design and Simplicity
Configuration, database access, SQL validation and authorization, MCP tools, and transport handling
MUST have clear, separate responsibilities. Code MUST use type hints, clear naming, cohesive
modules, consistent formatting, and explicit error handling. Dependencies and abstractions MUST be
limited to those justified by project requirements. The project MUST remain focused on secure
database capabilities exposed through MCP, not unrelated application features.

### V. Verifiable Quality and Specification-Driven Development
Requirements MUST be explicit, implementation plans MUST trace to requirements, and acceptance
criteria MUST be verifiable. Automated tests MUST use pytest and cover applicable security,
authorization, error-handling, and SQL-validation behavior. Unit tests MUST run without a live
MariaDB instance; optional integration tests MAY use a disposable database. Ruff MUST be used for
linting and formatting. Relevant changes MUST include tests and documentation updates. A change is
complete only when its applicable requirements, implementation, tests, security controls, and
documentation meet their acceptance criteria. No test or security check may be reported as passing
unless it was actually executed.

## MCP and Platform Compatibility

The server MUST follow the current official MCP protocol specifications and official Python SDK
best practices. MCP tools MUST expose only authorized database capabilities and MUST preserve the
security, authorization, and result bounds defined above. Documentation MUST accurately describe
the implemented protocol behavior and provide native setup instructions for Windows, Linux, and
macOS. Docker instructions MAY supplement, but MUST NOT replace, native setup instructions.

## Development, Testing, and Documentation

Changes MUST include verifiable acceptance criteria and maintain traceability from requirements
through plans, implementation, and tests. Security-sensitive changes MUST demonstrate the
applicable authorization and failure behavior in tests. Documentation MUST be updated when
behavior, configuration, setup, or security controls change. Security requirements MUST NOT be
weakened, and mandatory infrastructure dependencies MUST NOT be introduced without explicit
justification and specification approval.

## Governance

This constitution governs project requirements, design, implementation, testing, and documentation.
Every change and review MUST assess compliance with the applicable principles and acceptance
criteria. Amendments MUST state their rationale and impact, preserve traceability to project
requirements, and update the version and last-amended date. Versioning follows semantic rules:
MAJOR for backward-incompatible governance changes or removal of requirements, MINOR for new or
materially expanded principles or sections, and PATCH for clarifications and non-semantic edits.
Implementation plans MUST identify applicable security controls and verification evidence.

**Version**: 1.0.0 | **Ratified**: 2026-10-25 | **Last Amended**: 2026-10-25
