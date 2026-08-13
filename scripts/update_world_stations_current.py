#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

GHCN_YEAR_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/by_year/{year}.csv.gz"
HARD_MIN = -1000
HARD_MAX = 600
USER_AGENT = "climate-dashboard-world-ghcn-current/1.0"

ACTIVE_BUTTON_HTML = '''      <button id="worldStationsActiveOnly" class="action world-stations-active-toggle" type="button" aria-pressed="false">Nur aktive Stationen anzeigen</button>
'''
ACTIVE_CSS = r'''
.world-stations-active-toggle{background:#fff!important;color:#334149!important;border:1px solid #9aa6af!important}
.world-stations-active-toggle.is-active{background:#2f5f87!important;color:#fff!important;border-color:#2f5f87!important}
.world-stations-current-note{margin:0 0 12px;padding:9px 11px;border-radius:7px;background:#f3f7fa;border:1px solid #d5e0e7;color:#44525c;font-size:11px;line-height:1.45}
'''

OVERLAY_JS = r'''
function worldStationsApplyCurrentOverlay(){
  if(!worldStationsCurrentData) return;
  const overlay=worldStationsCurrentData.stations||{};
  const cutoff=worldStationsCurrentData.active_cutoff_date||"";
  for(const s of worldStationsRows){
    const o=overlay[s.id];
    s.active=false;
    s.currentLast="";
    if(!o) continue;
    s.currentLast=o[0]||"";
    s.active=Boolean(cutoff && s.currentLast && s.currentLast>=cutoff);
    const txLast=o[1]||"";
    const txValue=o[2];
    const txDate=o[3]||"";
    const tnLast=o[4]||"";
    const tnValue=o[5];
    const tnDate=o[6]||"";
    if(txLast && (!s.txLast || txLast>s.txLast)) s.txLast=txLast;
    if(tnLast && (!s.tnLast || tnLast>s.tnLast)) s.tnLast=tnLast;
    if(Number.isFinite(Number(txValue)) && (!Number.isFinite(Number(s.tx)) || Number(txValue)>Number(s.tx))){
      s.tx=Number(txValue); s.txDate=txDate; s.txIsCurrent=true;
    }
    if(Number.isFinite(Number(tnValue)) && (!Number.isFinite(Number(s.tn)) || Number(tnValue)<Number(s.tn))){
      s.tn=Number(tnValue); s.tnDate=tnDate; s.tnIsCurrent=true;
    }
  }
}
function worldStationsActiveOnly(){
  return document.getElementById("worldStationsActiveOnly")?.getAttribute("aria-pressed")==="true";
}
function updateWorldStationsActiveButton(){
  const btn=document.getElementById("worldStationsActiveOnly");
  if(!btn) return;
  const on=worldStationsActiveOnly();
  btn.classList.toggle("is-active",on);
  btn.textContent=on?"✓ Nur aktive Stationen anzeigen":"Nur aktive Stationen anzeigen";
}
function updateWorldStationsMapVisibility(){
  if(!worldStationsLayer || !worldStationMarkerById.size) return;
  const onlyActive=worldStationsActiveOnly();
  let visible=0;
  for(const marker of worldStationMarkerById.values()){
    const shouldShow=!onlyActive || marker._worldActive===true;
    const present=worldStationsLayer.hasLayer(marker);
    if(shouldShow && !present) marker.addTo(worldStationsLayer);
    if(!shouldShow && present) worldStationsLayer.removeLayer(marker);
    if(shouldShow) visible++;
  }
  const status=document.getElementById("worldStationsMapStatus");
  if(status && worldStationsCurrentData){
    status.textContent=onlyActive
      ? `${visible.toLocaleString("de-DE")} aktive GHCN-Temperaturstationen · Aktiv seit ${worldStationsCurrentData.active_cutoff_date}.`
      : `${visible.toLocaleString("de-DE")} GHCN-Temperaturstationen · aktuelle Daten bis ${worldStationsCurrentData.latest_valid_date||"–"}.`;
  }
}
function renderWorldStationsCurrentNote(){
  let note=document.getElementById("worldStationsCurrentNote");
  if(!note){
    const controls=document.querySelector("#worldStations .world-stations-controls");
    if(!controls) return;
    note=document.createElement("div");
    note.id="worldStationsCurrentNote";
    note.className="world-stations-current-note";
    controls.insertAdjacentElement("afterend",note);
  }
  if(!worldStationsCurrentData){
    note.textContent="2026-Aktualisierung derzeit nicht verfügbar; angezeigt wird die historische Basis bis Ende 2025.";
    return;
  }
  note.textContent=`GHCN-Daily aktuell bis ${worldStationsCurrentData.latest_valid_date||"–"} · ${Number(worldStationsCurrentData.active_station_count||0).toLocaleString("de-DE")} aktive Stationen. Aktiv = mindestens eine gültige TMAX- oder TMIN-Meldung in den letzten ${worldStationsCurrentData.active_window_days} Tagen relativ zum aktuellsten GHCN-Datum.`;
}
'''

