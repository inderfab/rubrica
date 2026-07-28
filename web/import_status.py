"""Hintergrund-Status fuer den Kontakte.app-Import. Bei grossen Adressbuechern
(1000+ Kontakte) dauert der Import zehn Minuten und mehr - ein einzelner
synchroner Request liesse sich vom Nutzer nicht von einem haengengebliebenen
Request unterscheiden (genau das war das Feedback aus dem Praxistest). Laeuft
daher in einem Hintergrund-Thread, die Web-UI fragt den Stand per Polling ab.

Nur ein Import gleichzeitig - ausreichend, da dies eine manuelle, einmalige
Administrationsaktion ist (Setup-Assistent oder Import-Seite), kein Feature mit
gleichzeitiger Nutzung durch mehrere Personen. Ein einziger globaler Zustand im
Prozessspeicher genuegt dafuer, keine Datenbank-Tabelle noetig.
"""
from __future__ import annotations

import threading

from db.connection import get_connection

_lock = threading.Lock()
_status: dict = {
    "laeuft": False, "phase": "", "verarbeitet": 0, "gesamt": 0,
    "fertig": False, "ergebnis": None, "fehler_meldung": None,
}


def status() -> dict:
    with _lock:
        return dict(_status)


def starten() -> bool:
    """Startet den Import im Hintergrund. Gibt False zurueck, falls bereits einer
    laeuft (verhindert einen doppelten Start bei mehrfachem Klick/Tab)."""
    with _lock:
        if _status["laeuft"]:
            return False
        _status.update(laeuft=True, phase="lese", verarbeitet=0, gesamt=0,
                        fertig=False, ergebnis=None, fehler_meldung=None)
    threading.Thread(target=_ausfuehren, daemon=True).start()
    return True


def _fortschritt(phase: str, verarbeitet: int, gesamt: int) -> None:
    with _lock:
        _status.update(phase=phase, verarbeitet=verarbeitet, gesamt=gesamt)


def _ausfuehren() -> None:
    from web.shared import importiere_kontakte_app_und_synchronisiere
    conn = get_connection()
    try:
        ergebnis = importiere_kontakte_app_und_synchronisiere(conn, fortschritt_callback=_fortschritt)
        with _lock:
            _status.update(laeuft=False, fertig=True, ergebnis=ergebnis)
    except Exception as exc:
        with _lock:
            _status.update(laeuft=False, fertig=True, fehler_meldung=f"{type(exc).__name__}: {exc}")
    finally:
        conn.close()
