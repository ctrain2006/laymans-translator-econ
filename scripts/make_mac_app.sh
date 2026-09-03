#!/bin/bash
# Builds "Layman's Translator.app" next to the source, so the app can be opened
# from Finder, the Dock, or Spotlight with no Terminal window.
#
#   bash scripts/make_mac_app.sh
#
# The bundle is a thin wrapper that runs app.py with the system Python. It
# declares a microphone usage string, which macOS requires before it will let
# speech mode record.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP="$SRC/Layman's Translator.app"
PYBIN="$(command -v python3)"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Layman's Translator</string>
  <key>CFBundleDisplayName</key><string>Layman's Translator</string>
  <key>CFBundleIdentifier</key><string>com.laymanstranslator.app</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key>
  <string>Speech mode listens to your question so it can translate economics jargon into plain English.</string>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/launcher" <<LAUNCH
#!/bin/bash
cd "$SRC"
exec "$PYBIN" app.py
LAUNCH

chmod +x "$APP/Contents/MacOS/launcher"
# Clear the quarantine flag and nudge LaunchServices to notice the new bundle.
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
touch "$APP"

echo "Built: $APP"
echo "Open it from Finder, or run:  open \"$APP\""
