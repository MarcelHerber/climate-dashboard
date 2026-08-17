#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path

CSS_BLOCK = '\n/* Stationsniederschlag · Monatslisten */\n.station-precip-monthly-card{padding-bottom:18px}\n.station-precip-monthly-card .anomaly-table-heading{margin-bottom:14px}\n.station-precip-monthly-wrap{\n  max-height:760px;overflow:auto;border:1px solid var(--border);\n  border-radius:7px;background:#fff;\n}\n.station-precip-monthly-table{\n  min-width:1120px;margin:0;table-layout:fixed;font-variant-numeric:tabular-nums;\n}\n.station-precip-monthly-table th,.station-precip-monthly-table td{\n  min-width:65px;height:36px;padding:7px 5px;\n  border-color:rgba(120,120,120,.28);white-space:nowrap;\n}\n.station-precip-monthly-table thead th{\n  position:sticky;top:0;z-index:3;background:#292f35;color:#fff;font-size:12px;\n}\n.station-precip-monthly-table .year-cell{\n  position:sticky;left:0;z-index:2;min-width:72px;width:72px;background:#fff;\n  font-weight:700;box-shadow:2px 0 0 rgba(0,0,0,.12);\n}\n.station-precip-monthly-table thead .year-cell{z-index:4;background:#20252a}\n.station-precip-monthly-table .annual-cell{\n  border-left:3px solid rgba(25,25,25,.58)!important;font-weight:700;\n}\n.station-precip-monthly-table tr.current-year .year-cell{background:#fff0bf;color:#251900}\n.station-precip-monthly-table tr.current-year td{border-top:2px solid #222;border-bottom:2px solid #222}\n.station-precip-monthly-table td.no-value{background:#f1f3f5;color:#999}\n.station-precip-monthly-note{margin:12px 0 0;color:var(--muted);font-size:13px;line-height:1.5}\n'
HTML_BLOCK = '\n    <div class="chart-container auto station-precip-monthly-card">\n      <div class="anomaly-table-heading">\n        <div>\n          <h2 id="stationPrecipMonthlyTitle">Monatsniederschlag · komplette Monatslisten</h2>\n          <p id="stationPrecipMonthlySubtitle">Monatssummen der ausgewählten Station in mm.</p>\n        </div>\n      </div>\n      <div class="station-precip-monthly-wrap">\n        <table id="stationPrecipMonthlyTable" class="station-precip-monthly-table">\n          <thead>\n            <tr>\n              <th class="year-cell">Jahr</th>\n              <th>Jan</th><th>Feb</th><th>Mär</th><th>Apr</th><th>Mai</th><th>Jun</th>\n              <th>Jul</th><th>Aug</th><th>Sep</th><th>Okt</th><th>Nov</th><th>Dez</th>\n              <th class="annual-cell">Jahressumme</th>\n            </tr>\n          </thead>\n          <tbody id="stationPrecipMonthlyBody"></tbody>\n        </table>\n      </div>\n      <p id="stationPrecipMonthlyNote" class="station-precip-monthly-note">\n        Angezeigt werden nur vollständig vorliegende Monate. „–“ bedeutet: Monat unvollständig oder noch nicht abgeschlossen.\n        Die Jahressumme wird nur bei zwölf vollständigen Monaten gebildet.\n      </p>\n    </div>\n'
JS_BLOCK = '\nfunction stationPrecipMonthlyFormat(value){\n  return Number.isFinite(Number(value))\n    ? Number(value).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})\n    : "–";\n}\nfunction stationPrecipCurrentMonthlyRow(stationId){\n  if(!stationPrecipIndex) return null;\n  const currentYear=Number(stationPrecipIndex.current_year);\n  const dataThrough=String(stationPrecipIndex.data_through||"");\n  if(!Number.isFinite(currentYear)) return null;\n  const payloadByMonth=new Map();\n  for(const payload of stationPrecipMonthCache.values()){\n    if(Number(payload?.year)===currentYear) payloadByMonth.set(Number(payload.month),payload);\n  }\n  const months=Array(12).fill(null);\n  for(let month=1;month<=12;month++){\n    const payload=payloadByMonth.get(month);\n    const values=payload?.stations?.[stationId];\n    if(!Array.isArray(values)) continue;\n    const daysInMonth=new Date(currentYear,month,0).getDate();\n    const monthEnd=`${currentYear}-${String(month).padStart(2,"0")}-${String(daysInMonth).padStart(2,"0")}`;\n    if(!dataThrough || dataThrough<monthEnd || values.length<daysInMonth) continue;\n    const complete=values.slice(0,daysInMonth).every(value=>\n      value!==null && value!==undefined && Number.isFinite(Number(value))\n    );\n    if(!complete) continue;\n    months[month-1]=Math.round(\n      values.slice(0,daysInMonth).reduce((sum,value)=>sum+Number(value),0)*10\n    )/10;\n  }\n  if(!months.some(Number.isFinite)) return null;\n  const annual=months.every(Number.isFinite)\n    ? Math.round(months.reduce((sum,value)=>sum+Number(value),0)*10)/10\n    : null;\n  return {year:currentYear,months,annual,current:true};\n}\nfunction updateStationPrecipMonthlyTable(stationId){\n  const body=document.getElementById("stationPrecipMonthlyBody");\n  if(!body) return;\n\n  const station=stationPrecipIndex?.stations?.find(item=>item.id===stationId);\n  const historical=Array.isArray(stationPrecipProfile?.monthly_history)\n    ? stationPrecipProfile.monthly_history.map(row=>({\n        year:Number(row.year),\n        months:Array.isArray(row.months)?row.months.slice(0,12):Array(12).fill(null),\n        annual:row.annual,\n        current:false\n      }))\n    : [];\n\n  const current=stationPrecipCurrentMonthlyRow(stationId);\n  const currentYear=Number(stationPrecipIndex?.current_year);\n  const rows=historical\n    .filter(row=>Number.isFinite(row.year) && row.year!==currentYear)\n    .sort((a,b)=>b.year-a.year);\n  if(current) rows.unshift(current);\n\n  const title=document.getElementById("stationPrecipMonthlyTitle");\n  const subtitle=document.getElementById("stationPrecipMonthlySubtitle");\n  const note=document.getElementById("stationPrecipMonthlyNote");\n  if(title) title.textContent=`Monatsniederschlag · ${station?.name||stationId}`;\n  if(subtitle){\n    const validYears=historical.map(row=>Number(row.year)).filter(Number.isFinite);\n    const firstHistorical=validYears.length?Math.min(...validYears):null;\n    const span=Number.isFinite(firstHistorical)?`${firstHistorical}–${currentYear}`:String(currentYear||"");\n    subtitle.textContent=`Monatssummen in mm · ${span} · neuestes Jahr oben`;\n  }\n\n  if(!rows.length){\n    body.innerHTML=\'<tr><td colspan="14" class="no-value">Noch keine Monatslisten im Stationsprofil vorhanden.</td></tr>\';\n    if(note) note.textContent="Die historischen Monatslisten werden beim nächsten vollständigen Neuaufbau der Niederschlagsprofile erzeugt.";\n    return;\n  }\n\n  body.innerHTML=rows.map(row=>{\n    const monthCells=Array.from({length:12},(_,index)=>{\n      const value=row.months?.[index];\n      const valid=Number.isFinite(Number(value));\n      return `<td class="${valid?"":"no-value"}">${valid?stationPrecipMonthlyFormat(value):"–"}</td>`;\n    }).join("");\n    const annualValid=Number.isFinite(Number(row.annual));\n    return `<tr class="${row.current?"current-year":""}">\n      <td class="year-cell">${row.year}</td>\n      ${monthCells}\n      <td class="annual-cell ${annualValid?"":"no-value"}">${annualValid?stationPrecipMonthlyFormat(row.annual):"–"}</td>\n    </tr>`;\n  }).join("");\n\n  if(note){\n    note.textContent="Nur vollständige Kalendermonate werden summiert; der 29. Februar zählt in Schaltjahren mit. "\n      +"Der laufende Monat bleibt bis zu seinem Abschluss „–“. Die Jahressumme erscheint nur bei zwölf vollständigen Monaten.";\n  }\n}\n'
MONTHLY_PY_BLOCK = '\ndef observations_to_monthly_history(observations, current_year: int) -> list[dict[str, Any]]:\n    """Monatssummen je Jahr; Ausgabe nur für vollständig vorliegende Kalendermonate."""\n    values_by_month: dict[tuple[int, int], dict[int, float]] = defaultdict(dict)\n    for observation in observations:\n        day = observation.day\n        if day.year >= current_year:\n            continue\n        value = observation.values.get("rsk_high")\n        if value is None:\n            continue\n        values_by_month[(day.year, day.month)][day.day] = float(value)\n\n    years = sorted({year for year, _month in values_by_month})\n    history: list[dict[str, Any]] = []\n    for year in years:\n        months: list[float | None] = []\n        for month in range(1, 13):\n            day_values = values_by_month.get((year, month), {})\n            expected_days = calendar.monthrange(year, month)[1]\n            complete = len(day_values) == expected_days and all(\n                day_number in day_values for day_number in range(1, expected_days + 1)\n            )\n            if complete:\n                total = sum(day_values[day_number] for day_number in range(1, expected_days + 1))\n                months.append(round(total, 1))\n            else:\n                months.append(None)\n\n        if not any(value is not None for value in months):\n            continue\n        annual = (\n            round(sum(float(value) for value in months), 1)\n            if all(value is not None for value in months)\n            else None\n        )\n        history.append({"year": year, "months": months, "annual": annual})\n\n    return history\n\n\n'

