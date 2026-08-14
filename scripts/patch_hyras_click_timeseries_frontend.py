#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "index.html"
MARKER = "// HYRAS_CLICK_TIMESERIES_V1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"HYRAS-Klick-Patch fehlgeschlagen ({label}): Treffer={count}")
    return text.replace(old, new, 1)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("HYRAS Klick-Zeitreihe und Maxima sind bereits im Frontend eingebaut.")
        return 0

    # 1) CSS
    css_anchor = "/* ================= 16.1 GEBIETSMITTEL-KARTENVERGLEICH ================= */"
    css = r'''
/* Version 15.6: HYRAS Klick-Zeitreihe + Kartenmaxima */
.hyras-canvas-stage{position:relative;width:fit-content;max-width:100%;margin:0 auto}
.hyras-canvas-stage canvas{display:block;max-width:100%;height:auto}
.hyras-selected-pin{position:absolute;z-index:30;width:18px;height:18px;border-radius:50%;border:3px solid #fff;background:#111;box-shadow:0 1px 7px rgba(0,0,0,.55);transform:translate(-50%,-50%);pointer-events:none}
.hyras-selected-pin::after{content:"";position:absolute;left:50%;top:50%;width:4px;height:4px;border-radius:50%;background:#fff;transform:translate(-50%,-50%)}
.hyras-maxima-strip{display:flex;justify-content:center;flex-wrap:wrap;gap:7px 12px;margin:7px 4px 2px;font-size:12px;color:#394650}
.hyras-maxima-strip span{display:inline-flex;align-items:center;gap:5px}
.hyras-maxima-badge{display:inline-grid;place-items:center;width:19px;height:19px;border-radius:50%;background:#b42318;color:#fff;font-size:11px;font-weight:800;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.28)}
.hyras-point-analysis{margin-top:16px;padding:16px;background:#fff;border:1px solid var(--border);border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.04)}
.hyras-point-analysis[hidden]{display:none}
.hyras-point-analysis-head{display:flex;flex-wrap:wrap;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px}
.hyras-point-analysis-head h3{margin:0 0 5px;font-size:20px}
.hyras-point-analysis-head p{margin:0;color:var(--muted);font-size:13px;line-height:1.45}
.hyras-point-stats{display:grid;grid-template-columns:repeat(4,minmax(145px,1fr));gap:10px;margin:12px 0}
.hyras-point-stat{padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:#fafbfc}
.hyras-point-stat .label{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.02em}
.hyras-point-stat .value{margin-top:5px;font-size:18px;font-weight:800;font-variant-numeric:tabular-nums}
.hyras-point-chart-wrap{position:relative;height:360px;margin-top:10px}
.hyras-point-chart-wrap canvas{width:100%!important;height:100%!important}
.hyras-point-note{margin:10px 0 0;color:var(--muted);font-size:12px;line-height:1.5}
@media(max-width:800px){.hyras-point-stats{grid-template-columns:1fr 1fr}.hyras-point-chart-wrap{height:320px}}
@media(max-width:520px){.hyras-point-stats{grid-template-columns:1fr}}

'''
    text = replace_once(text, css_anchor, css + css_anchor, "CSS")

    # 2) Analysis panel below map.
    html_old = '''  <p class="note" style="margin-top:10px"><strong>Interaktiv:</strong> Maus über die Karte bewegen (auf Touchgeräten tippen), um den Niederschlag der Rasterzelle, das Mittel 1991–2020, Prozent und Abweichung zu sehen.</p>\n  <p id="hyrasReferenceNote" class="note" style="margin-top:8px">Quelle: Deutscher Wetterdienst, HYRAS-DE-PR. Das Raster hat 1 km Auflösung. Laufender Monat, aktuelle Jahreszeit und Jahr werden bis zum letzten HYRAS-Tag fortgeschrieben und mit exakt demselben Kalenderabschnitt 1991–2020 verglichen.</p>'''
    html_new = '''  <p class="note" style="margin-top:10px"><strong>Interaktiv:</strong> Maus über die Karte bewegen, um die Rasterwerte zu sehen. <strong>Klick auf die Karte:</strong> Der nächstgelegene 5-km-Analysepunkt wird gewählt und darunter erscheint seine Niederschlags-Zeitreihe seit 1931. Die roten Markierungen 1–3 zeigen die räumlich getrennten Maxima der aktuell dargestellten Karte.</p>\n\n  <div id="hyrasPointAnalysis" class="hyras-point-analysis" hidden>\n    <div class="hyras-point-analysis-head">\n      <div>\n        <h3 id="hyrasPointTitle">HYRAS-Punktzeitreihe</h3>\n        <p id="hyrasPointSubtitle">Auf die Karte klicken, um einen Rasterpunkt auszuwählen.</p>\n      </div>\n    </div>\n    <div class="hyras-point-stats">\n      <div class="hyras-point-stat"><div class="label">Ausgewähltes Jahr</div><div id="hyrasPointSelectedValue" class="value">–</div></div>\n      <div class="hyras-point-stat"><div class="label">Rang</div><div id="hyrasPointRank" class="value">–</div></div>\n      <div class="hyras-point-stat"><div class="label">Rekordmaximum</div><div id="hyrasPointRecord" class="value">–</div></div>\n      <div class="hyras-point-stat"><div class="label">Mittel 1991–2020</div><div id="hyrasPointReference" class="value">–</div></div>\n    </div>\n    <div class="hyras-point-chart-wrap"><canvas id="hyrasPointChart"></canvas></div>\n    <p id="hyrasPointNote" class="hyras-point-note"></p>\n  </div>\n\n  <p id="hyrasReferenceNote" class="note" style="margin-top:8px">Quelle: Deutscher Wetterdienst, HYRAS-DE-PR. Das Raster hat 1 km Auflösung. Laufender Monat, aktuelle Jahreszeit und Jahr werden bis zum letzten HYRAS-Tag fortgeschrieben und mit exakt demselben Kalenderabschnitt 1991–2020 verglichen.</p>'''
    text = replace_once(text, html_old, html_new, "Analyse-Panel")

    # 3) Global state.
    globals_old = '''let hyrasPresetState=null;\nlet hyrasLivePresetState=null;\nconst hyrasWebImageCache=new Map();'''
    globals_new = '''let hyrasPresetState=null;\nlet hyrasLivePresetState=null;\nlet hyrasPointChart=null;\nlet hyrasClickSeriesManifest=null;\nlet hyrasSelectedGridPoint=null;\nlet hyrasPointRequest=0;\nconst hyrasClickSeriesPackCache=new Map();\nconst hyrasWebImageCache=new Map();'''
    text = replace_once(text, globals_old, globals_new, "Globale Zustände")

    # 4) Draw canvas in its own stage and hook maxima + click selection.
    draw_old = '''  const frame=document.getElementById("hyrasMapFrame");frame.innerHTML="";const wrap=document.createElement("div");wrap.className="hyras-dynamic-wrap";wrap.innerHTML=`<div class="hyras-dynamic-title">${title}</div><div class="hyras-dynamic-subtitle">${subtitle} · ${hyrasMetricConfig(metric).label}</div>`;wrap.appendChild(canvas);const legend=document.createElement("div");legend.className="hyras-dynamic-legend";legend.innerHTML=hyrasDynamicLegend(metric);wrap.appendChild(legend);frame.appendChild(wrap);hyrasAttachMouseover(canvas,wrap,state,geoLookup);'''
    draw_new = '''  const frame=document.getElementById("hyrasMapFrame");frame.innerHTML="";const wrap=document.createElement("div");wrap.className="hyras-dynamic-wrap";wrap.innerHTML=`<div class="hyras-dynamic-title">${title}</div><div class="hyras-dynamic-subtitle">${subtitle} · ${hyrasMetricConfig(metric).label}</div>`;const stage=document.createElement("div");stage.className="hyras-canvas-stage";stage.appendChild(canvas);wrap.appendChild(stage);const legend=document.createElement("div");legend.className="hyras-dynamic-legend";legend.innerHTML=hyrasDynamicLegend(metric);wrap.appendChild(legend);frame.appendChild(wrap);hyrasAttachMouseover(canvas,wrap,state,geoLookup);hyrasInstallClickAnalysis(canvas,stage,wrap,state,geoLookup,raster,metric);'''
    text = replace_once(text, draw_old, draw_new, "Karten-Hook")

    # 5) JavaScript helpers. Function declarations are hoisted, so inserting before renderHyras is sufficient.
    js = r'''// HYRAS_CLICK_TIMESERIES_V1
function hyrasClickSeriesBase(){return `${HYRAS_DATA_BASE}/click_series_5km`;}
async function hyrasLoadClickSeriesManifest(){
  if(hyrasClickSeriesManifest)return hyrasClickSeriesManifest;
  const response=await fetch(`${hyrasClickSeriesBase()}/manifest.json?t=${encodeURIComponent(hyrasIndex?.data_through||Date.now())}`,{cache:"no-store"});
  if(!response.ok)throw new Error(`Klick-Zeitreihenmanifest nicht verfügbar (${response.status}).`);
  hyrasClickSeriesManifest=await response.json();
  return hyrasClickSeriesManifest;
}
async function hyrasGunzipBuffer(buffer){
  if(typeof DecompressionStream==="undefined")throw new Error("Dieser Browser unterstützt die komprimierten HYRAS-Zeitreihen nicht.");
  const stream=new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).arrayBuffer();
}
async function hyrasLoadClickMonth(month){
  const key=Number(month);
  if(hyrasClickSeriesPackCache.has(key))return hyrasClickSeriesPackCache.get(key);
  const promise=(async()=>{
    const manifest=await hyrasLoadClickSeriesManifest(),mm=String(key).padStart(2,"0");
    const response=await fetch(`${hyrasClickSeriesBase()}/month_${mm}.u16.gz?t=${encodeURIComponent(manifest.last_year||"")}`);
    if(!response.ok)throw new Error(`HYRAS-Zeitreihenpack Monat ${mm} fehlt (${response.status}).`);
    const raw=await hyrasGunzipBuffer(await response.arrayBuffer()),values=new Uint16Array(raw);
    const expected=Number(manifest.years?.length||0)*Number(manifest.width||0)*Number(manifest.height||0);
    if(values.length!==expected)throw new Error(`HYRAS-Zeitreihenpack Monat ${mm} hat ${values.length} statt ${expected} Werte.`);
    return values;
  })().catch(error=>{hyrasClickSeriesPackCache.delete(key);throw error;});
  hyrasClickSeriesPackCache.set(key,promise);return promise;
}
function hyrasPartsFromDates(startIso,endIso){
  if(!startIso||!endIso)return [];
  const start=new Date(`${startIso}T00:00:00Z`),end=new Date(`${endIso}T00:00:00Z`),targetYear=end.getUTCFullYear(),parts=[];
  let y=start.getUTCFullYear(),m=start.getUTCMonth()+1;
  const ey=end.getUTCFullYear(),em=end.getUTCMonth()+1;
  for(let guard=0;guard<24;guard++){
    parts.push({month:m,offset:y-targetYear});
    if(y===ey&&m===em)break;
    m++;if(m===13){m=1;y++;}
  }
  return parts;
}
function hyrasCurrentSeriesSpec(){
  const special=document.getElementById("hyrasPeriodSelect")?.value;
  if(special==="__custom__")return null;
  if(special==="__historical__"){
    const state=hyrasHistoricalState;if(!state)return null;
    const selection=hyrasHistoricalSelection(Number(state.year),state.type,Number(state.month||1));
    return {label:state.label||"Historischer Zeitraum",parts:selection.map(item=>({month:Number(item.month),offset:Number(item.year)-Number(state.year)})),selectedYear:Number(state.year),appendCurrent:false,partial:false,historical:true};
  }
  const period=hyrasSelectedPeriod();if(!period)return null;
  return {label:period.label||"Aktueller Zeitraum",parts:hyrasPartsFromDates(period.start_date,period.end_date),selectedYear:Number(hyrasIndex?.year),appendCurrent:true,partial:Boolean(period.daily_live),historical:false,endDate:period.end_date};
}
function hyrasStateValueAtNorm(raster,state,xNorm,yNorm){
  if(!raster||!state?.width||!state?.height)return NaN;
  const col=Math.max(0,Math.min(state.width-1,Math.round(xNorm*(state.width-1)))),row=Math.max(0,Math.min(state.height-1,Math.round(yNorm*(state.height-1)))),idx=row*state.width+col;
  return raster.valid?.[idx]&&Number.isFinite(raster.values?.[idx])?Number(raster.values[idx]):NaN;
}
function hyrasPointLocationText(coord){
  if(!coord)return "Rasterpunkt";
  return `${Number(coord.lat).toLocaleString("de-DE",{minimumFractionDigits:3,maximumFractionDigits:3})}° N · ${Number(coord.lon).toLocaleString("de-DE",{minimumFractionDigits:3,maximumFractionDigits:3})}° E`;
}
function hyrasPeriodSeriesName(label){
  return String(label||"Niederschlag").replace(/\s+aktuell\s+\d{4}(?:\/\d{2})?$/i,"").replace(/\s+\d{4}$/i,"");
}
function hyrasSeriesRank(entries,year){
  const sorted=[...entries].filter(item=>Number.isFinite(item.value)).sort((a,b)=>b.value-a.value||a.year-b.year),found=sorted.findIndex(item=>item.year===year);
  return found>=0?{rank:found+1,count:sorted.length}:null;
}
function hyrasRenderPointSeries({spec,years,values,currentValue,coord,analysisKm}){
  const panel=document.getElementById("hyrasPointAnalysis");if(!panel)return;
  panel.hidden=false;
  let plotYears=[...years],plotValues=[...values],selectedYear=Number(spec.selectedYear),selectedValue=NaN;
  if(spec.appendCurrent&&Number.isFinite(currentValue)){
    const existing=plotYears.indexOf(selectedYear);if(existing>=0)plotValues[existing]=currentValue;else{plotYears.push(selectedYear);plotValues.push(currentValue);}
  }
  const selectedIndex=plotYears.indexOf(selectedYear);if(selectedIndex>=0)selectedValue=Number(plotValues[selectedIndex]);
  const historicalEntries=years.map((year,i)=>({year,value:Number(values[i])})).filter(item=>Number.isFinite(item.value));
  const comparisonEntries=plotYears.map((year,i)=>({year,value:Number(plotValues[i])})).filter(item=>Number.isFinite(item.value));
  const refVals=historicalEntries.filter(item=>item.year>=1991&&item.year<=2020).map(item=>item.value),reference=refVals.length?refVals.reduce((a,b)=>a+b,0)/refVals.length:NaN;
  const recordPool=spec.partial?historicalEntries:comparisonEntries,record=recordPool.length?[...recordPool].sort((a,b)=>b.value-a.value)[0]:null;
  const rank=spec.partial?null:hyrasSeriesRank(comparisonEntries,selectedYear);
  const seriesName=hyrasPeriodSeriesName(spec.label);
  document.getElementById("hyrasPointTitle").textContent=`${seriesName} · Zeitreihe seit ${plotYears[0]||"1931"}`;
  document.getElementById("hyrasPointSubtitle").textContent=`${hyrasPointLocationText(coord)} · HYRAS-Analyseraster ${analysisKm} km`;
  document.getElementById("hyrasPointSelectedValue").textContent=Number.isFinite(selectedValue)?`${selectedValue.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} l/m² · ${selectedYear}`:"–";
  document.getElementById("hyrasPointRank").textContent=spec.partial?"laufend · kein Rang":rank?`${rank.rank}. von ${rank.count}`:"–";
  document.getElementById("hyrasPointRecord").textContent=record?`${record.value.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} l/m² · ${record.year}`:"–";
  document.getElementById("hyrasPointReference").textContent=Number.isFinite(reference)?`${reference.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} l/m²`:"–";
  const note=document.getElementById("hyrasPointNote");
  note.textContent=spec.partial?`Hinweis: ${selectedYear} reicht nur bis ${hyrasDate(spec.endDate)}. Frühere Jahre zeigen für den bereits begonnenen Monatsumfang vollständige Monatswerte; deshalb wird für das laufende Jahr bewusst kein historischer Rang angegeben.`:`Zeitreihe aus den monatlichen HYRAS-Rastern. Rang und Rekord beziehen sich auf die an diesem ${analysisKm}-km-Analysepunkt verfügbaren Jahre.`;

  if(hyrasPointChart){hyrasPointChart.destroy();hyrasPointChart=null;}
  const ctx=document.getElementById("hyrasPointChart")?.getContext("2d");if(!ctx)return;
  const selectedData=plotYears.map((year,i)=>year===selectedYear?plotValues[i]:null),referenceData=plotYears.map(()=>Number.isFinite(reference)?reference:null);
  hyrasPointChart=new Chart(ctx,{type:"line",data:{labels:plotYears,datasets:[
    {label:"Niederschlag",data:plotValues,borderColor:"#52718a",backgroundColor:"rgba(82,113,138,.12)",borderWidth:1.6,pointRadius:1.8,pointHoverRadius:4,tension:.12,spanGaps:true},
    {label:"Mittel 1991–2020",data:referenceData,borderColor:"#222",borderWidth:1.4,borderDash:[6,5],pointRadius:0,spanGaps:true},
    {label:`Auswahl ${selectedYear}`,data:selectedData,borderColor:"#b42318",backgroundColor:"#b42318",pointRadius:6,pointHoverRadius:7,showLine:false}
  ]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{legend:{display:true},tooltip:{callbacks:{label:context=>`${context.dataset.label}: ${Number(context.raw).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} l/m²`}}},scales:{x:{title:{display:true,text:"Jahr"},ticks:{maxTicksLimit:16}},y:{beginAtZero:true,title:{display:true,text:"Niederschlag (l/m²)"}}}}});
}
async function hyrasUpdatePointAnalysis(state,geoLookupPath,point){
  const request=++hyrasPointRequest,panel=document.getElementById("hyrasPointAnalysis");if(panel)panel.hidden=false;
  const spec=hyrasCurrentSeriesSpec();
  if(!spec){
    if(panel){document.getElementById("hyrasPointTitle").textContent="HYRAS-Punktzeitreihe";document.getElementById("hyrasPointSubtitle").textContent="Für freie Start-/Endzeiträume ist die lange Punktzeitreihe nicht verfügbar. Bitte Monat, Jahreszeit, Jahr oder eine historische Karte wählen.";}
    return;
  }
  try{
    const manifest=await hyrasLoadClickSeriesManifest();if(request!==hyrasPointRequest)return;
    const col=Math.max(0,Math.min(manifest.width-1,Math.round(point.xNorm*(manifest.width-1)))),row=Math.max(0,Math.min(manifest.height-1,Math.round(point.yNorm*(manifest.height-1))));
    const xNorm=manifest.width>1?col/(manifest.width-1):0,yNorm=manifest.height>1?row/(manifest.height-1):0;
    hyrasSelectedGridPoint={xNorm,yNorm};
    const uniqueMonths=[...new Set(spec.parts.map(part=>part.month))],packs=new Map();
    await Promise.all(uniqueMonths.map(async month=>packs.set(month,await hyrasLoadClickMonth(month))));if(request!==hyrasPointRequest)return;
    const yearToIndex=new Map((manifest.years||[]).map((year,i)=>[Number(year),i])),years=[],values=[],plane=manifest.width*manifest.height,missing=Number(manifest.missing_value??65535),scale=Number(manifest.value_scale||10);
    for(const targetYear of (manifest.years||[]).map(Number)){
      let total=0,ok=true;
      for(const part of spec.parts){
        const yi=yearToIndex.get(targetYear+Number(part.offset||0));if(yi===undefined){ok=false;break;}
        const q=packs.get(part.month)?.[yi*plane+row*manifest.width+col];if(q===undefined||q===missing){ok=false;break;}
        total+=Number(q)/scale;
      }
      if(ok){years.push(targetYear);values.push(total);}
    }
    const currentValue=spec.appendCurrent?hyrasStateValueAtNorm(state.current,state,xNorm,yNorm):NaN;
    let coord=null;
    if(geoLookupPath){try{const lookup=await hyrasLoadGeoLookup(geoLookupPath),scol=Math.round(xNorm*(state.width-1)),srow=Math.round(yNorm*(state.height-1));coord=hyrasLookupCoord(lookup,scol,srow);}catch(error){console.warn("HYRAS Klick-Koordinate:",error);}}
    if(request!==hyrasPointRequest)return;
    hyrasRenderPointSeries({spec,years,values,currentValue,coord,analysisKm:Number(manifest.resolution_km||5)});
  }catch(error){
    console.error("HYRAS Klick-Zeitreihe:",error);
    if(panel){document.getElementById("hyrasPointTitle").textContent="HYRAS-Punktzeitreihe";document.getElementById("hyrasPointSubtitle").textContent=error.message;}
  }
}
function hyrasFindSeparatedMaxima(raster,state,count=3){
  const resolution=Math.max(.5,Number(state?.resolutionKm||1)),block=Math.max(4,Math.round(25/resolution)),minDist=Math.max(8,Math.round(45/resolution)),candidates=[];
  for(let y0=0;y0<state.height;y0+=block){for(let x0=0;x0<state.width;x0+=block){let best=-Infinity,bx=-1,by=-1;const y1=Math.min(state.height,y0+block),x1=Math.min(state.width,x0+block);for(let y=y0;y<y1;y++){let idx=y*state.width+x0;for(let x=x0;x<x1;x++,idx++){if(raster.valid?.[idx]&&Number.isFinite(raster.values?.[idx])&&Number(raster.values[idx])>best){best=Number(raster.values[idx]);bx=x;by=y;}}}if(bx>=0)candidates.push({col:bx,row:by,value:best});}}
  candidates.sort((a,b)=>b.value-a.value);const chosen=[];
  for(const candidate of candidates){if(chosen.every(item=>(item.col-candidate.col)**2+(item.row-candidate.row)**2>=minDist**2)){chosen.push(candidate);if(chosen.length>=count)break;}}
  return chosen;
}
function hyrasMetricMaxText(value,metric){
  if(metric==="percent")return `${Number(value).toLocaleString("de-DE",{maximumFractionDigits:0})} %`;
  const sign=metric==="anomaly"&&Number(value)>0?"+":"";return `${sign}${Number(value).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} l/m²`;
}
function hyrasDrawMapMaxima(canvas,raster,state,metric){
  const maxima=hyrasFindSeparatedMaxima(raster,state,3),ctx=canvas.getContext("2d"),sx=canvas.width/state.width,sy=canvas.height/state.height,radius=8*Math.max(1,Math.min(sx,sy));
  ctx.save();ctx.textAlign="center";ctx.textBaseline="middle";ctx.font=`700 ${Math.round(radius*1.05)}px Arial`;
  maxima.forEach((item,i)=>{const x=(item.col+.5)*sx,y=(item.row+.5)*sy;ctx.beginPath();ctx.arc(x,y,radius,0,Math.PI*2);ctx.fillStyle="#b42318";ctx.fill();ctx.lineWidth=Math.max(2,Math.round(radius*.22));ctx.strokeStyle="#fff";ctx.stroke();ctx.fillStyle="#fff";ctx.fillText(String(i+1),x,y+.4);});ctx.restore();
  return maxima;
}
function hyrasPlaceSelectedPin(stage,point){
  stage.querySelectorAll(".hyras-selected-pin").forEach(node=>node.remove());if(!point)return;
  const pin=document.createElement("div");pin.className="hyras-selected-pin";pin.style.left=`${point.xNorm*100}%`;pin.style.top=`${point.yNorm*100}%`;stage.appendChild(pin);
}
function hyrasInstallClickAnalysis(canvas,stage,wrap,state,geoLookupPath,raster,metric){
  const maxima=hyrasDrawMapMaxima(canvas,raster,state,metric),strip=document.createElement("div");strip.className="hyras-maxima-strip";strip.innerHTML=maxima.map((item,i)=>`<span><b class="hyras-maxima-badge">${i+1}</b>${hyrasMetricMaxText(item.value,metric)}</span>`).join("");wrap.appendChild(strip);
  const selectPoint=async rawPoint=>{
    try{const manifest=await hyrasLoadClickSeriesManifest(),col=Math.max(0,Math.min(manifest.width-1,Math.round(rawPoint.xNorm*(manifest.width-1)))),row=Math.max(0,Math.min(manifest.height-1,Math.round(rawPoint.yNorm*(manifest.height-1)))),point={xNorm:manifest.width>1?col/(manifest.width-1):0,yNorm:manifest.height>1?row/(manifest.height-1):0};hyrasSelectedGridPoint=point;hyrasPlaceSelectedPin(stage,point);await hyrasUpdatePointAnalysis(state,geoLookupPath,point);}catch(error){console.error("HYRAS Punktwahl:",error);}
  };
  canvas.addEventListener("click",event=>{const rect=canvas.getBoundingClientRect();if(!rect.width||!rect.height)return;selectPoint({xNorm:Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),yNorm:Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))});});
  if(hyrasSelectedGridPoint){hyrasPlaceSelectedPin(stage,hyrasSelectedGridPoint);hyrasUpdatePointAnalysis(state,geoLookupPath,hyrasSelectedGridPoint).catch(error=>console.error("HYRAS Punktzeitreihe aktualisieren:",error));}
}
'''
    text = replace_once(text, "function renderHyras(){\n", js + "function renderHyras(){\n", "JavaScript")

    # 6) Version badge.
    text = replace_once(
        text,
        "Version 15.5 · laufender Monat &amp; aktuelle Jahreszeit tagesgenau · Historie ab 1931 · Referenz 1991–2020",
        "Version 15.6 · Klick-Zeitreihe seit 1931 · Top-3-Maxima · laufende Zeiträume tagesgenau",
        "Versionsbadge",
    )

    TARGET.write_text(text, encoding="utf-8")
    print("HYRAS Klick-Zeitreihe seit 1931 und Top-3-Maxima im Frontend eingebaut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
