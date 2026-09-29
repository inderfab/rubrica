"""Reihenfolge der Telefonnummern-Liste (siehe db/queries.py::_nach_typ_reihenfolge_sortiert).
Nutzer-Anlass: die Liste im Kontaktformular zeigte die Nummern in Eingabe-/
DB-Reihenfolge (z.B. zuerst die Zentrale, dann Privat Handy, dann erst Direkt) -
gewuenscht ist eine feste, "aufsteigende" Reihenfolge nach der in den Einstellungen
konfigurierten Kategorie-Liste (dieselbe Reihenfolge, die das Formular fuer neue
Zeilen vorschlaegt)."""
from db import queries


def test_telefonnummern_werden_nach_konfigurierter_typ_reihenfolge_sortiert(tmp_db):
    kid = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "telefonnummern": [
            {"typ": "Privat", "nummer": "+41 79 111 11 11"},
            {"typ": "Direkt Handy", "nummer": "+41 79 222 22 22"},
            {"typ": "Direkt", "nummer": "+41 52 333 33 33"},
            {"typ": "Privat Handy", "nummer": "+41 79 444 44 44"},
        ],
    })
    kontakt = queries.get_kontakt(tmp_db, kid)
    assert [t["typ"] for t in kontakt["telefonnummern"]] == [
        "Direkt", "Direkt Handy", "Privat", "Privat Handy",
    ]


def test_gleicher_typ_behaelt_eingabereihenfolge(tmp_db):
    kid = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "telefonnummern": [
            {"typ": "Direkt", "nummer": "+41 52 111 11 11"},
            {"typ": "Direkt", "nummer": "+41 52 222 22 22"},
        ],
    })
    kontakt = queries.get_kontakt(tmp_db, kid)
    assert [t["nummer"] for t in kontakt["telefonnummern"]] == [
        "+41 52 111 11 11", "+41 52 222 22 22",
    ]


def test_nicht_konfigurierter_typ_landet_am_ende(tmp_db):
    kid = queries.create_kontakt(tmp_db, {
        "vorname": "Anna", "nachname": "Muster",
        "telefonnummern": [
            {"typ": "Zentrale", "nummer": "+41 52 213 33 60"},
            {"typ": "Direkt", "nummer": "+41 52 214 20 24"},
        ],
    })
    kontakt = queries.get_kontakt(tmp_db, kid)
    assert [t["typ"] for t in kontakt["telefonnummern"]] == ["Direkt", "Zentrale"]
