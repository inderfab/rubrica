#!/usr/bin/env bash
# Baut Rubrica Server.app als macOS-Bundle und .pkg-Installer.
# Vereinfacht gegenueber Archivio: kein eingebettetes Python - die App baut sich
# beim ersten Start ein venv mit dem System-Python auf (RUBRICA_DATA_DIR/.venv),
# analog zu Archivios Fallback-Pfad. Ausreichend, da iMac und Mac Studio dieselbe
# Python-Version mitbringen (siehe CLAUDE.md).
# Aufruf: bash scripts/build-pkg.sh
set -e
cd "$(dirname "$0")/.."

DIST="dist"
APP_NAME="Rubrica Server"
APP="$DIST/$APP_NAME.app"
VERSION=$(cat VERSION)
PKG="$DIST/rubrica-server-${VERSION}.pkg"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# ── Ressourcen ins Bundle kopieren ───────────────────────────────────────────
for dir in web db config importer sync; do
  cp -r "$dir" "$APP/Contents/Resources/"
done
find "$APP/Contents/Resources" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
cp requirements.txt         "$APP/Contents/Resources/"
cp config.yaml.example      "$APP/Contents/Resources/"
cp VERSION                  "$APP/Contents/Resources/"
cp scripts/radicale_set_password.py "$APP/Contents/Resources/"

# ── Gemeinsame venv-Bootstrap-Logik (von beiden Launchern eingebunden) ──────
cat > "$APP/Contents/Resources/bootstrap_venv.sh" <<'BOOTSTRAP'
# Wird von den Launcher-Skripten eingebunden (source). Erwartet $DATA_DIR, $RESOURCES.
VENV="$DATA_DIR/.venv"
mkdir -p "$DATA_DIR/logs"

PYTHON=""
for p in \
  /Library/Frameworks/Python.framework/Versions/3.9/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  /usr/local/bin/python3 \
  /opt/homebrew/bin/python3 \
  /usr/bin/python3; do
  if [ -x "$p" ]; then PYTHON="$p"; break; fi
done
if [ -z "$PYTHON" ]; then
  osascript -e 'display alert "Rubrica" message "Python 3 wird benoetigt (python.org/downloads)." as critical'
  exit 1
fi

if [ ! -x "$VENV/bin/python3" ]; then
  # Server und Radicale laufen als zwei separate launchd-Dienste und starten beide
  # bei RunAtLoad gleichzeitig - ohne Sperre wuerden beide gleichzeitig versuchen,
  # dasselbe venv aufzubauen ("File exists"-Fehler). mkdir ist auf POSIX atomar,
  # daher als einfache Lockdatei nutzbar.
  LOCK_DIR="$DATA_DIR/.venv-setup.lock"
  while ! mkdir "$LOCK_DIR" 2>/dev/null; do
    sleep 1
    [ -x "$VENV/bin/python3" ] && break
  done
  if [ ! -x "$VENV/bin/python3" ]; then
    osascript -e 'display notification "Erstinstallation laeuft, bitte warten…" with title "Rubrica"' 2>/dev/null || true
    echo "$(date): Erstinstallation - venv wird erstellt mit $PYTHON"
    "$PYTHON" -m venv "$VENV"
    "$VENV/bin/pip" install --upgrade pip -q
    "$VENV/bin/pip" install --prefer-binary -r "$RESOURCES/requirements.txt" -q
    echo "$(date): Installation abgeschlossen"
  fi
  rmdir "$LOCK_DIR" 2>/dev/null || true
fi

if [ ! -f "$DATA_DIR/config.yaml" ]; then
  sed "s|__RUBRICA_USER__|$(whoami)|g" "$RESOURCES/config.yaml.example" > "$DATA_DIR/config.yaml"
fi
BOOTSTRAP

