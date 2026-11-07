#!/usr/bin/env bash
# Build "Epson God Mode.app" and a .dmg on a Mac (Apple Silicon -> arm64, Intel -> x86_64).
#
# Unsigned (default):  ./packaging/build_macos.sh
# Signed + notarized:  export EGM_MAC_SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
#                      export EGM_NOTARY_PROFILE="egm-notary"   # created once with: xcrun notarytool store-credentials
#                      ./packaging/build_macos.sh
set -euo pipefail
cd "$(dirname "$0")/.."
APP="dist/Epson God Mode.app"
ARCH="$(uname -m)"
DMG="dist/EpsonGodMode-macos-${ARCH}.dmg"

if [ ! -d .venv ]; then
  python3 -m venv .venv || { echo "Python 3.10+ is required to build (https://www.python.org/downloads/macos/)"; exit 1; }
fi
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -e ".[patterns,macos]" pyinstaller

rm -rf build "$APP" "$DMG"
.venv/bin/python -m PyInstaller --noconfirm --clean packaging/egm.spec

IDENTITY="${EGM_MAC_SIGN_IDENTITY:-}"
if [ -n "$IDENTITY" ]; then
  echo "Signing with: $IDENTITY"
  codesign --force --deep --options runtime --timestamp \
           --entitlements packaging/macos/entitlements.plist --sign "$IDENTITY" "$APP"
else
  echo "No EGM_MAC_SIGN_IDENTITY set -> ad-hoc signature (runs on this Mac; other Macs will warn)"
  codesign --force --deep --sign - "$APP"
fi
codesign --verify --deep --strict --verbose=2 "$APP"

echo "Smoke test:"
"$APP/Contents/MacOS/egm" -d sim:L3111 waste

# disk image with an Applications shortcut
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Epson God Mode" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
[ -n "$IDENTITY" ] && codesign --force --timestamp --sign "$IDENTITY" "$DMG"

if [ -n "$IDENTITY" ] && [ -n "${EGM_NOTARY_PROFILE:-}" ]; then
  echo "Notarizing (a few minutes)..."
  xcrun notarytool submit "$DMG" --keychain-profile "$EGM_NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
  xcrun stapler staple "$APP"
  spctl --assess --type execute --verbose "$APP"
fi

echo
echo "Done:"
echo "  $APP"
echo "  $DMG"
if [ -z "$IDENTITY" ]; then
  echo "Unsigned build: on another Mac, open it once via System Settings > Privacy & Security > Open Anyway,"
  echo "or run:  xattr -dr com.apple.quarantine \"/Applications/Epson God Mode.app\""
fi
