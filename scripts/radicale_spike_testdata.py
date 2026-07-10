"""Phase-2-Spike: legt ueber CardDAV ein Testadressbuch mit zwei synthetischen
Kontakten und einer Apple-Gruppen-vCard (X-ADDRESSBOOKSERVER-KIND/-MEMBER) an.

Rein zum Verifizieren, ob Kontakte.app auf dem Mac so erzeugte Gruppen korrekt
anzeigt - siehe docs/konzept.md Abschnitt 5.2/9. Keine echten Kontaktdaten,
beliebig oft wiederholbar (PUT ueberschreibt). Voraussetzung: Radicale laeuft
lokal (bash scripts/radicale-dev.sh).

Aufruf: .venv/bin/python scripts/radicale_spike_testdata.py
"""
import httpx

BASE = "https://127.0.0.1:8443/fabio/testbook"

KONTAKT_1 = """BEGIN:VCARD
VERSION:3.0
UID:spike-contact-1
N:Spikeperson;Alice;;;
FN:Alice Spikeperson
ORG:Spike Testing AG
TEL;TYPE=CELL:+41 79 000 00 01
EMAIL;TYPE=WORK:alice.spike@example.com
END:VCARD
"""

KONTAKT_2 = """BEGIN:VCARD
VERSION:3.0
UID:spike-contact-2
N:Zweiter;Bob;;;
FN:Bob Zweiter
ORG:Spike Testing AG
TEL;TYPE=CELL:+41 79 000 00 02
EMAIL;TYPE=WORK:bob.spike@example.com
END:VCARD
"""

GRUPPE = """BEGIN:VCARD
VERSION:3.0
UID:spike-group-1
FN:Rubrica Testprojekt
N:Rubrica Testprojekt;;;;
X-ADDRESSBOOKSERVER-KIND:group
X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:spike-contact-1
X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:spike-contact-2
END:VCARD
"""

MKCOL_BODY = """<?xml version="1.0" encoding="utf-8"?>
<create xmlns="DAV:" xmlns:CR="urn:ietf:params:xml:ns:carddav">
  <set>
    <prop>
      <resourcetype><collection/><CR:addressbook/></resourcetype>
      <displayname>Rubrica Test</displayname>
    </prop>
  </set>
</create>"""


def main():
    with httpx.Client(auth=("fabio", ""), verify=False) as client:  # selbstsigniertes Zertifikat
        resp = client.request("MKCOL", f"{BASE}/", content=MKCOL_BODY,
                               headers={"Content-Type": "application/xml"})
        if resp.status_code not in (201, 405):  # 405 = existiert bereits
            resp.raise_for_status()
        print(f"Adressbuch: {resp.status_code}")

        for name, vcard in [
            ("spike-contact-1.vcf", KONTAKT_1),
            ("spike-contact-2.vcf", KONTAKT_2),
            ("spike-group-1.vcf", GRUPPE),
        ]:
            resp = client.put(f"{BASE}/{name}", content=vcard,
                               headers={"Content-Type": "text/vcard"})
            resp.raise_for_status()
            print(f"{name}: {resp.status_code}")

    print("\nFertig. CardDAV-Account in Kontakte.app einrichten:")
    print("  Server: Fabio-Mac-Studio.local, Port: 8443, SSL: an, Pfad: /fabio/testbook/, kein Passwort")


if __name__ == "__main__":
    main()
