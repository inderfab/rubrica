import threading
import time

from web import import_status


class _FakeConn:
    def close(self):
        pass


def test_starten_lehnt_zweiten_start_waehrend_laufendem_job_ab(monkeypatch):
    freigabe = threading.Event()

    def _blockierend(conn, fortschritt_callback=None):
        freigabe.wait(timeout=5)
        return {"gefunden": 0, "gruppen_gefunden": 0, "importiert": 0, "fehler": 0,
                "fehler_typen": {}, "ohne_uid": 0, "kontakte_gesamt": 0, "ordner_gesamt": 0}

    monkeypatch.setattr("web.shared.importiere_kontakte_app_und_synchronisiere", _blockierend)
    monkeypatch.setattr(import_status, "get_connection", lambda: _FakeConn())

    try:
        assert import_status.starten() is True
        # Job laeuft nun im Hintergrund-Thread - ein zweiter Start soll False liefern,
        # statt einen parallelen Import desselben Adressbuchs anzustossen.
        for _ in range(50):
            if import_status.status()["laeuft"]:
                break
            time.sleep(0.02)
        assert import_status.status()["laeuft"] is True
        assert import_status.starten() is False
    finally:
        freigabe.set()
        for _ in range(50):
            if not import_status.status()["laeuft"]:
                break
            time.sleep(0.02)


def test_ausfuehren_speichert_ergebnis_bei_erfolg(monkeypatch):
    monkeypatch.setattr("web.shared.importiere_kontakte_app_und_synchronisiere", lambda conn, fortschritt_callback=None: {
        "gefunden": 1, "gruppen_gefunden": 0, "importiert": 1, "fehler": 0,
        "fehler_typen": {}, "ohne_uid": 0, "kontakte_gesamt": 1, "ordner_gesamt": 0,
    })
    monkeypatch.setattr(import_status, "get_connection", lambda: _FakeConn())

    assert import_status.starten() is True
    for _ in range(50):
        if import_status.status()["fertig"]:
            break
        time.sleep(0.02)

    stand = import_status.status()
    assert stand["laeuft"] is False
    assert stand["fertig"] is True
    assert stand["ergebnis"]["importiert"] == 1
    assert stand["fehler_meldung"] is None


def test_ausfuehren_speichert_fehlermeldung_bei_ausnahme(monkeypatch):
    def _wirft(conn, fortschritt_callback=None):
        raise RuntimeError("Zugriff auf Kontakte verweigert")

    monkeypatch.setattr("web.shared.importiere_kontakte_app_und_synchronisiere", _wirft)
    monkeypatch.setattr(import_status, "get_connection", lambda: _FakeConn())

    assert import_status.starten() is True
    for _ in range(50):
        if import_status.status()["fertig"]:
            break
        time.sleep(0.02)

    stand = import_status.status()
    assert stand["fertig"] is True
    assert "Zugriff auf Kontakte verweigert" in stand["fehler_meldung"]
