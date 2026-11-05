#!/bin/bash
# Builds "Claude Profile Manager.app" into gui/build/. Requires Xcode Command Line Tools (Swift 5.9+).
# The app is a front-end for ../claude-manager.py; it installs nothing by itself.
set -euo pipefail
cd "$(dirname "$0")"
APP="build/Claude Profile Manager.app"
VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' ../claude-manager.py)"

swift build -c release
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$(swift build -c release --show-bin-path)/ClaudeProfileManager" "$APP/Contents/MacOS/ClaudeProfileManager"

if [ ! -f Resources/AppIcon.icns ] || [ Resources/Logo.svg -nt Resources/AppIcon.icns ]; then
  tmp="$(mktemp -d)"
  swift scripts/make-icon.swift Resources/Logo.svg "$tmp/icon.png" 1024
  mkdir "$tmp/AppIcon.iconset"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$tmp/icon.png" --out "$tmp/AppIcon.iconset/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) "$tmp/icon.png" --out "$tmp/AppIcon.iconset/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$tmp/AppIcon.iconset" -o Resources/AppIcon.icns
  rm -rf "$tmp"
fi
cp Resources/AppIcon.icns "$APP/Contents/Resources/"
cp Resources/Logo.svg "$APP/Contents/Resources/"
[ -f ../docs/Napoveda.pdf ] && cp ../docs/Napoveda.pdf "$APP/Contents/Resources/"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Claude Profile Manager</string>
  <key>CFBundleDisplayName</key><string>Claude Profile Manager</string>
  <key>CFBundleIdentifier</key><string>local.claudeprofiles.manager-gui</string>
  <key>CFBundleExecutable</key><string>ClaudeProfileManager</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>CFBundleDevelopmentRegion</key><string>cs</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>Claude Profile Manager ${VERSION}</string>
</dict></plist>
PLIST
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
echo "Built: $(pwd)/$APP"
