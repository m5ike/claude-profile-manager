#!/bin/bash
# Installs only this manager. Does not touch Claude data, login or shell rc.
set -euo pipefail
umask 077
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-$HOME/.local/share/claude-profile-manager}"
PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null || { echo "Python 3.9+ is required." >&2; exit 1; }
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 9), "Python 3.9+ is required"'
case "$DEST" in /*) ;; *) echo "INSTALL_DIR must be absolute." >&2; exit 1 ;; esac
if [[ -e "$DEST" || -L "$DEST" ]]; then
  echo "Refusing to overwrite existing installation: $DEST" >&2
  exit 1
fi
mkdir -p "$(dirname "$DEST")"
mkdir -m 700 "$DEST"
cp "$SRC/claude-manager.py" "$DEST/claude-manager.py"
chmod 700 "$DEST/claude-manager.py"
cp "$SRC/README.cs.md" "$DEST/README.cs.md"
for name in update.py update.sh install.sh run-tests.sh TEST_REPORT.md test-output.txt SHA256SUMS .gitignore; do
  cp "$SRC/$name" "$DEST/$name"
done
chmod 700 "$DEST/update.py" "$DEST/update.sh" "$DEST/install.sh" "$DEST/run-tests.sh"
mkdir -m 700 "$DEST/tests"
cp "$SRC/tests/test_manager.py" "$DEST/tests/test_manager.py"
cp "$SRC/tests/test_update.py" "$DEST/tests/test_update.py"
mkdir -m 700 "$DEST/sbin" "$DEST/data"
printf 'Installed into %s\nAdministration: %q\n' "$DEST" "$DEST/claude-manager.py"
printf 'Next: set-binary, create, launchers, path --write --yes (see README).\n'
printf 'Later updates: run update.sh from the NEW release, passing this installation directory and --yes.\n'
