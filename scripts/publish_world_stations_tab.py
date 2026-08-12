#!/usr/bin/env python3
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

TAB_MARKER = '<!-- ================= WELTWEITE STATIONEN · STAGE 9 ================= -->'
JS_MARKER = '// ================= WELTWEITE STATIONEN · STAGE 9 ================='
CSS_MARKER = '/* ================= WELTWEITE STATIONEN · STAGE 9 ================= */'

METRIC_ORDER = ['tmax_highest','tmax_lowest','tmin_highest','tmin_lowest']


def read_publishable(path: Path):
    with path.open('r', encoding='utf-8-sig', newline='') as fh:
        rows = list(csv.DictReader(fh, delimiter=';'))
    return rows


def build_web_data(rows, unresolved_count: int):
    countries = {}
    status_counts = Counter()
    for r in rows:
        code = r.get('country_code','').strip()
        if not code:
            continue
        country = r.get('country','').strip()
        metric = r.get('metric','').strip()
        if metric not in METRIC_ORDER:
            continue
        status = r.get('master_status','').strip()
        status_counts[status] += 1
        item = countries.setdefault(code, {'code':code, 'country':country, 'metrics':{}})
        raw_value = r.get('canonical_value_c','').strip()
        value = float(raw_value) if raw_value else None
        item['metrics'][metric] = {
            'value': value,
            'date': r.get('canonical_date','').strip(),
            'site': r.get('canonical_site','').strip(),
            'station_id': r.get('canonical_station_id','').strip(),
            'status': status,
            'source_type': r.get('canonical_source_type','').strip(),
            'official': r.get('official_verified','').strip().lower() == 'yes',
            'source': r.get('canonical_source','').strip(),
        }
    return {
        'schema_version': 1,
        'dataset': 'world_station_records_stage9_publishable',
        'baseline_through': '2025-12-31',
        'publishable_rows': sum(len(v['metrics']) for v in countries.values()),
        'unresolved_rows': unresolved_count,
        'country_codes': len(countries),
        'status_counts': dict(status_counts),
        'countries': sorted(countries.values(), key=lambda x: x['country'].casefold()),
    }


WORLD_CSS = r'''
/* ================= WELTWEITE STATIONEN · STAGE 9 ================= */
.world-stations-kpis{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:10px;margin:0 0 16px}
.world-stations-kpi{background:#fff;border:1px solid #d8e0e5;border-radius:10px;padding:12px 14px;box-shadow:0 2px 8px rgba(0,0,0,.04)}
.world-stations-kpi .label{font-size:10px;text-transform:uppercase;letter-spacing:.35px;color:#68737b;font-weight:800}
.world-stations-kpi .value{font-size:22px;font-weight:850;color:#1f2a31;margin-top:5px}
.world-stations-kpi .detail{font-size:11px;color:var(--muted);margin-top:2px;line-height:1.4}
.world-stations-controls{display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px;padding:14px 16px;margin-bottom:14px;background:#fff;border-radius:9px;box-shadow:var(--shadow)}
.world-stations-controls .control-group{min-width:190px}
.world-stations-controls .world-search{min-width:min(360px,100%);flex:1}
.world-stations-controls input{width:100%;padding:9px 10px;border:1px solid #bbb;border-radius:6px;background:#fff;font:inherit}
.world-stations-table-wrap{max-height:68vh;overflow:auto;border:1px solid var(--border);border-radius:9px;background:#fff;box-shadow:var(--shadow)}
.world-stations-table{margin:0;min-width:1080px;font-variant-numeric:tabular-nums}
.world-stations-table thead th{position:sticky;top:0;z-index:3;background:#292f35;color:#fff;font-size:12px}
.world-stations-table td{text-align:left;vertical-align:middle;font-size:13px}
.world-stations-table td.world-value{text-align:right;font-weight:800;white-space:nowrap}
.world-stations-table td.world-date{white-space:nowrap}
.world-stations-table tr:hover td{background:#f6f8fa}
.world-status-badge{display:inline-flex;align-items:center;padding:4px 7px;border-radius:999px;font-size:10px;font-weight:800;white-space:nowrap;background:#edf1f4;color:#3d4850}
.world-status-badge.official{background:#e3f2e7;color:#245b30}
.world-status-badge.secondary{background:#fff1cf;color:#6a4a00}
.world-status-badge.ghcn{background:#e7eef8;color:#31577b}
.world-stations-result-note{margin:8px 1px 12px;color:var(--muted);font-size:12px;line-height:1.45}
.world-stations-empty{padding:24px;text-align:center;color:var(--muted)}
@media(max-width:900px){.world-stations-kpis{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.world-stations-kpis{grid-template-columns:1fr}.world-stations-controls .control-group{min-width:100%}}
'''

