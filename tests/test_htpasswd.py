import bcrypt

from sync import htpasswd


def test_set_password_schreibt_bcrypt_hash(tmp_db):
    htpasswd.set_password("pas", "strut")

    pfad = htpasswd.htpasswd_pfad()
    assert pfad.exists()
    inhalt = pfad.read_text(encoding="utf-8").strip()
    login, digest = inhalt.split(":", maxsplit=1)
    assert login == "pas"
    # Der geschriebene Hash muss das Klartext-Passwort verifizieren.
    assert bcrypt.checkpw(b"strut", digest.encode("ascii"))


def test_set_password_ersetzt_bestehenden_eintrag_desselben_benutzers(tmp_db):
    htpasswd.set_password("pas", "altespasswort")
    htpasswd.set_password("pas", "neuespasswort")

    inhalt = htpasswd.htpasswd_pfad().read_text(encoding="utf-8").strip()
    zeilen = [z for z in inhalt.splitlines() if z]
    assert len(zeilen) == 1  # kein doppelter pas-Eintrag
    _, digest = zeilen[0].split(":", maxsplit=1)
    assert bcrypt.checkpw(b"neuespasswort", digest.encode("ascii"))
    assert not bcrypt.checkpw(b"altespasswort", digest.encode("ascii"))


def test_set_password_erhaelt_andere_benutzer(tmp_db):
    htpasswd.set_password("pas", "geheim1")
    htpasswd.set_password("fi", "geheim2")

    inhalt = htpasswd.htpasswd_pfad().read_text(encoding="utf-8")
    assert "pas:" in inhalt
    assert "fi:" in inhalt


def test_set_password_ignoriert_leere_eingaben(tmp_db):
    htpasswd.set_password("", "irgendwas")
    htpasswd.set_password("pas", "")
    assert not htpasswd.htpasswd_pfad().exists()
