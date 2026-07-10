"""Setzt/aktualisiert das Radicale-htpasswd-Passwort fuer einen Benutzer.

Aufruf: .venv/bin/python scripts/radicale_set_password.py <benutzername> <passwort>
"""
import os
import sys
from pathlib import Path

import bcrypt

DATA_DIR = Path(os.environ.get("RUBRICA_DATA_DIR", Path.home() / "Library/Application Support/Rubrica"))
HTPASSWD_PATH = DATA_DIR / "radicale-htpasswd"


def main():
    if len(sys.argv) != 3:
        print("Aufruf: radicale_set_password.py <benutzername> <passwort>")
        sys.exit(1)
    benutzer, passwort = sys.argv[1], sys.argv[2]

    hash_ = bcrypt.hashpw(passwort.encode("utf-8"), bcrypt.gensalt()).decode("ascii")

    zeilen = []
    if HTPASSWD_PATH.exists():
        zeilen = [z for z in HTPASSWD_PATH.read_text().splitlines() if z and not z.startswith(f"{benutzer}:")]
    zeilen.append(f"{benutzer}:{hash_}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HTPASSWD_PATH.write_text("\n".join(zeilen) + "\n")
    HTPASSWD_PATH.chmod(0o600)
    print(f"Passwort fuer '{benutzer}' gesetzt in {HTPASSWD_PATH}")


if __name__ == "__main__":
    main()
