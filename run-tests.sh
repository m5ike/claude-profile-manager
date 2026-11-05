#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 9)'
for pass in 1 2; do
  printf '\n=== COMPLETE TEST PASS %s/2 ===\n' "$pass"
  "$PYTHON" -m unittest discover -s tests -v
done
"$PYTHON" -m py_compile claude-manager.py update.py tests/test_manager.py tests/test_update.py
bash -n install.sh
bash -n run-tests.sh
bash -n update.sh
printf '\nBoth passes, Python syntax and shell syntax passed.\n'
