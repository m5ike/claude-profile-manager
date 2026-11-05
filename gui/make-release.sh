#!/bin/bash
# Builds dist/claude-profile-manager-VERSION.zip: the verified script payload (as listed in
# SHA256SUMS), the macOS app, the PDF manual and the changelog, plus a .sha256 next to the zip.
# Requires Xcode Command Line Tools; regenerate docs/Napoveda.pdf first if the manual changed.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' claude-manager.py)"
NAME="claude-profile-manager-$VERSION"
OUT="dist/$NAME"

# Refuse to package a payload whose checksums do not match (update.sh would reject it too).
shasum -a 256 -c SHA256SUMS >/dev/null

gui/build-app.sh >/dev/null
rm -rf "$OUT" "dist/$NAME.zip" "dist/$NAME.zip.sha256"
mkdir -p "$OUT/tests"
while read -r _ file; do
  mkdir -p "$OUT/$(dirname "$file")"
  cp -p "$file" "$OUT/$file"
done < SHA256SUMS
cp -p SHA256SUMS CHANGELOG.md docs/Napoveda.pdf "$OUT/"
ditto "gui/build/Claude Profile Manager.app" "$OUT/Claude Profile Manager.app"
(cd dist && ditto -c -k --norsrc --noextattr --noqtn --keepParent "$NAME" "$NAME.zip" &&
 shasum -a 256 "$NAME.zip" > "$NAME.zip.sha256")
echo "Release: $(pwd)/dist/$NAME.zip"
cat "dist/$NAME.zip.sha256"