def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: erwartete genau 1 Fundstelle, gefunden: {count}")
    return text.replace(old, new, 1)

def patch_index(index_path: Path) -> bool:
    text = index_path.read_text(encoding="utf-8")
    original = text

    if "/* Stationsniederschlag · Monatslisten */" not in text:
        text = replace_once(text, "</style>", CSS_BLOCK.rstrip() + "\n</style>", "CSS-Anker </style>")

    if 'id="stationPrecipMonthlyTable"' not in text:
        anchor = '    <p id="stationPrecipSourceNote" class="note"></p>'
        text = replace_once(text, anchor, HTML_BLOCK.rstrip() + "\n" + anchor,
                            "HTML-Anker stationPrecipSourceNote")

    if "function updateStationPrecipMonthlyTable(stationId)" not in text:
        anchor = "async function updateStationPrecipitation(){"
        text = replace_once(text, anchor, JS_BLOCK.rstrip() + "\n" + anchor,
                            "JS-Anker updateStationPrecipitation")

    call = "    updateStationPrecipMonthlyTable(stationId);"
    if call not in text:
        anchor = "    stationPrecipProfile=await profileResponse.json();"
        text = replace_once(text, anchor, anchor + "\n" + call,
                            "JS-Aufruf nach Profil-Laden")

    if text != original:
        index_path.write_text(text, encoding="utf-8", newline="\n")
        return True
    return False

