# MariaDB MCP Server

A native Python MCP server for permission-aware MariaDB discovery, read-only queries,
execution plans, and sanitized connection diagnostics. Local MCP communication uses
STDIO; Docker and remote HTTP are not required.

## Quick start

1. Install Python 3.11–3.14 and MariaDB Connector/C 3.3.1+ for your OS and Python
   architecture. See [native install and security setup](docs/security-and-setup.md).
2. Install the project:

   ```sh
   python -m venv .venv
   python -m pip install -e ".[dev]"
   ```

3. Create a local `mcp.toml` with an explicit database allowlist and a dedicated,
   non-root, read-only MariaDB account. Set `MARIADB_MCP_CONFIG` and
   `MARIADB_MCP_PASSWORD` through your local environment/secret manager.
4. Configure your MCP host to launch an absolute Python path with arguments
   `-m mariadb_mcp` over STDIO.

Run offline checks with `python -m pytest -m "not integration"`. Optional live database
checks can use the disposable Docker harness with `bash scripts/test-integration-docker.sh`,
or an explicitly configured MariaDB instance. Docker is test-only and is not required to
run the server. See
[security, configuration, tools, client setup, tests, and troubleshooting](docs/security-and-setup.md).
