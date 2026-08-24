#!/usr/bin/env sh
set -eu
printf 'Node: '; node --version
printf 'Docker: '; docker --version
printf 'Compose: '; docker compose version
if command -v nvidia-smi >/dev/null 2>&1; then nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader; else echo 'NVIDIA tools not installed yet'; fi
docker compose config --quiet
echo 'Compose configuration is valid.'
