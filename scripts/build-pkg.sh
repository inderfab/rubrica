#!/usr/bin/env bash
# Baut Rubrica Server.app als macOS-Bundle und .pkg-Installer.
# Eingebettetes Python (universal: arm64 + x86_64), analog zu Archivios
# scripts/build_server_app.sh - vermeidet Versions-/Abhaengigkeitsprobleme mit
# dem jeweiligen System-Python auf iMac/Mac Studio. Fallback auf System-Python +
# venv (siehe bootstrap_venv.sh) bleibt fuer den Fall, dass fuer die jeweilige
# Architektur kein eingebettetes Python mitgeliefert wurde.
# Aufruf: bash scripts/build-pkg.sh
set -e
cd "$(dirname "$0")/.."

DIST="dist"
APP_NAME="Rubrica Server"
APP="$DIST/$APP_NAME.app"
VERSION=$(cat VERSION)
PKG="$DIST/rubrica-server-${VERSION}.pkg"

mkdir -p "$DIST"
rm -rf "$APP"

# ── Eingebettetes Python (universal: arm64 + x86_64) ─────────────────────────
# Zum Updaten: nur diese Zeile anpassen (Major.Minor), neu builden - fertig.
PYTHON_VERSION="3.13"

REQ_HASH=$(md5 -q requirements.txt)

