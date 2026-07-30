from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _schweizer_telefonformat(nummer: str) -> str:
    """Normalisiert eine mit fuehrender 0 eingegebene Nummer (z.B. "079 123 45 67")
    auf das internationale Format mit Schweizer Landesvorwahl ("+41 79 123 45 67") -
    99% der Kontakte sind Schweizer Nummern (Nutzer-Vorgabe), Freitext-Eingabe ohne
    Vorwahl waere sonst der Normalfall. Bereits internationale Nummern (+.../00...)
    und Eingaben ohne fuehrende 0 (z.B. interne Kurzwahlen) bleiben unveraendert."""
    n = (nummer or "").strip()
    if not n or n.startswith("+") or n.startswith("00"):
        return n
    ziffern = re.sub(r"\D", "", n)
    if not ziffern.startswith("0") or len(ziffern) < 2:
        return n
    rest = ziffern[1:]
    if len(rest) == 9:
        return "+41 " + " ".join([rest[0:2], rest[2:5], rest[5:7], rest[7:9]])
    return "+41 " + rest


def _kontakt_row_to_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    kontakt = dict(row)
    kontakt["telefonnummern"] = [
        dict(r) for r in conn.execute(
            "SELECT id, typ, nummer FROM telefonnummern WHERE kontakt_id = ? ORDER BY id", (row["id"],)
        )
    ]
    kontakt["emails"] = [
        dict(r) for r in conn.execute(
            "SELECT id, typ, email FROM emails WHERE kontakt_id = ? ORDER BY id", (row["id"],)
        )
    ]
    kontakt["adressen"] = [
        dict(r) for r in conn.execute(
            "SELECT id, typ, strasse, plz, ort, region, land FROM adressen WHERE kontakt_id = ? ORDER BY id",
            (row["id"],),
        )
    ]
    kontakt["urls"] = [
        dict(r) for r in conn.execute(
            "SELECT id, typ, url FROM urls WHERE kontakt_id = ? ORDER BY id", (row["id"],)
        )
    ]
    kontakt["projekte"] = [
        dict(r) for r in conn.execute(
            """SELECT p.id, p.name FROM projekte p
               JOIN kontakte_projekte kp ON kp.projekt_id = p.id
               WHERE kp.kontakt_id = ? ORDER BY p.name""",
            (row["id"],),
        )
    ]
    return kontakt


def list_kontakte(conn: sqlite3.Connection, suche: str = "", projekt_id: int | None = None,
                   kategorie: str = "") -> list[dict]:
    sql = "SELECT DISTINCT k.* FROM kontakte k"
    joins = []
    where = []
    params: list = []

    if projekt_id:
        joins.append("JOIN kontakte_projekte kp ON kp.kontakt_id = k.id")
        where.append("kp.projekt_id = ?")
        params.append(projekt_id)

    if suche:
        # Pro Wort eine eigene, UND-verknuepfte Klausel statt eines einzelnen LIKE
        # ueber den ganzen Suchstring - sonst faende "Anna Muster" nie etwas,
        # da Vor- und Nachname in getrennten Spalten stehen (Wortreihenfolge ist
        # dadurch auch egal, "Muster Anna" findet denselben Kontakt).
        for wort in suche.split():
            where.append("(k.vorname LIKE ? OR k.nachname LIKE ? OR k.firma LIKE ?)")
            like = f"%{wort}%"
            params.extend([like, like, like])

    if kategorie:
        where.append("k.kategorie = ?")
        params.append(kategorie)

    if joins:
        sql += " " + " ".join(joins)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY k.nachname, k.vorname"

    rows = conn.execute(sql, params).fetchall()
    return [_kontakt_row_to_dict(conn, r) for r in rows]


