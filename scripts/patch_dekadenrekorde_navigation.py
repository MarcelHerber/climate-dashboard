#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

DESKTOP_MARKER = "<!-- DWD_DECADE_RECORDS_DESKTOP_NAV_V1 -->"
# Der Markername bleibt absichtlich gleich, damit der bereits hochgeladene
# Workflow unverändert weiterverwendet werden kann.
OVERVIEW_MARKER = "<!-- DWD_DECADE_RECORDS_OVERVIEW_LINK_V1 -->"

STATION_RECORDS_BUTTON = """  <button class="tab-button" onclick="switchTab('records')">Stationsrekorde</button>"""

DESKTOP_INSERT = """  <!-- DWD_DECADE_RECORDS_DESKTOP_NAV_V1 -->
  <button class="tab-button" onclick="window.location.href='dekadenrekorde.html'">Dekadenrekorde</button>"""

MOBILE_OLD = """  document.querySelectorAll(".tab-button").forEach(button=>{
    const match=button.getAttribute("onclick")?.match(/switchTab\('([^']+)'\)/);
    if(!match) return;
    const option=document.createElement("option");
    option.value=match[1];
    option.textContent=button.textContent.trim();
    select.appendChild(option);
  });
  select.addEventListener("change",()=>switchTab(select.value));"""

MOBILE_NEW = """  document.querySelectorAll(".tab-button").forEach(button=>{
    const match=button.getAttribute("onclick")?.match(/switchTab\('([^']+)'\)/);
    if(!match) return;
    const option=document.createElement("option");
    option.value=match[1];
    option.textContent=button.textContent.trim();
    select.appendChild(option);
  });

  <!-- DWD_DECADE_RECORDS_OVERVIEW_LINK_V1 -->
  const decadeRecordsOption=document.createElement("option");
  decadeRecordsOption.value="__decade_records__";
  decadeRecordsOption.textContent="Dekadenrekorde";
  select.appendChild(decadeRecordsOption);

  select.addEventListener("change",()=>{
    if(select.value==="__decade_records__"){
      window.location.href="dekadenrekorde.html";
      return;
    }
    switchTab(select.value);
  });"""


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    # Desktop: direkt hinter "Stationsrekorde".
    if DESKTOP_MARKER not in text:
        count = text.count(STATION_RECORDS_BUTTON)
        if count != 1:
            raise RuntimeError(
                "Desktop-Navigation: genau 1 Stationsrekorde-Button erwartet, "
                f"gefunden: {count}"
            )
        text = text.replace(
            STATION_RECORDS_BUTTON,
            STATION_RECORDS_BUTTON + "\n" + DESKTOP_INSERT,
            1,
        )

    # Mobil: eigener Eintrag in der automatisch erzeugten Bereichsauswahl.
    if OVERVIEW_MARKER not in text:
        count = text.count(MOBILE_OLD)
        if count != 1:
            raise RuntimeError(
                "Mobile Navigation: genau 1 Initialisierungsblock erwartet, "
                f"gefunden: {count}"
            )
        text = text.replace(MOBILE_OLD, MOBILE_NEW, 1)

    if DESKTOP_MARKER not in text:
        raise RuntimeError("Desktop-Marker fehlt nach Patch.")
    if OVERVIEW_MARKER not in text:
        raise RuntimeError("Mobile-Marker fehlt nach Patch.")
    if text.count("dekadenrekorde.html") < 2:
        raise RuntimeError(
            "Dekadenrekorde müssen für Desktop und Mobil verlinkt sein."
        )

    changed = text != original
    if changed:
        path.write_text(text, encoding="utf-8")
        print("Dekadenrekorde wurden in Desktop- und Mobilnavigation eingebaut.")
    else:
        print("Dekadenrekord-Navigation ist bereits vollständig vorhanden.")

    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="index.html")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_file():
        raise SystemExit(f"Datei nicht gefunden: {path}")

    patch(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
