"""Liest Kontaktvorschlaege aus einem dedizierten IMAP-Postfach (z.B. rubrica@
firma.ch) - so koennen Mitarbeitende von unterwegs eine vCard teilen (Kontakte.app
"Kontakt senden") oder schlicht Name + Telefonnummer/Mailadresse als Text an diese
Adresse schicken. Nie automatisch uebernommen: jede gefundene Nachricht erzeugt
einen offenen Eintrag in vorschlaege, der erst im Buero manuell bestaetigt wird
(siehe web/mail_vorschlaege.py) - ein von aussen erreichbares Postfach ist ein
weniger vertrauenswuerdiger Kanal als Import/Archivio, die vom Buero-Rechner selbst
ausgehen.

Nur lesend gegenueber dem Postfach: IMAP SELECT readonly + FETCH BODY.PEEK, kein
STORE/EXPUNGE/DELETE - angelehnt an /Users/dev/archivio/scanner/mail_scanner.py.
Dubletten (bereits verarbeitete Mails) werden ueber die Message-ID erkannt statt
ueber IMAP-Flags, damit ein Postfach-Wechsel/erneutes Verbinden nie zu Duplikaten
fuehrt.
"""
from __future__ import annotations

import email
import imaplib
from email.message import Message

from config import settings
from db import queries
from importer.signatur import parse_signatur
from importer.vcard import finde_match, parse_vcf


def konfiguriert() -> bool:
    return bool((settings.get("mail.host", "") or "").strip())


def _client() -> "imaplib.IMAP4_SSL | None":
    host = (settings.get("mail.host", "") or "").strip()
    if not host:
        return None
    port = int(settings.get("mail.port", 993) or 993)
    username = settings.get("mail.username", "") or ""
    passwort = settings.get("mail.password", "") or ""
    client = imaplib.IMAP4_SSL(host, port)
    client.socket().settimeout(30)  # haengende IMAP-Operationen nach 30s abbrechen
    client.login(username, passwort)
    return client


def _vcard_anhaenge(msg: Message) -> list[str]:
    anhaenge = []
    for part in msg.walk():
        content_type = (part.get_content_type() or "").lower()
        dateiname = (part.get_filename() or "").lower()
        if content_type in ("text/vcard", "text/x-vcard") or dateiname.endswith(".vcf"):
            payload = part.get_payload(decode=True)
            if payload:
                anhaenge.append(payload.decode("utf-8", errors="replace"))
    return anhaenge


def _text_koerper(msg: Message) -> str:
    if not msg.is_multipart():
        payload = msg.get_payload(decode=True)
        return payload.decode(msg.get_content_charset() or "utf-8", errors="replace") if payload else ""
    for part in msg.walk():
        if part.get_content_type() == "text/plain" and not part.get_filename():
            payload = part.get_payload(decode=True)
            if payload:
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    return ""


def _kandidaten_aus_nachricht(msg: Message) -> list[dict]:
    """vCard-Anhang hat Vorrang vor dem Mailtext - enthaelt eine Mail beides
    (z.B. eine Signatur unter einem geteilten Kontakt), zaehlt nur die vCard,
    um denselben Kontakt nicht doppelt vorzuschlagen."""
    vcards = _vcard_anhaenge(msg)
    if vcards:
        kandidaten = []
        for vc in vcards:
            kandidaten.extend(parse_vcf(vc))
        return kandidaten
    text = _text_koerper(msg)
    if not text.strip():
        return []
    kontakt = parse_signatur(text)
    if kontakt.get("vorname") or kontakt.get("nachname") or kontakt.get("emails"):
        return [kontakt]
    return []


def pruefe_mail_eingang(conn) -> dict:
    """Verbindet, liest alle Nachrichten im Posteingang (readonly), ueberspringt
    bereits verarbeitete (Message-ID schon in vorschlaege) und legt fuer neue
    Nachrichten je einen offenen Vorschlag an. Wirft bei Verbindungsfehlern
    (falsche Zugangsdaten, Netzwerk) die zugrundeliegende Exception weiter."""
    client = _client()
    if client is None:
        return {"aktiv": False, "gefunden": 0, "neu": 0, "fehler": 0}

    gefunden = neu = fehler = 0
    try:
        client.select("INBOX", readonly=True)
        status, daten = client.search(None, "ALL")
        uids = daten[0].split() if status == "OK" and daten and daten[0] else []

        for uid in uids:
            gefunden += 1
            try:
                status, msg_daten = client.fetch(uid, "(BODY.PEEK[])")
                roh = msg_daten[0][1]
                msg = email.message_from_bytes(roh)
                message_id = (msg.get("Message-ID") or "").strip()
                if message_id and queries.vorschlag_existiert_fuer_message_id(conn, message_id):
                    continue

                kandidaten = _kandidaten_aus_nachricht(msg)
                for kontakt in kandidaten:
                    kontakt.pop("gruppen", None)  # Apple-Gruppen sind hier nicht relevant
                    match_id = finde_match(conn, kontakt)
                    queries.create_vorschlag(conn, kontakt, kontakt_id=match_id,
                                              quelle="mail", message_id=message_id or None)
                    neu += 1
            except Exception:
                fehler += 1
    finally:
        try:
            client.logout()
        except Exception:
            pass

    return {"aktiv": True, "gefunden": gefunden, "neu": neu, "fehler": fehler}
