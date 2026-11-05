#!/bin/bash
# Renders docs/napoveda/napoveda.html into docs/Napoveda.pdf (needs Google Chrome + Swift).
# Screenshots in img/ are produced by the app itself:
#   "Claude Profile Manager.app/Contents/MacOS/ClaudeProfileManager" -snapshotDir DIR -snapshotAppearance light
set -euo pipefail
cd "$(dirname "$0")"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
tmp="$(mktemp -d)"
"$CHROME" --headless=new --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="$tmp/raw.pdf" "file://$PWD/napoveda.html" 2>/dev/null
swift stamp-pages.swift "$tmp/raw.pdf" ../Napoveda.pdf
rm -rf "$tmp"
echo "Written: $(cd .. && pwd)/Napoveda.pdf"
