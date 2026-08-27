// HYRAS_HISTORICAL_TEMPERATURE_1KM_V1
(() => {
  "use strict";

  const TEMP_PARAMETERS=new Set(["tmean","tmax","tmin"]);
  const MONTH_NAMES=["","Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"];
  const PARAM_LABELS={
    tmean:"Tmean · 2-m-Temperaturmittel",
    tmax:"Tmax · 2-m-Tagesmaximum",
    tmin:"Tmin · 2-m-Tagesminimum"
  };
  const ABS_LEGENDS={
    tmean:[-25,-15,-5,0,5,10,15,20,25,30,38],
    tmax:[-20,-10,0,5,10,15,20,25,30,35,45],
    tmin:[-30,-20,-10,-5,0,5,10,15,20,25,30]
  };
  const ABS_COLORS=["#313695","#4575b4","#74add1","#abd9e9","#e0f3f8","#ffffbf","#fee090","#fdae61","#f46d43","#d73027","#a50026"];
  const ANOM_LEGEND=[-6,-4,-2,-1,0,1,2,4,6];
  const ANOM_COLORS=["#313695","#4575b4","#74add1","#abd9e9","#f7f7f7","#fdae61","#f46d43","#d73027","#a50026"];

  let archiveIndex=null;
  let archiveLoading=null;
  let historicalState=null;
  let originalHistoricalMessage=null;

  function parameter(){
    return typeof hyrasParameter==="function"
      ?hyrasParameter()
      :(document.getElementById("hyrasParameterSelect")?.value||"precipitation");
  }
  function isTemperature(value=parameter()){
    return TEMP_PARAMETERS.has(value);
  }
  function reference(){
    if(typeof hyrasReferencePeriod==="function")return hyrasReferencePeriod();
    return document.getElementById("hyrasReferenceSelect")?.value||"1991-2020";
  }
  function referenceDisplay(){
    return reference().replace("-","–");
  }
  function historicalBox(){
    return document.getElementById("hyrasHistoricalApply")?.parentElement||null;
  }
  function metricGroup(){
    return document.getElementById("hyrasMetricSelect")?.closest(".control-group")||null;
  }
  function historicalMetricGroup(){
    return document.getElementById("hyrasHistoricalTemperatureMetricGroup");
  }
  function historicalMetricSelect(){
    return document.getElementById("hyrasHistoricalTemperatureMetric");
  }
  function historicalMetric(){
    const value=historicalMetricSelect()?.value;
    return value==="anomaly"?"anomaly":"absolute";
  }
  function statusElement(){
    return document.getElementById("hyrasStatus");
  }
  function messageElement(){
    return document.getElementById("hyrasHistoricalMessage");
  }
  function number(value,unit="°C",signed=false){
    const n=Number(value);
    if(!Number.isFinite(n))return "–";
    const sign=signed&&n>0?"+":"";
    return `${sign}${n.toLocaleString("de-DE",{minimumFractionDigits:2,maximumFractionDigits:2})} ${unit}`;
  }
  function pad(value){
    return String(value).padStart(2,"0");
  }
  function daysInMonth(year,month){
    return new Date(Date.UTC(year,month,0)).getUTCDate();
  }
  function selectedPeriod(){
    const year=Number(document.getElementById("hyrasHistoricalYear")?.value);
    const type=document.getElementById("hyrasHistoricalType")?.value||"month";
    const month=Number(document.getElementById("hyrasHistoricalMonth")?.value||1);
    let key,label,start,end;
    if(type==="month"){
      key=`month_${pad(month)}`;
      label=`${MONTH_NAMES[month]} ${year}`;
      start=`${year}-${pad(month)}-01`;
      end=`${year}-${pad(month)}-${pad(daysInMonth(year,month))}`;
    }else if(type==="spring"){
      key="spring";label=`Frühling ${year}`;start=`${year}-03-01`;end=`${year}-05-31`;
    }else if(type==="summer"){
      key="summer";label=`Sommer ${year}`;start=`${year}-06-01`;end=`${year}-08-31`;
    }else if(type==="autumn"){
      key="autumn";label=`Herbst ${year}`;start=`${year}-09-01`;end=`${year}-11-30`;
    }else if(type==="winter"){
      key="winter";label=`Winter ${year-1}/${String(year).slice(-2)}`;start=`${year-1}-12-01`;end=`${year}-02-${pad(daysInMonth(year,2))}`;
    }else{
      key="year";label=`Jahr ${year}`;start=`${year}-01-01`;end=`${year}-12-31`;
    }
    return {year,type,month,key,label,start,end};
  }

  async function ensureIndex(){
    if(archiveIndex)return archiveIndex;
    if(archiveLoading)return archiveLoading;
    archiveLoading=fetch(
      `${HYRAS_DATA_BASE}/historical_temperature_maps_1km/index.json?v=1`,
      {cache:"no-store"}
    ).then(response=>{
      if(!response.ok)throw new Error(`Historischer 1-km-Kartenindex fehlt (HTTP ${response.status}).`);
      return response.json();
    }).then(data=>{
      if(Number(data?.resolution_km)!==1)throw new Error("Historischer HYRAS-Kartenindex ist nicht 1 km.");
      archiveIndex=data;
      return data;
    }).finally(()=>{archiveLoading=null;});
    return archiveLoading;
  }

  function setTemperatureMetricOptions(preferred){
    const select=document.getElementById("hyrasMetricSelect");
    if(!select)return;
    const mode=(preferred==="anomaly"||preferred==="absolute")?preferred:"absolute";
    select.innerHTML=
      '<option value="absolute">Temperatur (°C)</option>'+
      `<option value="anomaly">Abweichung ${referenceDisplay()} (K)</option>`;
    select.value=mode;
  }

  function setYears(index,preserve=true){
    const select=document.getElementById("hyrasHistoricalYear");
    const p=parameter();
    const years=Object.keys(index?.parameters?.[p]||{}).map(Number).filter(Number.isFinite).sort((a,b)=>b-a);
    if(!select||!years.length)return;
    const previous=preserve?Number(select.value):NaN;
    select.innerHTML=years.map(year=>`<option value="${year}">${year}</option>`).join("");
    select.value=years.includes(previous)?String(previous):String(years[0]);
  }

  function periodIndex(meta,key){
    const keys=meta?.sprite_layout?.period_keys||archiveIndex?.period_keys||[];
    return keys.indexOf(key);
  }
  function spritePosition(meta,key){
    const i=periodIndex(meta,key);
    if(i<0)throw new Error(`Zeitraum ${key} fehlt im Kartensprite.`);
    const cols=Number(meta?.sprite_layout?.columns||5);
    const rows=Number(meta?.sprite_layout?.rows||4);
    const col=i%cols,row=Math.floor(i/cols);
    return {
      x:cols>1?col/(cols-1)*100:0,
      y:rows>1?row/(rows-1)*100:0
    };
  }
  function legendHtml(p,mode){
    const values=mode==="anomaly"?ANOM_LEGEND:ABS_LEGENDS[p];
    const colors=mode==="anomaly"?ANOM_COLORS:ABS_COLORS;
    const unit=mode==="anomaly"?"K":"°C";
    return values.map((value,i)=>{
      const label=mode==="anomaly"&&value>0?`+${value}`:String(value);
      return `<span><i style="background:${colors[i]}"></i>${label} ${unit}</span>`;
    }).join("");
  }

  function injectStyles(){
    if(document.getElementById("hyrasHistoricalTemperature1kmStyle"))return;
    const style=document.createElement("style");
    style.id="hyrasHistoricalTemperature1kmStyle";
    style.textContent=`
      .hyras-historical-range{display:flex!important}\n      .hyras-hist1km-wrap{width:100%;padding:12px;background:#fff}
      .hyras-hist1km-title{text-align:center;font-size:20px;font-weight:800;margin:4px 0}
      .hyras-hist1km-subtitle{text-align:center;color:#4b5563;font-size:13px;margin:0 0 10px}
      .hyras-hist1km-map{width:min(100%,820px);margin:0 auto;background-repeat:no-repeat;background-color:#fff;border-radius:4px}
      .hyras-hist1km-legend{display:flex;justify-content:center;flex-wrap:wrap;gap:6px 10px;margin:10px 4px 2px;font-size:11px;color:#4b5563}
      .hyras-hist1km-legend span{display:flex;align-items:center;gap:4px}
      .hyras-hist1km-legend i{display:inline-block;width:13px;height:13px;border:1px solid rgba(0,0,0,.18)}
      .hyras-hist1km-note{text-align:center;color:#68727b;font-size:12px;margin:9px 0 0}
    `;
    document.head.appendChild(style);
  }

  function setStats(p,period,stats){
    const ref=reference();
    const refStats=stats?.references?.[ref]||{};
    const current=Number(stats?.current_mean_c);
    const referenceMean=Number(refStats?.mean_c);
    const anomaly=Number(refStats?.anomaly_mean_k);
    const setHeading=(id,text)=>{
      const element=document.getElementById(id);
      const heading=element?.parentElement?.querySelector("h4");
      if(heading)heading.textContent=text;
    };

    document.getElementById("hyrasPeriodStat").textContent=period.label;
    document.getElementById("hyrasDataThrough").textContent=
      `${period.start.split("-").reverse().join(".")}–${period.end.split("-").reverse().join(".")}`;

    setHeading("hyrasCurrentMean","Rastermittel");
    document.getElementById("hyrasCurrentMean").textContent=number(current);
    document.getElementById("hyrasCurrentMeanDetail").textContent="historisches HYRAS-Raster · 1 km";

    setHeading("hyrasReferenceMean",`Mittel ${referenceDisplay()}`);
    document.getElementById("hyrasReferenceMean").textContent=number(referenceMean);
    document.getElementById("hyrasReferenceMeanDetail").textContent="gleicher Monat / gleiche Jahreszeit / gleiches Jahr";

    setHeading("hyrasPercentMean","Abweichung");
    document.getElementById("hyrasPercentMean").textContent=number(anomaly,"K",true);
    document.getElementById("hyrasAnomalyMean").textContent=`gegenüber ${referenceDisplay()}`;

    const note=document.getElementById("hyrasReferenceNote");
    if(note)note.textContent=
      `Quelle: Deutscher Wetterdienst · HYRAS-DE · ${PARAM_LABELS[p]} · historisches 1-km-Raster 1951–2025 · Referenz ${referenceDisplay()}.`;
  }

  async function renderHistoricalTemperature(){
    if(!historicalState||!isTemperature()||historicalState.parameter!==parameter())return;
    const p=historicalState.parameter;
    const period=historicalState.period;
    const index=await ensureIndex();
    const meta=index?.parameters?.[p]?.[String(period.year)];
    if(!meta)throw new Error(`${PARAM_LABELS[p]} ${period.year} fehlt im historischen 1-km-Archiv.`);

    const stats=meta?.stats?.[period.key];
    if(!stats?.available){
      throw new Error(
        period.key==="winter"&&period.year===1951
          ?"Winter 1950/51 ist nicht vollständig verfügbar, weil HYRAS erst 1951 beginnt."
          :`${period.label} ist im historischen 1-km-Archiv nicht verfügbar.`
      );
    }

    const mode=historicalMetric();
    historicalState.mode=mode;
    setTemperatureMetricOptions(mode);
    const spriteKey=mode==="anomaly"?`anomaly_${reference()}`:"absolute";
    const sprite=meta?.sprites?.[spriteKey];
    if(!sprite?.url)throw new Error(`Kartensprite ${spriteKey} fehlt für ${period.label}.`);

    const pos=spritePosition(meta,period.key);
    const frame=document.getElementById("hyrasMapFrame");
    if(!frame)return;
    injectStyles();
    frame.innerHTML=`
      <div class="hyras-hist1km-wrap">
        <div class="hyras-hist1km-title">${PARAM_LABELS[p]} · ${period.label}</div>
        <div class="hyras-hist1km-subtitle">${mode==="anomaly"?`Abweichung ${referenceDisplay()}`:"absolute Temperatur"} · natives HYRAS-1-km-Raster</div>
        <div class="hyras-hist1km-map"></div>
        <div class="hyras-hist1km-legend">${legendHtml(p,mode)}</div>
        <div class="hyras-hist1km-note">Historisches Kartenarchiv 1951–2025 · 1 km</div>
      </div>
    `;
    const map=frame.querySelector(".hyras-hist1km-map");
    map.style.aspectRatio=`${meta.width}/${meta.height}`;
    map.style.backgroundImage=`url("${sprite.url}")`;
    map.style.backgroundSize=`${Number(meta.sprite_layout?.columns||5)*100}% ${Number(meta.sprite_layout?.rows||4)*100}%`;
    map.style.backgroundPosition=`${pos.x}% ${pos.y}%`;

    setStats(p,period,stats);
    const link=document.getElementById("hyrasOpenImage");
    if(link)link.style.display="none";
    const status=statusElement();
    if(status)status.textContent=
      `${PARAM_LABELS[p]} · historische 1-km-Karte · ${period.label} · Referenz ${referenceDisplay()}`;
    const msg=messageElement();
    if(msg){
      msg.className="hyras-custom-message";
      msg.textContent=
        `${period.label} geladen · natives HYRAS-1-km-Raster · absolute Temperatur oder Abweichung zu ${referenceDisplay()}.`;
    }
  }

  async function applyHistoricalTemperature(){
    const msg=messageElement();
    try{
      const p=parameter();
      if(!isTemperature(p))return;
      const index=await ensureIndex();
      setYears(index,true);
      const period=selectedPeriod();
      if(!Number.isFinite(period.year))throw new Error("Bitte ein historisches Jahr auswählen.");
      if(!index?.parameters?.[p]?.[String(period.year)])throw new Error(`Jahr ${period.year} fehlt für ${PARAM_LABELS[p]}.`);

      const previousMode=historicalMetric();
      historicalState={parameter:p,period,mode:previousMode};
      setTemperatureMetricOptions(previousMode);

      if(msg){
        msg.className="hyras-custom-message";
        msg.textContent=`${period.label} wird aus dem historischen 1-km-Archiv geladen …`;
      }
      await renderHistoricalTemperature();
    }catch(error){
      console.error("HYRAS historische Temperaturkarte:",error);
      if(msg){
        msg.className="hyras-custom-message error";
        msg.textContent=error.message;
      }
      const frame=document.getElementById("hyrasMapFrame");
      if(frame)frame.innerHTML=`<div class="hyras-loading">${error.message}</div>`;
    }
  }

  async function syncParameterControls(){
    const p=parameter();
    const box=historicalBox();
    if(box)box.style.removeProperty("display");
    const histMetricGroup=historicalMetricGroup();
    if(!isTemperature(p)){
      historicalState=null;
      if(histMetricGroup)histMetricGroup.style.display="none";
      return;
    }
    if(histMetricGroup)histMetricGroup.style.display="";
    const group=metricGroup();
    if(group)group.style.display="none";

    const msg=messageElement();
    if(msg){
      if(originalHistoricalMessage===null)originalHistoricalMessage=msg.innerHTML;
      msg.className="hyras-custom-message";
      msg.textContent="Historische Temperaturkarten 1951–2025 · 1 km · Monat, Jahreszeit oder Gesamtjahr · Referenz 1961–1990 oder 1991–2020.";
    }

    try{
      const index=await ensureIndex();
      if(!isTemperature()||parameter()!==p)return;
      setYears(index,true);
      if(typeof hyrasHistoricalTypeControls==="function")hyrasHistoricalTypeControls();
    }catch(error){
      console.error("HYRAS 1-km-Historie:",error);
      if(msg){
        msg.className="hyras-custom-message error";
        msg.textContent=error.message;
      }
    }
  }

  const renderBeforeHistoricalTemperature=window.renderHyras;
  window.renderHyras=function(){
    if(historicalState&&isTemperature()&&historicalState.parameter===parameter()){
      renderHistoricalTemperature().catch(error=>{
        console.error("HYRAS historische Temperaturkarte:",error);
        const frame=document.getElementById("hyrasMapFrame");
        if(frame)frame.innerHTML=`<div class="hyras-loading">${error.message}</div>`;
      });
      return;
    }
    return renderBeforeHistoricalTemperature.apply(this,arguments);
  };

  const switchBeforeHistoricalTemperature=window.hyrasSwitchParameter;
  window.hyrasSwitchParameter=async function(){
    historicalState=null;
    const result=await switchBeforeHistoricalTemperature.apply(this,arguments);
    await syncParameterControls();
    return result;
  };

  const applyButton=document.getElementById("hyrasHistoricalApply");
  applyButton?.addEventListener("click",event=>{
    if(!isTemperature())return;
    event.preventDefault();
    event.stopImmediatePropagation();
    applyHistoricalTemperature();
  },true);

  document.getElementById("hyrasMetricSelect")?.addEventListener("change",event=>{
    if(historicalState&&isTemperature()){
      const value=event.target.value;
      if(value==="absolute"||value==="anomaly")historicalState.mode=value;
    }
  },true);

  historicalMetricSelect()?.addEventListener("change",()=>{
    if(historicalState&&isTemperature()){
      historicalState.mode=historicalMetric();
      renderHistoricalTemperature().catch(error=>console.error("HYRAS historische Darstellung:",error));
    }
  });

  document.getElementById("hyrasPeriodSelect")?.addEventListener("change",()=>{
    if(!historicalState||!isTemperature())return;
    historicalState=null;
    const group=metricGroup();
    if(group)group.style.display="none";
  },true);

  document.getElementById("hyrasParameterSelect")?.addEventListener("change",()=>{
    historicalState=null;
  },true);

  document.getElementById("hyrasHistoricalYear")?.addEventListener("change",()=>{
    if(historicalState&&isTemperature())historicalState=null;
  },true);
  document.getElementById("hyrasHistoricalType")?.addEventListener("change",()=>{
    if(historicalState&&isTemperature())historicalState=null;
  },true);
  document.getElementById("hyrasHistoricalMonth")?.addEventListener("change",()=>{
    if(historicalState&&isTemperature())historicalState=null;
  },true);

  const historicalVisibilityWatch=()=>{
    const box=historicalBox();
    if(box&&box.style.display==="none")box.style.removeProperty("display");
  };
  const historicalBoxNode=historicalBox();
  if(historicalBoxNode){
    new MutationObserver(historicalVisibilityWatch).observe(
      historicalBoxNode,
      {attributes:true,attributeFilter:["style"]}
    );
  }

  window.setTimeout(syncParameterControls,0);
  window.setTimeout(syncParameterControls,400);
  window.setTimeout(historicalVisibilityWatch,800);
  window.setTimeout(historicalVisibilityWatch,1600);
})();
