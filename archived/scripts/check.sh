#!/usr/bin/env bash
set -euo pipefail

repository_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(uname -s)" != "Linux" ]]; then
    echo "Run this script from WSL2 or a Linux CI runner." >&2
    exit 2
fi
if [[ "$repository_dir" == /mnt/* ]]; then
    echo "Move the checkout into the WSL2 Linux filesystem before running checks." >&2
    exit 2
fi
cd "$repository_dir"

uv lock --project windows-client --check
uv sync --project windows-client --frozen --group dev
uv run --frozen --project windows-client pytest
uv run --frozen --project windows-client ruff check windows-client scripts
uv run --frozen --project windows-client ruff format --check windows-client scripts
uv run --frozen --project windows-client pyright --project windows-client/pyproject.toml
uv run --frozen --project windows-client python scripts/check_repository.py .
