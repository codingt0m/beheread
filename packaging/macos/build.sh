#!/bin/bash
# Construit Beheread pour macOS (Apple Silicon) : verification du code et
# tests, puis l'application (PyInstaller), puis les fichiers a publier, dans
# dist/ :
#   Beheread-<version>-macos.dmg   image disque : Beheread.app + raccourci Applications
#   SHA256SUMS-macos.txt           somme de controle du .dmg
# Prerequis : un Mac, Python 3.10+, pip install -r requirements-dev.txt.
# Equivalent de build.bat (Windows) ; meme script en local et pour la
# publication (.github/workflows/release.yml).
set -euo pipefail

cd "$(dirname "$0")/../.."
VERSION=$(python3 -c "from beheread.version import __version__; print(__version__)")
DMG="Beheread-$VERSION-macos.dmg"

echo "=== Beheread $VERSION : verification du code et tests ==="
python3 -m ruff check .
python3 -m pytest -q

echo "=== Application (dist/Beheread.app) ==="
python3 -m PyInstaller beheread.spec --noconfirm
APP=dist/Beheread.app

# Signature « ad hoc » de l'ensemble (obligatoire sur Apple Silicon ; sans
# compte Apple Developer, Gatekeeper demandera une confirmation au premier
# lancement, voir le README).
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

echo "=== Verification du demarrage ==="
# l'application emballee doit se lancer (bibliotheques Qt completes) puis se
# fermer d'elle-meme ; donnees dans un dossier jetable
SMOKE_HOME=$(mktemp -d)
HOME="$SMOKE_HOME" BEHEREAD_SMOKE_TEST=1 "$APP/Contents/MacOS/Beheread"
test -f "$SMOKE_HOME/Library/Application Support/Beheread/beheread.db"
rm -rf "$SMOKE_HOME"

echo "=== Image disque ==="
STAGING=build/dmg
rm -rf "$STAGING" "dist/$DMG"
mkdir -p "$STAGING"
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
hdiutil create -volname "Beheread $VERSION" -srcfolder "$STAGING" -ov -format UDZO "dist/$DMG"

echo "=== Somme de controle ==="
(cd dist && shasum -a 256 "$DMG" > SHA256SUMS-macos.txt)

echo "Fichiers a publier, dans dist/ :"
echo "  $DMG"
echo "  SHA256SUMS-macos.txt"
