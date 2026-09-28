"""Erinnert per E-Mail an Kontaktvorschlaege, die laenger als SCHWELLWERT_STUNDEN offen
sind - Nutzer-Meldung: Vorschlaege liegen teilweise lange unbemerkt herum. Jeder Vorschlag
wird GENAU EINMAL gemeldet (kein taeglicher Spam) - sobald er faellig ist und noch nicht
gemeldet wurde, kommt er in die naechste Sammel-Mail (queries.vorschlaege_faellig_fuer_
erinnerung); danach markiert (queries.markiere_erinnerung_gesendet), auch wenn er noch Tage
offen bleibt. Mehrere gleichzeitig faellige Vorschlaege landen in EINER Mail statt einzeln
(Nutzer-Vorgabe: kein Spam bei Schueben aus Kontakte.app).

Optionale ZWEITE Erinnerung an eine Ausweich-Adresse nach mehreren Tagen (Nutzer-Anlass:
"wenn Empfänger 1 in den Ferien ist") - eigener Schwellwert (smtp.eskalation_tage, vom Nutzer
in den Einstellungen gewaehlt: 3/7/14 Tage) und eigenes "schon gesendet"-Feld
(eskalation_gesendet_am), unabhaengig von der ersten Erinnerung.

Nur ausgehend (SMTP) - Gegenstueck zu mail_intake.py (nur eingehend, IMAP). Eigene, vom
Nutzer selbst einzugebende SMTP-Zugangsdaten (siehe /einstellungen) statt Wiederverwendung
der IMAP-Zugangsdaten aus mail_intake - Versand kann andere Authentifizierung brauchen als
Abruf, auch beim selben Postfach-Anbieter."""
from __future__ import annotations

import smtplib
from datetime import datetime
from email.mime.text import MIMEText

from config import settings
from db import queries

# Ab wann ein offener Vorschlag als "liegt zu lange rum" gilt (Nutzer-Vorgabe: 24 Stunden,
# danach hoechstens einmal gemeldet - siehe queries.vorschlaege_faellig_fuer_erinnerung).
SCHWELLWERT_STUNDEN = 24


def konfiguriert() -> bool:
    return bool((settings.get("smtp.host", "") or "").strip()
                and (settings.get("smtp.empfaenger", "") or "").strip())


def _eskalation_tage() -> int:
    try:
        return int(settings.get("smtp.eskalation_tage", 0) or 0)
    except (TypeError, ValueError):
        return 0


def eskalation_konfiguriert() -> bool:
    return bool((settings.get("smtp.empfaenger2", "") or "").strip() and _eskalation_tage() > 0)


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


def _sende(empfaenger: str, betreff: str, text: str) -> None:
    absender = settings.get("smtp.username", "") or settings.get("smtp.empfaenger", "")
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


def _lesbares_datum(iso: str) -> str:
    """"2026-09-25T14:04:35Z" -> "14:04 25.09.2026" (Nutzer-Vorgabe: die ISO-Rohform in der
    Mail war schwer lesbar). Faellt auf den Rohwert zurueck, falls das Format doch einmal
    abweicht - eine unlesbare Mail ist immer noch besser als eine, die gar nicht ankommt."""
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").strftime("%H:%M %d.%m.%Y")
    except ValueError:
        return iso


def _betreff(faellige: list[dict]) -> str:
    return f"Rubrica: {len(faellige)} offene Kontaktvorschläge warten"


def _text(faellige: list[dict], dauer_text: str) -> str:
    zeilen = [
        f"- {_anzeige_name(v)} ({_quelle_lesbar(v['quelle'])}, seit {_lesbares_datum(v['created_at'])} offen)"
        for v in faellige
    ]
    return (
        f"{len(faellige)} Kontaktvorschläge sind seit über {dauer_text} offen "
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
    _sende(settings.get("smtp.empfaenger", ""), _betreff(faellige), _text(faellige, "24 Stunden"))
    queries.markiere_erinnerung_gesendet(conn, [v["id"] for v in faellige])
    return {"aktiv": True, "anzahl": len(faellige)}


def sende_eskalation(conn) -> dict:
    """Wie sende_erinnerung, aber fuer die zweite, optionale Ausweich-Adresse nach dem in
    den Einstellungen gewaehlten Tage-Schwellwert (3/7/14). Unabhaengig von der ersten
    Erinnerung - ein Vorschlag kann die erste laengst bekommen haben und trotzdem separat
    fuer die zweite faellig sein."""
    if not eskalation_konfiguriert():
        return {"aktiv": False, "anzahl": 0}
    tage = _eskalation_tage()
    faellige = queries.vorschlaege_faellig_fuer_eskalation(conn, tage * 24)
    if not faellige:
        return {"aktiv": True, "anzahl": 0}
    _sende(settings.get("smtp.empfaenger2", ""), _betreff(faellige), _text(faellige, f"{tage} Tagen"))
    queries.markiere_eskalation_gesendet(conn, [v["id"] for v in faellige])
    return {"aktiv": True, "anzahl": len(faellige)}


def pruefe_und_beschreibe(conn) -> str:
    """Fuehrt sende_erinnerung() UND sende_eskalation() aus und baut daraus einen fertigen
    Anzeigetext - fuer den "Jetzt prüfen"-Knopf in den Einstellungen, analog zu
    mail_intake.pruefe_und_beschreibe."""
    try:
        ergebnis = sende_erinnerung(conn)
        if not ergebnis["aktiv"]:
            return "Erinnerungsmail nicht konfiguriert (SMTP-Server oder Empfänger fehlt)."
        if ergebnis["anzahl"] == 0:
            text = "Keine seit über 24 Stunden offenen Vorschläge - keine Mail verschickt."
        else:
            text = f"Erinnerungsmail mit {ergebnis['anzahl']} Vorschlägen verschickt."

        eskalation = sende_eskalation(conn)
        if eskalation["aktiv"] and eskalation["anzahl"] > 0:
            text += f" Zweite Erinnerung mit {eskalation['anzahl']} Vorschlägen an die zweite Adresse verschickt."
        return text
    except Exception as exc:
        return f"Versand fehlgeschlagen: {type(exc).__name__}: {exc}"


def sende_testmail() -> str:
    """Verschickt sofort eine feste Testmail, unabhaengig von faelligen Vorschlaegen -
    prueft SMTP-Zugangsdaten UND dass die Mail beim konfigurierten Empfänger ankommt."""
    if not konfiguriert():
        return "Kein SMTP-Server konfiguriert (Host oder Empfänger fehlt)."
    try:
        _sende(settings.get("smtp.empfaenger", ""), "Rubrica: Testmail",
               "Diese Testmail bestätigt, dass die Erinnerungsmail-Einstellungen funktionieren.")
        return "Testmail verschickt."
    except Exception as exc:
        return f"Versand fehlgeschlagen: {type(exc).__name__}: {exc}"
