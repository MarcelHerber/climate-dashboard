#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


TARGETS = [
    Path("index.html"),
    Path("scripts/apply_station_calendar_frequency_feature.py"),
]

HTML_OLD = '''        <div>\n          <h2>Kalenderhäufigkeit · Schneehöhe</h2>\n          <p>Wie häufig lag am jeweiligen Kalendertag eine Schneedecke von mindestens 1, 5 oder 10 cm?</p>\n        </div>\n      </div>\n'''

HTML_NEW = '''        <div>\n          <h2>Kalenderhäufigkeit · Schneehöhe</h2>\n          <p>Wie häufig lag am jeweiligen Kalendertag eine Schneedecke von mindestens 1, 5 oder 10 cm?</p>\n        </div>\n        <div class="control-group" style="min-width:300px">\n          <label for="stationClimateDaysSnowFrequencyStationSelect">Schneestation</label>\n          <select id="stationClimateDaysSnowFrequencyStationSelect" onchange="renderStationClimateDaysFrequency()"></select>\n        </div>\n      </div>\n'''

FUNCTION_ANCHOR = '''async function renderStationClimateDaysFrequency(stationOverride=null){\n'''

HELPERS = '''function stationClimateDaysPopulateSnowFrequencyStations(preferredStation){\n  const select=document.getElementById("stationClimateDaysSnowFrequencyStationSelect");\n  const stations=stationClimateDaysSnowFrequencyIndex?.stations||[];\n  if(!select||!stations.length) return null;\n\n  const previous=select.value;\n  if(select.options.length!==stations.length){\n    select.innerHTML="";\n    stations\n      .slice()\n      .sort((a,b)=>`${a.state||""} ${a.name||""}`.localeCompare(`${b.state||""} ${b.name||""}`,"de"))\n      .forEach(item=>{\n        const option=document.createElement("option");\n        option.value=item.id;\n        option.textContent=`${item.name} (${item.id}) · ${item.state||""}`;\n        select.appendChild(option);\n      });\n  }\n\n  if(previous && stations.some(item=>item.id===previous)){\n    select.value=previous;\n  }else if(preferredStation && stations.some(item=>item.id===preferredStation.id)){\n    select.value=preferredStation.id;\n  }else{\n    const sameState=preferredStation?stations.find(item=>item.state===preferredStation.state):null;\n    select.value=(sameState||stations[0])?.id||"";\n  }\n  return stations.find(item=>item.id===select.value)||null;\n}\n\n'''

SNOW_OLD = '''  let snow=null;\n  try{snow=await stationClimateDaysLoadSnowFrequency(station.id);}catch(_error){snow=null;}\n  if(requestId!==stationClimateDaysFrequencyRequest) return;\n  const snowBody=document.querySelector("#stationClimateDaysSnowFrequencyRecords tbody");\n  const snowNote=document.getElementById("stationClimateDaysSnowFrequencyNote");\n  if(snow){\n    stationClimateDaysSnowFrequencyChart=stationClimateDaysFrequencyChart(\n      "stationClimateDaysSnowFrequencyChart",\n      stationClimateDaysSnowFrequencyChart,\n      snow,\n      [1,5,10],\n      ["#8fc7e8","#4f8fc4","#24527a"],\n      `Kalenderhäufigkeit Schneehöhe – ${station.name}`\n    );\n'''

SNOW_NEW = '''  let snow=null;\n  let snowStation=null;\n  try{\n    if(!stationClimateDaysSnowFrequencyIndex){\n      const response=await dashboardFetch("station_snow_height_index.json",{cache:"no-store"});\n      if(response.ok) stationClimateDaysSnowFrequencyIndex=await response.json();\n    }\n    snowStation=stationClimateDaysPopulateSnowFrequencyStations(station);\n    if(snowStation) snow=await stationClimateDaysLoadSnowFrequency(snowStation.id);\n  }catch(_error){snow=null;}\n  if(requestId!==stationClimateDaysFrequencyRequest) return;\n  const snowBody=document.querySelector("#stationClimateDaysSnowFrequencyRecords tbody");\n  const snowNote=document.getElementById("stationClimateDaysSnowFrequencyNote");\n  if(snow && snowStation){\n    stationClimateDaysSnowFrequencyChart=stationClimateDaysFrequencyChart(\n      "stationClimateDaysSnowFrequencyChart",\n      stationClimateDaysSnowFrequencyChart,\n      snow,\n      [1,5,10],\n      ["#8fc7e8","#4f8fc4","#24527a"],\n      `Kalenderhäufigkeit Schneehöhe – ${snowStation.name}`\n    );\n'''

NOTE_OLD = '''    if(snowNote) snowNote.textContent="Je Kalendertag werden nur akzeptierte historische Schneehöhenjahre mit gültigem DWD-Wert SHK_TAG berücksichtigt. Angezeigt wird Schneedecke/Schneehöhe, nicht zwingend Neuschneefall.";\n  }else{\n    if(stationClimateDaysSnowFrequencyChart){stationClimateDaysSnowFrequencyChart.destroy();stationClimateDaysSnowFrequencyChart=null;}\n    if(snowBody) snowBody.innerHTML='<tr><td colspan="3">Für diese Station sind noch keine Kalenderhäufigkeiten der Schneehöhe verfügbar.</td></tr>';\n    if(snowNote) snowNote.textContent="Die Schneehöhen-Häufigkeiten werden beim nächsten Neuaufbau der historischen Schneehöhenprofile ergänzt.";\n  }\n'''

NOTE_NEW = '''    if(snowNote){\n      const separate=snowStation.id!==station.id\n        ?`Für ${station.name} liegt kein qualifiziertes Schneehöhenprofil vor; ausgewählt ist ${snowStation.name} (${snowStation.id}). `\n        :"";\n      snowNote.textContent=separate+"Je Kalendertag werden nur akzeptierte historische Schneehöhenjahre mit gültigem DWD-Wert SHK_TAG berücksichtigt. Angezeigt wird Schneedecke/Schneehöhe, nicht zwingend Neuschneefall.";\n    }\n  }else{\n    if(stationClimateDaysSnowFrequencyChart){stationClimateDaysSnowFrequencyChart.destroy();stationClimateDaysSnowFrequencyChart=null;}\n    if(snowBody) snowBody.innerHTML='<tr><td colspan="3">Für die gewählte Schneestation sind keine Kalenderhäufigkeiten verfügbar.</td></tr>';\n    if(snowNote) snowNote.textContent="Bitte eine andere Schneestation wählen. Es werden nur Stationen mit ausreichend langen und vollständigen SHK_TAG-Reihen angeboten.";\n  }\n'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: erwartete genau 1 Fundstelle, gefunden: {count}")
    return text.replace(old, new, 1)


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if "stationClimateDaysSnowFrequencyStationSelect" in text:
        print(f"{path}: Schneestationsauswahl bereits vorhanden")
        return False

    text = replace_once(text, HTML_OLD, HTML_NEW, f"{path}: Schnee-HTML")
    text = replace_once(text, FUNCTION_ANCHOR, HELPERS + FUNCTION_ANCHOR, f"{path}: Hilfsfunktionen")
    text = replace_once(text, SNOW_OLD, SNOW_NEW, f"{path}: Schnee-Ladevorgang")
    text = replace_once(text, NOTE_OLD, NOTE_NEW, f"{path}: Schnee-Hinweis")
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"{path}: Schneestationsauswahl eingebaut")
    return True


def main() -> None:
    changed = False
    for path in TARGETS:
        changed = patch(path) or changed
    if not changed:
        print("Keine Änderungen nötig.")


if __name__ == "__main__":
    main()
