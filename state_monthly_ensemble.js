(function(){
"use strict";

const DATA_URLS=[
  "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/state-monthly-ensemble/state_monthly_ensemble.json",
  "https://cdn.jsdelivr.net/gh/MarcelHerber/climate-dashboard@state-monthly-ensemble/state_monthly_ensemble.json"
];
const MODEL_ORDER=["gefs","ifs","aifs","icon_eu"];
const MODEL_LABELS={gefs:"GFS / GEFS",ifs:"ECMWF IFS ENS",aifs:"ECMWF AIFS ENS",icon_eu:"DWD ICON-EU EPS"};
const MONTHS=["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"];
let data=null,charts={},loading=null;
const hydro={precipitation:null,sunshine:null},hydroLoading={},hydroErrors={};
const REFERENCE_URLS=[
  "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/state-monthly-reference/monthly_reference_1991_2020.json",
  "https://cdn.jsdelivr.net/gh/MarcelHerber/climate-dashboard@state-monthly-reference/monthly_reference_1991_2020.json"
];
let monthlyNormals=null,referenceLoading=null,referenceError=null;
const DAILY_PRECIP_REFERENCE_URLS=[
  "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/state-monthly-daily-reference/daily_precip_reference_1991_2020.json",
  "https://cdn.jsdelivr.net/gh/MarcelHerber/climate-dashboard@state-monthly-daily-reference/daily_precip_reference_1991_2020.json"
];
let dailyRainReference=null,dailyRainLoading=null,dailyRainError=null;
const HYDRO_CONFIG={
  precipitation:{label:"Niederschlag",unit:"mm",source:"DWD HYRAS-DE-PRE",urls:[
    "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/state-monthly-precip/state_monthly_precip.json",
    "https://cdn.jsdelivr.net/gh/MarcelHerber/climate-dashboard@state-monthly-precip/state_monthly_precip.json"]},
  sunshine:{label:"Sonnenscheindauer",unit:"h",source:"DWD DUETT",urls:[
    "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/state-monthly-sun/state_monthly_sun.json",
    "https://cdn.jsdelivr.net/gh/MarcelHerber/climate-dashboard@state-monthly-sun/state_monthly_sun.json"]}
};

function el(id){return document.getElementById(id);}
function num(v){if(v==null||v==="")return null;v=Number(v);return Number.isFinite(v)?v:null;}
function fmt(v,d=2){v=num(v);return v==null?"–":v.toLocaleString("de-DE",{minimumFractionDigits:d,maximumFractionDigits:d});}
function dateShort(iso){if(!iso)return"–";const p=String(iso).split("-");return p.length===3?`${p[2]}.${p[1]}.`:iso;}
function fmtRun(iso){if(!iso)return"Laufzeit nicht gemeldet";const d=new Date(iso);if(Number.isNaN(d.getTime()))return iso;return d.toLocaleString("de-DE",{timeZone:"UTC",day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})+" UTC";}
function setStatus(text,type="info"){const n=el("stateMonthlyStatus");if(!n)return;n.className="state-monthly-status "+type;n.textContent=text;}
function validData(j){return j&&[1,2].includes(j.schema_version)&&Array.isArray(j.dates)&&j.regions&&Array.isArray(j.regions_order);}
async function fetchData(force){
  let last=null;
  for(const base of DATA_URLS){
    try{
      const url=base+(force?(base.includes("?")?"&":"?")+"t="+Date.now():"");
      const r=await fetch(url,{cache:force?"no-store":"default"});
      if(!r.ok)throw new Error("HTTP "+r.status);
      const j=await r.json();if(!validData(j))throw new Error("Unerwartetes Datenformat");return j;
    }catch(e){last=e;console.warn("Bundesland Monats-Ensembles",base,e);}
  }
  throw last||new Error("Monats-Ensembles nicht verfügbar");
}
function selectedParameter(){return el("stateMonthlyParameter")?.value||"temperature";}
function hydroMode(){return selectedParameter()!=="temperature";}
function parameterDoc(){return hydro[selectedParameter()]||null;}
function paramConfig(){return HYDRO_CONFIG[selectedParameter()]||{label:"Temperatur",unit:"°C",source:"DWD HYRAS-DE-TAS"};}
function historicalMonthNormal(param,reg){
  if(!monthlyNormals||!HYDRO_CONFIG[param])return null;
  const doc=hydro[param];
  const key=String(doc?.month||"").padStart(2,"0");
  const raw=monthlyNormals.months?.[key]?.[param]?.[reg]?.month_total;
  const value=num(raw);
  return value!=null&&value>=0?value:null;
}
function dailyRainRunning(regionName){
  const doc=parameterDoc();
  if(selectedParameter()!=="precipitation"||!dailyRainReference||!doc)return null;
  const key=String(doc.month||"").padStart(2,"0");
  const entry=dailyRainReference.months?.[key]?.regions?.[regionName];
  const normal=entry?.running_mm;
  const refs=dailyRainReference.months?.[key]?.dates;
  if(!Array.isArray(normal)||!Array.isArray(refs)||normal.length!==refs.length)return null;
  return (doc.dates||[]).map(iso=>{
    if(iso.slice(5,7)!==key)return null;
    const day=Number(iso.slice(8,10)),index=day-1;
    if(!Number.isInteger(day)||day<1||index>=refs.length||refs[index]!==iso.slice(5))return null;
    return num(normal[index]);
  });
}
function hydroReferenceDatasets(){
  const key=selectedParameter(),regionName=el("stateMonthlyRegion")?.value||"Deutschland";
  const normal=historicalMonthNormal(key,regionName);
  const daily=dailyRainRunning(regionName);
  const out=[];
  if(daily&&daily.some(v=>v!=null))out.push({
    label:"Tagesgenaue 1991–2020-Referenz · kumuliert (HYRAS 2 km)",
    data:daily,borderColor:"#b044d6",borderWidth:2.4,pointRadius:0,tension:.1,spanGaps:false
  });
  if(normal!==null)out.push({
    label:`Klimasumme 1991–2020 · vollständiger Monat ${fmt(normal,1)} ${paramConfig().unit}`,
    data:periodDates().map(()=>normal),borderColor:"rgba(176,68,214,.65)",
    borderWidth:1.6,borderDash:[3,6],pointRadius:0,tension:0,spanGaps:false
  });
  return out;
}
function selectedPeriod(){return el("stateMonthlyPeriod")?.value||"month";}
function selectedMetric(){return el("stateMonthlyMetric")?.value||"absolute";}
function periodDates(){
  if(hydroMode())return parameterDoc()?.dates||[];
  return data?.periods?.[selectedPeriod()]?.dates|| (selectedPeriod()==="month"?data?.dates:[])||[];
}
function labels(){return periodDates().map(dateShort);}
function region(){
  const name=el("stateMonthlyRegion")?.value||"Deutschland";
  if(hydroMode())return parameterDoc()?.regions?.[name]||null;
  const reg=data?.regions?.[name]||null;
  if(!reg)return null;
  return data?.periods ? reg.periods?.[selectedPeriod()]||null :
    (selectedPeriod()==="month"?reg:null);
}
function palette(model){
  return model==="gefs"?{main:"#111827",control:"#12b76a",min:"#3155a5",max:"#c0362c"}:
         model==="ifs"?{main:"#111827",control:"#18a66a",min:"#3155a5",max:"#c0362c"}:
         model==="aifs"?{main:"#111827",control:"#19a866",min:"#3155a5",max:"#c0362c"}:
         {main:"#111827",control:"#188a55",min:"#3155a5",max:"#c0362c"};
}
function connectForecast(arr,r){
  const a=(arr||[]).slice(),obs=r.observed_running||[];let oi=-1;
  for(let i=0;i<obs.length;i++)if(num(obs[i])!=null)oi=i;
  if(oi>=0&&a.slice(oi+1).some(v=>num(v)!=null))a[oi]=obs[oi];
  return a;
}
// Die x-Achse zeigt stets den ganzen Monat. Für die y-Achse zählen
// ausschließlich echte Temperaturwerte, nicht fehlende (null/undefined).
function chartBounds(datasets){
  const values=[];
  for(const dataset of datasets){
    for(const raw of dataset.data||[]){
      const value=num(raw);
      if(value!==null)values.push(value);
    }
  }
  if(!values.length)return hydroMode()?{min:0,max:10}:{min:-5,max:20};
  const mn=Math.min(...values),mx=Math.max(...values);
  const pad=Math.max(.25,(mx-mn)*.08);
  let min=Math.floor((mn-pad)*2)/2;
  let max=Math.ceil((mx+pad)*2)/2;
  if(hydroMode())min=Math.max(0,min);
  if(max-min<2){min-=1;max+=1;}
  if(hydroMode())min=0;
  return{min,max};
}
function bandDataset(label,dataArr,bg,fill,target,borderWidth=0){return{label,data:dataArr,borderColor:"rgba(0,0,0,0)",backgroundColor:bg,borderWidth,pointRadius:0,fill:fill?target:false,tension:.15,spanGaps:false};}
function datasetsFor(modelKey,r){
  const m=r.models?.[modelKey];if(!m)return[];
  const s=m.stats||{},p=palette(modelKey),obs=r.observed_running||[],clim=r.climatology_running||[];
  const p05=connectForecast(s.p05,r),p95=connectForecast(s.p95,r),p20=connectForecast(s.p20,r),p80=connectForecast(s.p80,r);
  const min=connectForecast(s.min,r),max=connectForecast(s.max,r),avg=connectForecast(s.mean,r),ctl=connectForecast(m.control,r);
  return[
    {label:hydroMode()?"Beobachtete Monatssumme":"Beobachtetes laufendes Monatsmittel",data:obs,borderColor:"#f57c00",backgroundColor:"#f57c00",borderWidth:2.2,pointRadius:0,tension:.08,spanGaps:false},
    ...(!hydroMode()?[{label:`Klimamittel 1991–2020 (${fmt(r.climatology_month_mean,2)} °C)`,data:clim,borderColor:"#b044d6",borderWidth:2,borderDash:[11,4,2,4],pointRadius:0,tension:.08,spanGaps:false}]:hydroReferenceDatasets()),
    bandDataset("5–95 % Untergrenze",p05,"rgba(120,120,120,0)",false,false),
    bandDataset("5–95 %",p95,"rgba(120,120,120,.18)",true,"-1"),
    bandDataset("20–80 % Untergrenze",p20,"rgba(90,90,90,0)",false,false),
    bandDataset("20–80 %",p80,"rgba(90,90,90,.26)",true,"-1"),
    {label:"Minimum",data:min,borderColor:p.min,borderWidth:1.4,borderDash:[6,3],pointRadius:0,tension:.12,spanGaps:false},
    {label:"Maximum",data:max,borderColor:p.max,borderWidth:1.4,borderDash:[6,3],pointRadius:0,tension:.12,spanGaps:false},
    {label:"Ensemble-Mittel",data:avg,borderColor:p.main,borderWidth:2.4,pointRadius:0,tension:.12,spanGaps:false},
    {label:"Kontroll-/Basislauf",data:ctl,borderColor:p.control,borderWidth:2,pointRadius:0,tension:.12,spanGaps:false}
  ];
}
function displayDatasets(modelKey,r){
  const datasets=datasetsFor(modelKey,r);
  if(selectedMetric()!=="anomaly"||hydroMode())return datasets;
  const clim=r.climatology_running||[];
  return datasets.map((d,i)=>({
    ...d,
    label:i===1?"Referenz 1991–2020 · 0 K":d.label,
    data:(d.data||[]).map((raw,index)=>{
      const value=num(raw),reference=num(clim[index]);
      if(value===null||reference===null)return null;
      return Number((value-reference).toFixed(3));
    })
  }));
}
function chartOptions(bounds){const anomaly=selectedMetric()==="anomaly"&&!hydroMode(),unit=hydroMode()?paramConfig().unit:(anomaly?"K":"°C");return{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:"index",intersect:false},
  scales:{x:{grid:{color:"rgba(120,130,140,.18)"},ticks:{maxRotation:0,autoSkip:true,maxTicksLimit:16,font:{size:11}},title:{display:true,text:"Tag"}},y:{min:bounds.min,max:bounds.max,grid:{color:"rgba(120,130,140,.28)"},title:{display:true,text:hydroMode()?`kumulierte ${paramConfig().label} [${unit}]`:(anomaly?"Abweichung 1991–2020 [K]":"laufendes Mittel [°C]")},ticks:{callback:v=>Number(v).toFixed(1)}}},
  plugins:{legend:{display:false},datalabels:{display:false},tooltip:{callbacks:{label(ctx){const v=num(ctx.raw);if(v===null)return null;return `${ctx.dataset.label}: ${v>0&&anomaly?"+":""}${fmt(v,2)} ${unit}`;}}}}};}
function destroyCharts(){Object.values(charts).forEach(c=>c?.destroy());charts={};}
function renderLegend(){
  const n=el("stateMonthlyLegend");if(!n)return;
  const currentRegion=el("stateMonthlyRegion")?.value||"Deutschland";
  const daily=hydroMode()?dailyRainRunning(currentRegion):null;
  const monthly=hydroMode()?historicalMonthNormal(selectedParameter(),currentRegion):null;
  n.innerHTML=`<span><i class="sm-swatch obs"></i>Beobachtung</span>${hydroMode()?((daily?.some(v=>v!=null)?'<span><i class="sm-swatch climate"></i>1991–2020 · bis zum Tag (2 km)</span>':"")+(monthly!==null?'<span><i class="sm-swatch climate"></i>1991–2020 · gesamter Monat</span>':"")):`<span><i class="sm-swatch climate"></i>${selectedMetric()==="anomaly"?"0 K Referenz":"1991–2020"}</span>`}<span><i class="sm-band outer"></i>5–95 %</span><span><i class="sm-band inner"></i>20–80 %</span><span><i class="sm-swatch avg"></i>Ensemble-Mittel</span><span><i class="sm-swatch ctl"></i>Kontroll-/Basislauf</span>`;
}
function render(){
  if(!data&&!parameterDoc())return;
  destroyCharts();
  const r=region();
  if(!r){
    setStatus(hydroMode()?(
      hydroErrors[selectedParameter()]?
      `Die ${paramConfig().label}-Daten sind noch nicht verfügbar: ${hydroErrors[selectedParameter()]}`:
      `${paramConfig().label}-Monatsausblick wird geladen oder der Datenlauf ist noch nicht veröffentlicht.`
    ):"Die Jahreszeiten- und Jahresdaten werden noch berechnet. Monatsdaten bleiben verfügbar.","warn");
    MODEL_ORDER.forEach(k=>{const card=el("stateMonthlyChart_"+k)?.closest(".state-monthly-card");if(card)card.hidden=true;});
    return;
  }
  const labs=labels();
  MODEL_ORDER.forEach(k=>{
    const canvas=el("stateMonthlyChart_"+k),card=canvas?.closest(".state-monthly-card"),m=r.models?.[k];if(!canvas||!card)return;
    card.hidden=!m;const title=card.querySelector("h3");if(title)title.textContent=MODEL_LABELS[k]||k;
    const meta=card.querySelector(".state-monthly-model-meta");
    if(meta)meta.textContent=m?`${m.member_count} Member · Prognose bis ${dateShort(m.forecast_through)} · ${m.support_points} Stützpunkte · Lauf ${fmtRun(m.run)}`:"nicht verfügbar";
    if(m){
      const datasets=displayDatasets(k,r);
      charts[k]=new Chart(canvas,{type:"line",data:{labels:labs,datasets},options:chartOptions(chartBounds(datasets))});
    }
  });
  applyView();renderLegend();renderHeader(r);
}
function renderHeader(r){
  const reg=el("stateMonthlyRegion")?.value||"Deutschland";
  if(hydroMode()){
    const d=parameterDoc(),config=paramConfig();
    const title=el("stateMonthlyTitle");
    if(title)title.textContent=`${reg} · ${config.label} · ${MONTHS[(d.month||1)-1]} ${d.year}`;
    const info=el("stateMonthlyInfo");
    const normal=historicalMonthNormal(selectedParameter(),reg);
    const normalText=normal===null?"Klimareferenz 1991–2020 noch nicht verfügbar":`1991–2020: Monatsgesamtwert ${fmt(normal,1)} ${config.unit}`;
    if(info){
      info.innerHTML=`<strong>${config.source} bis ${dateShort(r.observed_through)}</strong><span>Bisher ${fmt(r.observed_current,1)} ${config.unit}</span><span>Beobachtung + Ensemblefortschreibung</span><span>${normalText}</span>`;
      if(selectedParameter()==="precipitation"){
        const daily=dailyRainRunning(reg);
        const index=(d.dates||[]).indexOf(r.observed_through);
        const reference=index>=0?num(daily?.[index]):null;
        if(reference!==null){
          const diff=num(r.observed_current)-reference;
          const item=document.createElement("span");
          const percent=reference>0?` (${fmt(num(r.observed_current)/reference*100,0)} % des Mittels)`:"";
          item.textContent=`Klimasumme bis ${dateShort(r.observed_through)}: ${fmt(reference,1)} mm · Abweichung ${diff>=0?"+":""}${fmt(diff,1)} mm${percent}`;
          info.appendChild(item);
        }
      }
      // A monthly anomaly is meaningful only if an ensemble reaches the final
      // day of the month. Do not infer a month-end outcome from 7/15-day runs.
      if(normal!==null&&normal>0){
        const lastIndex=(d.dates||[]).length-1;
        for(const modelKey of MODEL_ORDER){
          const value=num(r.models?.[modelKey]?.stats?.mean?.[lastIndex]);
          if(value===null)continue;
          const delta=value-normal,percentage=100*value/normal;
          const chip=document.createElement("span");
          chip.textContent=`${MODEL_LABELS[modelKey]||modelKey}: Monatsende ${fmt(value,1)} ${config.unit} · ${delta>=0?"+":""}${fmt(delta,1)} ${config.unit} (${fmt(percentage,0)} % vom Mittel)`;
          info.appendChild(chip);
        }
      }
    }
    const generated=new Date(d.generated_at);
    const label=Number.isNaN(generated.getTime())?d.generated_at:generated.toLocaleString("de-DE",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
    const qc=d.station_quality;
    const qcWarning=selectedParameter()==="sunshine"?qc?.warnings?.find(item=>item.region===reg):null;
    const qcText=qc?.complete?` · SDK-Plausibilitätsvergleich ${qc.evaluated?.length||0} Gebiete`:"";
    if(qcWarning&&info){
      const chip=document.createElement("span");
      chip.textContent=`Stationsvergleich: Differenz ${qcWarning.difference_h>=0?"+":""}${fmt(qcWarning.difference_h,1)} h (nur Qualitätskontrolle)`;
      info.appendChild(chip);
    }
    setStatus(`Datenstand ${config.source}: ${d.observation_data_through} · Generiert ${label} · ${Object.keys(r.models||{}).length}/4 Ensemblemodelle${qcText}`,Object.keys(r.models||{}).length===4&&!qcWarning?"ok":"warn");
    const note=el("stateMonthlyDataNote");
    if(note){
      const dayAvailable=dailyRainRunning(reg)?.some(v=>v!=null);
      const refNote=dayAvailable?
        "Die durchgezogene violette Linie ist die echte kumulierte Tagesreferenz 1991–2020 aus historischen HYRAS-Tagesrastern (2-km-Webgitter); die fein gestrichelte Linie markiert den amtlichen Monatsnormalwert (1 km). Kleinere Unterschiede am Monatsende sind wegen der Gitterauflösung möglich.":
        normal===null?"Noch keine Klimareferenz geladen.":"Die gestrichelte Klimareferenz zeigt die volle Monatssumme; dies ist keine Tagesklimatologie.";
      note.textContent=`${config.source} · ${config.unit} · kumulierte Gebietssummen. ${refNote} Modellprognosen sind Flächenannäherungen aus Stützpunkten. ${selectedParameter()==="sunshine"?"Historische Sonnenschein-Norm: stationsinterpoliertes DWD-Raster; aktuelle DUETT-Daten kombinieren Satellit und Stationen, daher methodischer Unterschied. Eine belastbare tagesgenaue Sonnenscheinreferenz fehlt noch.":""} Fehlende Tage werden nicht zu null.`;
    }
    return;
  }
  const note=el("stateMonthlyDataNote");
  if(note)note.textContent="Beobachtungen und Klimareferenz: DWD HYRAS-DE-TAS, 1-km-Flächenmittel. Ensembleprognosen aus räumlich verteilten Modellstützpunkten. Temperatur-Abweichung gegen das bis zum jeweiligen Tag aufgelaufene Klimamittel 1991–2020.";

  const period=selectedPeriod(),p=data.periods?.[period];
  const month=MONTHS[(data.month||1)-1]||String(data.month);
  let periodLabel=month+" "+data.year;
  if(period==="year")periodLabel="Jahr "+data.year;
  if(period==="season"){
    periodLabel=(p?.label||"Jahreszeit")+" "+data.year;
    if(p&&p.end_date.slice(0,4)!==p.start_date.slice(0,4)){
      periodLabel=(p.label||"Winter")+" "+p.start_date.slice(0,4)+"/"+p.end_date.slice(2,4);
    }
  }
  const title=el("stateMonthlyTitle");if(title)title.textContent=`${reg} · ${periodLabel}`;
  const dates=periodDates(),obsIndex=dates.indexOf(r.observed_through);
  const reference=num(r.climatology_to_date)??num(r.climatology_running?.[obsIndex]);
  const diff=num(r.observed_anomaly_to_date)??(reference!=null&&num(r.observed_current)!=null?r.observed_current-reference:null);
  const climateFinal=num(r.climatology_period_mean)??num(r.climatology_month_mean);
  const info=el("stateMonthlyInfo");if(info)info.innerHTML=`<strong>HYRAS bis ${dateShort(r.observed_through)}</strong><span>bisheriges Periodenmittel ${fmt(r.observed_current,2)} °C</span><span>Klima 1991–2020 bis dahin ${fmt(reference,2)} °C</span><span>Abweichung ${diff==null?"–":`${diff>=0?"+":""}${fmt(diff,2)} K`}</span><span>Klimamittel gesamte Periode ${fmt(climateFinal,2)} °C</span>`;
  const gen=new Date(data.generated_at),generated=Number.isNaN(gen.getTime())?data.generated_at:gen.toLocaleString("de-DE",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
  const partial=p&&p.complete_reference_period===false?" · Winter startet mangels Vorjahresdaten erst am 01.01.":"";
  setStatus(`Datenstand HYRAS ${data.observation_data_through} · Ensemble-Daten erzeugt ${generated} · ${Object.keys(r.models||{}).length}/4 Modelle verfügbar${partial}`,Object.keys(r.models||{}).length===4&& !partial?"ok":"warn");
}
function applyView(){
  const view=el("stateMonthlyView")?.value||"four",grid=el("stateMonthlyGrid");if(!grid)return;
  grid.classList.toggle("single",view!=="four");
  grid.querySelectorAll(".state-monthly-card").forEach(card=>{const k=card.dataset.model;card.classList.toggle("view-hidden",view!=="four"&&view!==k);});
  window.setTimeout(()=>Object.values(charts).forEach(c=>c?.resize()),60);
}
function fillRegions(){
  const s=el("stateMonthlyRegion"),order=data?.regions_order||parameterDoc()?.regions_order;
  if(!s||!order)return;const old=s.value||"Deutschland";s.innerHTML="";
  order.forEach(name=>{const o=document.createElement("option");o.value=name;o.textContent=name;s.appendChild(o);});s.value=order.includes(old)?old:"Deutschland";
}
async function load(force=false){
  if(loading)return loading;setStatus("Bundesland-Monatsensembles werden geladen …","info");
  loading=fetchData(force).then(j=>{data=j;fillRegions();render();return j;}).catch(e=>{console.error(e);setStatus("Monats-Ensembles konnten nicht geladen werden: "+e.message,"error");throw e;}).finally(()=>{loading=null;});
  return loading;
}
async function fetchHydro(param,force=false){
  const cfg=HYDRO_CONFIG[param];
  if(!cfg)return null;
  if(force)hydro[param]=null;
  if(hydroLoading[param])return hydroLoading[param];
  const task=(async()=>{
    let last=null;
    for(const base of cfg.urls){
      try{
        const url=base+(force?"?t="+Date.now():"");
        const response=await fetch(url,{cache:force?"no-store":"default"});
        if(!response.ok)throw new Error("HTTP "+response.status);
        const json=await response.json();
        if(json.schema_version!==1||json.parameter!==param||!Array.isArray(json.dates)||!json.regions)throw new Error("Ungültiges Datenformat");
        if(json.unit!==cfg.unit)throw new Error("Unerwartete Einheit: "+json.unit);
        const now=new Date();
        const parts=new Intl.DateTimeFormat("en-GB",{timeZone:"Europe/Berlin",year:"numeric",month:"2-digit"}).formatToParts(now);
        const currentMonth=parts.find(p=>p.type==="year").value+"-"+parts.find(p=>p.type==="month").value;
        const datasetMonth=`${json.year}-${String(json.month).padStart(2,"0")}`;
        if(datasetMonth!==currentMonth)throw new Error("Letzter Datenstand "+datasetMonth+" (aktueller Monat "+currentMonth+")");
        hydro[param]=json;
        delete hydroErrors[param];
        if(!data)fillRegions();
        if(selectedParameter()===param)render();
        return json;
      }catch(error){last=error;console.warn("Monatsausblick",param,base,error);}
    }
    hydroErrors[param]=last?.message||"Daten nicht veröffentlicht";
    if(selectedParameter()===param)render();
    throw last||new Error("Datensatz fehlt");
  })();
  hydroLoading[param]=task;
  try{return await task;}finally{delete hydroLoading[param];}
}
async function fetchMonthlyNormals(force=false){
  if(monthlyNormals&&!force)return monthlyNormals;
  if(referenceLoading)return referenceLoading;
  referenceLoading=(async()=>{
    let last=null;
    for(const base of REFERENCE_URLS){
      try{
        const response=await fetch(base+(force?"?t="+Date.now():""),{cache:force?"no-store":"default"});
        if(!response.ok)throw new Error("HTTP "+response.status);
        const doc=await response.json();
        if(doc.schema_version!==1||doc.reference_period!=="1991-2020"||
           doc.product!=="state_monthly_hydro_sun_climatology"||!doc.months||
           doc.daily_climatology_available!==false)throw new Error("Klimareferenz-Datenformat ungültig");
        monthlyNormals=doc;referenceError=null;
        if(hydroMode())render();
        return doc;
      }catch(error){last=error;console.warn("Monats-Klimareferenz",base,error);}
    }
    referenceError=last?.message||"noch nicht veröffentlicht";
    if(hydroMode())render();
    return null;
  })();
  try{return await referenceLoading;}finally{referenceLoading=null;}
}
async function fetchDailyRainReference(force=false){
  if(dailyRainReference&&!force)return dailyRainReference;
  if(dailyRainLoading)return dailyRainLoading;
  dailyRainLoading=(async()=>{
    let last=null;
    for(const base of DAILY_PRECIP_REFERENCE_URLS){
      try{
        const response=await fetch(base+(force?"?t="+Date.now():""),{cache:force?"no-store":"default"});
        if(!response.ok)throw new Error("HTTP "+response.status);
        const doc=await response.json();
        if(doc.schema_version!==1||doc.parameter!=="precipitation"||
           doc.reference_period!=="1991-2020"||doc.daily_climatology_available!==true||
           doc.product!=="state_monthly_daily_precip_climatology"||
           !doc.months||doc.regions_order?.length!==17)throw new Error("Tagesreferenz-Datenformat ungültig");
        dailyRainReference=doc;
        dailyRainError=null;
        if(selectedParameter()==="precipitation")render();
        return doc;
      }catch(error){last=error;console.warn("HYRAS Tagesklima 1991–2020",base,error);}
    }
    dailyRainError=last?.message||"Tagesreferenz noch nicht veröffentlicht";
    if(selectedParameter()==="precipitation")render();
    return null;
  })();
  try{return await dailyRainLoading;}finally{dailyRainLoading=null;}
}
function syncParameterControls(){
  const monthly=hydroMode(),period=el("stateMonthlyPeriod"),metric=el("stateMonthlyMetric");
  if(period){
    period.querySelectorAll("option").forEach(option=>{option.disabled=monthly&&option.value!=="month";});
    if(monthly)period.value="month";
  }
  if(metric){
    metric.querySelectorAll("option").forEach(option=>{option.disabled=monthly&&option.value==="anomaly";});
    if(monthly)metric.value="absolute";
    metric.disabled=monthly;
  }
  const description=el("stateMonthlyExportDescription");
  if(description)description.textContent=monthly?
    "Kumulierte Monatssumme · Beobachtung + Ensemble-Prognose · "+paramConfig().unit:
    "Laufendes Periodenmittel · Beobachtung + Ensemble-Fortschreibung · Temperatur oder Anomalie";
}
function onParameterChange(){
  syncParameterControls();
  render();
  if(hydroMode()&&!parameterDoc())fetchHydro(selectedParameter()).catch(()=>{});
  if(hydroMode()&&!monthlyNormals)fetchMonthlyNormals().catch(()=>{});
  if(selectedParameter()==="precipitation"&&!dailyRainReference)fetchDailyRainReference().catch(()=>{});
}
function reloadActive(){
  if(hydroMode()){
    fetchHydro(selectedParameter(),true).catch(()=>{});
    fetchMonthlyNormals(true).catch(()=>{});
    if(selectedParameter()==="precipitation")fetchDailyRainReference(true).catch(()=>{});
  }else load(true);
}
function filename(ext){const reg=(el("stateMonthlyRegion")?.value||"Deutschland").replace(/[^a-z0-9äöüß_-]+/gi,"_");const d=hydroMode()?parameterDoc():data;return `Ensemble_${selectedParameter()}_${selectedPeriod()}_${selectedMetric()}_${d?.year||""}_${String(d?.month||"").padStart(2,"0")}_${reg}.${ext}`;}
function saveBlob(blob,name){const u=URL.createObjectURL(blob),a=document.createElement("a");a.href=u;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),1000);}
async function exportPng(){try{if(!window.html2canvas)throw new Error("html2canvas fehlt");const c=await window.captureDashboardWithWhiteBackground(el("stateMonthlyExportArea"),{backgroundColor:"#fff",scale:2,useCORS:true,logging:false});c.toBlob(b=>b&&saveBlob(b,filename("png")),"image/png");}catch(e){alert("PNG konnte nicht erstellt werden: "+e.message);}}
async function exportPdf(){try{if(!window.html2canvas||!window.jspdf?.jsPDF)throw new Error("PDF-Bibliothek fehlt");const c=await window.captureDashboardWithWhiteBackground(el("stateMonthlyExportArea"),{backgroundColor:"#fff",scale:2,useCORS:true,logging:false}),J=window.jspdf.jsPDF,p=new J({orientation:"landscape",unit:"mm",format:"a4"}),pw=p.internal.pageSize.getWidth(),ph=p.internal.pageSize.getHeight(),m=7,s=Math.min((pw-2*m)/c.width,(ph-2*m)/c.height),w=c.width*s,h=c.height*s;p.addImage(c.toDataURL("image/jpeg",.93),"JPEG",(pw-w)/2,(ph-h)/2,w,h);p.save(filename("pdf"));}catch(e){alert("PDF konnte nicht erstellt werden: "+e.message);}}
function mount(){
  if(!el("state-monthly-ensemble"))return;
  el("stateMonthlyRegion")?.addEventListener("change",render);el("stateMonthlyView")?.addEventListener("change",applyView);
  el("stateMonthlyParameter")?.addEventListener("change",onParameterChange);
  el("stateMonthlyPeriod")?.addEventListener("change",render);
  el("stateMonthlyMetric")?.addEventListener("change",render);
  el("stateMonthlyReload")?.addEventListener("click",reloadActive);el("stateMonthlyPng")?.addEventListener("click",exportPng);el("stateMonthlyPdf")?.addEventListener("click",exportPdf);
  const panel=el("state-monthly-ensemble");
  new MutationObserver(()=>{if(panel.classList.contains("active")){if(!data)load(false);window.setTimeout(()=>Object.values(charts).forEach(c=>c?.resize()),80);}}).observe(panel,{attributes:true,attributeFilter:["class"]});
  syncParameterControls();
  if(panel.classList.contains("active"))load(false);
}
window.ensureStateMonthlyEnsembleLoaded=function(){return data?Promise.resolve(data):load(false);};
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",mount);else mount();
})();