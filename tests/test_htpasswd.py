import bcrypt

from sync import htpasswd


def test_set_password_schreibt_bcrypt_hash(tmp_db):
    htpasswd.set_password("rubrica", "geheim")

    pfad = htpasswd.htpasswd_pfad()
    assert pfad.exists()
    inhalt = pfad.read_text(encoding="utf-8").strip()
    login, digest = inhalt.split(":", maxsplit=1)
    assert login == "rubrica"
    # Der geschriebene Hash muss das Klartext-Passwort verifizieren.
    assert bcrypt.checkpw(b"geheim", digest.encode("ascii"))


def test_set_password_ersetzt_bestehenden_eintrag_desselben_benutzers(tmp_db):
    htpasswd.set_password("rubrica", "altespasswort")
    htpasswd.set_password("rubrica", "neuespasswort")

    inhalt = htpasswd.htpasswd_pfad().read_text(encoding="utf-8").strip()
    zeilen = [z for z in inhalt.splitlines() if z]
    assert len(zeilen) == 1  # kein doppelter Eintrag
    _, digest = zeilen[0].split(":", maxsplit=1)
    assert bcrypt.checkpw(b"neuespasswort", digest.encode("ascii"))
    assert not bcrypt.checkpw(b"altespasswort", digest.encode("ascii"))


def test_set_password_erhaelt_andere_benutzer(tmp_db):
    htpasswd.set_password("rubrica", "geheim1")
    htpasswd.set_password("altbenutzer", "geheim2")

    inhalt = htpasswd.htpasswd_pfad().read_text(encoding="utf-8")
    assert "rubrica:" in inhalt
    assert "altbenutzer:" in inhalt


def test_set_password_ignoriert_leere_eingaben(tmp_db):
    htpasswd.set_password("", "irgendwas")
    htpasswd.set_password("rubrica", "")
    assert not htpasswd.htpasswd_pfad().exists()


def test_remove_password_entfernt_nur_diesen_benutzer(tmp_db):
    htpasswd.set_password("altbenutzer", "geheim1")
    htpasswd.set_password("rubrica", "geheim2")

    htpasswd.remove_password("altbenutzer")

    inhalt = htpasswd.htpasswd_pfad().read_text(encoding="utf-8")
    assert "altbenutzer:" not in inhalt
    assert "rubrica:" in inhalt


def test_remove_password_ohne_bestehende_datei_tut_nichts(tmp_db):
    htpasswd.remove_password("rubrica")
    assert not htpasswd.htpasswd_pfad().exists()
