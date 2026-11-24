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
const DAILY_SUN_REFERENCE_URLS=[
  "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/state-monthly-daily-sun/daily_sun_reference_1991_2020.json",
  "https://cdn.jsdelivr.net/gh/MarcelHerber/climate-dashboard@state-monthly-daily-sun/daily_sun_reference_1991_2020.json"
];
let dailySunReference=null,dailySunLoading=null,dailySunError=null;
const OLD_REFERENCE_BRANCH="state-monthly-reference-1961-1990";
const OLD_REFERENCE_FILES={monthly:"monthly_reference_1961_1990.json",precipitation:"daily_precip_reference_1961_1990.json",sunshine:"daily_sun_reference_1961_1990.json"};
const oldReferences={},oldReferenceLoading={},oldReferenceErrors={};
const CLIMATE_REGIONS=["Deutschland","Baden-Württemberg","Bayern","Berlin","Brandenburg","Bremen","Hamburg","Hessen","Mecklenburg-Vorpommern","Niedersachsen","Nordrhein-Westfalen","Rheinland-Pfalz","Saarland","Sachsen","Sachsen-Anhalt","Schleswig-Holstein","Thüringen"];
const CLIMATE_MONTH_DAYS=Object.fromEntries(Array.from({length:12},(_,i)=>{
  const key=String(i+1).padStart(2,"0");
  return [key,Array.from({length:new Date(Date.UTC(2000,i+1,0)).getUTCDate()},(_,j)=>`${key}-${String(j+1).padStart(2,"0")}`)];
}));
const CLIMATE_DAYS=Object.values(CLIMATE_MONTH_DAYS).flat();
let exporting=false;
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
function runAgeHours(iso,now=Date.now()){
  if(typeof iso!=="string"||!iso)return null;
  const age=(now-Date.parse(iso))/3600000;
  return Number.isFinite(age)&&age>=-1?Math.max(0,age):null;
}
function modelFreshness(m){
  const age=runAgeHours(m?.run);
  if(age===null){
    const retrieved=runAgeHours(m?.retrieved_at);
    return retrieved===null?"Laufzeit nicht verifizierbar":`Laufzeit nicht verifizierbar (Datenabruf vor ${Math.round(retrieved)} h)`;
  }
  return age>24?`veraltet (${Math.round(age)} h)`:(m.retained?"älterer Lauf (API-Störung)":"");
}
function freshnessWarning(doc,models,complete=false,preview=false){
  const warnings=[],generated=runAgeHours(doc?.generated_at);
  if(generated===null)warnings.push("Erstellungszeit unbekannt");
  else if(generated>24)warnings.push(`Datensatz veraltet (${Math.round(generated)} h)`);
  if(!complete){
    const missing=MODEL_ORDER.filter(k=>!models?.[k]);
    if(missing.length&&!preview)warnings.push(`${missing.length} Modelle fehlen: ${missing.map(k=>MODEL_LABELS[k]).join(", ")}`);
    for(const k of MODEL_ORDER){
      if(!models?.[k])continue;
      const issue=modelFreshness(models[k]);
      if(issue)warnings.push(`${MODEL_LABELS[k]}: ${issue}`);
    }
  }
  return warnings.length?" · "+warnings.join(" · "):"";
}
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
function selectedReference(){return el("stateMonthlyReference")?.value==="1961-1990"?"1961-1990":"1991-2020";}
function referenceLabel(){return selectedReference().replace("-","–");}
function oldReferenceSelected(){return selectedReference()==="1961-1990";}
function exactKeys(actual,expected){return Array.isArray(actual)&&actual.length===expected.length&&new Set(actual).size===expected.length&&expected.every(key=>actual.includes(key));}
function strictNumber(value){return typeof value==="number"&&Number.isFinite(value);}
function readyReference(series){return Array.isArray(series)&&series.length===periodDates().length&&series.length>0&&series.every(strictNumber);}
function validOldReference(kind,doc){
  if(doc?.schema_version!==1)return false;
  if(kind==="temperature"){
    return doc.reference==="1961-1990"&&doc.parameter==="tmean"&&doc.unit==="°C"&&exactKeys(Object.keys(doc.regions||{}),CLIMATE_REGIONS)&&
      CLIMATE_REGIONS.every(region=>exactKeys(Object.keys(doc.regions[region]||{}),CLIMATE_DAYS)&&CLIMATE_DAYS.every(day=>strictNumber(doc.regions[region][day])));
  }
  const product=kind==="monthly"?"state_monthly_hydro_sun_climatology":kind==="precipitation"?"state_monthly_daily_precip_climatology":"state_monthly_daily_sunshine_climatology_station_reconstruction";
  if(doc.reference_period!=="1961-1990"||doc.product!==product||!exactKeys(Object.keys(doc.months||{}),Object.keys(CLIMATE_MONTH_DAYS))||
     !exactKeys(doc.regions_order,CLIMATE_REGIONS)||doc.daily_climatology_available!==(kind!=="monthly"))return false;
  if(kind==="monthly")return Object.values(doc.months).every(month=>["precipitation","sunshine"].every(param=>
    exactKeys(Object.keys(month?.[param]||{}),CLIMATE_REGIONS)&&CLIMATE_REGIONS.every(region=>{
      const value=month[param][region]?.month_total;return strictNumber(value)&&value>=0;
    })));
  const sunshine=kind==="sunshine",unit=sunshine?"h":"mm";
  if(doc.parameter!==kind||doc.unit!==unit)return false;
  return Object.entries(CLIMATE_MONTH_DAYS).every(([month,dates])=>{
    const entry=doc.months?.[month];
    if(!Array.isArray(entry?.dates)||entry.dates.length!==dates.length||!dates.every((day,i)=>entry.dates[i]===day)||!exactKeys(Object.keys(entry.regions||{}),CLIMATE_REGIONS))return false;
    return CLIMATE_REGIONS.every(region=>{
      const daily=entry.regions[region]?.[`daily_${unit}`],running=entry.regions[region]?.[`running_${unit}`];
      if(!Array.isArray(daily)||!Array.isArray(running)||daily.length!==dates.length||running.length!==dates.length)return false;
      let sum=0;
      return daily.every((value,i)=>{
        if(!strictNumber(value)||value<0||sunshine&&value>24.01||!strictNumber(running[i])||running[i]<0||i>0&&running[i]<running[i-1])return false;
        sum+=value;
        // Daily data are rounded to four decimals; running data to three.
        return Math.abs(sum-running[i])<.003;
      });
    });
  });
}
function hydroMode(){return selectedParameter()!=="temperature";}
function monthKey(doc){return doc?.year&&doc?.month?`${doc.year}-${String(doc.month).padStart(2,"0")}`:null;}
function calendarMonthKey(today=new Date(),offset=0){
  const parts=new Intl.DateTimeFormat("en-GB",{timeZone:"Europe/Berlin",year:"numeric",month:"2-digit"}).formatToParts(today);
  const year=Number(parts.find(p=>p.type==="year").value),month=Number(parts.find(p=>p.type==="month").value);
  const target=new Date(Date.UTC(year,month-1+offset,1));
  return `${target.getUTCFullYear()}-${String(target.getUTCMonth()+1).padStart(2,"0")}`;
}
let lastCalendarMonth=calendarMonthKey();
function checkCalendarMonth(){
  const month=calendarMonthKey();
  if(lastCalendarMonth===month)return false;
  lastCalendarMonth=month;
  const period=el("stateMonthlyPeriod");if(period)period.value="month";
  return true;
}
function activeMonthDoc(root,period="month",today=new Date()){
  if(!root)return null;
  if(period==="next_month"){
    const preview=root.next_month;
    return monthKey(preview)===calendarMonthKey(today,1)&&preview?.models_order?.length?preview:null;
  }
  return monthKey(root.next_month)===calendarMonthKey(today)?root.next_month:root;
}
function temperatureDoc(){return activeMonthDoc(data,selectedPeriod());}
function parameterDoc(){return activeMonthDoc(hydro[selectedParameter()],selectedPeriod());}
function effectivePeriod(){return selectedPeriod()==="next_month"?"month":selectedPeriod();}
function paramConfig(){return HYDRO_CONFIG[selectedParameter()]||{label:"Temperatur",unit:"°C",source:"DWD HYRAS-DE-TAS"};}
function historicalMonthNormal(param,reg){
  const normals=oldReferenceSelected()?oldReferences.monthly:monthlyNormals;
  if(!normals||!HYDRO_CONFIG[param])return null;
  const doc=parameterDoc();
  const key=String(doc?.month||"").padStart(2,"0");
  const raw=normals.months?.[key]?.[param]?.[reg]?.month_total;
  const value=num(raw);
  return value!=null&&value>=0?value:null;
}
function dailyHydroRunning(regionName){
  const doc=parameterDoc(),param=selectedParameter();
  const reference=oldReferenceSelected()?oldReferences[param]:param==="precipitation"?dailyRainReference:param==="sunshine"?dailySunReference:null;
  if(!reference||!doc)return null;
  const key=String(doc.month||"").padStart(2,"0");
  const entry=reference.months?.[key]?.regions?.[regionName];
  const normal=param==="sunshine"?entry?.running_h:entry?.running_mm;
  const refs=reference.months?.[key]?.dates;
  if(!Array.isArray(normal)||!Array.isArray(refs)||normal.length!==refs.length)return null;
  const series=(doc.dates||[]).map(iso=>{
    if(iso.slice(5,7)!==key)return null;
    const day=Number(iso.slice(8,10)),index=day-1;
    if(!Number.isInteger(day)||day<1||index>=refs.length||refs[index]!==iso.slice(5))return null;
    return num(normal[index]);
  });
  return oldReferenceSelected()&&!readyReference(series)?null:series;
}
function hydroReferenceDatasets(){
  const key=selectedParameter(),regionName=el("stateMonthlyRegion")?.value||"Deutschland";
  const normal=historicalMonthNormal(key,regionName);
  const daily=dailyHydroRunning(regionName);
  const out=[];
  if(daily&&(oldReferenceSelected()?readyReference(daily):daily.some(v=>v!=null)))out.push({
    label:selectedParameter()==="sunshine"?`Stationsbasierte ${referenceLabel()}-Tagesreferenz · kumuliert (DWD SDK, 6 km)`:`Tagesgenaue ${referenceLabel()}-Referenz · kumuliert (HYRAS 2 km)`,
    data:daily,borderColor:"#b044d6",borderWidth:2.4,pointRadius:0,tension:.1,spanGaps:false,
    isDailyClimate:true
  });
  // The official whole-month normal is a horizontal guide ONLY in the
  // absolute view; subtracting/dividing it at every day is scientifically wrong.
  if(normal!==null&&selectedMetric()==="absolute")out.push({
    label:`Klimasumme ${referenceLabel()} · vollständiger Monat ${fmt(normal,1)} ${paramConfig().unit}`,
    data:periodDates().map(()=>normal),borderColor:"rgba(176,68,214,.65)",
    borderWidth:1.6,borderDash:[3,6],pointRadius:0,tension:0,spanGaps:false
  });
  return out;
}
function selectedPeriod(){return el("stateMonthlyPeriod")?.value||"month";}
function selectedMetric(){return el("stateMonthlyMetric")?.value||"absolute";}
function periodDates(){
  if(hydroMode())return parameterDoc()?.dates||[];
  const doc=temperatureDoc(),period=effectivePeriod();
  return doc?.periods?.[period]?.dates|| (period==="month"?doc?.dates:[])||[];
}
function labels(){return periodDates().map(dateShort);}
function temperatureRunning(r){
  if(!oldReferenceSelected())return r?.climatology_running||[];
  const name=el("stateMonthlyRegion")?.value||"Deutschland";
  const days=oldReferences.temperature?.regions?.[name];
  if(!days)return [];
  let sum=0,missing=false;
  const running=periodDates().map((date,i)=>{
    const v=num(days[date.slice(5)]);
    if(v===null)missing=true;
    if(missing)return null;
    sum+=v;
    return sum/(i+1);
  });
  return readyReference(running)?running:[];
}
function temperatureNormal(r){
  if(!oldReferenceSelected())return num(r?.climatology_period_mean)??num(r?.climatology_month_mean);
  return num(temperatureRunning(r).at(-1));
}
function region(){
  const name=el("stateMonthlyRegion")?.value||"Deutschland";
  if(hydroMode())return parameterDoc()?.regions?.[name]||null;
  const doc=temperatureDoc(),reg=doc?.regions?.[name]||null;
  if(!reg)return null;
  return doc?.periods ? reg.periods?.[effectivePeriod()]||null :
    (effectivePeriod()==="month"?reg:null);
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
  if(!values.length)return hydroMode()?(selectedMetric()==="anomaly"?{min:-5,max:5}:{min:0,max:10}):{min:-5,max:20};
  const mn=Math.min(...values),mx=Math.max(...values);
  const pad=Math.max(.25,(mx-mn)*.08);
  let min=Math.floor((mn-pad)*2)/2;
  let max=Math.ceil((mx+pad)*2)/2;
  if(hydroMode()&&selectedMetric()!=="anomaly")min=Math.max(0,min);
  if(max-min<2){min-=1;max+=1;}
  if(hydroMode()&&selectedMetric()!=="anomaly")min=0;
  return{min,max};
}
function bandDataset(label,dataArr,bg,fill,target,borderWidth=0){return{label,data:dataArr,borderColor:"rgba(0,0,0,0)",backgroundColor:bg,borderWidth,pointRadius:0,fill:fill?target:false,tension:.15,spanGaps:false};}
function isolatedRadius(values){return values.filter(v=>num(v)!==null).length===1?3:0;}
function datasetsFor(modelKey,r){
  const m=r.models?.[modelKey],obs=r.observed_running||[],clim=temperatureRunning(r);
  const base=[
    {label:hydroMode()?"Beobachtete Monatssumme":"Beobachtetes laufendes Monatsmittel",data:obs,borderColor:"#f57c00",backgroundColor:"#f57c00",borderWidth:2.2,pointRadius:isolatedRadius(obs),tension:.08,spanGaps:false},
    ...(!hydroMode()?((oldReferenceSelected()?readyReference(clim):clim.some(v=>num(v)!==null))?[{label:`Klimamittel ${referenceLabel()} (${fmt(temperatureNormal(r),2)} °C)`,data:clim,borderColor:"#b044d6",borderWidth:2,borderDash:[11,4,2,4],pointRadius:0,tension:.08,spanGaps:false,isTemperatureClimate:true}]:[]):hydroReferenceDatasets())
  ];
  if(!m||!m.forecast_through)return base;
  const s=m.stats||{},p=palette(modelKey);
  const p05=connectForecast(s.p05,r),p95=connectForecast(s.p95,r),p20=connectForecast(s.p20,r),p80=connectForecast(s.p80,r);
  const min=connectForecast(s.min,r),max=connectForecast(s.max,r),avg=connectForecast(s.mean,r),ctl=connectForecast(m.control,r);
  return[
    ...base,
    bandDataset("5–95 % Untergrenze",p05,"rgba(120,120,120,0)",false,false),
    bandDataset("5–95 %",p95,"rgba(120,120,120,.18)",true,"-1"),
    bandDataset("20–80 % Untergrenze",p20,"rgba(90,90,90,0)",false,false),
    bandDataset("20–80 %",p80,"rgba(90,90,90,.26)",true,"-1"),
    {label:"Minimum",data:min,borderColor:p.min,borderWidth:1.4,borderDash:[6,3],pointRadius:isolatedRadius(min),tension:.12,spanGaps:false},
    {label:"Maximum",data:max,borderColor:p.max,borderWidth:1.4,borderDash:[6,3],pointRadius:isolatedRadius(max),tension:.12,spanGaps:false},
    {label:"Ensemble-Mittel",data:avg,borderColor:p.main,borderWidth:2.4,pointRadius:isolatedRadius(avg),tension:.12,spanGaps:false},
    {label:"Kontroll-/Basislauf",data:ctl,borderColor:p.control,borderWidth:2,pointRadius:isolatedRadius(ctl),tension:.12,spanGaps:false}
  ];
}
// Every ensemble quantile, control run and observation must be compared with
// the *same calendar-day cumulative climate*. Never use whole-month normals
// for within-month anomalies. Missing/zero reference points fail closed.
function transformHydroValue(value,reference,metric){
  const observed=num(value),climate=num(reference);
  if(observed===null||climate===null||climate<0)return null;
  if(metric==="absolute")return observed;
  if(metric==="anomaly")return Number((observed-climate).toFixed(3));
  if(metric==="percent")return climate>0?Number((observed/climate*100).toFixed(3)):null;
  return null;
}
function displayDatasets(modelKey,r){
  const datasets=datasetsFor(modelKey,r),metric=selectedMetric();
  if(hydroMode()){
    if(metric==="absolute")return datasets;
    const regionName=el("stateMonthlyRegion")?.value||"Deutschland";
    const daily=dailyHydroRunning(regionName);
    // Show no calculated anomalies if a real daily reference has not loaded
    // yet; the selector also disables anomaly/percent until it has.
    return datasets.map(dataset=>({
      ...dataset,
      label:dataset.isDailyClimate?
        (metric==="percent"?`Klimareferenz ${referenceLabel()} · 100 %`:
         `Klimareferenz ${referenceLabel()} · 0 `+paramConfig().unit):
        dataset.label,
      data:(dataset.data||[]).map((v,i)=>transformHydroValue(
        v,Array.isArray(daily)?daily[i]:null,metric))
    }));
  }
  if(metric!=="anomaly")return datasets;
  const clim=temperatureRunning(r);
  return datasets.map(d=>({
    ...d,
    label:d.isTemperatureClimate?`Referenz ${referenceLabel()} · 0 K`:d.label,
    data:(d.data||[]).map((raw,index)=>{
      const value=num(raw),reference=num(clim[index]);
      if(value===null||reference===null)return null;
      return Number((value-reference).toFixed(3));
    })
  }));
}
function chartOptions(bounds){
  const metric=selectedMetric(),anomaly=metric==="anomaly";
  const unit=hydroMode()?(metric==="percent"?"%":paramConfig().unit):(anomaly?"K":"°C");
  const hydroAxis=metric==="percent"?`Prozent der Tagesklimareferenz ${referenceLabel()} [%]`:
    anomaly?`Abweichung zur Tagesklimareferenz ${referenceLabel()} [${unit}]`:
    `kumulierte ${paramConfig().label} [${unit}]`;
  return{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:"index",intersect:false},
    scales:{x:{grid:{color:"rgba(120,130,140,.18)"},ticks:{maxRotation:0,autoSkip:true,maxTicksLimit:16,font:{size:11}},title:{display:true,text:"Tag"}},
      y:{min:bounds.min,max:bounds.max,grid:{color:"rgba(120,130,140,.28)"},
        title:{display:true,text:hydroMode()?hydroAxis:(anomaly?`Abweichung ${referenceLabel()} [K]`:"laufendes Mittel [°C]")},
        ticks:{callback:v=>Number(v).toFixed(metric==="percent"?0:1)}}},
    plugins:{legend:{display:false},datalabels:{display:false},tooltip:{callbacks:{label(ctx){
      const v=num(ctx.raw);if(v===null)return null;
      return `${ctx.dataset.label}: ${v>0&&anomaly?"+":""}${fmt(v,metric==="percent"?1:2)} ${unit}`;
    }}}}
  };
}
function destroyCharts(){Object.values(charts).forEach(c=>c?.destroy());charts={};}
function renderLegend(){
  const n=el("stateMonthlyLegend");if(!n)return;
  const regionName=el("stateMonthlyRegion")?.value||"Deutschland";
  const daily=hydroMode()?dailyHydroRunning(regionName):null;
  const available=oldReferenceSelected()?readyReference(daily):daily?.some(v=>v!=null);
  const monthly=hydroMode()?historicalMonthNormal(selectedParameter(),regionName):null;
  const metric=selectedMetric();
  let climateLegend="";
  if(hydroMode()){
    if(metric!=="absolute"&&available){
      climateLegend=`<span><i class="sm-swatch climate"></i>${referenceLabel()} · ${metric==="percent"?"100 %":"0 "+paramConfig().unit}</span>`;
    }else if(metric==="absolute"){
      climateLegend=(available?`<span><i class="sm-swatch climate"></i>${referenceLabel()} · bis zum Tag</span>`:"")+
        (monthly!==null?`<span><i class="sm-swatch climate"></i>${referenceLabel()} · gesamter Monat</span>`:"");
    }
  }else if(oldReferenceSelected()?readyReference(temperatureRunning(region())):temperatureRunning(region()).some(v=>num(v)!==null))climateLegend=`<span><i class="sm-swatch climate"></i>${referenceLabel()}${metric==="anomaly"?" · 0 K Referenz":""}</span>`;
  n.innerHTML=`<span><i class="sm-swatch obs"></i>Beobachtung</span>${climateLegend}<span><i class="sm-band outer"></i>5–95 %</span><span><i class="sm-band inner"></i>20–80 %</span><span><i class="sm-swatch avg"></i>Ensemble-Mittel</span><span><i class="sm-swatch ctl"></i>Kontroll-/Basislauf</span>`;
}
function render(){
  checkCalendarMonth();
  if(!data&&!parameterDoc())return;
  syncParameterControls();
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
  const observedOnly=r.observed_through&&!Object.values(r.models||{}).some(m=>m.forecast_through);
  MODEL_ORDER.forEach(k=>{
    const canvas=el("stateMonthlyChart_"+k),card=canvas?.closest(".state-monthly-card"),m=r.models?.[k]?.forecast_through?r.models[k]:null;if(!canvas||!card)return;
    const obsCard=observedOnly&&k===MODEL_ORDER[0];
    card.hidden=!m&&!obsCard;const title=card.querySelector("h3");if(title)title.textContent=obsCard?(hydroMode()?"Beobachtete Monatssumme":"Beobachtetes Periodenmittel"):MODEL_LABELS[k]||k;
    const meta=card.querySelector(".state-monthly-model-meta");
    if(meta)meta.textContent=m?`${m.member_count} Member · Prognose bis ${dateShort(m.forecast_through)} · ${m.support_points} Stützpunkte · ${m.run?"Lauf "+fmtRun(m.run):m.retrieved_at?"Datenabruf "+fmtRun(m.retrieved_at):"Laufzeit nicht gemeldet"}${modelFreshness(m)?" · "+modelFreshness(m):""}`:obsCard?`Nur ${paramConfig().source}-Beobachtungen`:"nicht verfügbar";
    if(m||obsCard){
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
    const normalText=normal===null?`Klimareferenz ${referenceLabel()} noch nicht verfügbar`:`${referenceLabel()}: Monatsgesamtwert ${fmt(normal,1)} ${config.unit}`;
    if(info){
      info.innerHTML=(r.observed_through?`<strong>${config.source} bis ${dateShort(r.observed_through)}</strong><span>Bisher ${fmt(r.observed_current,1)} ${config.unit}</span><span>Beobachtung + Ensemblefortschreibung</span>`:`<strong>Noch keine Beobachtungen – reine Ensemble-Prognose</strong>`)+`<span>${normalText}</span>`;
      if(hydroMode()){
        const daily=dailyHydroRunning(reg);
        const index=(d.dates||[]).indexOf(r.observed_through);
        const reference=index>=0?num(daily?.[index]):null;
        const observed=num(r.observed_current);
        if(reference!==null&&observed!==null){
          const diff=observed-reference;
          const item=document.createElement("span");
          const percent=reference>0?` (${fmt(observed/reference*100,0)} % des Mittels)`:"";
          item.textContent=`Klimasumme ${referenceLabel()} bis ${dateShort(r.observed_through)}: ${fmt(reference,1)} ${config.unit} · Abweichung ${diff>=0?"+":""}${fmt(diff,1)} ${config.unit}${percent}`;
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
    const retained=Object.values(r.models||{}).filter(m=>m.retained).length;
    const complete=!!d.observation_complete,preview=selectedPeriod()==="next_month";
    const daySeries=dailyHydroRunning(reg),dayAvailable=oldReferenceSelected()?readyReference(daySeries):daySeries?.some(v=>v!=null);
    const refPending=oldReferenceSelected()&&(!dayAvailable||normal===null);
    const freshness=freshnessWarning(d,r.models,complete,preview);
    setStatus(`${d.observation_data_through?`Datenstand ${config.source}: ${d.observation_data_through}`:"Noch keine Beobachtungen"} · Generiert ${label} · ${complete?"Monat vollständig beobachtet":`${Object.keys(r.models||{}).length}/4 Ensemblemodelle`}${preview?" · Reichweite je Modell unterschiedlich":""}${retained?` · ${retained} aus vorherigen Läufen`:""}${qcText}${refPending?` · Klimareferenz ${referenceLabel()} noch nicht vollständig verfügbar`:""}${freshness}`,!freshness&&!refPending&&(complete||(preview||Object.keys(r.models||{}).length===4)&&!qcWarning&&!retained)?"ok":"warn");
    const note=el("stateMonthlyDataNote");
    if(note){
      const refNote=dayAvailable?
        (selectedParameter()==="sunshine"?
         `Die durchgezogene violette Linie zeigt die aus DWD-SDK-Tagesstationswerten ${referenceLabel()} rekonstruierte Tagesklimatologie (6-km-IDW-Gitter, monatsweise an die amtlichen 1-km-Normalwerte angepasst). Sie ist KEIN amtliches tägliches DWD-Raster und keine DUETT-Klimatologie.`:
         `Die durchgezogene violette Linie ist die echte kumulierte Tagesreferenz ${referenceLabel()} aus historischen HYRAS-Tagesrastern (2-km-Webgitter); die fein gestrichelte Linie markiert den amtlichen Monatsnormalwert (1 km). Kleinere Unterschiede am Monatsende sind wegen der Gitterauflösung möglich.`):
        normal===null?`Klimareferenz ${referenceLabel()} noch nicht geladen oder veröffentlicht.`:`Die gestrichelte Klimareferenz ${referenceLabel()} zeigt die volle Monatssumme; dies ist keine Tagesklimatologie.`;
      const metricDescription=selectedMetric()==="percent"?
        "Diese Darstellung zeigt 100 % als kumuliertes Tagesklimamittel; bei Klimawert 0 bleibt der Prozentwert leer.":
        selectedMetric()==="anomaly"?
        "Diese Darstellung zeigt Abweichungen vom kumulierten Tagesklimamittel; die Nulllinie bedeutet genau im Mittel.":
        "Diese Darstellung zeigt absolute kumulierte Gebietssummen.";
      note.textContent=`${config.source} · ${config.unit} · ${metricDescription} ${refNote} Modellprognosen sind Flächenannäherungen aus Stützpunkten. ${selectedParameter()==="sunshine"?"Historische Sonnenschein-Norm: stationsinterpoliertes DWD-Raster; aktuelle DUETT-Daten kombinieren Satellit und Stationen, daher methodischer Unterschied. Die historische Sonnenschein-Tagesreferenz ist eine stationsbasierte Rekonstruktion und methodisch nicht identisch mit DUETT.":""} Fehlende Tage werden nicht zu null.`;
    }
    return;
  }
  const note=el("stateMonthlyDataNote");
  if(note)note.textContent=`Beobachtungen und Klimareferenz: DWD HYRAS-DE-TAS, 1-km-Flächenmittel. Ensembleprognosen aus räumlich verteilten Modellstützpunkten. Temperatur-Abweichung gegen das bis zum jeweiligen Tag aufgelaufene Klimamittel ${referenceLabel()}.`;

  const doc=temperatureDoc();if(!doc)return;
  const period=effectivePeriod(),p=doc.periods?.[period];
  const month=MONTHS[(doc.month||1)-1]||String(doc.month);
  let periodLabel=month+" "+doc.year;
  if(period==="year")periodLabel="Jahr "+doc.year;
  if(period==="season"){
    periodLabel=(p?.label||"Jahreszeit")+" "+doc.year;
    if(p&&p.end_date.slice(0,4)!==p.start_date.slice(0,4)){
      periodLabel=(p.label||"Winter")+" "+p.start_date.slice(0,4)+"/"+p.end_date.slice(2,4);
    }
  }
  const title=el("stateMonthlyTitle");if(title)title.textContent=`${reg} · ${periodLabel}`;
  const dates=periodDates(),obsIndex=dates.indexOf(r.observed_through);
  const reference=oldReferenceSelected()?num(temperatureRunning(r)[obsIndex]):num(r.climatology_to_date)??num(r.climatology_running?.[obsIndex]);
  const calculatedDiff=reference!=null&&num(r.observed_current)!=null?r.observed_current-reference:null;
  const diff=oldReferenceSelected()?calculatedDiff:num(r.observed_anomaly_to_date)??calculatedDiff;
  const climateFinal=temperatureNormal(r);
  const info=el("stateMonthlyInfo");if(info)info.innerHTML=(r.observed_through?`<strong>HYRAS bis ${dateShort(r.observed_through)}</strong><span>bisheriges Periodenmittel ${fmt(r.observed_current,2)} °C</span><span>Klima ${referenceLabel()} bis dahin ${fmt(reference,2)} °C</span><span>Abweichung ${diff==null?"–":`${diff>=0?"+":""}${fmt(diff,2)} K`}</span>`:`<strong>Noch keine Beobachtungen – reine Ensemble-Prognose</strong>`)+`<span>Klimamittel gesamte Periode ${fmt(climateFinal,2)} °C</span>`;
  const gen=new Date(doc.generated_at),generated=Number.isNaN(gen.getTime())?doc.generated_at:gen.toLocaleString("de-DE",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
  const partial=p&&p.complete_reference_period===false?" · Winter startet mangels Vorjahresdaten erst am 01.01.":"";
  const refPending=oldReferenceSelected()&&climateFinal===null;
  const preview=selectedPeriod()==="next_month",complete=r.observed_through===dates[dates.length-1],available=Object.fromEntries(Object.entries(r.models||{}).filter(([,m])=>m.forecast_through)),freshness=freshnessWarning(doc,available,complete,preview);
  setStatus(`${r.observed_through?`Datenstand HYRAS ${r.observed_through}`:"Noch keine Beobachtungen"} · Ensemble-Daten erzeugt ${generated} · ${complete?"Periode vollständig beobachtet":`${Object.keys(available).length}/4 Modelle verfügbar`}${preview?" · Reichweite je Modell unterschiedlich":""}${partial}${refPending?` · Klimareferenz ${referenceLabel()} noch nicht verfügbar`:""}${freshness}`,(complete||preview||Object.keys(available).length===4)&&!partial&&!refPending&&!freshness?"ok":"warn");
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
        const currentMonth=calendarMonthKey(),datasetMonth=monthKey(activeMonthDoc(json));
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
async function fetchDailySunReference(force=false){
  if(dailySunReference&&!force)return dailySunReference;
  if(dailySunLoading)return dailySunLoading;
  dailySunLoading=(async()=>{
    let last=null;
    for(const base of DAILY_SUN_REFERENCE_URLS){
      try{
        const response=await fetch(base+(force?"?t="+Date.now():""),{cache:force?"no-store":"default"});
        if(!response.ok)throw new Error("HTTP "+response.status);
        const doc=await response.json();
        if(doc.schema_version!==1||doc.parameter!=="sunshine"||
           doc.reference_period!=="1991-2020"||doc.daily_climatology_available!==true||
           doc.product!=="state_monthly_daily_sunshine_climatology_station_reconstruction"||
           !doc.months||doc.regions_order?.length!==17)throw new Error("Tagesreferenz-Datenformat ungültig");
        dailySunReference=doc;
        dailySunError=null;
        if(selectedParameter()==="sunshine")render();
        return doc;
      }catch(error){last=error;console.warn("DWD SDK-Sonnen-Tagesklima 1991–2020",base,error);}
    }
    dailySunError=last?.message||"Sonnen-Tagesreferenz noch nicht veröffentlicht";
    if(selectedParameter()==="sunshine")render();
    return null;
  })();
  try{return await dailySunLoading;}finally{dailySunLoading=null;}
}
async function fetchOldReference(kind,force=false){
  if(oldReferences[kind]&&!force)return oldReferences[kind];
  if(oldReferenceLoading[kind])return oldReferenceLoading[kind];
  const branch=kind==="temperature"?"hyras-data":OLD_REFERENCE_BRANCH;
  const file=kind==="temperature"?"tmean/regions/climate_1961_1990.json":OLD_REFERENCE_FILES[kind];
  if(!file)return null;
  const urls=[
    `https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/${branch}/${file}`,
    `https://cdn.jsdelivr.net/gh/MarcelHerber/climate-dashboard@${branch}/${file}`
  ];
  const task=(async()=>{
    let last=null;
    for(const base of urls){
      try{
        const response=await fetch(base+(force?"?t="+Date.now():""),{cache:force?"no-store":"default"});
        if(!response.ok)throw new Error("HTTP "+response.status);
        const doc=await response.json();
        if(!validOldReference(kind,doc))throw new Error("Klimareferenz-Datenformat ungültig oder unvollständig");
        oldReferences[kind]=doc;
        delete oldReferenceErrors[kind];
        return doc;
      }catch(error){last=error;console.warn("Klimareferenz 1961–1990",kind,base,error);}
    }
    oldReferenceErrors[kind]=last?.message||"noch nicht veröffentlicht";
    return null;
  })();
  oldReferenceLoading[kind]=task;
  try{return await task;}finally{
    delete oldReferenceLoading[kind];
    // A reference finishing after a selection change must not update the other reference.
    if(oldReferenceSelected()&&(kind===selectedParameter()||kind==="monthly"&&hydroMode()))render();
  }
}
function syncParameterControls(){
  const monthly=hydroMode(),period=el("stateMonthlyPeriod"),metric=el("stateMonthlyMetric");
  if(period){
    const root=monthly?hydro[selectedParameter()]:data,preview=activeMonthDoc(root,"next_month");
    const current=activeMonthDoc(root);
    period.querySelectorAll("option").forEach(option=>{
      option.disabled=option.value==="next_month"?!preview&&(!!root||!!hydroErrors[selectedParameter()]||period.value!=="next_month"):monthly&&option.value!=="month";
      if(option.value==="month"&&current?.month)option.textContent=`${MONTHS[current.month-1]} ${current.year} (${monthKey(current)===calendarMonthKey()?"laufend":"zuletzt verfügbar"})`;
      if(option.value==="next_month")option.textContent=preview?`${MONTHS[preview.month-1]} ${preview.year} (Vorschau)`:"Folgemonat (noch keine Prognose)";
    });
    if(period.querySelector(`option[value="${period.value}"]`)?.disabled)period.value="month";
  }
  const view=el("stateMonthlyView"),r=region(),models=r?Object.fromEntries(Object.entries(r.models||{}).filter(([,m])=>m.forecast_through)):null;
  if(view){
    view.querySelectorAll("option").forEach(option=>{
      option.disabled=!!models&&option.value!=="four"&&!models[option.value];
    });
    if(view.querySelector(`option[value="${view.value}"]`)?.disabled)view.value="four";
  }
  if(metric){
    const regionName=el("stateMonthlyRegion")?.value||"Deutschland";
    const reference=monthly?dailyHydroRunning(regionName):null;
    const hasDaily=oldReferenceSelected()?readyReference(reference):Array.isArray(reference)&&reference.some(v=>num(v)!==null&&v>0);
    const tempReferenceReady=!oldReferenceSelected()||readyReference(temperatureRunning(region()));
    const options={
      absolute:monthly?`Gesamtsumme (${paramConfig().unit})`:"Temperaturmittel (°C)",
      anomaly:monthly?`Abweichung ${referenceLabel()} (${paramConfig().unit})`:`Abweichung ${referenceLabel()} (K)`,
      percent:"Prozent des Klimamittels (%)"
    };
    metric.querySelectorAll("option").forEach(option=>{
      if(Object.hasOwn(options,option.value))option.textContent=options[option.value];
      option.disabled=option.value==="percent"&&!monthly||
        monthly&&option.value!=="absolute"&&!hasDaily||
        !monthly&&option.value==="anomaly"&&!tempReferenceReady;
    });
    const selected=metric.querySelector(`option[value="${metric.value}"]`);
    if(!selected||selected.disabled)metric.value="absolute";
    metric.disabled=exporting;
    metric.title=monthly&&!hasDaily||!monthly&&!tempReferenceReady?`Abweichung${monthly?"/Prozent":""} nach Laden der tagesgenauen ${referenceLabel()}-Referenz verfügbar`:"";
  }
  const description=el("stateMonthlyExportDescription");
  if(description){
    if(monthly){
      const mode=selectedMetric();
      const metricText=mode==="percent"?"Prozent des Klimamittels [%]":
        mode==="anomaly"?`Abweichung von der täglichen Klimareferenz [${paramConfig().unit}]`:
        `Kumulierte Monatssumme [${paramConfig().unit}]`;
      const reference=dailyHydroRunning(el("stateMonthlyRegion")?.value||"Deutschland"),available=oldReferenceSelected()?readyReference(reference):reference?.some(v=>v!=null);
      const method=available?(selectedParameter()==="sunshine"?" · DWD SDK-Stationsrekonstruktion (6 km), keine DUETT-Klimatologie":" · HYRAS 2 km Tagesreferenz") :" (Tageswerte noch nicht verfügbar)";
      description.textContent=`${metricText} · Beobachtung + Ensemble-Prognose · Klimareferenz ${referenceLabel()}${method}`;
    }else description.textContent=`${selectedMetric()==="anomaly"?"Abweichung [K]":"Laufendes Periodenmittel [°C]"} · Beobachtung + Ensemble-Fortschreibung · Klimareferenz ${referenceLabel()}${oldReferenceSelected()&&temperatureNormal(region())===null?" (noch nicht verfügbar)":""}`;
  }
  const panel=el("state-monthly-ensemble"),header=panel?.querySelector(".state-monthly-header");
  const headline=header?.querySelector("p"),status=header?.querySelector(".section-status");
  if(headline)headline.textContent="Temperatur, Niederschlag und Sonnenscheindauer: Beobachtete Gebietswerte und Ensembleprognosen mit wählbarer Klimareferenz für Deutschland und alle Bundesländer.";
  if(status)status.textContent=`${paramConfig().source} · Klimareferenz ${referenceLabel()} · Ensemble-Prognose`;
}
function loadReference(force=false){
  const param=selectedParameter();
  if(oldReferenceSelected()){
    if(hydroMode())fetchOldReference("monthly",force).catch(()=>{});
    fetchOldReference(param,force).catch(()=>{});
  }else if(hydroMode()){
    if(force||!monthlyNormals)fetchMonthlyNormals(force).catch(()=>{});
    if(param==="precipitation"&&(force||!dailyRainReference))fetchDailyRainReference(force).catch(()=>{});
    if(param==="sunshine"&&(force||!dailySunReference))fetchDailySunReference(force).catch(()=>{});
  }
}
function onParameterChange(){
  syncParameterControls();
  render();
  if(hydroMode()&&!hydro[selectedParameter()])fetchHydro(selectedParameter()).catch(()=>{});
  loadReference();
}
function onReferenceChange(){syncParameterControls();render();loadReference();}
function reloadActive(){
  if(hydroMode()){
    fetchHydro(selectedParameter(),true).catch(()=>{});
  }else load(true);
  loadReference(true);
}
function filename(ext){const reg=(el("stateMonthlyRegion")?.value||"Deutschland").replace(/[^a-z0-9äöüß_-]+/gi,"_");const d=hydroMode()?parameterDoc():temperatureDoc();return `Ensemble_${selectedParameter()}_${selectedPeriod()}_${selectedMetric()}_${selectedReference()}_${d?.year||""}_${String(d?.month||"").padStart(2,"0")}_${reg}.${ext}`;}
function saveBlob(blob,name){const u=URL.createObjectURL(blob),a=document.createElement("a");a.href=u;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),1000);}
async function withExportControlsLocked(capture){
  if(exporting)return;
  if(checkCalendarMonth())render();
  exporting=true;
  const controls=["stateMonthlyRegion","stateMonthlyParameter","stateMonthlyPeriod","stateMonthlyMetric","stateMonthlyReference","stateMonthlyView","stateMonthlyReload","stateMonthlyPng","stateMonthlyPdf"].map(el).filter(Boolean);
  const disabled=controls.map(control=>control.disabled);
  controls.forEach(control=>control.disabled=true);
  try{await capture();}finally{
    exporting=false;
    controls.forEach((control,i)=>control.disabled=disabled[i]);
    syncParameterControls();
  }
}
async function exportPng(){return withExportControlsLocked(async()=>{try{if(!window.html2canvas)throw new Error("html2canvas fehlt");const name=filename("png"),c=await window.captureDashboardWithWhiteBackground(el("stateMonthlyExportArea"),{backgroundColor:"#fff",scale:2,useCORS:true,logging:false});c.toBlob(b=>b&&saveBlob(b,name),"image/png");}catch(e){alert("PNG konnte nicht erstellt werden: "+e.message);}});}
async function exportPdf(){return withExportControlsLocked(async()=>{try{if(!window.html2canvas||!window.jspdf?.jsPDF)throw new Error("PDF-Bibliothek fehlt");const name=filename("pdf"),c=await window.captureDashboardWithWhiteBackground(el("stateMonthlyExportArea"),{backgroundColor:"#fff",scale:2,useCORS:true,logging:false}),J=window.jspdf.jsPDF,p=new J({orientation:"landscape",unit:"mm",format:"a4"}),pw=p.internal.pageSize.getWidth(),ph=p.internal.pageSize.getHeight(),m=7,s=Math.min((pw-2*m)/c.width,(ph-2*m)/c.height),w=c.width*s,h=c.height*s;p.addImage(c.toDataURL("image/jpeg",.93),"JPEG",(pw-w)/2,(ph-h)/2,w,h);p.save(name);}catch(e){alert("PDF konnte nicht erstellt werden: "+e.message);}});}
function mount(){
  if(!el("state-monthly-ensemble"))return;
  const period=el("stateMonthlyPeriod");
  if(period&&!period.querySelector('option[value="next_month"]')){
    const option=document.createElement("option");option.value="next_month";option.textContent="Folgemonat";option.disabled=true;period.appendChild(option);
  }
  // Insert the control in older cached index documents too.
  if(!el("stateMonthlyReference")){
    const metric=el("stateMonthlyMetric"),group=metric?.closest(".control-group");
    if(group){
      const wrapper=document.createElement("div");wrapper.className="control-group";
      const label=document.createElement("label");label.htmlFor="stateMonthlyReference";label.textContent="Klimareferenz";
      const select=document.createElement("select");select.id="stateMonthlyReference";
      for(const period of ["1991-2020","1961-1990"]){const option=document.createElement("option");option.value=period;option.textContent=period.replace("-","–");select.appendChild(option);}
      select.value="1991-2020";wrapper.append(label,select);group.before(wrapper);
    }
  }
  el("stateMonthlyReference")?.addEventListener("change",onReferenceChange);
  el("stateMonthlyRegion")?.addEventListener("change",render);el("stateMonthlyView")?.addEventListener("change",applyView);
  el("stateMonthlyParameter")?.addEventListener("change",onParameterChange);
  el("stateMonthlyPeriod")?.addEventListener("change",render);
  el("stateMonthlyMetric")?.addEventListener("change",render);
  el("stateMonthlyReload")?.addEventListener("click",reloadActive);el("stateMonthlyPng")?.addEventListener("click",exportPng);el("stateMonthlyPdf")?.addEventListener("click",exportPdf);
  const panel=el("state-monthly-ensemble");
  const refreshCalendar=()=>{if(!exporting&&checkCalendarMonth()){render();reloadActive();}};
  new MutationObserver(()=>{if(panel.classList.contains("active")){refreshCalendar();if(!data)load(false);window.setTimeout(()=>Object.values(charts).forEach(c=>c?.resize()),80);}}).observe(panel,{attributes:true,attributeFilter:["class"]});
  window.setInterval(()=>{if(panel.classList.contains("active"))refreshCalendar();},30000);
  document.addEventListener("visibilitychange",()=>{if(!document.hidden&&panel.classList.contains("active"))refreshCalendar();});
  syncParameterControls();
  if(panel.classList.contains("active"))load(false);
}
window.ensureStateMonthlyEnsembleLoaded=function(){return data?Promise.resolve(data):load(false);};
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",mount);else mount();
})();