# ── Launcher: Web-Server ─────────────────────────────────────────────────────
cat > "$APP/Contents/MacOS/Rubrica Server" <<'LAUNCHER'
#!/usr/bin/env bash
BUNDLE="$(cd "$(dirname "$0")/.." && pwd)"
RESOURCES="$BUNDLE/Resources"
DATA_DIR="$HOME/Library/Application Support/Rubrica"
mkdir -p "$DATA_DIR/logs"
exec >> "$DATA_DIR/logs/server.log" 2>&1
echo "$(date): Rubrica Server v$(cat "$RESOURCES/VERSION" 2>/dev/null) starting"

source "$RESOURCES/bootstrap_venv.sh"

cd "$RESOURCES"
export RUBRICA_DATA_DIR="$DATA_DIR"
exec "$DATA_DIR/.venv/bin/uvicorn" web.main:app --host 0.0.0.0 --port 8000
LAUNCHER
chmod +x "$APP/Contents/MacOS/Rubrica Server"

# ── Launcher: Radicale (CardDAV) ─────────────────────────────────────────────
cat > "$APP/Contents/MacOS/Rubrica Radicale" <<'LAUNCHER'
#!/usr/bin/env bash
BUNDLE="$(cd "$(dirname "$0")/.." && pwd)"
RESOURCES="$BUNDLE/Resources"
DATA_DIR="$HOME/Library/Application Support/Rubrica"
mkdir -p "$DATA_DIR/logs"
exec >> "$DATA_DIR/logs/radicale.log" 2>&1
echo "$(date): Rubrica Radicale starting"

source "$RESOURCES/bootstrap_venv.sh"

HOSTNAME_LOCAL="$(scutil --get LocalHostName 2>/dev/null || hostname).local"
mkdir -p "$DATA_DIR/radicale"

TLS_DIR="$DATA_DIR/radicale-tls"
if [ ! -f "$TLS_DIR/cert.pem" ]; then
  mkdir -p "$TLS_DIR"
  /usr/bin/openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$TLS_DIR/key.pem" -out "$TLS_DIR/cert.pem" \
    -days 3650 -subj "/CN=$HOSTNAME_LOCAL" \
    -addext "subjectAltName=DNS:$HOSTNAME_LOCAL,DNS:localhost,IP:127.0.0.1" 2>/dev/null
  echo "$(date): Selbstsigniertes Zertifikat fuer $HOSTNAME_LOCAL erstellt"
fi

HTPASSWD_PATH="$DATA_DIR/radicale-htpasswd"
if [ ! -f "$HTPASSWD_PATH" ]; then
  GENERATED_PW=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)
  "$DATA_DIR/.venv/bin/python3" "$RESOURCES/radicale_set_password.py" "$(whoami)" "$GENERATED_PW"
  {
    echo "Rubrica CardDAV-Zugangsdaten (generiert $(date))"
    echo "Server:   $HOSTNAME_LOCAL"
    echo "Port:     8443"
    echo "Benutzer: $(whoami)"
    echo "Passwort: $GENERATED_PW"
    echo "Pfad:     /$(whoami)/kontakte/"
  } > "$DATA_DIR/RADICALE-ZUGANGSDATEN.txt"
  chmod 600 "$DATA_DIR/RADICALE-ZUGANGSDATEN.txt"
  osascript -e "display alert \"Rubrica CardDAV eingerichtet\" message \"Server: $HOSTNAME_LOCAL\nPort: 8443\nBenutzer: $(whoami)\nPasswort: $GENERATED_PW\nPfad: /$(whoami)/kontakte/\n\nAuch gespeichert in:\n$DATA_DIR/RADICALE-ZUGANGSDATEN.txt\"" 2>/dev/null || true
fi

CONFIG_PATH="$DATA_DIR/radicale.conf"
if [ ! -f "$CONFIG_PATH" ]; then
  sed "s|__RUBRICA_DATA_DIR__|$DATA_DIR|g" "$RESOURCES/config/radicale.conf.example" > "$CONFIG_PATH"
fi

