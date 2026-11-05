#!/bin/bash
# Run this from the NEW release; explicit --yes authorizes update + shell repair.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null || { echo "Python 3.9+ is required." >&2; exit 1; }
exec "$PYTHON" "$SRC/update.py" "$@"
