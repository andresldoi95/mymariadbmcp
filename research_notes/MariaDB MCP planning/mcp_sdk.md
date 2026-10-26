# Official MCP Python SDK and native STDIO compatibility

Research snapshot: 2026-10-25. Scope: a native, local MariaDB MCP server on Windows, Linux, and macOS. MCP transport and annotations do not by themselves enforce database permissions or make arbitrary SQL safe.

## What Python versions and official MCP SDK package/API are currently supported and suitable for native STDIO?

### Takeaway

Use the official `mcp` package, pin a tested 2.x release (2.3.0 is the latest published on this research date), and use v2's `MCPServer` API with `mcp.run()`'s default STDIO transport. Choose Python 3.11+ as the product floor: the current SDK repository README/docs say 3.11+, and Python 3.10 reached end-of-life on 2026-10-01. Test 3.11–3.14 across Windows, Linux, and macOS; 3.15 is current but the SDK's PyPI classifiers do not yet list it.

### Cited Findings

- The official SDK is `modelcontextprotocol/python-sdk`; its README gives the v2-style `from mcp.server import MCPServer`, `MCPServer("Demo")`, and `@mcp.tool()` API and says the SDK supports STDIO, Streamable HTTP, and SSE. The repository README currently states Python 3.11+. — [Official Python SDK repository](https://github.com/modelcontextprotocol/python-sdk)
- PyPI lists `mcp` 2.3.0 as its latest release on 2026-10-25 (released 2026-10-02), marked Production/Stable. It declares `Requires-Python >=3.10` and classifiers for 3.10–3.14. The README content rendered on PyPI says 3.10+, conflicting with the GitHub README's 3.11+; treat metadata as installability, not proof that EOL Python 3.10 is a good new deployment target. — [PyPI project `mcp`](https://pypi.org/project/mcp/)
- The Python Developer's Guide lists 3.10 as EOL since 2026-10-01; 3.11/3.12/3.13 are in security-only support and 3.14/3.15 in bugfix support. — [Python Developer's Guide: version status](https://devguide.python.org/versions/)
- SDK documentation describes `mcp.run()` with no arguments as starting STDIO and documents a local client launching the server child process through stdin/stdout. — [SDK: Connect to a real host](https://py.sdk.modelcontextprotocol.io/get-started/real-host/)
- The same SDK page's launch example is `uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py`; it identifies `mcp[cli]` as the extra supplying the `mcp` command. Plain package installation is sufficient when launching the Python script directly and not using the CLI. — [SDK repository README](https://github.com/modelcontextprotocol/python-sdk); [SDK: Connect to a real host](https://py.sdk.modelcontextprotocol.io/get-started/real-host/)
- PyPI shows stable SDK v2.0.0 released 2026-07-28 and later v2 releases; v2's API is a breaking change from v1. — [PyPI release history](https://pypi.org/project/mcp/); [SDK migration guide](https://py.sdk.modelcontextprotocol.io/migration/)
- Python packaging metadata uses `[project].requires-python` to declare supported interpreter versions, and installers use the metadata to determine compatibility. — [PyPA `pyproject.toml` specification](https://packaging.python.org/en/latest/specifications/pyproject-toml/#requires-python)

### Inferences

- For new deployments, `requires-python = ">=3.11"` is the prudent overlap of current SDK guidance and upstream-maintained Python versions; accepting 3.10 merely because the published SDK metadata permits it would include an EOL interpreter.
- Pin `mcp==2.3.0` (or another exact version selected after CI testing) in reproducible installs/configs; don't use floating `mcp` in a client quickstart. The 1.x and 2.x APIs are not interchangeable; use the documented v2 names/API and verify exact pin compatibility.
- The pure-Python SDK's STDIO subprocess pattern is appropriate on all three desktop OSes. The protocol's subprocess streams are portable, but the SDK pages do not give an explicit tested OS/version support matrix for every SDK release; validate native install, DB driver, interpreter command, and client launch on each OS.

### Gaps

- Official SDK source evidence reviewed here does not explicitly enumerate tested OS/architecture combinations for each 2.3.0 wheel/release. The package is marked `py3-none-any`, but that tag alone does not prove every dependency/driver works on every target.
- SDK package metadata says Python `>=3.10`, while its README/docs say `3.11+`; no official explanation for the mismatch was found. The recommendation above resolves this conservatively rather than claiming the metadata changed.
- PyPI's classifiers stop at 3.14. Python 3.15 is in upstream bugfix support, but explicit SDK test/support status for 3.15 was not established from the cited package metadata.

## What are official SDK expectations around tool discovery, tool schemas, structured content, errors, and STDIO logging?

### Takeaway

Use a small, stable set of explicitly named tools with descriptive docstrings, typed/constrained input parameters, and typed output models for documented JSON schemas. Let clients discover tools via standard `tools/list`; return structured, bounded data; mark genuinely read-only calls with advisory annotations; translate expected failures to curated safe `ToolError` messages and keep unexpected exception detail in protected stderr logs. Never write application output to STDOUT.

### Cited Findings

- The protocol requires a tools-capable server to respond to `tools/list`; the available set should be deterministic in order and must not vary per connection or as a side effect of requests. `listChanged` is for implementations that will notify clients when the available set changes. — [MCP 2026-07-28 Tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- SDK `@mcp.tool()` derives a tool name from the function name, description from its docstring, and input schema from type hints/defaults. `Annotated` plus Pydantic `Field` can express descriptions and constraints; validation rejects invalid arguments before the handler. — [SDK: Tools](https://py.sdk.modelcontextprotocol.io/servers/tools/)
- MCP input schemas must be JSON Schema objects with root `type: "object"`; absent `$schema` defaults to JSON Schema 2020-12. Output schemas are optional; if supplied, server results must conform. — [MCP Tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- SDK v2 return type annotations drive output schemas. Pydantic models, dataclasses, `TypedDict`s, and string-keyed dictionaries make useful object-shaped outputs; values are validated against the generated schema. The SDK supplies `content` for the model and `structured_content` for client code; scalars and lists may be wrapped in `{"result": ...}`. — [SDK: Structured Output](https://py.sdk.modelcontextprotocol.io/servers/structured-output/)
- Protocol `structuredContent` can be any JSON value conforming to `outputSchema`; for backward compatibility, a structured result should also have serialized JSON in a text content block. — [MCP Tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- Tool annotations include hints such as `readOnlyHint`, but clients must treat annotations as untrusted unless the server is trusted. SDK documentation explicitly says hints are not security guarantees. — [MCP Tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools); [SDK: Tools](https://py.sdk.modelcontextprotocol.io/servers/tools/)
- MCP calls distinguish protocol/request errors (JSON-RPC errors) from tool execution errors (`isError: true` in a tool result). Execution errors are suitable for actionable recoverable feedback; the protocol says server implementations must validate inputs, implement access control, rate-limit calls, and sanitize tool outputs. — [MCP Tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- SDK v2 `ToolError` produces `is_error=True` and exposes its message to the model; an unexpected exception yields a generic client-facing tool failure while the server logs the traceback. SDK docs warn that an `MCPError` is forwarded verbatim, so its message/data must also be safe if used. — [SDK: Handling errors](https://py.sdk.modelcontextprotocol.io/servers/handling-errors/)
- STDIO is one newline-delimited UTF-8 JSON-RPC message per line. Server STDOUT must contain only valid MCP messages; STDERR may be used for logging. The client launches the subprocess, and servers should exit promptly at stdin EOF. — [MCP STDIO transport specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio)
- The SDK recommends Python's standard `logging`, which writes to stderr by default; it cautions against `print()` because stdout is the protocol channel (and buffered output can corrupt it). The 2026-07-28 spec deprecates protocol `notifications/message` logging. — [SDK: Logging](https://py.sdk.modelcontextprotocol.io/handlers/logging/); [MCP debugging guide](https://modelcontextprotocol.io/docs/2026-07-28/tools/debugging)

### Inferences

- Use protocol-level `tools/list` for MCP tool discovery; don't invent a redundant `list_tools` tool. If database discovery is a product feature, expose a separate, constrained catalog-inspection tool (e.g. list permitted schemas/tables) rather than returning the entire catalog during every tools/list.
- Keep tool definitions static and ordered, with `listChanged` false/unset if the tool registry does not change. Do not make tool visibility depend on whichever database was last queried; stable discovery is easier for client caching and avoids an implicit authorization boundary.
- Candidate surface: `list_databases`/`list_tables` with an allowlist and limits; `query_read_only(sql, parameters, row_limit)`; `explain_read_only(sql, parameters)`; and `diagnose()` returning only non-secret status/version/capability fields. Prefer precise names/descriptions and bounds; exact choices should be fixed in the product contract.
- Use separate Pydantic output models for discovery, rows, plan nodes, and diagnostics, with explicit nullability and output limits. Avoid unbounded result sets and avoid exposing exception strings, DSNs, usernames/passwords, local paths, or full connection environment in structured results.
- Mark query, explain, discovery, and diagnostics `read_only_hint=True` and `open_world_hint=False` when accurate. Treat the flag solely as client-facing metadata: enforce read-only access through a MariaDB account with only required grants and server-side validation/allowlisting, not through the hint or SQL prompt text.
- Raise `ToolError` only with an intentionally sanitized, user-actionable message. For driver/SQL implementation exceptions, allow generic failure handling or map into a short safe category; log details only to stderr after redacting secrets/query literals where applicable. SDK's traceback logging is useful but can itself leak sensitive SQL/context if the application logs raw exceptions.
- Add `outputSchema` through typed return types where stable structured result contracts help clients. Keep result text useful for the model and ensure structured values are JSON-serializable and bounded.

### Gaps

- The MCP spec does not prescribe MariaDB-specific SQL parsing, read-only enforcement, plan format, diagnostic fields, or which catalog objects to expose; these must be product-level security/API decisions.
- Output schemas are optional by protocol; choosing a schema for every tool is a contract recommendation, not an MCP MUST.

## What client integration/configuration details should a contract and quickstart capture?

### Takeaway

Document the subprocess launch command—not a remote URL—as the integration contract. Provide explicit absolute paths for the interpreter/launcher and server script, an exact SDK/runtime pin, environment-variable names and safe configuration steps, plus client-specific config examples and restart/troubleshooting steps. STDIO requires no listening port, Docker, or remote HTTP endpoint.

### Cited Findings

- Official SDK guidance says a host launches the local server as a child process and communicates over stdin/stdout; default `mcp.run()` is STDIO and needs no port. The canonical SDK CLI command is `uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py`. — [SDK: Connect to a real host](https://py.sdk.modelcontextprotocol.io/get-started/real-host/)
- The SDK warns that the host's working directory may differ from the user's shell and may be undefined; use absolute paths. A host may have a minimal `PATH`, so the `uv` executable may need its absolute path. `mcp install` writes a pinned command for Claude Desktop. — [SDK: Connect to a real host](https://py.sdk.modelcontextprotocol.io/get-started/real-host/); [MCP debugging guide](https://modelcontextprotocol.io/docs/2026-07-28/tools/debugging)
- SDK docs provide host config examples: Claude Desktop JSON under `mcpServers`; Claude Code `claude mcp add <name> -- <command>`; Cursor `.cursor/mcp.json` under `mcpServers`; and VS Code `.vscode/mcp.json` under `servers` with `type: "stdio"`. These structures differ by client. — [SDK: Connect to a real host](https://py.sdk.modelcontextprotocol.io/get-started/real-host/)
- The SDK's Claude Desktop example uses absolute path to `uv`, `args` with `run --frozen --with mcp[cli]==2.0.0 mcp run <absolute server path>`, and notes environment variables can go in the config's `env` field. Host config environment inheritance is limited/platform-dependent. — [SDK: Connect to a real host](https://py.sdk.modelcontextprotocol.io/get-started/real-host/); [MCP debugging guide](https://modelcontextprotocol.io/docs/2026-07-28/tools/debugging)
- MCP clients may capture, forward, or ignore stderr and should not assume stderr means failure; STDIO server process should exit on EOF. — [MCP STDIO transport specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio)
- The SDK says test the launch command directly; a silent process waiting on stdin is expected, while startup tracebacks/immediate exit indicate an issue. It recommends MCP Inspector for local development/testing. Client config changes require host restart; Claude Desktop needs a full quit/reopen. — [SDK: Connect to a real host](https://py.sdk.modelcontextprotocol.io/get-started/real-host/); [MCP debugging guide](https://modelcontextprotocol.io/docs/2026-07-28/tools/debugging)

### Inferences

- Define a canonical tested command in the contract and show host-specific translations. Example for an installed app: `"command": "/absolute/path/to/python", "args": ["-m", "mariadb_mcp"]` (packaged module/entry point) or the SDK CLI pattern `uv run --with "mcp[cli]==2.3.0" mcp run /absolute/path/to/server.py`. The CLI form needs the `cli` extra. For a locked uv project, document `--frozen` and exact constraints so client startup cannot mutate project files. On Windows, show absolute executable/script paths and confirm actual interpreter invocation; do not assume `python`/`uv` is in the host's PATH.
- State prerequisites: supported Python, MariaDB reachable locally or via the user's configured database host, a dedicated least-privileged account, and the install/upgrade route. Avoid requiring Docker; the host starts the installed native process directly.
- Document the configuration keys (server name, command, args, env, optional cwd only where host supports it), location per supported client, how to edit/restart, and a verification sequence: launch command, inspect discovered tools, run harmless read query/explain, test sanitized diagnostics, inspect stderr/client logs.
- Treat DB credentials as configuration secrets: use a user-managed environment/config secret mechanism, don't put passwords in command arguments or tool schemas/results/logs, and describe exactly which environment variable names are read. Avoid encouraging `.env` files in source control; if supported, explain file permissions and absolute path behavior.
- Specify tool names, descriptions, JSON input/output schemas, row/plan limits, SQL parameter convention, allowed database scope, expected error categories, and what diagnostic fields are intentionally omitted. Specify the supported protocol/client scope and version-upgrade testing procedure.
- Explain that a normal idle STDIO server can appear silent because stdout is reserved for MCP wire traffic; stderr is diagnostic output. Include Inspector instructions and common host `PATH`, path quoting, config reload, and environment inheritance troubleshooting.

### Gaps

- There is no universal MCP client configuration-file format. Exact config paths and supported fields vary by host and host release; examples in the SDK docs are representative and must be rechecked for each named product/version.
- The SDK docs document the `uv` launch option and Python subprocess concept, but do not specify one universally correct `python` executable name/path for all shells, operating systems, or managed installations. The quickstart should offer verified OS-specific commands rather than assume.
- Credential storage/secret-injection capability is host-specific and not standardized by the MCP protocol. Keep secrets external to tool arguments and disclose each supported host's actual handling.