def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")

def download_year(year: int):
    url=GHCN_YEAR_URL.format(year=year)
    req=Request(url, headers={"User-Agent":USER_AGENT, "Accept-Encoding":"identity"})
    return urlopen(req, timeout=900), url

def parse_year(stream, baseline_ids: set[str]):
    stations={}
    latest=""
    counts={"rows":0,"temp_rows":0,"valid_temp_rows":0,"qflag_rejected":0,"hard_rejected":0,"unknown_station_rows":0}
    with gzip.GzipFile(fileobj=stream, mode="rb") as gz, io.TextIOWrapper(gz, encoding="ascii", errors="replace", newline="") as txt:
        reader=csv.reader(txt)
        for row in reader:
            counts["rows"]+=1
            if len(row)<7:
                continue
            sid, ymd, element, raw_value, mflag, qflag, sflag = row[:7]
            if element not in {"TMAX","TMIN"}:
                continue
            counts["temp_rows"]+=1
            if sid not in baseline_ids:
                counts["unknown_station_rows"]+=1
                continue
            if qflag.strip():
                counts["qflag_rejected"]+=1
                continue
            try:
                value=int(raw_value)
            except ValueError:
                continue
            if not (HARD_MIN <= value <= HARD_MAX):
                counts["hard_rejected"]+=1
                continue
            try:
                d=f"{ymd[0:4]}-{ymd[4:6]}-{ymd[6:8]}"
                date.fromisoformat(d)
            except Exception:
                continue
            counts["valid_temp_rows"]+=1
            if d>latest: latest=d
            s=stations.setdefault(sid, {"last_any":"","tx_last":"","tx_max":None,"tx_date":"","tn_last":"","tn_min":None,"tn_date":""})
            if d>s["last_any"]: s["last_any"]=d
            if element=="TMAX":
                if d>s["tx_last"]: s["tx_last"]=d
                if s["tx_max"] is None or value>s["tx_max"] or (value==s["tx_max"] and d<s["tx_date"]):
                    s["tx_max"]=value; s["tx_date"]=d
            else:
                if d>s["tn_last"]: s["tn_last"]=d
                if s["tn_min"] is None or value<s["tn_min"] or (value==s["tn_min"] and d<s["tn_date"]):
                    s["tn_min"]=value; s["tn_date"]=d
    return stations, latest, counts

def build_overlay(baseline_path: Path, output_path: Path, year: int, active_days: int):
    base=json.loads(baseline_path.read_text(encoding="utf-8"))
    ids={row[0] for row in base.get("stations",[]) if row}
    with download_year(year)[0] as response:
        source_url=GHCN_YEAR_URL.format(year=year)
        parsed, latest, counts=parse_year(response, ids)
    if not latest:
        raise RuntimeError("Keine gültigen TMAX/TMIN-Daten im aktuellen GHCN-Jahresfile gefunden.")
    cutoff=(date.fromisoformat(latest)-timedelta(days=active_days)).isoformat()
    compact={}
    active_count=0
    for sid,s in parsed.items():
        if s["last_any"]>=cutoff:
            active_count+=1
        compact[sid]=[
            s["last_any"],
            s["tx_last"],
            None if s["tx_max"] is None else round(s["tx_max"]/10.0,1),
            s["tx_date"],
            s["tn_last"],
            None if s["tn_min"] is None else round(s["tn_min"]/10.0,1),
            s["tn_date"],
        ]
    out={
        "schema_version":1,
        "dataset":"world_ghcn_temperature_current_overlay",
        "source_year":year,
        "source_url":source_url,
        "updated_at_utc":utc_now(),
        "latest_valid_date":latest,
        "active_window_days":active_days,
        "active_cutoff_date":cutoff,
        "baseline_station_count":len(ids),
        "stations_with_current_year_temperature":len(compact),
        "active_station_count":active_count,
        "counts":counts,
        "station_fields":["last_any","tmax_last","tmax_year_max_c","tmax_year_max_date","tmin_last","tmin_year_min_c","tmin_year_min_date"],
        "stations":compact,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, ensure_ascii=False, separators=(",",":"))+"\n", encoding="utf-8")
    return out

