"""Run the local MCP server over STDIO."""

from __future__ import annotations

import logging
import sys

from mariadb_mcp.config import ConfigurationError, load_config
from mariadb_mcp.server import create_server


def main() -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    try:
        config = load_config()
    except ConfigurationError:
        logging.getLogger("mariadb_mcp").error("Server configuration is invalid.")
        create_server().run("stdio")
        return 0
    create_server(config).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
