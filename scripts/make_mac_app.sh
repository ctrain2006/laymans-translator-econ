#!/bin/bash
# Builds a double-clickable "Layman's Translator.app".
#
#   bash scripts/make_mac_app.sh          -> installs to ~/Applications
#   bash scripts/make_mac_app.sh --here   -> builds next to the source instead
#
# The bundle is SELF-CONTAINED: the Python files are copied inside it. That
# matters on macOS, because an app bundle is not allowed to read files in
# ~/Desktop, ~/Documents or ~/Downloads without an explicit permission grant.
# A bundle that pointed back at source on the Desktop would fail to start with
# "Operation not permitted". Reading its own Resources always works.
#
# Because the code is copied in, re-run this script after changing the source.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
PYBIN="$(command -v python3)"
NAME="Layman's Translator"

if [ "${1:-}" = "--here" ]; then
  DEST="$SRC"
else
  DEST="$HOME/Applications"
  mkdir -p "$DEST"
fi
APP="$DEST/$NAME.app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# The app's own copy of the program.
for f in app.py engine.py glossary.py glossary_textbook.py speech.py voice.py; do
  cp "$SRC/$f" "$APP/Contents/Resources/$f"
done

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$NAME</string>
  <key>CFBundleDisplayName</key><string>$NAME</string>
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
# Log startup trouble somewhere findable, since LaunchServices discards output.
exec 2> "\$HOME/Library/Logs/laymans-translator.log"
cd "\$(dirname "\$0")/../Resources" || exit 1
exec "$PYBIN" app.py
LAUNCH

chmod +x "$APP/Contents/MacOS/launcher"
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
touch "$APP"

echo "Built: $APP"
echo
echo "Open it from Finder or Spotlight, or run:"
echo "  open \"$APP\""
echo
echo "Re-run this script after changing the Python source."