def patch_index(path: Path):
    text=path.read_text(encoding="utf-8")
    changed=False

    if "worldStationsActiveOnly" not in text:
        needle='      <button id="worldStationsReset" class="action" type="button">Filter zurücksetzen</button>\n'
        if needle not in text:
            raise RuntimeError("World-Stations-Resetbutton im index.html nicht gefunden.")
        text=text.replace(needle, ACTIVE_BUTTON_HTML+needle, 1)
        changed=True

    if ".world-stations-active-toggle" not in text:
        text=text.replace("</style>", ACTIVE_CSS+"\n</style>", 1)
        changed=True

    if "let worldStationsCurrentData=null;" not in text:
        needle="let worldStationsData=null;\n"
        if needle not in text: raise RuntimeError("worldStationsData JS-Marke nicht gefunden.")
        text=text.replace(needle, needle+"let worldStationsCurrentData=null;\n",1)
        changed=True

    if "function worldStationsApplyCurrentOverlay()" not in text:
        needle="function renderWorldStationsKpis(){"
        if needle not in text: raise RuntimeError("renderWorldStationsKpis JS-Marke nicht gefunden.")
        text=text.replace(needle, OVERLAY_JS+"\n"+needle,1)
        changed=True

    active_line='    if(worldStationsActiveOnly() && !s.active) return false;\n'
    filter_needle='  return worldStationsRows.filter(s=>{\n'
    if active_line not in text:
        if filter_needle not in text: raise RuntimeError("World-Stations-Filter nicht gefunden.")
        text=text.replace(filter_needle, filter_needle+active_line,1)
        changed=True

    event_block='''  const activeBtn=document.getElementById("worldStationsActiveOnly");
  if(activeBtn && !activeBtn.dataset.worldBound){
    activeBtn.addEventListener("click",()=>{
      activeBtn.setAttribute("aria-pressed",worldStationsActiveOnly()?"false":"true");
      updateWorldStationsActiveButton();
      renderWorldStationsTable({resetPage:true});
      updateWorldStationsMapVisibility();
    });
    activeBtn.dataset.worldBound="1";
  }
'''
    bind_needle='  const reset=document.getElementById("worldStationsReset");\n'
    if event_block not in text:
        if bind_needle not in text: raise RuntimeError("World-Stations-Bind-Marke nicht gefunden.")
        text=text.replace(bind_needle,event_block+bind_needle,1)
        changed=True

    marker_needle='      marker.bindPopup(()=>worldStationsPopupHtml(s),{maxWidth:360});\n'
    marker_line='      marker._worldActive=s.active===true;\n'
    if marker_line not in text:
        if marker_needle not in text: raise RuntimeError("World-Stations-Marker-Marke nicht gefunden.")
        text=text.replace(marker_needle,marker_line+marker_needle,1)
        changed=True

    old='''      const response=await fetch("data/world_stations_stage9.json",{cache:"no-store"});
      if(!response.ok) throw new Error(`HTTP ${response.status}`);
      worldStationsData=await response.json();
      worldStationsRows=(worldStationsData.stations||[]).map(worldStationsDecode);
'''
    new='''      const [response,currentResponse]=await Promise.all([
        fetch("data/world_stations_stage9.json",{cache:"no-store"}),
        fetch("data/world_stations_current.json",{cache:"no-store"})
      ]);
      if(!response.ok) throw new Error(`HTTP ${response.status}`);
      worldStationsData=await response.json();
      worldStationsCurrentData=currentResponse.ok?await currentResponse.json():null;
      worldStationsRows=(worldStationsData.stations||[]).map(worldStationsDecode);
      worldStationsApplyCurrentOverlay();
      renderWorldStationsCurrentNote();
      updateWorldStationsActiveButton();
'''
    if 'fetch("data/world_stations_current.json"' not in text:
        if old not in text: raise RuntimeError("World-Stations-Ladeblock nicht gefunden.")
        text=text.replace(old,new,1)
        changed=True

    old_status='''  if(status) status.textContent=`${worldStationMarkerById.size.toLocaleString("de-DE")} GHCN-Temperaturstationen auf der Karte · historische Werte bis 31.12.2025.`;
'''
    if old_status in text:
        text=text.replace(old_status,'  updateWorldStationsMapVisibility();\n',1)
        changed=True

    old_head='<span class="section-status">Historische Basis bis 31.12.2025 · GHCN-Daily</span>'
    new_head='<span class="section-status">Historische Basis bis 31.12.2025 + laufende GHCN-Daily-Daten 2026</span>'
    if old_head in text:
        text=text.replace(old_head,new_head,1); changed=True
    old_note='TMAX = höchstes gültiges Tagesmaximum der Station bis Ende 2025. TMIN = tiefstes gültiges Tagesminimum der Station bis Ende 2025.'
    new_note='TMAX = höchstes gültiges Tagesmaximum der Station inklusive laufender 2026-Daten. TMIN = tiefstes gültiges Tagesminimum der Station inklusive laufender 2026-Daten.'
    if old_note in text:
        text=text.replace(old_note,new_note,1); changed=True

    if changed:
        path.write_text(text, encoding="utf-8")
    return changed