WORLD_HTML = r'''
<!-- ================= WELTWEITE STATIONEN · STAGE 9 ================= -->
<div id="worldStations" class="tab-content">
  <div class="section-header">
    <h2>Weltweite Stationen</h2>
    <p>Globale Temperatur-Extremreferenzen aus GHCN-Daily, ergänzt um offizielle und geprüfte sekundäre Länderreferenzen. Historische Basis bis einschließlich 31.12.2025.</p>
    <span class="section-status">Weltweite historische Basis · Stage 9</span>
  </div>
  <div id="worldStationsLoading" class="record-loading">Weltweite Stationsdaten werden beim ersten Öffnen geladen …</div>
  <div id="worldStationsContent" hidden>
    <div id="worldStationsKpis" class="world-stations-kpis"></div>
    <div class="world-stations-controls">
      <div class="control-group world-search">
        <label for="worldStationsSearch">Land, Ort oder Station suchen</label>
        <input id="worldStationsSearch" type="search" placeholder="z. B. Deutschland, Palermo, 03772 …" autocomplete="off">
      </div>
      <div class="control-group">
        <label for="worldStationsMetric">Kennzahl</label>
        <select id="worldStationsMetric">
          <option value="all">Alle Kennzahlen</option>
          <option value="tmax_highest">Höchste Tmax</option>
          <option value="tmax_lowest">Niedrigste Tmax</option>
          <option value="tmin_highest">Höchste Tmin</option>
          <option value="tmin_lowest">Niedrigste Tmin</option>
        </select>
      </div>
      <div class="control-group">
        <label for="worldStationsStatus">Quellenstatus</label>
        <select id="worldStationsStatus">
          <option value="all">Alle veröffentlichten</option>
          <option value="official">Offizielle Referenz</option>
          <option value="secondary">Sekundär bestätigt</option>
          <option value="ghcn">GHCN-Kandidat</option>
        </select>
      </div>
    </div>
    <div id="worldStationsResultNote" class="world-stations-result-note"></div>
    <div class="world-stations-table-wrap">
      <table class="world-stations-table">
        <thead><tr><th>Land / Gebiet</th><th>Kennzahl</th><th>Wert</th><th>Datum</th><th>Station / Ort</th><th>Stations-ID</th><th>Status</th></tr></thead>
        <tbody id="worldStationsTableBody"></tbody>
      </table>
    </div>
    <p class="note">Hinweis: Die 24 noch offenen QC-Kombinationen aus Stage 9 werden hier bewusst nicht als Rekord veröffentlicht. „GHCN-Kandidat“ bedeutet bereinigter Stationskandidat; eine amtliche nationale Bestätigung wird nur dort ausgewiesen, wo sie als eigene Referenz vorliegt.</p>
  </div>
</div>
'''

