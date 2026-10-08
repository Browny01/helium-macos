#!/usr/bin/env bash
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
root="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$root/devutils/fork_release.py" "$@"
