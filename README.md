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

## GitHub Copilot in VS Code

Copilot Chat can use this server as a local STDIO MCP server. Install the project
in a virtual environment as above, then add this configuration to
`.vscode/mcp.json`:

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "mariadbMcpPassword",
      "description": "MariaDB read-only password",
      "password": true
    }
  ],
  "servers": {
    "mariadb": {
      "type": "stdio",
      "command": "/absolute/path/to/mymariadbmcp/.venv/bin/python",
      "args": ["-m", "mariadb_mcp"],
      "env": {
        "MARIADB_MCP_CONFIG": "/absolute/path/to/mcp.toml",
        "MARIADB_MCP_PASSWORD": "${input:mariadbMcpPassword}"
      }
    }
  }
}
```

Replace both paths with absolute paths on your machine. VS Code prompts for the
database password instead of storing it in this file. Start the server from the
MCP configuration or use **MCP: List Servers** from the Command Palette to check
its status. In Copilot Chat, select **Agent** mode to use the server's tools.
Keep local paths and credentials out of shared configuration. See
[security and setup](docs/security-and-setup.md) for database account and access
policy guidance.

## OpenCode

OpenCode V2 can launch this server over local STDIO. Merge the following MCP
entry into your project `opencode.jsonc` or your global OpenCode configuration
(keep any existing settings):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "mariadb": {
        "type": "local",
        "command": [
          "/absolute/path/to/mymariadbmcp/.venv/bin/python",
          "-m",
          "mariadb_mcp"
        ],
        "environment": {
          "MARIADB_MCP_CONFIG": "/absolute/path/to/mcp.toml",
          "MARIADB_MCP_PASSWORD": "{env:MARIADB_MCP_PASSWORD}"
        }
      }
    }
  }
}
```

Replace the paths with absolute paths on your machine, and make sure
`MARIADB_MCP_PASSWORD` is set in the environment available to OpenCode. The
`{env:...}` value keeps the password out of the config file. Check the server
connection with `opencode mcp list` or `/mcps`. Do not commit machine-specific
paths or credentials in shared configuration.

Run offline checks with `python -m pytest -m "not integration"`. Optional live database
checks can use the disposable Docker harness with `bash scripts/test-integration-docker.sh`,
or an explicitly configured MariaDB instance. Docker is test-only and is not required to
run the server. See
[security, configuration, tools, client setup, tests, and troubleshooting](docs/security-and-setup.md).