def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/"index.html"
        p.write_text('''<style></style>
<div id="worldStations"><span class="section-status">Historische Basis bis 31.12.2025 · GHCN-Daily</span>
<div class="world-stations-controls">
      <button id="worldStationsReset" class="action" type="button">Filter zurücksetzen</button>
</div>
<p>TMAX = höchstes gültiges Tagesmaximum der Station bis Ende 2025. TMIN = tiefstes gültiges Tagesminimum der Station bis Ende 2025.</p></div>
<script>
let worldStationsData=null;
function getFilteredWorldStations(){
  return worldStationsRows.filter(s=>{
    if(cc && s.cc!==cc) return false;
});}
function renderWorldStationsKpis(){}
function bindWorldStationsControls(){
  const reset=document.getElementById("worldStationsReset");
}
async function buildWorldStationsMap(){
      const marker=L.circleMarker([1,2],{});
      marker.bindPopup(()=>worldStationsPopupHtml(s),{maxWidth:360});
  if(status) status.textContent=`${worldStationMarkerById.size.toLocaleString("de-DE")} GHCN-Temperaturstationen auf der Karte · historische Werte bis 31.12.2025.`;
}
async function ensureWorldStationsLoaded(){
      const response=await fetch("data/world_stations_stage9.json",{cache:"no-store"});
      if(!response.ok) throw new Error(`HTTP ${response.status}`);
      worldStationsData=await response.json();
      worldStationsRows=(worldStationsData.stations||[]).map(worldStationsDecode);
}
</script>''',encoding="utf-8")
        assert patch_index(p)
        t=p.read_text(encoding="utf-8")
        assert "worldStationsActiveOnly" in t
        assert 'fetch("data/world_stations_current.json"' in t
        assert "worldStationsApplyCurrentOverlay" in t
    print("SELF-TEST OK")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--baseline-json", default="data/world_stations_stage9.json")
    ap.add_argument("--output", default="data/world_stations_current.json")
    ap.add_argument("--index", default="index.html")
    ap.add_argument("--year", type=int, default=datetime.now(timezone.utc).year)
    ap.add_argument("--active-days", type=int, default=60)
    ap.add_argument("--self-test", action="store_true")
    args=ap.parse_args()
    if args.self_test:
        self_test(); return
    changed=patch_index(Path(args.index))
    out=build_overlay(Path(args.baseline_json),Path(args.output),args.year,args.active_days)
    print(json.dumps({
        "index_changed":changed,
        "year":args.year,
        "latest_valid_date":out["latest_valid_date"],
        "stations_with_current_year_temperature":out["stations_with_current_year_temperature"],
        "active_station_count":out["active_station_count"],
        "active_cutoff_date":out["active_cutoff_date"],
        "output":args.output,
        "output_bytes":Path(args.output).stat().st_size,
    },ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
