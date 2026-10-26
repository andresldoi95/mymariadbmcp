#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

project_name="mariadb-mcp-integration-$$"
compose=(docker compose -p "$project_name" -f docker-compose.integration.yml)
cleanup() {
  "${compose[@]}" down --volumes --remove-orphans
}
trap cleanup EXIT

"${compose[@]}" up --build --abort-on-container-exit --exit-code-from integration integration