def patch_updater(script_path: Path) -> bool:
    text = script_path.read_text(encoding="utf-8")
    original = text

    if "import calendar" not in text:
        text = replace_once(text, "import argparse\n", "import argparse\nimport calendar\n", "Import argparse")

    if "def observations_to_monthly_history(" not in text:
        anchor = "def build_profile_payload(\n"
        text = replace_once(text, anchor, MONTHLY_PY_BLOCK + anchor,
                            "Python-Anker build_profile_payload")

    assignment = "    monthly_history = observations_to_monthly_history(observations, current_year)\n"
    if assignment not in text:
        anchor = "    curves = observations_to_complete_curves(observations, current_year)\n"
        text = replace_once(text, anchor, anchor + assignment, "Python-Anker curves")

    if '"monthly_history": monthly_history,' not in text:
        anchor = '        "reference_year_list": reference_years,\n'
        text = replace_once(text, anchor, anchor + '        "monthly_history": monthly_history,\n',
                            "Payload-Anker reference_year_list")

    if "STATE_VERSION = 3" in text:
        text = text.replace("STATE_VERSION = 3", "STATE_VERSION = 4", 1)
    elif "STATE_VERSION = 4" not in text:
        raise RuntimeError("STATE_VERSION ist weder 3 noch 4; bitte Version prüfen.")

    if text != original:
        script_path.write_text(text, encoding="utf-8", newline="\n")
        return True
    return False

def main() -> int:
    root = Path.cwd()
    if not (root / "index.html").exists():
        root = Path(__file__).resolve().parent
    if not (root / "index.html").exists() and (root.parent / "index.html").exists():
        root = root.parent

    index_path = root / "index.html"
    script_path = root / "scripts" / "update_station_precip.py"
    missing = [str(path) for path in (index_path, script_path) if not path.exists()]
    if missing:
        print("FEHLER: Dateien nicht gefunden:")
        for path in missing:
            print("  -", path)
        print("\nLege dieses Skript ins Hauptverzeichnis des climate-dashboard-Repositories.")
        return 2

    changed_index = patch_index(index_path)
    changed_script = patch_updater(script_path)

    print("Stationsniederschlag · Monatslisten")
    print(f"  index.html: {'geändert' if changed_index else 'bereits aktuell'}")
    print(f"  scripts/update_station_precip.py: {'geändert' if changed_script else 'bereits aktuell'}")
    print("\nSTATE_VERSION = 4 erzwingt beim nächsten Niederschlagslauf einmalig")
    print("den vollständigen Neuaufbau der historischen Stationsprofile.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
