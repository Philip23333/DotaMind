#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="$project_dir/compose.wsl.yml"
data_overlay="$project_dir/compose.data.yml"

if command -v docker >/dev/null 2>&1; then
  exec docker compose -f "$compose_file" -f "$data_overlay" "$@"
fi

# Docker Desktop can also be used before WSL Integration is enabled.
windows_cmd=/mnt/c/Windows/System32/cmd.exe
if [[ -x "$windows_cmd" ]] && command -v wslpath >/dev/null 2>&1; then
  windows_docker="$(cd /mnt/c/Windows && "$windows_cmd" /c where docker.exe </dev/null 2>/dev/null | tr -d '\r' | head -n 1)" || true
  if [[ -n "${windows_docker:-}" ]]; then
    docker_bin="$(wslpath -u "$windows_docker")"
    exec "$docker_bin" compose \
      -f "$(wslpath -w "$compose_file")" \
      -f "$(wslpath -w "$data_overlay")" \
      "$@"
  fi
fi

echo 'Docker is unavailable. Start Docker Desktop and enable Settings > Resources > WSL Integration for this distribution.' >&2
exit 1
