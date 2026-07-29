from db import queries


def test_create_vorschlag_mit_message_id_und_dublettenschutz(tmp_db):
    vorschlag_id = queries.create_vorschlag(
        tmp_db, {"vorname": "Anna", "nachname": "Muster"}, quelle="mail", message_id="<abc@example.com>",
    )
    assert vorschlag_id

    assert queries.vorschlag_existiert_fuer_message_id(tmp_db, "<abc@example.com>") is True
    assert queries.vorschlag_existiert_fuer_message_id(tmp_db, "<anderer@example.com>") is False


def test_create_vorschlag_ohne_message_id_weiterhin_moeglich(tmp_db):
    # bestehende Aufrufer (Import, Archivio) uebergeben nie eine message_id.
    vorschlag_id = queries.create_vorschlag(tmp_db, {"vorname": "Bruno", "nachname": "Beispiel"}, quelle="import")
    assert vorschlag_id
    vorschlag = queries.get_vorschlag(tmp_db, vorschlag_id)
    assert vorschlag["message_id"] is None


def test_list_vorschlaege_filtert_nach_quelle(tmp_db):
    queries.create_vorschlag(tmp_db, {"vorname": "Anna", "nachname": "Muster"}, quelle="mail")
    queries.create_vorschlag(tmp_db, {"vorname": "Bruno", "nachname": "Beispiel"}, quelle="import")

    nur_mail = queries.list_vorschlaege(tmp_db, status="offen", quelle="mail")
    assert len(nur_mail) == 1
    assert nur_mail[0]["rohdaten"]["vorname"] == "Anna"

    alle = queries.list_vorschlaege(tmp_db, status="offen")
    assert len(alle) == 2


def test_quelle_mail_ist_in_der_datenbank_erlaubt(tmp_db):
    # Regression: CHECK-Constraint erlaubte frueher nur 'import'/'archivio'.
    vorschlag_id = queries.create_vorschlag(tmp_db, {"vorname": "Anna"}, quelle="mail")
    vorschlag = queries.get_vorschlag(tmp_db, vorschlag_id)
    assert vorschlag["quelle"] == "mail"
