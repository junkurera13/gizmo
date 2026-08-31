#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
APP_PATH="$REPO_ROOT/dist/Gizmo Simulator.app"

swift build --package-path "$SCRIPT_DIR" -c release
BIN_DIR="$(swift build --package-path "$SCRIPT_DIR" -c release --show-bin-path)"

mkdir -p "$APP_PATH/Contents/MacOS"
mkdir -p "$APP_PATH/Contents/Resources"
install -m 755 "$BIN_DIR/GizmoSimulator" "$APP_PATH/Contents/MacOS/GizmoSimulator"
install -m 644 "$SCRIPT_DIR/Info.plist" "$APP_PATH/Contents/Info.plist"

ICON_SOURCE="$SCRIPT_DIR/AppIcon.png"
ICON_DESTINATION="$APP_PATH/Contents/Resources/AppIcon.icns"
swift "$SCRIPT_DIR/tools/make_app_icon.swift" "$ICON_SOURCE" "$ICON_DESTINATION"

SKIN_SOURCE="$SCRIPT_DIR/DeviceSkins/current"
SKIN_DESTINATION="$APP_PATH/Contents/Resources/DeviceSkins/current"
SKIN_IMAGE="$(plutil -extract imageFilename raw "$SKIN_SOURCE/skin.json")"
PRESSED_SKIN_IMAGE="$(plutil -extract pressedImageFilename raw "$SKIN_SOURCE/skin.json" 2>/dev/null || true)"
mkdir -p "$SKIN_DESTINATION"
install -m 644 "$SKIN_SOURCE/skin.json" "$SKIN_DESTINATION/skin.json"
install -m 644 "$SKIN_SOURCE/$SKIN_IMAGE" "$SKIN_DESTINATION/$SKIN_IMAGE"
if [[ -n "$PRESSED_SKIN_IMAGE" ]]; then
    install -m 644 "$SKIN_SOURCE/$PRESSED_SKIN_IMAGE" "$SKIN_DESTINATION/$PRESSED_SKIN_IMAGE"
fi

codesign --force --deep --sign - "$APP_PATH"

echo "$APP_PATH"
