"""Erinnert per E-Mail an Kontaktvorschlaege, die laenger als SCHWELLWERT_STUNDEN offen
sind - Nutzer-Meldung: Vorschlaege liegen teilweise lange unbemerkt herum. Jeder Vorschlag
wird GENAU EINMAL gemeldet (kein taeglicher Spam) - sobald er faellig ist und noch nicht
gemeldet wurde, kommt er in die naechste Sammel-Mail (queries.vorschlaege_faellig_fuer_
erinnerung); danach markiert (queries.markiere_erinnerung_gesendet), auch wenn er noch Tage
offen bleibt. Mehrere gleichzeitig faellige Vorschlaege landen in EINER Mail statt einzeln
(Nutzer-Vorgabe: kein Spam bei Schueben aus Kontakte.app).

Nur ausgehend (SMTP) - Gegenstueck zu mail_intake.py (nur eingehend, IMAP). Eigene, vom
Nutzer selbst einzugebende SMTP-Zugangsdaten (siehe /einstellungen) statt Wiederverwendung
der IMAP-Zugangsdaten aus mail_intake - Versand kann andere Authentifizierung brauchen als
Abruf, auch beim selben Postfach-Anbieter."""
from __future__ import annotations

import smtplib
from email.mime.text import MIMEText

from config import settings
from db import queries

# Ab wann ein offener Vorschlag als "liegt zu lange rum" gilt (Nutzer-Vorgabe: 24 Stunden,
# danach hoechstens einmal gemeldet - siehe queries.vorschlaege_faellig_fuer_erinnerung).
SCHWELLWERT_STUNDEN = 24


def konfiguriert() -> bool:
    return bool((settings.get("smtp.host", "") or "").strip()
                and (settings.get("smtp.empfaenger", "") or "").strip())


def _verbindung() -> smtplib.SMTP:
    host = (settings.get("smtp.host", "") or "").strip()
    port = int(settings.get("smtp.port", 587) or 587)
    username = settings.get("smtp.username", "") or ""
    passwort = settings.get("smtp.password", "") or ""
    # Port 465 = implizites TLS von Anfang an, alles andere (typisch 587) = erst
    # unverschluesselt verbinden, dann per STARTTLS umschalten - die beiden ueblichen
    # SMTP-Varianten, ein fester Port-465-Sonderfall genuegt dafuer.
    if port == 465:
        client = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        client = smtplib.SMTP(host, port, timeout=30)
        client.starttls()
    if username:
        client.login(username, passwort)
    return client


def _sende(betreff: str, text: str) -> None:
    absender = settings.get("smtp.username", "") or settings.get("smtp.empfaenger", "")
    empfaenger = settings.get("smtp.empfaenger", "") or ""
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = betreff
    msg["From"] = absender
    msg["To"] = empfaenger
    client = _verbindung()
    try:
        client.send_message(msg)
    finally:
        client.quit()


def _quelle_lesbar(quelle: str) -> str:
    return "Kontakte.app" if quelle == "kontakte_app" else "Mail"


def _anzeige_name(v: dict) -> str:
    d = v["rohdaten"]
    name = f"{d.get('vorname', '')} {d.get('nachname', '')}".strip()
    return name or d.get("firma") or "(ohne Namen)"


def _betreff(faellige: list[dict]) -> str:
    return f"Rubrica: {len(faellige)} offene Kontaktvorschläge warten"


def _text(faellige: list[dict]) -> str:
    zeilen = [
        f"- {_anzeige_name(v)} ({_quelle_lesbar(v['quelle'])}, seit {v['created_at']} offen)"
        for v in faellige
    ]
    return (
        f"{len(faellige)} Kontaktvorschläge sind seit über {SCHWELLWERT_STUNDEN} Stunden offen "
        "und warten auf eine Entscheidung:\n\n"
        + "\n".join(zeilen)
        + "\n\nIm Browser unter /vorschlaege ansehen, übernehmen oder ablehnen."
    )


def sende_erinnerung(conn) -> dict:
    """Sendet ggf. EINE Sammel-Mail fuer alle faelligen Vorschlaege und markiert sie
    danach als erinnert. Wird sowohl vom Hintergrund-Thread (web/main.py) als auch vom
    manuellen "Jetzt prüfen"-Knopf in den Einstellungen aufgerufen."""
    if not konfiguriert():
        return {"aktiv": False, "anzahl": 0}
    faellige = queries.vorschlaege_faellig_fuer_erinnerung(conn, SCHWELLWERT_STUNDEN)
    if not faellige:
        return {"aktiv": True, "anzahl": 0}
    _sende(_betreff(faellige), _text(faellige))
    queries.markiere_erinnerung_gesendet(conn, [v["id"] for v in faellige])
    return {"aktiv": True, "anzahl": len(faellige)}


def pruefe_und_beschreibe(conn) -> str:
    """Fuehrt sende_erinnerung() aus und baut daraus einen fertigen Anzeigetext -
    fuer den "Jetzt prüfen"-Knopf in den Einstellungen, analog zu
    mail_intake.pruefe_und_beschreibe."""
    try:
        ergebnis = sende_erinnerung(conn)
        if not ergebnis["aktiv"]:
            return "Erinnerungsmail nicht konfiguriert (SMTP-Server oder Empfänger fehlt)."
        if ergebnis["anzahl"] == 0:
            return "Keine seit über 24 Stunden offenen Vorschläge - keine Mail verschickt."
        return f"Erinnerungsmail mit {ergebnis['anzahl']} Vorschlägen verschickt."
    except Exception as exc:
        return f"Versand fehlgeschlagen: {type(exc).__name__}: {exc}"


def sende_testmail() -> str:
    """Verschickt sofort eine feste Testmail, unabhaengig von faelligen Vorschlaegen -
    prueft SMTP-Zugangsdaten UND dass die Mail beim konfigurierten Empfänger ankommt."""
    if not konfiguriert():
        return "Kein SMTP-Server konfiguriert (Host oder Empfänger fehlt)."
    try:
        _sende("Rubrica: Testmail", "Diese Testmail bestätigt, dass die Erinnerungsmail-Einstellungen funktionieren.")
        return "Testmail verschickt."
    except Exception as exc:
        return f"Versand fehlgeschlagen: {type(exc).__name__}: {exc}"