_build_python() {
    local PBS_ARCH="$1"   # z.B. aarch64-apple-darwin
    local ARCH_TAG="$2"   # z.B. arm64 oder x86_64

    local PY_BASE="$DIST/.python-base-$ARCH_TAG"
    local PY_INSTALLED="$DIST/.python-installed-$ARCH_TAG"
    local STAMP="$DIST/.python-stamp-$ARCH_TAG"
    local EXPECTED="$PYTHON_VERSION:$PBS_ARCH:$REQ_HASH"

    if [ "$(cat "$STAMP" 2>/dev/null)" = "$EXPECTED" ] && [ -x "$PY_INSTALLED/bin/python3" ]; then
        echo "  $ARCH_TAG: Cache gültig"
        return
    fi

    if [ "$(cat "$PY_BASE/.version" 2>/dev/null)" != "$PYTHON_VERSION:$PBS_ARCH" ]; then
        echo "  $ARCH_TAG: Python herunterladen ($PBS_ARCH)…"
        rm -rf "$PY_BASE"
        mkdir -p "$PY_BASE"

        local URL
        URL=$(curl -sLf "https://api.github.com/repos/indygreg/python-build-standalone/releases/latest" \
            | python3 -c "
import sys, json
rel = json.load(sys.stdin)
arch = '$PBS_ARCH'
py  = '$PYTHON_VERSION'
for a in rel['assets']:
    u = a['browser_download_url']
    if (f'cpython-{py}.' in u and arch in u
            and 'install_only_stripped' in u
            and 'freethreaded' not in u
            and u.endswith('.tar.gz')):
        print(u); break
" 2>/dev/null || echo "")

        if [ -z "$URL" ]; then
            echo "  ⚠  $ARCH_TAG: python-build-standalone nicht gefunden"
            return
        fi
        curl -L --progress-bar "$URL" | tar -xz -C "$PY_BASE" --strip-components=1
        echo "$PYTHON_VERSION:$PBS_ARCH" > "$PY_BASE/.version"
    else
        echo "  $ARCH_TAG: Python bereits im Cache"
    fi

    echo "  $ARCH_TAG: Pakete installieren…"
    rm -rf "$PY_INSTALLED"
    cp -r "$PY_BASE" "$PY_INSTALLED"

    local PIP_CMD="$PY_INSTALLED/bin/python3"
    if [ "$ARCH_TAG" = "x86_64" ] && [ "$(uname -m)" = "arm64" ]; then
        PIP_CMD="arch -x86_64 $PY_INSTALLED/bin/python3"
    fi

    $PIP_CMD -m pip install --prefer-binary -q --no-warn-script-location -r requirements.txt

    echo "$EXPECTED" > "$STAMP"
    echo "  $ARCH_TAG: Pakete installiert"
}

echo "→ Python-Umgebungen vorbereiten…"
_build_python "aarch64-apple-darwin" "arm64"
_build_python "x86_64-apple-darwin"  "x86_64"

# ── Bundle-Struktur ───────────────────────────────────────────────────────────
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$APP/Contents/Frameworks"

for dir in web db config importer sync export archivio_bridge; do
  cp -r "$dir" "$APP/Contents/Resources/"
done
find "$APP/Contents/Resources" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
cp requirements.txt         "$APP/Contents/Resources/"
cp config.yaml.example      "$APP/Contents/Resources/"
cp VERSION                  "$APP/Contents/Resources/"
cp scripts/radicale_set_password.py "$APP/Contents/Resources/"
cp scripts/generate-cert.sh         "$APP/Contents/Resources/"

# ── Python-Umgebungen ins Bundle kopieren und bereinigen ─────────────────────
_install_python_to_bundle() {
    local ARCH_TAG="$1"
    local SRC="$DIST/.python-installed-$ARCH_TAG"
    local DST="$APP/Contents/Frameworks/rubrica-python-$ARCH_TAG"

    if [ ! -x "$SRC/bin/python3" ]; then
        echo "  ⚠  $ARCH_TAG: kein Python — wird übersprungen"
        return
    fi

    echo "  $ARCH_TAG: kopieren…"
    cp -r "$SRC" "$DST"

    find "$DST" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    find "$DST" -name "*.pyc"  -delete 2>/dev/null || true
    find "$DST" -name "*.dSYM" -type d -exec rm -rf {} + 2>/dev/null || true
    find "$DST" -name "*.pyi"  -delete 2>/dev/null || true

    echo "  $ARCH_TAG: $(du -sh "$DST" | cut -f1)"
}

echo "→ Python-Umgebungen ins Bundle kopieren…"
_install_python_to_bundle "arm64"
_install_python_to_bundle "x86_64"

# ── Ad-hoc Code-Signierung ────────────────────────────────────────────────────
# Erforderlich, damit macOS Gatekeeper die nativen Bibliotheken (.so, .dylib,
# u.a. bcrypt) zulaesst.
if command -v codesign &>/dev/null; then
    echo "→ Ad-hoc Code-Signierung…"
    for ARCH_TAG in arm64 x86_64; do
        PF="$APP/Contents/Frameworks/rubrica-python-$ARCH_TAG"
        [ -d "$PF" ] || continue
        find "$PF" \( -name "*.so" -o -name "*.dylib" \) -type f \
            | while read -r f; do codesign -s - --force "$f" 2>/dev/null || true; done
        find "$PF/bin" -type f \
            | while read -r f; do codesign -s - --force "$f" 2>/dev/null || true; done
    done
    echo "  Signierung abgeschlossen (nur Binaries, nicht Bundle)"
fi

# ── Gemeinsame venv-Bootstrap-Logik (Fallback, falls kein eingebettetes Python
#    fuer die jeweilige Architektur mitgeliefert wurde) ──────────────────────
cat > "$APP/Contents/Resources/bootstrap_venv.sh" <<'BOOTSTRAP'
# Wird von den Launcher-Skripten eingebunden (source), NUR falls kein
# eingebettetes Python fuer die aktuelle Architektur vorhanden ist.
# Erwartet $DATA_DIR, $RESOURCES.
VENV="$DATA_DIR/.venv"
mkdir -p "$DATA_DIR/logs"

PYTHON=""
for p in \
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/3.9/bin/python3 \
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
    echo "$(date): Erstinstallation (Fallback, kein eingebettetes Python) - venv wird erstellt mit $PYTHON"
    "$PYTHON" -m venv "$VENV"
    "$VENV/bin/pip" install --upgrade pip -q
    "$VENV/bin/pip" install --prefer-binary -r "$RESOURCES/requirements.txt" -q
    echo "$(date): Installation abgeschlossen"
  fi
  rmdir "$LOCK_DIR" 2>/dev/null || true
fi
RUBRICA_PYTHON="$VENV/bin/python3"

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

# ── 1. Eingebettetes Python (immer bevorzugt) ────────────────────────────────
ARCH=$(uname -m)
EMBEDDED_PY="$BUNDLE/Frameworks/rubrica-python-$ARCH/bin/python3"
if [ -x "$EMBEDDED_PY" ]; then
  echo "$(date): Eingebettetes Python ($ARCH): $("$EMBEDDED_PY" --version 2>&1)"
  RUBRICA_PYTHON="$EMBEDDED_PY"
  if [ ! -f "$DATA_DIR/config.yaml" ]; then
    sed "s|__RUBRICA_USER__|$(whoami)|g" "$RESOURCES/config.yaml.example" > "$DATA_DIR/config.yaml"
  fi
else
  # ── 2. Fallback: System-Python + venv ──────────────────────────────────────
  echo "$(date): Kein eingebettetes Python für $ARCH — Fallback auf System-Python/venv"
  source "$RESOURCES/bootstrap_venv.sh"
fi

cd "$RESOURCES"
export RUBRICA_DATA_DIR="$DATA_DIR"
exec "$RUBRICA_PYTHON" -m uvicorn web.main:app --host 0.0.0.0 --port 8001
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

# ── 1. Eingebettetes Python (immer bevorzugt) ────────────────────────────────
ARCH=$(uname -m)
EMBEDDED_PY="$BUNDLE/Frameworks/rubrica-python-$ARCH/bin/python3"
if [ -x "$EMBEDDED_PY" ]; then
  echo "$(date): Eingebettetes Python ($ARCH): $("$EMBEDDED_PY" --version 2>&1)"
  RUBRICA_PYTHON="$EMBEDDED_PY"
else
  echo "$(date): Kein eingebettetes Python für $ARCH — Fallback auf System-Python/venv"
  source "$RESOURCES/bootstrap_venv.sh"
fi

HOSTNAME_LOCAL="$(scutil --get LocalHostName 2>/dev/null || hostname).local"
mkdir -p "$DATA_DIR/radicale"

TLS_DIR="$DATA_DIR/radicale-tls"
if [ ! -f "$TLS_DIR/cert.pem" ]; then
  # Erzeugt eine lokale CA + Apple-konformes Leaf-Zertifikat. Normalerweise hat
  # das bereits das Postinstall-Skript erledigt (inkl. CA-Vertrauensstellung);
  # dies ist der Fallback fuer einen manuellen App-Start ohne .pkg-Installation.
  /bin/bash "$RESOURCES/generate-cert.sh" "$TLS_DIR" "$HOSTNAME_LOCAL"
  echo "$(date): TLS-Zertifikat fuer $HOSTNAME_LOCAL erstellt (CA ggf. noch als vertrauenswuerdig zu markieren)"
fi

HTPASSWD_PATH="$DATA_DIR/radicale-htpasswd"
if [ ! -f "$HTPASSWD_PATH" ]; then
  GENERATED_PW=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)
  "$RUBRICA_PYTHON" "$RESOURCES/radicale_set_password.py" "$(whoami)" "$GENERATED_PW"
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