WORLD_JS = r'''
// ================= WELTWEITE STATIONEN · STAGE 9 =================
let worldStationsLoaded=false;
let worldStationsLoadingPromise=null;
let worldStationsData=null;
let worldStationsRows=[];
const WORLD_STATION_METRICS={
  tmax_highest:{label:"Höchste Tmax",short:"Tmax max"},
  tmax_lowest:{label:"Niedrigste Tmax",short:"Tmax min"},
  tmin_highest:{label:"Höchste Tmin",short:"Tmin max"},
  tmin_lowest:{label:"Niedrigste Tmin",short:"Tmin min"}
};
function worldStationsEscape(value){
  return String(value??"").replace(/[&<>\"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'\"':"&quot;","'":"&#39;"}[char]));
}
function worldStationsStatusGroup(row){
  if(row.status==="OFFICIAL_SOURCE_BACKED" || row.status==="OFFICIAL_COVERAGE_GAP") return "official";
  if(row.status==="SECONDARY_SOURCE_BACKED") return "secondary";
  return "ghcn";
}
function worldStationsStatusLabel(row){
  const group=worldStationsStatusGroup(row);
  if(group==="official") return row.status==="OFFICIAL_SOURCE_BACKED"?"Offiziell bestätigt":"Offizielle Referenz";
  if(group==="secondary") return "Sekundär bestätigt";
  return "GHCN-Kandidat";
}
function worldStationsFormatValue(value){
  if(!Number.isFinite(Number(value))) return "–";
  return `${Number(value).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} °C`;
}
function worldStationsFlatten(data){
  const rows=[];
  (data.countries||[]).forEach(country=>{
    Object.entries(country.metrics||{}).forEach(([metric,item])=>rows.push({
      country_code:country.code,
      country:country.country,
      metric,
      ...item
    }));
  });
  return rows.sort((a,b)=>a.country.localeCompare(b.country,"de") || Object.keys(WORLD_STATION_METRICS).indexOf(a.metric)-Object.keys(WORLD_STATION_METRICS).indexOf(b.metric));
}
function renderWorldStationsKpis(){
  const box=document.getElementById("worldStationsKpis");
  if(!box || !worldStationsData) return;
  box.innerHTML=`
    <div class="world-stations-kpi"><div class="label">Länder / Gebiete</div><div class="value">${Number(worldStationsData.country_codes||0).toLocaleString("de-DE")}</div><div class="detail">GHCN-Ländercodes in der Masterbasis</div></div>
    <div class="world-stations-kpi"><div class="label">Veröffentlicht</div><div class="value">${Number(worldStationsData.publishable_rows||0).toLocaleString("de-DE")}</div><div class="detail">Land-/Extrem-Kombinationen</div></div>
    <div class="world-stations-kpi"><div class="label">Noch offen</div><div class="value">${Number(worldStationsData.unresolved_rows||0).toLocaleString("de-DE")}</div><div class="detail">werden bewusst nicht angezeigt</div></div>
    <div class="world-stations-kpi"><div class="label">Historische Basis</div><div class="value">2025</div><div class="detail">Daten bis 31.12.2025</div></div>`;
}
function renderWorldStationsTable(){
  const tbody=document.getElementById("worldStationsTableBody");
  const note=document.getElementById("worldStationsResultNote");
  if(!tbody) return;
  const query=(document.getElementById("worldStationsSearch")?.value||"").trim().toLocaleLowerCase("de");
  const metric=document.getElementById("worldStationsMetric")?.value||"all";
  const status=document.getElementById("worldStationsStatus")?.value||"all";
  const filtered=worldStationsRows.filter(row=>{
    if(metric!=="all" && row.metric!==metric) return false;
    if(status!=="all" && worldStationsStatusGroup(row)!==status) return false;
    if(query){
      const haystack=[row.country,row.country_code,row.site,row.station_id].join(" ").toLocaleLowerCase("de");
      if(!haystack.includes(query)) return false;
    }
    return true;
  });
  if(note) note.textContent=`${filtered.length.toLocaleString("de-DE")} von ${worldStationsRows.length.toLocaleString("de-DE")} veröffentlichten Datensätzen angezeigt.`;
  if(!filtered.length){
    tbody.innerHTML='<tr><td colspan="7" class="world-stations-empty">Keine passenden Datensätze gefunden.</td></tr>';
    return;
  }
  tbody.innerHTML=filtered.map(row=>{
    const group=worldStationsStatusGroup(row);
    return `<tr>
      <td><strong>${worldStationsEscape(row.country)}</strong><br><span class="note">${worldStationsEscape(row.country_code)}</span></td>
      <td>${worldStationsEscape(WORLD_STATION_METRICS[row.metric]?.label||row.metric)}</td>
      <td class="world-value">${worldStationsFormatValue(row.value)}</td>
      <td class="world-date">${worldStationsEscape(row.date||"–")}</td>
      <td>${worldStationsEscape(row.site||"–")}</td>
      <td>${worldStationsEscape(row.station_id||"–")}</td>
      <td><span class="world-status-badge ${group}">${worldStationsEscape(worldStationsStatusLabel(row))}</span></td>
    </tr>`;
  }).join("");
}
function bindWorldStationsControls(){
  ["worldStationsSearch","worldStationsMetric","worldStationsStatus"].forEach(id=>{
    const el=document.getElementById(id);
    if(!el || el.dataset.worldBound) return;
    el.addEventListener(id==="worldStationsSearch"?"input":"change",renderWorldStationsTable);
    el.dataset.worldBound="1";
  });
}
async function ensureWorldStationsLoaded(){
  if(worldStationsLoaded){renderWorldStationsTable();return;}
  if(worldStationsLoadingPromise) return worldStationsLoadingPromise;
  const loading=document.getElementById("worldStationsLoading");
  const content=document.getElementById("worldStationsContent");
  worldStationsLoadingPromise=(async()=>{
    try{
      const response=await fetch("data/world_stations_stage9.json",{cache:"no-store"});
      if(!response.ok) throw new Error(`HTTP ${response.status}`);
      worldStationsData=await response.json();
      worldStationsRows=worldStationsFlatten(worldStationsData);
      renderWorldStationsKpis();
      bindWorldStationsControls();
      renderWorldStationsTable();
      if(loading) loading.hidden=true;
      if(content) content.hidden=false;
      worldStationsLoaded=true;
    }catch(error){
      console.error("Weltweite Stationsdaten konnten nicht geladen werden:",error);
      if(loading){loading.hidden=false;loading.textContent=`Weltweite Stationsdaten konnten nicht geladen werden: ${error.message}`;}
    }finally{
      worldStationsLoadingPromise=null;
    }
  })();
  return worldStationsLoadingPromise;
}
'''


