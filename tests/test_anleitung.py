"""Die Anleitung existiert an zwei Orten (App-Reiter /anleitung und statische
Website docs/docs.html), aber nur EINE Quelle: web/templates/_anleitung_inhalt.html.
Diese Tests sichern genau das ab - sonst laeuft die Website unbemerkt gegenueber
der ausgelieferten App auseinander."""
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from web.main import app

WURZEL = Path(__file__).resolve().parent.parent
FRAGMENT = WURZEL / "web" / "templates" / "_anleitung_inhalt.html"
DOCS_HTML = WURZEL / "docs" / "docs.html"


def test_anleitung_seite_laedt(tmp_db):
    r = TestClient(app).get("/anleitung")
    assert r.status_code == 200
    assert "Anleitung" in r.text


def test_anleitung_enthaelt_kernabschnitte(tmp_db):
    r = TestClient(app).get("/anleitung")
    for anker in ["installation", "carddav", "vorschlaege", "export", "hilfe"]:
        assert f'id="{anker}"' in r.text, f"Abschnitt {anker} fehlt in /anleitung"


def test_anleitung_ist_ueber_navigation_erreichbar(tmp_db):
    # Der Reiter muss auf jeder Seite auftauchen (base.html), sonst findet ihn niemand.
    r = TestClient(app).get("/kontakte")
    assert r.status_code == 200
    assert 'href="/anleitung"' in r.text


def test_anleitung_laedt_eigenes_stylesheet(tmp_db):
    """Ohne anleitung.css faellt die Seite auf die App-Grundstile zurueck und die
    Schrittfolgen/Hinweiskaesten sehen kaputt aus."""
    r = TestClient(app).get("/anleitung")
    assert "/static/anleitung.css" in r.text
    assert (WURZEL / "web" / "static" / "anleitung.css").is_file()


def test_fragment_enthaelt_keine_jinja_syntax():
    """Das Fragment wird von scripts/build-website.py woertlich in die statische
    Seite uebernommen - Jinja-Syntax wuerde dort ungerendert sichtbar werden."""
    inhalt = FRAGMENT.read_text(encoding="utf-8")
    assert "{{" not in inhalt
    assert "{%" not in inhalt


def test_docs_html_ist_aktuell():
    """docs/docs.html wird generiert. Wer die Anleitung aendert, muss
    scripts/build-website.py laufen lassen - dieser Test erinnert daran."""
    ergebnis = subprocess.run(
        [sys.executable, str(WURZEL / "scripts" / "build-website.py"), "--check"],
        capture_output=True, text=True,
    )
    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr


def test_statische_seite_enthaelt_denselben_text_wie_die_app(tmp_db):
    """Stichprobe ueber beide Ausgabewege: derselbe Satz muss in der App-Seite und
    in der statischen Website stehen."""
    app_text = TestClient(app).get("/anleitung").text
    website_text = DOCS_HTML.read_text(encoding="utf-8")
    for satz in ["Kontakte.app verbinden", "Vorschläge", "Wenn etwas klemmt"]:
        assert satz in app_text, f"{satz} fehlt in der App-Anleitung"
        assert satz in website_text, f"{satz} fehlt auf der Website"


def test_interne_doku_wird_nicht_von_github_pages_veroeffentlicht():
    """docs/ ist zugleich der GitHub-Pages-Ordner. CHANGELOG-INTERN.md enthaelt
    reale Namen/Pfade aus dem Betrieb und darf dort nie mit ausgeliefert werden."""
    config = (WURZEL / "docs" / "_config.yml").read_text(encoding="utf-8")
    assert "CHANGELOG-INTERN.md" in config
