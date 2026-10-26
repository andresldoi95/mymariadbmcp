# Feature Specification: MariaDB MCP Server

**Feature Branch**: `Not created`

**Created**: 2026-10-25

**Status**: Draft

**Input**: User description: Build a custom MCP server that enables AI assistants to securely discover MariaDB metadata, run authorized read-only queries, and analyze queries. It must run natively across Windows, Linux, and macOS; use configurable connections and access restrictions; enforce bounded, fail-closed access; support STDIO; include automated offline unit tests and optional disposable-database integration tests; and provide complete installation, configuration, security, client, testing, and troubleshooting documentation. Database modifications and privileged administration are out of scope.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Discover an authorized database (Priority: P1)

An AI assistant connects to the server and discovers the available tools. A user can then list only the databases, schemas, and tables they are permitted to see, inspect a table's columns and types, and review its keys, indexes, and relationships.

**Why this priority**: Reliable, permission-aware discovery is the foundation for useful and safe database assistance.

**Independent Test**: Connect an MCP client to a configured test database and verify tool discovery and metadata results against the configured access scope, without running a data query.

**Acceptance Scenarios**:

1. **Given** a reachable database and configured allowed objects, **When** a client discovers tools and requests database, schema, or table listings, **Then** it receives only objects visible to the database account and allowed by server restrictions.
2. **Given** an allowed table, **When** a client requests its structure, **Then** the result identifies column names and types, primary keys, indexes, and foreign-key relationships that are available to the account.
3. **Given** an object outside the configured scope, **When** a client requests or attempts to discover it, **Then** the server does not disclose its metadata or contents.

---

### User Story 2 - Retrieve authorized data safely (Priority: P1)

An AI assistant submits a read-only query over authorized objects and receives a structured, bounded result it can explain to the user. The user can apply supported filters, sorting, and pagination within configured limits.

**Why this priority**: Read-only querying is the principal data-access value while preserving the initial release's safety boundary.

**Independent Test**: Run allowed and disallowed query scenarios against a fixture or mocked database layer; verify result contents, bounds, and authorization decisions without requiring a live MariaDB instance for unit tests.

**Acceptance Scenarios**:

1. **Given** a valid read-only query over allowed objects, **When** the assistant executes it, **Then** the response includes column information, rows, execution metadata, and an indication of whether results were truncated.
2. **Given** a query requesting more rows than the configured limit, **When** it executes, **Then** the server returns no more than the configured limit and clearly indicates truncation or the availability of another page.
3. **Given** an unauthorized object, restricted column, unsupported construct, multi-statement request, or state-changing operation, **When** it is submitted directly or nested within a query, **Then** the server rejects it without returning protected data or executing a change.
4. **Given** supported filter, sort, and pagination inputs, **When** they are valid for the requested authorized data, **Then** the returned rows follow those inputs and remain within configured result bounds.

---

### User Story 3 - Analyze a query and check connectivity (Priority: P2)

An AI assistant or operator requests an execution plan for a supported read-only query or checks whether the configured database connection is usable, without exposing credentials or sensitive connection details.

**Why this priority**: Query analysis and safe diagnostics help users understand performance and resolve setup problems without expanding access into administration.

**Independent Test**: Verify plans are returned only for supported authorized read-only queries, and diagnostics distinguish successful and failed connections while omitting secret values.

**Acceptance Scenarios**:

1. **Given** a supported, authorized read-only query, **When** a client requests its execution plan, **Then** the server returns the plan without executing a data modification or exposing unauthorized object details.
2. **Given** an unsupported or unauthorized query, **When** a client requests its plan, **Then** the request is rejected under the same safety and access rules as query execution.
3. **Given** valid or invalid connection settings, **When** an operator requests diagnostics, **Then** the response reports a useful connection status and safe error category without revealing passwords, secret-bearing configuration, or sensitive server details.

---

### User Story 4 - Configure and operate the server securely (Priority: P2)

A database owner configures a native local server for an assistant, defines connection and access scope, and follows the documentation to grant the minimum required database permissions, test the setup, and troubleshoot failures.

**Why this priority**: Clear configuration and a database-enforced permission boundary are necessary for safe adoption across supported desktop platforms.

**Independent Test**: Follow the installation and configuration documentation on each supported operating system, run the offline test suite, and verify the least-privilege account can perform permitted reads but cannot modify data.

**Acceptance Scenarios**:

1. **Given** supported Windows, Linux, or macOS environments, **When** an operator follows the native setup instructions, **Then** the server can be started without requiring Docker.
2. **Given** configured object restrictions and a dedicated read-only database account, **When** the server receives a request, **Then** both application restrictions and database permissions constrain access.
3. **Given** no live MariaDB service, **When** a developer runs unit tests, **Then** database-operation, validation, authorization, error-handling, and MCP behavior tests can run without a database instance.

### Edge Cases