def get_kontakt(conn: sqlite3.Connection, kontakt_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM kontakte WHERE id = ?", (kontakt_id,)).fetchone()
    if row is None:
        return None
    return _kontakt_row_to_dict(conn, row)


def create_kontakt(conn: sqlite3.Connection, daten: dict) -> int:
    with conn:
        cur = conn.execute(
            """INSERT INTO kontakte (vorname, nachname, firma, rolle, kategorie, notizen, apple_uid)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                daten.get("vorname", ""), daten.get("nachname", ""),
                daten.get("firma", ""), daten.get("rolle", ""), daten.get("kategorie", ""),
                daten.get("notizen", ""), daten.get("apple_uid") or None,
            ),
        )
        kontakt_id = cur.lastrowid
        _replace_telefonnummern(conn, kontakt_id, daten.get("telefonnummern", []))
        _replace_emails(conn, kontakt_id, daten.get("emails", []))
        _replace_adressen(conn, kontakt_id, daten.get("adressen", []))
        _replace_urls(conn, kontakt_id, daten.get("urls", []))
    return kontakt_id


def update_kontakt(conn: sqlite3.Connection, kontakt_id: int, daten: dict) -> None:
    with conn:
        conn.execute(
            """UPDATE kontakte SET vorname = ?, nachname = ?, firma = ?, rolle = ?,
               kategorie = ?, notizen = ?, updated_at = ? WHERE id = ?""",
            (
                daten.get("vorname", ""), daten.get("nachname", ""),
                daten.get("firma", ""), daten.get("rolle", ""), daten.get("kategorie", ""),
                daten.get("notizen", ""), _now(), kontakt_id,
            ),
        )
        _replace_telefonnummern(conn, kontakt_id, daten.get("telefonnummern", []))
        _replace_emails(conn, kontakt_id, daten.get("emails", []))
        _replace_adressen(conn, kontakt_id, daten.get("adressen", []))
        _replace_urls(conn, kontakt_id, daten.get("urls", []))


_ERLAUBTE_MEHRFACHFELDER = {"vorname", "nachname", "firma", "rolle", "kategorie", "notizen"}


def update_kontakt_felder(conn: sqlite3.Connection, kontakt_id: int, felder: dict) -> None:
    """Partielles Update nur der uebergebenen Scalar-Spalten - fasst (anders als
    update_kontakt) Telefonnummern/E-Mails/Adressen/URLs nicht an. Fuer das
    Sammel-Bearbeiten mehrerer ausgewaehlter Kontakte."""
    spalten = [f for f in felder if f in _ERLAUBTE_MEHRFACHFELDER]
    if not spalten:
        return
    zuweisungen = ", ".join(f"{spalte} = ?" for spalte in spalten)
    werte = [felder[spalte] for spalte in spalten]
    with conn:
        conn.execute(
            f"UPDATE kontakte SET {zuweisungen}, updated_at = ? WHERE id = ?",
            (*werte, _now(), kontakt_id),
        )


_KATEGORIE_TABELLEN = {"telefon": "telefonnummern", "email": "emails"}


def kategorie_umstellen(conn: sqlite3.Connection, feld: str, kontakt_id: int, von: str, nach: str) -> None:
    """Stellt bei einem Kontakt alle Telefonnummern/E-Mails einer Kategorie
    (Direkt/Privat/Allgemein) auf eine andere um - fuer das Sammel-Bearbeiten
    mehrerer ausgewaehlter Kontakte, ohne die Werte selbst anzufassen (siehe
    docs/konzept.md: variable Anzahl Eintraege je Kontakt macht ein
    positionsbasiertes Bearbeiten der Werte selbst nicht sinnvoll)."""
    tabelle = _KATEGORIE_TABELLEN.get(feld)
    if not tabelle or not von or not nach:
        return
    with conn:
        conn.execute(f"UPDATE {tabelle} SET typ = ? WHERE kontakt_id = ? AND typ = ?", (nach, kontakt_id, von))


_FELD_SPALTEN = {"kategorie": "kategorie", "rolle": "rolle"}


def feld_werte_uebersicht(conn: sqlite3.Connection, feld: str) -> list[dict]:
    """Listet alle in `kontakte` verwendeten Werte eines Scalar-Felds (Funktion/Rolle)
    mit Anzahl betroffener Kontakte - Grundlage fuer die Verwaltungsseite (Tippfehler
    korrigieren, global umbenennen, loeschen+neu zuweisen)."""
    spalte = _FELD_SPALTEN.get(feld)
    if not spalte:
        return []
    rows = conn.execute(
        f"SELECT {spalte} AS wert, COUNT(*) AS anzahl FROM kontakte "
        f"WHERE {spalte} != '' GROUP BY {spalte} ORDER BY {spalte} COLLATE NOCASE"
    ).fetchall()
    return [dict(r) for r in rows]


def feld_wert_umbenennen(conn: sqlite3.Connection, feld: str, alter_wert: str, neuer_wert: str) -> list[int]:
    """Aendert einen Funktion-/Rolle-Wert bei ALLEN betroffenen Kontakten auf einmal.
    Ein leerer `neuer_wert` entfernt die Zuweisung (Feld wird geleert). Ein bereits
    bestehender `neuer_wert` fuehrt die Kontakte effektiv zusammen (z.B. beim Loeschen
    eines doppelten/falsch geschriebenen Werts). Gibt die betroffenen kontakt_ids
    zurueck, damit der Aufrufer sie erneut zu Radicale pushen kann."""
    spalte = _FELD_SPALTEN.get(feld)
    if not spalte or not alter_wert or alter_wert == neuer_wert:
        return []
    betroffene = [r["id"] for r in conn.execute(f"SELECT id FROM kontakte WHERE {spalte} = ?", (alter_wert,))]
    if not betroffene:
        return []
    with conn:
        conn.execute(f"UPDATE kontakte SET {spalte} = ? WHERE {spalte} = ?", (neuer_wert, alter_wert))
    return betroffene


def merge_kontakt(conn: sqlite3.Connection, kontakt_id: int, daten: dict) -> None:
    """Wie update_kontakt, aber fuer Vorschlaege: leere Felder ueberschreiben nichts,
    Telefonnummern/E-Mails/Adressen/URLs werden ergaenzt statt ersetzt (kein Datenverlust bei Dedup).
    Notizen werden angehaengt statt ersetzt, falls beide Seiten Text enthalten."""
    bestehend = get_kontakt(conn, kontakt_id)
    if bestehend is None:
        return

    neue_notizen = daten.get("notizen", "").strip()
    if neue_notizen and bestehend["notizen"] and neue_notizen != bestehend["notizen"]:
        notizen = bestehend["notizen"] + "\n---\n" + neue_notizen
    else:
        notizen = neue_notizen or bestehend["notizen"]

    with conn:
        conn.execute(
            """UPDATE kontakte SET vorname = ?, nachname = ?, firma = ?, rolle = ?,
               kategorie = ?, notizen = ?, apple_uid = ?, updated_at = ? WHERE id = ?""",
            (
                daten.get("vorname") or bestehend["vorname"],
                daten.get("nachname") or bestehend["nachname"],
                daten.get("firma") or bestehend["firma"],
                daten.get("rolle") or bestehend["rolle"],
                daten.get("kategorie") or bestehend["kategorie"],
                notizen,
                # Einmal gesetzte apple_uid bleibt erhalten (verlaesslicher Wiedererkennungs-
                # Anker) - wird nur befuellt, wenn der bestehende Kontakt noch keine hat.
                bestehend.get("apple_uid") or daten.get("apple_uid") or None,
                _now(), kontakt_id,
            ),
        )
        bestehende_nummern = {t["nummer"] for t in bestehend["telefonnummern"]}
        for tel in daten.get("telefonnummern", []):
            if tel.get("nummer") and tel["nummer"] not in bestehende_nummern:
                conn.execute(
                    "INSERT INTO telefonnummern (kontakt_id, typ, nummer) VALUES (?, ?, ?)",
                    (kontakt_id, tel.get("typ", "mobil"), _schweizer_telefonformat(tel["nummer"])),
                )
        bestehende_mails = {e["email"] for e in bestehend["emails"]}
        for mail in daten.get("emails", []):
            if mail.get("email") and mail["email"] not in bestehende_mails:
                conn.execute(
                    "INSERT INTO emails (kontakt_id, typ, email) VALUES (?, ?, ?)",
                    (kontakt_id, mail.get("typ", "arbeit"), mail["email"]),
                )
        bestehende_adressen = {
            (a["strasse"], a["plz"], a["ort"]) for a in bestehend["adressen"]
        }
        for adr in daten.get("adressen", []):
            schluessel = (adr.get("strasse", ""), adr.get("plz", ""), adr.get("ort", ""))
            if any(schluessel) and schluessel not in bestehende_adressen:
                conn.execute(
                    """INSERT INTO adressen (kontakt_id, typ, strasse, plz, ort, region, land)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (kontakt_id, adr.get("typ", "arbeit"), adr.get("strasse", ""),
                     adr.get("plz", ""), adr.get("ort", ""), adr.get("region", ""), adr.get("land", "")),
                )
        bestehende_urls = {u["url"] for u in bestehend["urls"]}
        for u in daten.get("urls", []):
            if u.get("url") and u["url"] not in bestehende_urls:
                conn.execute(
                    "INSERT INTO urls (kontakt_id, typ, url) VALUES (?, ?, ?)",
                    (kontakt_id, u.get("typ", "homepage"), u["url"]),
                )


def delete_kontakt(conn: sqlite3.Connection, kontakt_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM kontakte WHERE id = ?", (kontakt_id,))


def delete_alle_kontakte(conn: sqlite3.Connection) -> int:
    """Loescht ALLE Kontakte (fuer einen sauberen Neustart vor einem erneuten Import,
    siehe web/settings.py) - telefonnummern/emails/adressen/urls/kontakte_projekte sowie
    darauf verweisende vorschlaege-Eintraege werden per ON DELETE CASCADE automatisch mit
    entfernt. Ordner (projekte) bleiben bewusst erhalten. Gibt die Anzahl geloeschter
    Kontakte zurueck."""
    with conn:
        anzahl = conn.execute("SELECT COUNT(*) FROM kontakte").fetchone()[0]
        conn.execute("DELETE FROM kontakte")
    return anzahl


def _replace_telefonnummern(conn: sqlite3.Connection, kontakt_id: int, nummern: list[dict]) -> None:
    conn.execute("DELETE FROM telefonnummern WHERE kontakt_id = ?", (kontakt_id,))
    for tel in nummern:
        if tel.get("nummer"):
            conn.execute(
                "INSERT INTO telefonnummern (kontakt_id, typ, nummer) VALUES (?, ?, ?)",
                (kontakt_id, tel.get("typ", "mobil"), _schweizer_telefonformat(tel["nummer"])),
            )


def _replace_emails(conn: sqlite3.Connection, kontakt_id: int, mails: list[dict]) -> None:
    conn.execute("DELETE FROM emails WHERE kontakt_id = ?", (kontakt_id,))
    for mail in mails:
        if mail.get("email"):
            conn.execute(
                "INSERT INTO emails (kontakt_id, typ, email) VALUES (?, ?, ?)",
                (kontakt_id, mail.get("typ", "arbeit"), mail["email"]),
            )


def _replace_adressen(conn: sqlite3.Connection, kontakt_id: int, adressen: list[dict]) -> None:
    conn.execute("DELETE FROM adressen WHERE kontakt_id = ?", (kontakt_id,))
    for adr in adressen:
        if any(adr.get(f) for f in ("strasse", "plz", "ort")):
            conn.execute(
                """INSERT INTO adressen (kontakt_id, typ, strasse, plz, ort, region, land)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (kontakt_id, adr.get("typ", "arbeit"), adr.get("strasse", ""),
                 adr.get("plz", ""), adr.get("ort", ""), adr.get("region", ""), adr.get("land", "")),
            )


def _replace_urls(conn: sqlite3.Connection, kontakt_id: int, urls: list[dict]) -> None:
    conn.execute("DELETE FROM urls WHERE kontakt_id = ?", (kontakt_id,))
    for u in urls:
        if u.get("url"):
            conn.execute(
                "INSERT INTO urls (kontakt_id, typ, url) VALUES (?, ?, ?)",
                (kontakt_id, u.get("typ", "homepage"), u["url"]),
            )


def set_kontakt_projekte(conn: sqlite3.Connection, kontakt_id: int, projekt_ids: list[int]) -> None:
    with conn:
        conn.execute("DELETE FROM kontakte_projekte WHERE kontakt_id = ?", (kontakt_id,))
        for pid in projekt_ids:
            conn.execute(
                "INSERT OR IGNORE INTO kontakte_projekte (kontakt_id, projekt_id) VALUES (?, ?)",
                (kontakt_id, pid),
            )


def add_kontakt_projekt(conn: sqlite3.Connection, kontakt_id: int, projekt_id: int) -> None:
    """Fuegt EIN Ordner zu einem Kontakt hinzu, ohne bestehende Zuordnungen zu
    entfernen (im Gegensatz zu set_kontakt_projekte, das die ganze Liste ersetzt).
    Fuer die Drag&Drop-Zuordnung in der Kontaktliste."""
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO kontakte_projekte (kontakt_id, projekt_id) VALUES (?, ?)",
            (kontakt_id, projekt_id),
        )


def list_projekte(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM projekte ORDER BY name")]


def get_or_create_projekt(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM projekte WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    with conn:
        cur = conn.execute("INSERT INTO projekte (name) VALUES (?)", (name,))
        return cur.lastrowid


def delete_projekt(conn: sqlite3.Connection, projekt_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM projekte WHERE id = ?", (projekt_id,))


def rename_projekt(conn: sqlite3.Connection, projekt_id: int, neuer_name: str) -> None:
    with conn:
        conn.execute("UPDATE projekte SET name = ? WHERE id = ?", (neuer_name, projekt_id))


def postfach_zuordnungen(conn: sqlite3.Connection) -> dict:
    """Postfach -> {projekt_id, name}, fuer alle aktuell zugeordneten Postfaecher."""
    rows = conn.execute(
        "SELECT pz.postfach AS postfach, p.id AS projekt_id, p.name AS name "
        "FROM postfach_zuordnung pz JOIN projekte p ON p.id = pz.projekt_id"
    ).fetchall()
    return {r["postfach"]: {"projekt_id": r["projekt_id"], "name": r["name"]} for r in rows}


def postfach_zuordnen(conn: sqlite3.Connection, postfach: str, projekt_id: "int | None") -> None:
    """Ordnet ein Postfach einem Ordner zu (projekt_id=None entfernt die Zuordnung)."""
    if not postfach:
        return
    with conn:
        if projekt_id is None:
            conn.execute("DELETE FROM postfach_zuordnung WHERE postfach = ?", (postfach,))
        else:
            conn.execute(
                "INSERT INTO postfach_zuordnung (postfach, projekt_id) VALUES (?, ?) "
                "ON CONFLICT(postfach) DO UPDATE SET projekt_id = excluded.projekt_id",
                (postfach, projekt_id),
            )


def list_vorschlaege(conn: sqlite3.Connection, status: str = "offen", quelle: str | None = None) -> list[dict]:
    sql = "SELECT * FROM vorschlaege WHERE status = ?"
    params: list = [status]
    if quelle:
        sql += " AND quelle = ?"
        params.append(quelle)
    sql += " ORDER BY created_at"
    rows = conn.execute(sql, params).fetchall()
    result = []
    for row in rows:
        v = dict(row)
        v["rohdaten"] = json.loads(v["rohdaten"])
        if v["kontakt_id"]:
            v["bestehender_kontakt"] = get_kontakt(conn, v["kontakt_id"])
        result.append(v)
    return result


def get_vorschlag(conn: sqlite3.Connection, vorschlag_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM vorschlaege WHERE id = ?", (vorschlag_id,)).fetchone()
    if row is None:
        return None
    v = dict(row)
    v["rohdaten"] = json.loads(v["rohdaten"])
    return v


def create_vorschlag(conn: sqlite3.Connection, rohdaten: dict, kontakt_id: int | None = None,
                      quelle: str = "import", message_id: str | None = None) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO vorschlaege (kontakt_id, quelle, status, rohdaten, message_id) VALUES (?, ?, 'offen', ?, ?)",
            (kontakt_id, quelle, json.dumps(rohdaten, ensure_ascii=False), message_id),
        )
        return cur.lastrowid


def update_vorschlag_rohdaten(conn: sqlite3.Connection, vorschlag_id: int, rohdaten: dict) -> None:
    """Ersetzt die rohdaten eines noch offenen Vorschlags - genutzt beim Bearbeiten
    vor der Uebernahme (z.B. Mail-Vorschlaege, siehe web/mail_vorschlaege.py), damit
    dieselbe vorschlag_id (und damit derselbe Datensatz) bestaetigt wird, statt einen
    zusaetzlichen Vorschlag anzulegen und den urspruenglichen offen zu lassen."""
    with conn:
        conn.execute(
            "UPDATE vorschlaege SET rohdaten = ? WHERE id = ?",
            (json.dumps(rohdaten, ensure_ascii=False), vorschlag_id),
        )


def vorschlag_existiert_fuer_message_id(conn: sqlite3.Connection, message_id: str) -> bool:
    """Dublettenschutz fuer den Mail-Eingang (mail_intake.py): eine bereits verarbeitete
    Mail (gleiche Message-ID) soll bei jedem taeglichen/manuellen Check nicht erneut
    einen Vorschlag erzeugen."""
    return conn.execute(
        "SELECT 1 FROM vorschlaege WHERE message_id = ? LIMIT 1", (message_id,)
    ).fetchone() is not None


def set_vorschlag_status(conn: sqlite3.Connection, vorschlag_id: int, status: str) -> None:
    with conn:
        conn.execute("UPDATE vorschlaege SET status = ? WHERE id = ?", (status, vorschlag_id))


def bestaetige_vorschlag(conn: sqlite3.Connection, vorschlag_id: int,
                          ordner_ids: list[int] | None = None) -> int:
    """Uebernimmt den Vorschlag in kontakte (neu anlegen oder mergen) und markiert ihn bestaetigt.
    Gibt die betroffene kontakt_id zurueck. `ordner_ids` weist zusaetzlich zu den automatisch aus
    Apple-Gruppen erkannten Ordnern (gruppen_als_ordner) manuell ausgewaehlte, bestehende Ordner zu -
    ergaenzend, nicht ersetzend (analog zum Ordner-zuweisen-Button in der Kontaktliste)."""
    vorschlag = get_vorschlag(conn, vorschlag_id)
    if vorschlag is None:
        raise ValueError(f"Vorschlag {vorschlag_id} nicht gefunden")
    daten = vorschlag["rohdaten"]

    if vorschlag["kontakt_id"]:
        kontakt_id = vorschlag["kontakt_id"]
        merge_kontakt(conn, kontakt_id, daten)
    else:
        kontakt_id = create_kontakt(conn, daten)

    for gruppe in daten.get("gruppen_als_ordner", []):
        projekt_id = get_or_create_projekt(conn, gruppe)
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO kontakte_projekte (kontakt_id, projekt_id) VALUES (?, ?)",
                (kontakt_id, projekt_id),
            )

    for projekt_id in ordner_ids or []:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO kontakte_projekte (kontakt_id, projekt_id) VALUES (?, ?)",
                (kontakt_id, projekt_id),
            )

    set_vorschlag_status(conn, vorschlag_id, "bestaetigt")
    return kontakt_id