exec "$DATA_DIR/.venv/bin/python3" -m radicale --config "$CONFIG_PATH"
LAUNCHER
chmod +x "$APP/Contents/MacOS/Rubrica Radicale"

# ── Info.plist ────────────────────────────────────────────────────────────────
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key>
  <string>ch.strut.rubrica.server</string>
  <key>CFBundleName</key>
  <string>Rubrica Server</string>
  <key>CFBundleExecutable</key>
  <string>Rubrica Server</string>
  <key>CFBundleVersion</key>
  <string>${VERSION}</string>
  <key>CFBundleShortVersionString</key>
  <string>${VERSION}</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>LSUIElement</key>
  <true/>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST
echo -n "APPL????" > "$APP/Contents/PkgInfo"

echo "✓ $APP gebaut"

# ── PKG-Installer ─────────────────────────────────────────────────────────────
if ! command -v pkgbuild &>/dev/null; then
  echo "⚠️  pkgbuild nicht gefunden - PKG wird uebersprungen"
  exit 0
fi

PKG_ROOT=$(mktemp -d)
PKG_SCRIPTS=$(mktemp -d)
mkdir -p "$PKG_ROOT/Applications"
cp -r "$APP" "$PKG_ROOT/Applications/"

# Wichtig: den Build-Ordner NICHT als "Rubrica Server.app" im Projektordner stehen
# lassen. macOS' PackageKit erkennt Bundles mit gleicher CFBundleIdentifier ueber
# Launch Services/Spotlight und leitet die Installation dorthin um ("relocation"),
# statt nach /Applications zu kopieren, wenn hier noch eine Kopie liegt. Deshalb
# wird die Launch-Services-Registrierung des Build-Pfads explizit aufgehoben,
# bevor er geloescht wird.
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
[ -x "$LSREGISTER" ] && "$LSREGISTER" -u "$APP" 2>/dev/null || true
rm -rf "$APP"

cat > "$PKG_SCRIPTS/postinstall" <<'POSTINSTALL'
#!/bin/bash
CURRENT_USER=$(stat -f "%Su" /dev/console 2>/dev/null || echo "")
[ -z "$CURRENT_USER" ] || [ "$CURRENT_USER" = "root" ] && exit 0

xattr -cr "/Applications/Rubrica Server.app" 2>/dev/null || true

USER_UID=$(id -u "$CURRENT_USER")
LA_DIR="/Users/$CURRENT_USER/Library/LaunchAgents"
sudo -u "$CURRENT_USER" mkdir -p "$LA_DIR"

_install_agent() {
  local LABEL="$1"
  local EXECUTABLE="$2"
  local PLIST="$LA_DIR/$LABEL.plist"
  cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$EXECUTABLE</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>30</integer>
  <key>ProcessType</key>
  <string>Interactive</string>
</dict>
</plist>
PLISTEOF
  chown "$CURRENT_USER" "$PLIST"
  sudo -u "$CURRENT_USER" launchctl bootout "gui/$USER_UID/$LABEL" 2>/dev/null || true
  if ! sudo -u "$CURRENT_USER" launchctl bootstrap "gui/$USER_UID" "$PLIST" 2>/dev/null; then
    sudo -u "$CURRENT_USER" launchctl load "$PLIST" 2>/dev/null || true
  fi
}

_install_agent "ch.strut.rubrica.server" "/Applications/Rubrica Server.app/Contents/MacOS/Rubrica Server"
_install_agent "ch.strut.rubrica.radicale" "/Applications/Rubrica Server.app/Contents/MacOS/Rubrica Radicale"

exit 0
POSTINSTALL
chmod +x "$PKG_SCRIPTS/postinstall"

pkgbuild \
  --root "$PKG_ROOT" \
  --scripts "$PKG_SCRIPTS" \
  --identifier "ch.strut.rubrica.server" \
  --version "$VERSION" \
  --install-location "/" \
  "$PKG"

rm -rf "$PKG_ROOT" "$PKG_SCRIPTS"
echo "✓ $PKG erstellt"
