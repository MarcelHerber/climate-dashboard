#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "index.html"
MARKER = "// HYRAS_TMEAN_FRONTEND_V1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"HYRAS-Tmean-Frontend-Patch fehlgeschlagen ({label}): Treffer={count}")
    return text.replace(old, new, 1)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("HYRAS Tmean ist bereits im Frontend eingebaut.")
        return 0

    # Parameter selector before the existing period selector.
    controls_old = '''  <div class="controls">\n    <div class="control-group">\n      <label for="hyrasPeriodSelect">Zeitraum</label>'''
    controls_new = '''  <div class="controls">\n    <div class="control-group">\n      <label for="hyrasParameterSelect">Parameter</label>\n      <select id="hyrasParameterSelect">\n        <option value="precipitation">Niederschlag</option>\n        <option value="tmean">2-m-Temperaturmittel</option>\n      </select>\n    </div>\n    <div class="control-group">\n      <label for="hyrasPeriodSelect">Zeitraum</label>'''
    text = replace_once(text, controls_old, controls_new, "Parameter-Auswahl")

    # Header wording/version.
    text = text.replace(
        "Flächendeckender Niederschlag auf dem 1-km-Raster HYRAS-DE des Deutschen Wetterdienstes.",
        "Flächendeckender Niederschlag und Temperatur auf dem HYRAS-DE-Raster des Deutschen Wetterdienstes.",
        1,
    )
    text = text.replace(
        "Version 15.6 · Klick-Zeitreihe seit 1931 · Top-3-Maxima · laufende Zeiträume tagesgenau",
        "Version 15.7 · Niederschlag + Tmean · Historie ab 1931/1951 · Referenz 1991–2020",
        1,
    )

    # Extra state next to HYRAS state variables.
    state_old = '''let hyrasLivePresetState=null;\nlet hyrasPointChart=null;'''
    state_new = '''let hyrasLivePresetState=null;\nlet hyrasTmeanIndex=null;\nlet hyrasTmeanHistoryManifest=null;\nlet hyrasTmeanHistoricalState=null;\nconst hyrasTmeanFileCache=new Map();\nconst hyrasTmeanMonthCache=new Map();\nlet hyrasPointChart=null;'''
    text = replace_once(text, state_old, state_new, "Tmean-State")

    js = r'''// HYRAS_TMEAN_FRONTEND_V1
function hyrasParameter(){return document.getElementById("hyrasParameterSelect")?.value||"precipitation";}
function hyrasTmeanBase(){return `${HYRAS_DATA_BASE}/tmean`;}
async function hyrasTmeanFetchJson(path){
  const response=await fetch(`${hyrasTmeanBase()}/${path}?t=${encodeURIComponent(hyrasTmeanIndex?.data_through||Date.now())}`,{cache:"no-store"});
  if(!response.ok)throw new Error(`HYRAS Tmean ${path} nicht verfügbar (${response.status}).`);
  return response.json();
}
async function hyrasTmeanGunzip(buffer){
  if(typeof DecompressionStream==="undefined")throw new Error("Dieser Browser unterstützt die komprimierten HYRAS-Tmean-Raster nicht.");
  const stream=new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).arrayBuffer();
}
async function hyrasTmeanLoadI16(path){
  if(hyrasTmeanFileCache.has(path))return hyrasTmeanFileCache.get(path);
  const promise=(async()=>{
    const response=await fetch(`${hyrasTmeanBase()}/${path}?t=${encodeURIComponent(hyrasTmeanIndex?.data_through||"")}`);
    if(!response.ok)throw new Error(`Tmean-Raster ${path} fehlt (${response.status}).`);
    return new Int16Array(await hyrasTmeanGunzip(await response.arrayBuffer()));
  })().catch(error=>{hyrasTmeanFileCache.delete(path);throw error;});
  hyrasTmeanFileCache.set(path,promise);return promise;
}
function hyrasTmeanDecodePlane(raw,width,height,scale=100,missing=-32768,offset=0){
  const n=width*height,values=new Float32Array(n),valid=new Uint8Array(n);
  for(let i=0;i<n;i++){
    const q=raw[offset+i];
    if(q===undefined||q===missing){values[i]=NaN;continue;}
    values[i]=Number(q)/scale;valid[i]=1;
  }
  return {values,valid,width,height};
}
async function hyrasTmeanEnsureLoaded(){
  if(!hyrasTmeanIndex)hyrasTmeanIndex=await hyrasTmeanFetchJson("index.json");
  if(!hyrasTmeanHistoryManifest)hyrasTmeanHistoryManifest=await hyrasTmeanFetchJson(hyrasTmeanIndex.history_manifest||"history_5km/manifest.json");
  return hyrasTmeanIndex;
}
function hyrasTmeanMetricOptions(hasAnomaly=true){
  const select=document.getElementById("hyrasMetricSelect");if(!select)return;
  const previous=select.value;
  select.innerHTML='<option value="absolute">Temperatur (°C)</option><option value="anomaly">Abweichung 1991–2020 (K)</option>';
  select.querySelector('option[value="anomaly"]').disabled=!hasAnomaly;
  select.value=(previous==="anomaly"&&hasAnomaly)?"anomaly":"absolute";
}
function hyrasRestorePrecipMetricOptions(){
  const select=document.getElementById("hyrasMetricSelect");if(!select)return;
  select.innerHTML='<option value="percent">Prozent des Mittels 1991–2020</option><option value="sum">Niederschlagssumme</option><option value="anomaly">Abweichung in l/m²</option>';
  select.value="percent";
}
function hyrasTmeanDefaultPeriod(){
  const periods=hyrasTmeanIndex?.periods||[];
  return periods.find(p=>p.period_type==="season_live")||periods.find(p=>p.period_type==="month_live")||periods.find(p=>p.key===`${hyrasTmeanIndex?.year}_${String(hyrasTmeanIndex?.latest_complete_month||1).padStart(2,"0")}`)||periods[0]||null;
}
function hyrasTmeanSelectedPeriod(){
  const key=document.getElementById("hyrasPeriodSelect")?.value;
  return (hyrasTmeanIndex?.periods||[]).find(p=>p.key===key)||hyrasTmeanDefaultPeriod();
}
function hyrasTmeanPopulatePeriods(){
  const select=document.getElementById("hyrasPeriodSelect");if(!select||!hyrasTmeanIndex)return;
  const periods=hyrasTmeanIndex.periods||[];select.innerHTML="";
  const live=document.createElement("optgroup");live.label="Aktueller Datenstand";
  const complete=document.createElement("optgroup");complete.label="Abgeschlossene Perioden 2026";
  periods.forEach(period=>{
    const opt=document.createElement("option");opt.value=period.key;opt.textContent=period.label;
    (period.live?live:complete).appendChild(opt);
  });
  if(live.children.length)select.appendChild(live);if(complete.children.length)select.appendChild(complete);
  const hist=document.createElement("optgroup");hist.label="Historische Karten";
  const hop=document.createElement("option");hop.value="__historical__";hop.textContent=`Historische Karte ${hyrasTmeanIndex.history_first_year}–${hyrasTmeanIndex.history_last_year}`;hist.appendChild(hop);select.appendChild(hist);
  const def=hyrasTmeanDefaultPeriod();if(def)select.value=def.key;
}
function hyrasTmeanPopulateHistoricalYears(){
  const select=document.getElementById("hyrasHistoricalYear"),manifest=hyrasTmeanHistoryManifest;if(!select||!manifest)return;
  const years=[...(manifest.years||[])].sort((a,b)=>b-a);select.innerHTML=years.map(y=>`<option value="${y}">${y}</option>`).join("");
  if(years.length)select.value=String(years[0]);
  const msg=document.getElementById("hyrasHistoricalMessage");if(msg)msg.textContent=`Tmean-Historie ${manifest.first_year}–${manifest.last_year} · ${manifest.resolution_km} km. Monat, Jahreszeit oder Jahr wählen.`;
}
function hyrasRestorePrecipHistoricalYears(){
  const select=document.getElementById("hyrasHistoricalYear");if(!select||!hyrasHistoricalManifest)return;
  const years=[...(hyrasHistoricalManifest.years||[])].sort((a,b)=>b-a);select.innerHTML=years.map(y=>`<option value="${y}">${y}</option>`).join("");if(years.length)select.value=String(years[0]);
}
function hyrasTmeanHistoricalSelection(year,type,month){
  if(type==="month")return [{year,month}];
  if(type==="spring")return [3,4,5].map(m=>({year,month:m}));
  if(type==="summer")return [6,7,8].map(m=>({year,month:m}));
  if(type==="autumn")return [9,10,11].map(m=>({year,month:m}));
  if(type==="winter")return [{year:year-1,month:12},{year,month:1},{year,month:2}];
  return Array.from({length:12},(_,i)=>({year,month:i+1}));
}
function hyrasTmeanHistoricalLabel(year,type,month){
  const monthNames=["","Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"];
  if(type==="month")return `${monthNames[month]} ${year}`;
  if(type==="spring")return `Frühling ${year}`;if(type==="summer")return `Sommer ${year}`;if(type==="autumn")return `Herbst ${year}`;if(type==="winter")return `Winter ${year}`;return `Jahr ${year}`;
}
function hyrasTmeanDays(year,month){return new Date(Date.UTC(year,month,0)).getUTCDate();}
async function hyrasTmeanLoadMonthPack(month){
  const m=Number(month);if(hyrasTmeanMonthCache.has(m))return hyrasTmeanMonthCache.get(m);
  const path=`history_${hyrasTmeanHistoryManifest.resolution_km}km/month_${String(m).padStart(2,"0")}.i16.gz`;
  const promise=hyrasTmeanLoadI16(path);hyrasTmeanMonthCache.set(m,promise);return promise;
}
async function hyrasTmeanHistoricalRaster(selection,targetYear){
  const mf=hyrasTmeanHistoryManifest,w=Number(mf.width),h=Number(mf.height),plane=w*h,years=(mf.years||[]).map(Number),yearIndex=new Map(years.map((y,i)=>[y,i])),scale=Number(mf.value_scale||100),missing=Number(mf.missing_value??-32768);
  const months=[...new Set(selection.map(x=>x.month))],packs=new Map();await Promise.all(months.map(async m=>packs.set(m,await hyrasTmeanLoadMonthPack(m))));
  const out=new Float32Array(plane),valid=new Uint8Array(plane),weightSum=new Float32Array(plane);
  for(const item of selection){
    const yi=yearIndex.get(Number(item.year));if(yi===undefined)throw new Error(`Tmean-Jahr ${item.year} nicht verfügbar.`);
    const raw=packs.get(item.month),weight=hyrasTmeanDays(item.year,item.month),offset=yi*plane;
    for(let i=0;i<plane;i++){const q=raw[offset+i];if(q===missing)continue;out[i]+=Number(q)/scale*weight;weightSum[i]+=weight;}
  }
  for(let i=0;i<plane;i++){if(weightSum[i]>0){out[i]/=weightSum[i];valid[i]=1;}else out[i]=NaN;}
  return {values:out,valid,width:w,height:h,resolutionKm:Number(mf.resolution_km||5),targetYear};
}
async function hyrasTmeanHistoricalReference(type,month){
  const mf=hyrasTmeanHistoryManifest,w=Number(mf.width),h=Number(mf.height),plane=w*h,sum=new Float64Array(plane),count=new Uint16Array(plane);
  for(let year=1991;year<=2020;year++){
    const selection=hyrasTmeanHistoricalSelection(year,type,month),state=await hyrasTmeanHistoricalRaster(selection,year);
    for(let i=0;i<plane;i++){if(state.valid[i]){sum[i]+=state.values[i];count[i]++;}}
  }
  const values=new Float32Array(plane),valid=new Uint8Array(plane);for(let i=0;i<plane;i++){if(count[i]){values[i]=sum[i]/count[i];valid[i]=1;}else values[i]=NaN;}
  return {values,valid,width:w,height:h,resolutionKm:Number(mf.resolution_km||5)};
}
function hyrasTmeanSubtract(a,b){
  const n=a.values.length,values=new Float32Array(n),valid=new Uint8Array(n);for(let i=0;i<n;i++){if(a.valid[i]&&b.valid[i]){values[i]=a.values[i]-b.values[i];valid[i]=1;}else values[i]=NaN;}return {values,valid,width:a.width,height:a.height,resolutionKm:a.resolutionKm};
}
function hyrasTmeanMean(raster){let s=0,n=0;for(let i=0;i<raster.values.length;i++){if(raster.valid[i]&&Number.isFinite(raster.values[i])){s+=raster.values[i];n++;}}return n?s/n:NaN;}
function hyrasTmeanHexRgb(hex){const n=parseInt(hex.slice(1),16);return [(n>>16)&255,(n>>8)&255,n&255];}
function hyrasTmeanInterpColor(value,stops){
  if(!Number.isFinite(value))return [0,0,0,0];if(value<=stops[0][0])return [...hyrasTmeanHexRgb(stops[0][1]),255];if(value>=stops.at(-1)[0])return [...hyrasTmeanHexRgb(stops.at(-1)[1]),255];
  for(let i=1;i<stops.length;i++){if(value<=stops[i][0]){const [a,ca]=stops[i-1],[b,cb]=stops[i],t=(value-a)/(b-a),ra=hyrasTmeanHexRgb(ca),rb=hyrasTmeanHexRgb(cb);return [0,1,2].map(k=>Math.round(ra[k]+(rb[k]-ra[k])*t)).concat(255);}}
  return [0,0,0,255];
}
function hyrasTmeanColor(value,mode){
  const absolute=[[-15,"#313695"],[-10,"#4575b4"],[-5,"#74add1"],[0,"#abd9e9"],[5,"#e0f3f8"],[10,"#ffffbf"],[15,"#fee090"],[20,"#fdae61"],[25,"#f46d43"],[30,"#d73027"],[35,"#a50026"]];
  const anomaly=[[-6,"#313695"],[-4,"#4575b4"],[-2,"#74add1"],[-1,"#abd9e9"],[0,"#f7f7f7"],[1,"#fdae61"],[2,"#f46d43"],[4,"#d73027"],[6,"#a50026"]];
  return hyrasTmeanInterpColor(value,mode==="anomaly"?anomaly:absolute);
}
function hyrasTmeanLegend(mode){
  const vals=mode==="anomaly"?[-6,-4,-2,-1,0,1,2,4,6]:[-15,-10,-5,0,5,10,15,20,25,30,35];
  return vals.map(v=>{const [r,g,b]=hyrasTmeanColor(v,mode);return `<span><i style="background:rgb(${r},${g},${b})"></i>${v>0&&mode==="anomaly"?"+":""}${v}${mode==="anomaly"?" K":" °C"}</span>`;}).join("");
}
async function hyrasTmeanDrawMap(raster,{title,subtitle,mode,resolutionKm}){
  const raw=document.createElement("canvas");raw.width=raster.width;raw.height=raster.height;const rctx=raw.getContext("2d"),img=rctx.createImageData(raw.width,raw.height);
  for(let i=0,j=0;i<raster.values.length;i++,j+=4){if(!raster.valid[i]){img.data[j+3]=0;continue;}const [r,g,b,a]=hyrasTmeanColor(raster.values[i],mode);img.data[j]=r;img.data[j+1]=g;img.data[j+2]=b;img.data[j+3]=a;}
  rctx.putImageData(img,0,0);const scale=Number(resolutionKm||1)<=1?1:4,canvas=document.createElement("canvas");canvas.width=raw.width*scale;canvas.height=raw.height*scale;const ctx=canvas.getContext("2d");ctx.imageSmoothingEnabled=false;ctx.drawImage(raw,0,0,canvas.width,canvas.height);
  const boundary=hyrasIndex?.interactive?.boundary_overlay_1km;if(boundary){try{const response=await fetch(`${HYRAS_DATA_BASE}/${boundary}?t=${Date.now()}`);if(response.ok){const bmp=await createImageBitmap(await response.blob());ctx.imageSmoothingEnabled=true;ctx.drawImage(bmp,0,0,canvas.width,canvas.height);bmp.close?.();}}catch(error){console.warn("Tmean-Grenzen:",error);}}
  const frame=document.getElementById("hyrasMapFrame");frame.innerHTML="";const wrap=document.createElement("div");wrap.className="hyras-dynamic-wrap";wrap.innerHTML=`<div class="hyras-dynamic-title">${title}</div><div class="hyras-dynamic-subtitle">${subtitle}</div>`;wrap.appendChild(canvas);const legend=document.createElement("div");legend.className="hyras-dynamic-legend";legend.innerHTML=hyrasTmeanLegend(mode);wrap.appendChild(legend);frame.appendChild(wrap);
  const link=document.getElementById("hyrasOpenImage");if(link){link.textContent="PNG herunterladen";link.target="";link.download=`hyras_tmean_${mode}.png`;link.href=canvas.toDataURL("image/png");link.style.display="inline-block";}
}
function hyrasTmeanSetKpis({label,dateLabel,currentMean,referenceMean,anomalyMean,live=false,resolutionKm=1}){
  document.getElementById("hyrasPeriodStat").textContent=label||"–";document.getElementById("hyrasDataThrough").textContent=dateLabel||"–";
  const cur=document.getElementById("hyrasCurrentMean"),ref=document.getElementById("hyrasReferenceMean"),pct=document.getElementById("hyrasPercentMean"),detail=document.getElementById("hyrasAnomalyMean");
  if(cur?.parentElement?.querySelector("h4"))cur.parentElement.querySelector("h4").textContent="Rastermittel";if(ref?.parentElement?.querySelector("h4"))ref.parentElement.querySelector("h4").textContent="Mittel 1991–2020";if(pct?.parentElement?.querySelector("h4"))pct.parentElement.querySelector("h4").textContent="Abweichung";
  cur.textContent=Number.isFinite(currentMean)?`${currentMean.toLocaleString("de-DE",{minimumFractionDigits:2,maximumFractionDigits:2})} °C`:"–";document.getElementById("hyrasCurrentMeanDetail").textContent=`HYRAS-Tmean · ${resolutionKm} km Darstellung`;
  ref.textContent=Number.isFinite(referenceMean)?`${referenceMean.toLocaleString("de-DE",{minimumFractionDigits:2,maximumFractionDigits:2})} °C`:"–";document.getElementById("hyrasReferenceMeanDetail").textContent=live?"für laufenden Teilzeitraum noch nicht verfügbar":"gleicher Zeitraum 1991–2020";
  pct.textContent=Number.isFinite(anomalyMean)?`${anomalyMean>=0?"+":""}${anomalyMean.toLocaleString("de-DE",{minimumFractionDigits:2,maximumFractionDigits:2})} K`:"–";detail.textContent=Number.isFinite(anomalyMean)?"gegenüber 1991–2020":"Abweichung noch nicht verfügbar";
}
async function hyrasTmeanRenderCurrent(period){
  const mode=document.getElementById("hyrasMetricSelect")?.value||"absolute",hasAnomaly=Boolean(period.anomaly);hyrasTmeanMetricOptions(hasAnomaly);const selectedMode=document.getElementById("hyrasMetricSelect")?.value||"absolute";
  const path=selectedMode==="anomaly"?period.anomaly:period.absolute;if(!path)throw new Error("Für diesen laufenden Tmean-Zeitraum ist die Abweichung noch nicht verfügbar.");
  const raw=await hyrasTmeanLoadI16(path),w=Number(hyrasTmeanIndex.grid_1km.width),h=Number(hyrasTmeanIndex.grid_1km.height),raster=hyrasTmeanDecodePlane(raw,w,h,100,-32768);
  const stats=period.stats||{},anom=Number(stats.anomaly_mean_k),ref=Number(stats.reference_mean_c),cur=Number(stats.current_mean_c);
  hyrasTmeanSetKpis({label:period.label,dateLabel:`${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)}`,currentMean:cur,referenceMean:ref,anomalyMean:anom,live:Boolean(period.live),resolutionKm:1});
  await hyrasTmeanDrawMap(raster,{title:`HYRAS Tmean · ${period.label}`,subtitle:`${selectedMode==="anomaly"?"Abweichung 1991–2020":"2-m-Temperaturmittel"} · ${hyrasDate(period.start_date)}–${hyrasDate(period.end_date)}`,mode:selectedMode,resolutionKm:1});
  const note=document.getElementById("hyrasReferenceNote");if(note)note.textContent=period.reference_exact?"Quelle: Deutscher Wetterdienst · HYRAS-DE Tmean. Abweichung gegenüber dem gleichen Zeitraum 1991–2020.":"Quelle: Deutscher Wetterdienst · HYRAS-DE Tmean. Für laufende Teilzeiträume ist in dieser Stufe zunächst die absolute Temperatur verfügbar.";
}
async function hyrasTmeanApplyHistorical(){
  const msg=document.getElementById("hyrasHistoricalMessage");try{
    await hyrasTmeanEnsureLoaded();const year=Number(document.getElementById("hyrasHistoricalYear")?.value),type=document.getElementById("hyrasHistoricalType")?.value||"month",month=Number(document.getElementById("hyrasHistoricalMonth")?.value||1);if(!Number.isFinite(year))throw new Error("Bitte ein historisches Jahr auswählen.");
    const selection=hyrasTmeanHistoricalSelection(year,type,month),available=new Set((hyrasTmeanHistoryManifest.years||[]).map(Number));for(const item of selection){if(!available.has(item.year))throw new Error(`${hyrasTmeanHistoricalLabel(year,type,month)} benötigt das nicht verfügbare Jahr ${item.year}.`);}
    if(msg)msg.textContent="Historische Tmean-Karte wird aus den Monatsrastern zusammengesetzt …";const current=await hyrasTmeanHistoricalRaster(selection,year),reference=await hyrasTmeanHistoricalReference(type,month);hyrasTmeanHistoricalState={year,type,month,label:hyrasTmeanHistoricalLabel(year,type,month),current,reference,anomaly:hyrasTmeanSubtract(current,reference)};
    const select=document.getElementById("hyrasPeriodSelect");if(select)select.value="__historical__";await hyrasTmeanRenderHistorical();if(msg)msg.textContent=`${hyrasTmeanHistoricalState.label} geladen · ${hyrasTmeanHistoryManifest.resolution_km}-km-Analyseraster.`;
  }catch(error){console.error("Tmean Historie:",error);if(msg){msg.className="hyras-custom-message error";msg.textContent=error.message;}}
}
async function hyrasTmeanRenderHistorical(){
  const state=hyrasTmeanHistoricalState;if(!state){const frame=document.getElementById("hyrasMapFrame");if(frame)frame.innerHTML='<div class="hyras-loading">Historisches Tmean-Jahr unten auswählen und „Anzeigen“ klicken.</div>';return;}
  hyrasTmeanMetricOptions(true);const mode=document.getElementById("hyrasMetricSelect")?.value||"absolute",raster=mode==="anomaly"?state.anomaly:state.current,cur=hyrasTmeanMean(state.current),ref=hyrasTmeanMean(state.reference),anom=cur-ref;
  hyrasTmeanSetKpis({label:state.label,dateLabel:`Historische HYRAS-Tmean-Karte · ${state.year}`,currentMean:cur,referenceMean:ref,anomalyMean:anom,live:false,resolutionKm:Number(hyrasTmeanHistoryManifest.resolution_km||5)});
  await hyrasTmeanDrawMap(raster,{title:`HYRAS Tmean · ${state.label}`,subtitle:`${mode==="anomaly"?"Abweichung 1991–2020":"2-m-Temperaturmittel"} · Historie seit ${hyrasTmeanHistoryManifest.first_year}`,mode,resolutionKm:Number(hyrasTmeanHistoryManifest.resolution_km||5)});
  const note=document.getElementById("hyrasReferenceNote");if(note)note.textContent=`Quelle: Deutscher Wetterdienst · HYRAS-DE Tmean. Historische Karten ${hyrasTmeanHistoryManifest.first_year}–${hyrasTmeanHistoryManifest.last_year} auf ${hyrasTmeanHistoryManifest.resolution_km}-km-Analyseraster; Referenz 1991–2020.`;
}
async function renderHyrasTmean(){
  try{await hyrasTmeanEnsureLoaded();document.getElementById("hyrasPointAnalysis")?.setAttribute("hidden","");const special=document.getElementById("hyrasPeriodSelect")?.value;if(special==="__historical__"){await hyrasTmeanRenderHistorical();return;}const period=hyrasTmeanSelectedPeriod();if(period)await hyrasTmeanRenderCurrent(period);}catch(error){console.error("HYRAS Tmean:",error);const frame=document.getElementById("hyrasMapFrame");if(frame)frame.innerHTML=`<div class="hyras-loading">${error.message}</div>`;}
}
async function hyrasSwitchParameter(){
  const isTmean=hyrasParameter()==="tmean",custom=document.getElementById("hyrasCustomApply")?.closest(".hyras-custom-range"),panel=document.getElementById("hyrasPointAnalysis");if(panel)panel.hidden=true;hyrasTmeanHistoricalState=null;hyrasHistoricalState=null;hyrasCustomState=null;hyrasPresetState=null;hyrasLivePresetState=null;
  if(isTmean){
    if(custom)custom.style.display="none";const status=document.getElementById("hyrasStatus");if(status)status.textContent="HYRAS Tmean wird geladen …";await hyrasTmeanEnsureLoaded();hyrasTmeanPopulatePeriods();hyrasTmeanPopulateHistoricalYears();hyrasTmeanMetricOptions(Boolean(hyrasTmeanSelectedPeriod()?.anomaly));if(status)status.textContent=`Tmean · Daten bis ${hyrasDate(hyrasTmeanIndex.data_through)} · Historie ${hyrasTmeanIndex.history_first_year}–${hyrasTmeanIndex.history_last_year}`;await renderHyrasTmean();
  }else{
    if(custom)custom.style.display="";hyrasRestorePrecipMetricOptions();populateHyrasPeriods();hyrasRestorePrecipHistoricalYears();const status=document.getElementById("hyrasStatus");if(status&&hyrasIndex)status.textContent=`Niederschlag · Daten bis ${hyrasDate(hyrasIndex.data_through)} · Historie ${hyrasIndex.historical_first_year}–${hyrasIndex.historical_last_year}`;renderHyras();
  }
}
'''

    text = replace_once(text, "function renderHyras(){\n", js + "function renderHyras(){\n", "Tmean-JavaScript")

    # Route existing renderer when Tmean is selected.
    render_old = '''function renderHyras(){\n  if(!hyrasIndex)return;'''
    render_new = '''function renderHyras(){\n  if(hyrasParameter()==="tmean"){renderHyrasTmean();return;}\n  if(!hyrasIndex)return;'''
    text = replace_once(text, render_old, render_new, "Render-Routing")

    # Route historical Apply button and install parameter-change listener.
    hist_listener_old = 'document.getElementById("hyrasHistoricalApply")?.addEventListener("click",()=>hyrasApplyHistorical());'
    hist_listener_new = 'document.getElementById("hyrasHistoricalApply")?.addEventListener("click",()=>hyrasParameter()==="tmean"?hyrasTmeanApplyHistorical():hyrasApplyHistorical());'
    text = replace_once(text, hist_listener_old, hist_listener_new, "Historie-Routing")

    init_anchor = '''function initHyrasControls(){\n  document.getElementById("hyrasMetricSelect")?.addEventListener("change",()=>renderHyras());'''
    init_new = '''function initHyrasControls(){\n  document.getElementById("hyrasParameterSelect")?.addEventListener("change",()=>hyrasSwitchParameter());\n  document.getElementById("hyrasMetricSelect")?.addEventListener("change",()=>renderHyras());'''
    text = replace_once(text, init_anchor, init_new, "Parameter-Listener")

    TARGET.write_text(text, encoding="utf-8")
    print("HYRAS Tmean Stufe 2 im Frontend eingebaut: Parameterwahl + aktuelle/historische Karten.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
