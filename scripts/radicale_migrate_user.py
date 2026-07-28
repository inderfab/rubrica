"""Migriert den Radicale-htpasswd-Eintrag von einem alten auf den neuen,
fest verdrahteten Benutzernamen (sync.radicale.RADICALE_BENUTZER).

Aufruf: .venv/bin/python scripts/radicale_migrate_user.py <alter_benutzer> <neuer_benutzer>

Uebernimmt das bestehende radicale.password aus config.yaml (Client-Seite bleibt
unveraendert), schreibt einen neuen htpasswd-Eintrag fuer <neuer_benutzer> und
entfernt den alten Eintrag - genutzt von scripts/migrate-radicale-user.sh.
"""
import sys
from pathlib import Path

# Beide moeglichen Layouts abdecken: im Dev-Repo liegt dieses Skript unter
# scripts/ (sync/config eine Ebene hoeher), im gepackten .app-Bundle flach in
# Contents/Resources/ (sync/config als Geschwisterordner).
_hier = Path(__file__).resolve().parent
sys.path.insert(0, str(_hier))
sys.path.insert(0, str(_hier.parent))

from config import settings  # noqa: E402
from sync import htpasswd  # noqa: E402


def main():
    if len(sys.argv) != 3:
        print("Aufruf: radicale_migrate_user.py <alter_benutzer> <neuer_benutzer>")
        sys.exit(1)
    alter_benutzer, neuer_benutzer = sys.argv[1], sys.argv[2]

    passwort = settings.get("radicale.password", "") or ""
    if not passwort:
        print("Kein radicale.password in config.yaml gefunden - Abbruch.")
        sys.exit(1)

    htpasswd.set_password(neuer_benutzer, passwort)
    htpasswd.remove_password(alter_benutzer)
    print(f"htpasswd migriert: '{alter_benutzer}' -> '{neuer_benutzer}' in {htpasswd.htpasswd_pfad()}")


if __name__ == "__main__":
    main()