- The database is unreachable, credentials are invalid, or the account lacks permission for some metadata; diagnostics remain safe and partial metadata is not mistaken for complete access.
- A query returns no rows, contains null values or unusual column types, exceeds a row or result-size limit, or runs past its timeout; the response remains well-formed and resources are released.
- An input uses multiple statements, comments, quoted identifiers, nested queries, joins, CTEs, unions, functions, or other constructs to disguise access to a restricted object; the server rejects it if it cannot establish safe authorization for every referenced object.
- A client submits malformed arguments, an invalid page or sort field, an unsupported SQL construct, or an execution-plan request for a query that cannot be safely analyzed; the server returns a clear, sanitized error.
- A database error includes sensitive connection or query details; those details are not copied into logs or client-visible errors.
- A client disconnects or cancels a request while it is running; the server stops or bounds the work where supported and closes its resources.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The server MUST allow compatible MCP clients to connect over local STDIO and discover its available tools.
- **FR-002**: The server MUST be installable and runnable as a native Python application on Windows, Linux, and macOS without requiring Docker.
- **FR-003**: Operators MUST be able to configure a connection to a local or remote MariaDB instance without committing credentials to the project.
- **FR-004**: The server MUST provide tools to list accessible databases, schemas, and tables, and inspect table columns and types, primary keys, indexes, and foreign-key relationships.
- **FR-005**: The server MUST provide a read-only query capability for authorized database objects, with supported filtering, sorting, and pagination.
- **FR-006**: A query response MUST provide column information, returned rows, execution metadata, and an explicit truncation indication when a result is cut off or bounded.
- **FR-007**: The server MUST provide execution plans only for supported read-only queries that pass the same access and safety checks as data queries.
- **FR-008**: The server MUST provide connection diagnostics that communicate useful status and failure information without disclosing credentials or sensitive connection details.
- **FR-009**: The server MUST default to read-only behavior and MUST reject data modification, schema modification, administrative, multi-statement, or otherwise state-changing requests.
- **FR-010**: Operators MUST be able to restrict accessible databases, schemas, tables, and columns. Requests outside that scope MUST be denied, including when restricted objects are referenced indirectly.
- **FR-011**: Before execution or plan retrieval, the server MUST validate the complete submitted statement and establish authorization for every object it references, including objects reached through joins, nested queries, CTEs, set operations, and other supported constructs. It MUST reject unsupported or ambiguous constructs when safe authorization cannot be established.
- **FR-012**: The server MUST use database-account permissions as an independent access boundary and document how to configure a dedicated, non-administrative, read-only account.
- **FR-013**: Operators MUST be able to configure query timeouts and result bounds. The server MUST enforce them, release database resources on success and failure, and prevent unbounded result retrieval.
- **FR-014**: Invalid inputs, rejected queries, unavailable connections, database errors, timeouts, and unsupported constructs MUST produce predictable, sanitized responses and MUST NOT expose credentials or sensitive database information in logs or client responses.
- **FR-015**: The server MUST provide a consistent mechanism for adding tools that reuses shared database access, validation, authorization, timeout, and error-handling behavior.
- **FR-016**: Automated tests MUST cover database operations, SQL validation, access restrictions, error handling, and MCP tool behavior. Unit tests MUST run without a live MariaDB instance; optional integration tests MAY use a disposable MariaDB database.
- **FR-017**: Documentation MUST cover native installation, configuration, least-privilege database permissions, available tools, startup, MCP client integration, testing, and troubleshooting.
- **FR-018**: The initial release MUST exclude database modifications, administrative operations, and other privileged capabilities.

### Key Entities *(include if feature involves data)*

- **Connection Profile**: Non-secret connection settings and protected credentials used to reach a MariaDB instance.
- **Access Scope**: The configured databases, schemas, tables, and columns the server may expose, further constrained by database-account permissions.
- **Database Object Metadata**: Discoverable database, schema, table, column, key, index, and relationship information.
- **Read Query**: A validated request to retrieve data from authorized objects, including optional filters, sort order, and page bounds.
- **Query Result**: Column descriptions, returned rows, execution metadata, and truncation state.
- **Execution Plan**: Analysis information for a supported, authorized read-only query.
- **Diagnostic Result**: Safe connection status and failure information that excludes secrets.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In acceptance testing, clients successfully discover the server's available tools and complete each supported metadata-discovery task in at least 95% of valid, authorized scenarios.
- **SC-002**: In acceptance testing, every successful query response contains column information, rows, execution metadata, and an accurate truncation indicator when applicable.
- **SC-003**: 100% of tested unauthorized, state-changing, multi-statement, or unclassifiable requests are denied without returning protected data or changing database contents.
- **SC-004**: Every query in timeout and result-bound tests completes within its configured time limit or is stopped with a safe timeout outcome, and no response exceeds its configured result bound.
- **SC-005**: In secret-scanning tests using sentinel credentials and sensitive connection values, none appear in logs, diagnostics, or client-visible errors.
- **SC-006**: Developers can run the complete unit-test suite without a live database, and the native setup and client-connection procedure can be completed on Windows, Linux, and macOS by following the documentation.

## Assumptions

- The initial release supports local STDIO only; remote HTTP transport is deferred to avoid expanding the initial network-facing surface.
- The server connects using a dedicated, non-root MariaDB account with read-only grants. Application restrictions supplement, and do not replace, those database permissions.
- Access is deny-by-default: operators configure the objects that may be exposed, and omitted or ambiguous scope does not grant access.
- Credentials are supplied through environment variables or another protected local configuration mechanism; no credential is included in examples, source control, logs, or tool responses.
- Query timeout and result-size defaults are conservative and configurable; clients may request smaller bounds but cannot override configured maximums.
- Only SQL constructs that can be safely validated and authorized are supported. Unsupported constructs are rejected rather than passed through.
- Optional integration tests may require a disposable MariaDB instance; normal unit tests do not.
- Filtering, sorting, and pagination are applied only to authorized query results and do not expand the underlying object access scope.
