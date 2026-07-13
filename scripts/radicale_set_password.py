"""Setzt/aktualisiert das Radicale-htpasswd-Passwort fuer einen Benutzer.

Aufruf: .venv/bin/python scripts/radicale_set_password.py <benutzername> <passwort>

Delegiert an sync.htpasswd.set_password (dieselbe Logik nutzt auch die
Einstellungen-Seite), damit es nur eine Quelle fuer das htpasswd-Format gibt.
"""
import sys
from pathlib import Path

# Beide moeglichen Layouts abdecken: im Dev-Repo liegt dieses Skript unter
# scripts/ (sync/ eine Ebene hoeher), im gepackten .app-Bundle flach in
# Contents/Resources/ (sync/ als Geschwisterordner). Beide Kandidaten in den
# Pfad legen, damit der Import in beiden Faellen aufloest.
_hier = Path(__file__).resolve().parent
sys.path.insert(0, str(_hier))
sys.path.insert(0, str(_hier.parent))

from sync import htpasswd  # noqa: E402


def main():
    if len(sys.argv) != 3:
        print("Aufruf: radicale_set_password.py <benutzername> <passwort>")
        sys.exit(1)
    benutzer, passwort = sys.argv[1], sys.argv[2]
    htpasswd.set_password(benutzer, passwort)
    print(f"Passwort fuer '{benutzer}' gesetzt in {htpasswd.htpasswd_pfad()}")


if __name__ == "__main__":
    main()
