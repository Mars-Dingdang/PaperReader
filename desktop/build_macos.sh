#!/usr/bin/env bash
set -euo pipefail

report_failure() {
  local exit_code="$1"
  local line_number="$2"
  local failed_command="$3"
  failed_command="${failed_command//'%'/'%25'}"
  failed_command="${failed_command//$'\r'/'%0D'}"
  failed_command="${failed_command//$'\n'/'%0A'}"
  echo "::error title=macOS packaging failed::line ${line_number}: ${failed_command} (exit ${exit_code})"
}
trap 'report_failure "$?" "$LINENO" "$BASH_COMMAND"' ERR

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(cd "$PROJECT_ROOT" && node -p "require('./frontend/package.json').version")"
ICON_SOURCE="$PROJECT_ROOT/desktop/assets/PaperReader-icon-source.png"
ICON_FILE="$PROJECT_ROOT/desktop/assets/PaperReader.icns"

cd "$PROJECT_ROOT/frontend"
npm ci
npm run build

python -c 'from PIL import Image; import sys; Image.open(sys.argv[1]).convert("RGBA").save(sys.argv[2], format="ICNS")' "$ICON_SOURCE" "$ICON_FILE"

cd "$PROJECT_ROOT"
rm -rf "$PROJECT_ROOT/build/bdist.macosx-11.0-arm64" "$PROJECT_ROOT/dist/PaperReader.app"
mkdir -p "$PROJECT_ROOT/build"
PY2APP_LOG="$PROJECT_ROOT/build/macos-py2app.log"
if ! python desktop/setup_macos.py py2app >"$PY2APP_LOG" 2>&1; then
  tail -120 "$PY2APP_LOG"
  PY2APP_ERROR="$(tail -8 "$PY2APP_LOG")"
  PY2APP_ERROR="${PY2APP_ERROR//'%'/'%25'}"
  PY2APP_ERROR="${PY2APP_ERROR//$'\r'/'%0D'}"
  PY2APP_ERROR="${PY2APP_ERROR//$'\n'/'%0A'}"
  echo "::error title=py2app failed::${PY2APP_ERROR}"
  exit 1
fi
PYTHON_SITE="$(python -c 'import site; print(site.getsitepackages()[0])')"
PYTHON_PREFIX="$(python -c 'import sys; print(sys.prefix)')"
PYTHON_LIB="$PROJECT_ROOT/dist/PaperReader.app/Contents/Resources/lib/python3.11"
RUNTIME_PACKAGES=(pypdfium2 pypdfium2_raw)
for RUNTIME_PACKAGE in "${RUNTIME_PACKAGES[@]}"; do
  cp -R "$PYTHON_SITE/$RUNTIME_PACKAGE" "$PYTHON_LIB/$RUNTIME_PACKAGE"
done
RUNTIME_LIBS=(libffi.8.dylib libbz2.dylib libcrypto.3.dylib libexpat.1.dylib libncursesw.6.dylib libsqlite3.dylib libssl.3.dylib libz.1.dylib libicudata.78.dylib libicui18n.78.dylib libicuuc.78.dylib)
for RUNTIME_LIB in "${RUNTIME_LIBS[@]}"; do
  if [[ -f "$PYTHON_PREFIX/lib/$RUNTIME_LIB" ]]; then
    cp "$PYTHON_PREFIX/lib/$RUNTIME_LIB" "$PROJECT_ROOT/dist/PaperReader.app/Contents/Frameworks/$RUNTIME_LIB"
  fi
done
codesign --force --deep --sign - "$PROJECT_ROOT/dist/PaperReader.app"

mkdir -p "$PROJECT_ROOT/release"
DMG="$PROJECT_ROOT/release/PaperReader-v${VERSION}-macOS-arm64.dmg"
rm -f "$DMG"
hdiutil create -volname PaperReader -srcfolder "$PROJECT_ROOT/dist/PaperReader.app" -ov -format UDZO "$DMG"
shasum -a 256 "$DMG" > "$DMG.sha256"
echo "macOS package: $DMG"
