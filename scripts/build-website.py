#!/usr/bin/env python3
"""Erzeugt die statische Anleitungs-Seite docs/docs.html.

Der Anleitungstext existiert bewusst nur EINMAL, naemlich in
web/templates/_anleitung_inhalt.html - dieselbe Datei wird vom Server unter
/anleitung eingebunden (siehe web/anleitung.py). Dieses Skript legt lediglich
den Seitenrahmen der oeffentlichen Website darum und bettet das gemeinsame
Stylesheet web/static/anleitung.css ein (die statische Seite auf GitHub Pages
hat keinen Zugriff auf /static/). So koennen Website und installierte App nie
auseinanderlaufen.

Aufruf nach jeder Aenderung an der Anleitung:  python3 scripts/build-website.py
Der Test tests/test_anleitung.py prueft, dass docs/docs.html aktuell ist.
"""
from __future__ import annotations

import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
FRAGMENT = WURZEL / "web" / "templates" / "_anleitung_inhalt.html"
CSS = WURZEL / "web" / "static" / "anleitung.css"
ZIEL = WURZEL / "docs" / "docs.html"

_SEITE = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Anleitung – Rubrica</title>
  <!-- ACHTUNG: Diese Datei wird von scripts/build-website.py erzeugt.
       Nicht von Hand bearbeiten - der Inhalt steht in
       web/templates/_anleitung_inhalt.html (gemeinsame Quelle mit der App). -->
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      background: #fff;
      color: #111;
      line-height: 1.7;
    }}

    header {{
      padding: 28px 48px;
      border-bottom: 1px solid #e8e8e8;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}
    .wordmark {{
      display: inline-flex;
      align-items: center;
      gap: 9px;
      font-size: 18px;
      font-weight: 600;
      letter-spacing: -0.3px;
      color: #111;
      text-decoration: none;
    }}
    .wordmark svg {{ display: block; }}
    .back-link {{ font-size: 13px; color: #999; text-decoration: none; }}
    .back-link:hover {{ color: #111; }}

    .page {{
      max-width: 1060px;
      margin: 0 auto;
      padding: 60px 24px 120px;
    }}

    footer {{
      border-top: 1px solid #e8e8e8;
      padding: 32px 48px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 13px;
      color: #999;
      flex-wrap: wrap;
      gap: 8px;
    }}
    footer a {{ color: #999; text-decoration: none; }}
    footer a:hover {{ color: #111; }}

    .anleitung-inhalt a {{ color: #111; }}

    @media (max-width: 740px) {{
      header {{ padding: 20px 24px; }}
      .page {{ padding: 40px 20px 80px; }}
      footer {{ padding: 24px; flex-direction: column; align-items: flex-start; }}
    }}

/* ── aus web/static/anleitung.css ── */
{css}
  </style>
</head>
<body>

  <header>
    <a class="wordmark" href="index.html">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-linecap="round" stroke-linejoin="round" width="22" height="22">
        <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" stroke-width="2"/>
        <path d="M9 7h6" stroke-width="2"/>
        <path d="M9 11h6" stroke-width="2"/>
      </svg>
      Rubrica
    </a>
    <a class="back-link" href="index.html">← Zurück</a>
  </header>

  <div class="page">
{inhalt}
  </div>

  <footer>
    <span>Rubrica</span>
    <span>© 2026 Rubrica</span>
  </footer>

</body>
</html>
"""


def baue_seite() -> str:
    css = CSS.read_text(encoding="utf-8").strip()
    inhalt = FRAGMENT.read_text(encoding="utf-8").strip()
    return _SEITE.format(css=css, inhalt=inhalt)


def main() -> int:
    neu = baue_seite()
    # --check (fuer den Test): nur pruefen, ob die erzeugte Datei aktuell ist.
    if "--check" in sys.argv:
        if not ZIEL.exists() or ZIEL.read_text(encoding="utf-8") != neu:
            print("docs/docs.html ist nicht aktuell - bitte scripts/build-website.py ausfuehren.")
            return 1
        print("docs/docs.html ist aktuell.")
        return 0

    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    ZIEL.write_text(neu, encoding="utf-8")
    print(f"✓ {ZIEL.relative_to(WURZEL)} erzeugt ({len(neu)} Zeichen)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
