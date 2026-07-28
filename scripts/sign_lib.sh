#!/usr/bin/env bash
# Gemeinsame Signier-/Notarisierungs-Funktionen fuer scripts/build-pkg.sh. Eng
# an /Users/dev/archivio/scripts/sign_lib.sh angelehnt (dort bereits produktiv
# erprobt) - siehe docs/CHANGELOG-INTERN.md Kapitel 1 fuer die Historie zweier
# dort bereits geloester Fehlerklassen, die hier von Anfang an vermieden werden:
#
#   1. Eingebettete Python-Umgebungen MUESSEN unter Contents/Resources liegen,
#      NICHT unter Contents/Frameworks - codesign behandelt jedes Verzeichnis
#      direkt unter Contents/Frameworks als vermeintliches Nested-Framework-
#      Bundle und lehnt es ohne gueltige Framework-Struktur (Versions/, eigenes
#      Info.plist) mit "bundle format unrecognized" ab, was die Signierung des
#      GESAMTEN Bundles verhindert.
#   2. sign_inner() MUSS --entitlements auf die inneren Mach-O-Binaries anwenden,
#      nicht nur sign_bundle() auf das aeussere Bundle - Entitlements gelten pro
#      Mach-O-Datei, nicht vererbt ueber exec() hinweg. Der gepackte Launcher
#      execi't direkt in den eingebetteten python3; fehlen dort die Entitlements
#      (disable-library-validation etc.), toetet der Kernel den Prozess unter
#      Hardened Runtime lautlos beim ersten Versuch, ausfuehrbaren Speicher zu
#      allozieren (bcrypt/cryptography bringen kompilierte Erweiterungen mit).
#
# Umgebungsvariablen (alle optional - ohne sie wird ad-hoc signiert/gar nicht
# notarisiert, mit deutlicher Warnung; lokale Entwicklung bleibt so unveraendert
# moeglich):
#   RUBRICA_SIGN_APP        z.B. "Developer ID Application: Firma GmbH (TEAMID)"
#   RUBRICA_SIGN_INSTALLER  z.B. "Developer ID Installer: Firma GmbH (TEAMID)"
#   RUBRICA_NOTARY_PROFILE  Name des per `xcrun notarytool store-credentials`
#                           gespeicherten Keychain-Profils, z.B. "rubrica-notary"

_RUBRICA_ADHOC_WARNUNG_GEZEIGT=""
_warn_adhoc_once() {
  if [ -z "$_RUBRICA_ADHOC_WARNUNG_GEZEIGT" ]; then
    echo "⚠️  RUBRICA_SIGN_APP nicht gesetzt - signiere nur ad-hoc (Gatekeeper-Warnung beim Installieren auf fremden Macs)"
    _RUBRICA_ADHOC_WARNUNG_GEZEIGT=1
  fi
}

sign_inner() {   # $1 = Verzeichnis (z.B. das Bundle selbst oder ein eingebetteter Python-Baum)
  local ROOT="$1"
  [ -d "$ROOT" ] || return 0
  if [ -n "$RUBRICA_SIGN_APP" ]; then
    find "$ROOT" \( -name "*.so" -o -name "*.dylib" -o -perm +111 \) -type f -print0 \
      | while IFS= read -r -d '' f; do
          file "$f" | grep -q 'Mach-O' || continue
          codesign --force --timestamp --options runtime \
                   --entitlements config/entitlements.plist \
                   --sign "$RUBRICA_SIGN_APP" "$f" 2>/dev/null || true
        done
  else
    _warn_adhoc_once
    find "$ROOT" \( -name "*.so" -o -name "*.dylib" \) -type f | while read -r f; do
      codesign -s - --force "$f" 2>/dev/null || true
    done
    find "$ROOT/bin" -type f 2>/dev/null | while read -r f; do
      codesign -s - --force "$f" 2>/dev/null || true
    done
  fi
}

sign_bundle() {  # $1 = .app-Pfad
  local APP_PATH="$1"
  sign_inner "$APP_PATH"
  if [ -n "$RUBRICA_SIGN_APP" ]; then
    codesign --force --timestamp --options runtime \
             --entitlements config/entitlements.plist \
             --sign "$RUBRICA_SIGN_APP" "$APP_PATH"
    codesign --verify --deep --strict --verbose=2 "$APP_PATH"
    echo "  ✓ signiert: $APP_PATH"
  else
    _warn_adhoc_once
    codesign -s - --force "$APP_PATH" 2>/dev/null || true
  fi
}

notarize_and_staple() {   # $1 = .app- oder .pkg-Pfad
  local TARGET="$1"
  if [ -z "$RUBRICA_NOTARY_PROFILE" ]; then
    echo "⚠️  RUBRICA_NOTARY_PROFILE nicht gesetzt — überspringe Notarisierung für $TARGET"
    return 0
  fi
  if [ -z "$RUBRICA_SIGN_APP" ]; then
    echo "⚠️  Notarisierung übersprungen — $TARGET ist nicht signiert (RUBRICA_SIGN_APP fehlt)"
    return 0
  fi

  echo "→ Notarisiere $TARGET (kann mehrere Minuten dauern)…"
  local SUBMIT_PATH="$TARGET"
  local TMP_ZIP=""
  case "$TARGET" in
    *.app)
      TMP_ZIP=$(mktemp -t rubrica-notarize).zip
      ditto -c -k --keepParent "$TARGET" "$TMP_ZIP"
      SUBMIT_PATH="$TMP_ZIP"
      ;;
  esac

  xcrun notarytool submit "$SUBMIT_PATH" --keychain-profile "$RUBRICA_NOTARY_PROFILE" --wait

  [ -n "$TMP_ZIP" ] && rm -f "$TMP_ZIP"

  xcrun stapler staple "$TARGET"
  echo "  ✓ notarisiert + gestapelt: $TARGET"
}