def insert_once(text, marker, needle, payload, where='before'):
    if marker in text:
        return text, False
    if needle not in text:
        raise RuntimeError(f'Einfügemarke nicht gefunden: {needle[:80]}')
    replacement = payload + '\n' + needle if where == 'before' else needle + '\n' + payload
    return text.replace(needle, replacement, 1), True


def patch_index(text: str):
    changed = False
    text, c = insert_once(text, CSS_MARKER, '</style>', WORLD_CSS.rstrip(), 'before'); changed |= c

    button = '  <button class="tab-button" onclick="switchTab(\'worldStations\')">Weltweite Stationen</button>'
    if "switchTab('worldStations')" not in text:
        anchor = '  <button class="tab-button" onclick="switchTab(\'europeStations\')">Europa-Stationen</button>'
        if anchor not in text:
            raise RuntimeError('Tab-Anker Europa-Stationen nicht gefunden.')
        text = text.replace(anchor, anchor + '\n' + button, 1)
        changed = True

    text, c = insert_once(text, TAB_MARKER, '<!-- ================= STATIONSREKORDE ================= -->', WORLD_HTML.rstrip(), 'before'); changed |= c

    lazy = '  if(tab==="worldStations") ensureWorldStationsLoaded();'
    if lazy not in text:
        anchor = '  if(tab==="europeStations") ensureEuropeStationMap();'
        if anchor not in text:
            raise RuntimeError('switchTab-Anker EuropeStations nicht gefunden.')
        text = text.replace(anchor, anchor + '\n' + lazy, 1)
        changed = True

    text, c = insert_once(text, JS_MARKER, 'function initializeMobileTabNavigation(){', WORLD_JS.rstrip() + '\n\n', 'before'); changed |= c

    text = text.replace(
        '<!-- Climate Dashboard build 18.4: ERA5-Land V8.1 + Stations-V5 Europa-Rekordkarte -->',
        '<!-- Climate Dashboard build 18.5: ERA5-Land V8.1 + Europa-Rekordkarte + Weltweite Stationen Stage 9 -->',
        1,
    )
    return text, changed


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--index', default='index.html')
    p.add_argument('--publishable-csv', required=True)
    p.add_argument('--output-json', default='data/world_stations_stage9.json')
    p.add_argument('--unresolved-count', type=int, default=24)
    args=p.parse_args()

    index_path=Path(args.index)
    csv_path=Path(args.publishable_csv)
    out_path=Path(args.output_json)

    rows=read_publishable(csv_path)
    data=build_web_data(rows,args.unresolved_count)
    if data['publishable_rows'] != len(rows):
        raise RuntimeError(f"Publishable row mismatch: JSON={data['publishable_rows']} CSV={len(rows)}")
    out_path.parent.mkdir(parents=True,exist_ok=True)
    out_path.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')

    original=index_path.read_text(encoding='utf-8')
    patched,changed=patch_index(original)
    if changed:
        index_path.write_text(patched,encoding='utf-8')

    print(json.dumps({
        'index_changed':changed,
        'publishable_rows':data['publishable_rows'],
        'country_codes':data['country_codes'],
        'unresolved_rows':data['unresolved_rows'],
        'status_counts':data['status_counts'],
        'output_json':str(out_path),
    },ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