exec "$RUBRICA_PYTHON" -m radicale --config "$CONFIG_PATH"
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

echo "✓ $APP gebaut ($(du -sh "$APP" | cut -f1))"

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

# ── TLS-Zertifikat erzeugen und lokale CA systemweit vertrauen ────────────────
# Muss VOR dem Start der launchd-Dienste geschehen, damit Radicale das fertige
# Zertifikat vorfindet. Erzeugung laeuft als Nutzer (Dateien gehoeren dann dem
# Nutzer, Radicale kann key.pem lesen); die CA-Vertrauensstellung laeuft als root
# und braucht daher keinen interaktiven Dialog. Ohne diesen Schritt lehnt der
# Kontakte-Sync-Daemon von macOS die Verbindung still ab (siehe docs/konzept.md 9).
APP_RES="/Applications/Rubrica Server.app/Contents/Resources"
DATA_DIR="/Users/$CURRENT_USER/Library/Application Support/Rubrica"
TLS_DIR="$DATA_DIR/radicale-tls"
HOSTNAME_LOCAL="$(sudo -u "$CURRENT_USER" scutil --get LocalHostName 2>/dev/null || hostname).local"
if [ ! -f "$TLS_DIR/cert.pem" ]; then
  sudo -u "$CURRENT_USER" mkdir -p "$TLS_DIR"
  sudo -u "$CURRENT_USER" /bin/bash "$APP_RES/generate-cert.sh" "$TLS_DIR" "$HOSTNAME_LOCAL"
fi
if [ -f "$TLS_DIR/ca-cert.pem" ]; then
  security add-trusted-cert -d -r trustRoot -p ssl \
    -k /Library/Keychains/System.keychain "$TLS_DIR/ca-cert.pem" 2>/dev/null || true
fi

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
echo "✓ $PKG erstellt ($(du -sh "$PKG" | cut -f1))"
