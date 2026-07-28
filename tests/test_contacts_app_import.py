import textwrap

from importer import contacts_app

VCARD_MIT_UID = textwrap.dedent("""\
    BEGIN:VCARD
    VERSION:3.0
    N:Muster;Anna;;;
    FN:Anna Muster
    TEL;TYPE=CELL:+41 79 123 45 67
    X-ABUID:anna-abuid
    END:VCARD
""")

VCARD_OHNE_UID = textwrap.dedent("""\
    BEGIN:VCARD
    VERSION:3.0
    N:Beispiel;Carla;;;
    FN:Carla Beispiel
    TEL;TYPE=CELL:+41 79 111 22 33
    END:VCARD
""")


def test_importiert_kontakte_und_gruppe_als_ordner(tmp_db, monkeypatch):
    monkeypatch.setattr(contacts_app, "_hole_daten",
                         lambda: ([VCARD_MIT_UID, VCARD_OHNE_UID], {"Projekt X": ["anna-abuid"]}))

    ergebnis = contacts_app.importiere_aus_kontakte_app(tmp_db)

    assert ergebnis["gefunden"] == 2
    assert ergebnis["gruppen_gefunden"] == 1
    assert ergebnis["importiert"] == 2
    assert ergebnis["fehler"] == 0
    assert ergebnis["ohne_uid"] == 1
    assert ergebnis["kontakte_gesamt"] == 2
    assert ergebnis["ordner_gesamt"] == 1
    assert len(ergebnis["kontakt_ids"]) == 2

    ordner = tmp_db.execute("SELECT name FROM projekte").fetchall()
    assert [o["name"] for o in ordner] == ["Projekt X"]


def test_leerer_bestand_liefert_nullen(tmp_db, monkeypatch):
    monkeypatch.setattr(contacts_app, "_hole_daten", lambda: ([], {}))

    ergebnis = contacts_app.importiere_aus_kontakte_app(tmp_db)

    assert ergebnis["gefunden"] == 0
    assert ergebnis["importiert"] == 0
    assert ergebnis["kontakte_gesamt"] == 0
