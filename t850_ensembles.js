(function(){
"use strict";

const ENSEMBLE_API="https://ensemble-api.open-meteo.com/v1/ensemble";
const DWD_ICON_API="https://api.open-meteo.com/v1/dwd-icon";
const SINGLE_RUN_API="https://single-runs-api.open-meteo.com/v1/forecast";
const GEO="https://geocoding-api.open-meteo.com/v1/search";
const CLIMATE_URLS=[
  "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/t850-climatology/t850_climatology_1991_2020.json",
  "https://cdn.jsdelivr.net/gh/MarcelHerber/climate-dashboard@t850-climatology/t850_climatology_1991_2020.json"
];
const MODELS=[
  {
    key:"ecmwf",label:"ECMWF IFS ENS",api:"ecmwf_ifs025_ensemble",ensembleMeta:"ecmwf_ifs025_ensemble",
    forecastDays:15,mainHours:360,
    mainApi:"ecmwf_ifs025",mainMeta:"ecmwf_ifs025",mainLabel:"IFS Hauptlauf 0,25°",
    canvas:"t850ChartEcmwf",meta:"t850MetaEcmwf",run:"t850RunEcmwf",color:"#2563eb"
  },
  {
    key:"aifs",label:"ECMWF AIFS ENS",api:"ecmwf_aifs025_ensemble",ensembleMeta:"ecmwf_aifs025_ensemble",
    forecastDays:15,mainHours:360,
    mainApi:"ecmwf_aifs025_single",mainMeta:"ecmwf_aifs025_single",mainLabel:"AIFS Hauptlauf 0,25°",
    canvas:"t850ChartAifs",meta:"t850MetaAifs",run:"t850RunAifs",color:"#7c3aed"
  },
  {
    key:"icon",label:"DWD ICON-EU EPS",api:"dwd_icon_eu_eps",ensembleMeta:"dwd_icon_eu_eps",
    mode:"iconFallback",forecastDays:5,mainHours:120,
    mainApi:"icon_eu",mainMeta:"dwd_icon_eu",mainLabel:"ICON-EU Hauptlauf",
    canvas:"t850ChartIcon",meta:"t850MetaIcon",run:"t850RunIcon",color:"#15803d"
  },
  {
    key:"gefs",label:"GFS / GEFS Seamless",api:"ncep_gefs_seamless",ensembleMeta:"ncep_gefs025",
    forecastDays:35,mainHours:384,
    mainApi:"ncep_gfs_seamless",mainMeta:"ncep_gfs025",mainLabel:"GFS Seamless Hauptlauf",
    canvas:"t850ChartGefs",meta:"t850MetaGefs",run:"t850RunGefs",color:"#c2410c"
  }
];
const HOURS=[0,6,12,18];
let mounted=false,charts={},comparison=null,climate=null,climatePromise=null,lastPlace=null,aborter=null,lastResults=[];

function el(id){return document.getElementById(id);}
function finite(v){if(v==null||v==="")return null;v=Number(v);return Number.isFinite(v)?v:null;}
function round(v,d){if(v==null||v==="")return null;v=Number(v);return Number.isFinite(v)?Number(v.toFixed(d==null?2:d)):null;}
function parseUtc(value){
  const text=String(value||"");
  const normalized=/Z$|[+-]\d\d:\d\d$/.test(text)?text:text+"Z";
  return new Date(normalized);
}
function fmtTime(value){
  const d=parseUtc(value); if(Number.isNaN(d.getTime())) return String(value||"");
  return String(d.getUTCDate()).padStart(2,"0")+"."+String(d.getUTCMonth()+1).padStart(2,"0")+". "+String(d.getUTCHours()).padStart(2,"0")+"Z";
}
function fmtRun(value){
  const d=parseUtc(value);if(Number.isNaN(d.getTime()))return "–";
  return String(d.getUTCDate()).padStart(2,"0")+"."+String(d.getUTCMonth()+1).padStart(2,"0")+"."+d.getUTCFullYear()+" · "+String(d.getUTCHours()).padStart(2,"0")+" UTC";
}
function fmtTemp(v){
  v=Number(v); if(!Number.isFinite(v)) return "–";
  return v.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})+" °C";
}
function setStatus(text,type){
  const node=el("t850Status"); if(!node) return;
  node.className="t850-status "+(type||"info"); node.textContent=text||""; node.hidden=!text;
}
function setBusy(busy){
  const b=el("t850LoadButton");
  if(b){b.disabled=busy;b.textContent=busy?"Lade …":"Ensembles laden";}
  ["t850PngDownload","t850PdfDownload"].forEach(function(id){const x=el(id);if(x)x.disabled=busy||!lastPlace;});
}
function setMeta(model,text,type){
  const node=el(model.meta); if(!node)return;
  node.className="t850-model-meta "+(type||"muted");node.textContent=text;
}
function setRun(model,text,type){
  const node=el(model.run);if(!node)return;
  node.className="t850-run-label "+(type||"");node.textContent=text;
}
function placeLabel(p){
  const vals=[p.name,p.admin1,p.country].filter(Boolean);
  return Array.from(new Set(vals)).join(" · ");
}
async function resolvePlace(q,signal){
  const u=new URL(GEO);
  u.searchParams.set("name",q);u.searchParams.set("count","6");u.searchParams.set("language","de");u.searchParams.set("format","json");
  const r=await fetch(u,{signal:signal,cache:"no-store"});if(!r.ok)throw new Error("Ortssuche HTTP "+r.status);
  const j=await r.json(),items=Array.isArray(j.results)?j.results:[];
  if(!items.length)throw new Error("Kein Ort für „"+q+"“ gefunden.");
  return items[0];
}
async function loadClimate(){
  if(climate)return climate;
  if(!climatePromise)climatePromise=(async function(){
    let last=null;
    for(const url of CLIMATE_URLS){
      try{
        const r=await fetch(url+"?v=2",{cache:"force-cache"});if(!r.ok)throw new Error("HTTP "+r.status);
        const j=await r.json();
        if(Number(j.schema_version)!==1||!j.grid||!Array.isArray(j.values))throw new Error("Unerwartetes Format");
        climate=j;return j;
      }catch(e){last=e;console.warn("T850 Klimatologie",url,e);}
    }
    throw last||new Error("Klimatologie nicht verfügbar");
  })().catch(function(e){climatePromise=null;throw e;});
  return climatePromise;
}
function gridPoint(c,lat,lon){
  if(!c||!c.grid)return null;
  const g=c.grid,step=Number(g.step),lat0=Number(g.lat_min),lon0=Number(g.lon_min),nlat=Number(g.nlat),nlon=Number(g.nlon);
  if(![step,lat0,lon0,nlat,nlon].every(Number.isFinite))return null;
  const iy=Math.round((Number(lat)-lat0)/step),ix=Math.round((Number(lon)-lon0)/step);
  if(iy<0||ix<0||iy>=nlat||ix>=nlon)return null;
  return {iy:iy,ix:ix,lat:lat0+iy*step,lon:lon0+ix*step,nlon:nlon};
}
function climateValue(c,p,month,hour){
  const hs=Array.isArray(c.hours)?c.hours:HOURS;
  let hi=hs.findIndex(function(v){return Number(v)===Number(hour);});if(hi<0)hi=0;
  const mi=Math.max(1,Math.min(12,Number(month)))-1;
  return finite(c.values[(((p.iy*p.nlon+p.ix)*12+mi)*hs.length+hi)]);
}
function nearestHour(h){return HOURS.reduce(function(best,v){return Math.abs(v-h)<Math.abs(best-h)?v:best;},HOURS[0]);}
function interpolatedClimate(c,p,iso){
  const d=parseUtc(iso);if(Number.isNaN(d.getTime()))return null;
  const h=nearestHour(d.getUTCHours()),y=d.getUTCFullYear(),m=d.getUTCMonth()+1,anchor=new Date(Date.UTC(y,m-1,15,h));
  let lm,rm,ld,rd;
  if(d<anchor){
    rm=m;rd=anchor;lm=m===1?12:m-1;ld=new Date(Date.UTC(m===1?y-1:y,lm-1,15,h));
  }else{
    lm=m;ld=anchor;rm=m===12?1:m+1;rd=new Date(Date.UTC(m===12?y+1:y,rm-1,15,h));
  }
  const a=climateValue(c,p,lm,h),b=climateValue(c,p,rm,h);
  if(a==null)return b;if(b==null)return a;
  const f=Math.max(0,Math.min(1,(d-ld)/(rd-ld)));return a+(b-a)*f;
}
function climateSeries(c,lat,lon,times){
  const p=gridPoint(c,lat,lon);
  return {point:p,values:p?times.map(function(t){return round(interpolatedClimate(c,p,t),2);}):times.map(function(){return null;})};
}
function pressureKey(hourly){
  const keys=Object.keys(hourly||{});
  return keys.find(function(k){return k==="temperature_850hPa";})||
    keys.find(function(k){return /^temperature_850hPa_/.test(k)&&!/member\d+$/.test(k);})||null;
}
function synopticIndexes(times,maxHours){
  const indexed=(times||[]).map(function(t,i){return {t:t,i:i,d:parseUtc(t)};}).filter(function(x){return !Number.isNaN(x.d.getTime());});
  if(!indexed.length)return [];
  const hours=Number(maxHours);
  const limit=Number.isFinite(hours)?indexed[0].d.getTime()+hours*3600000+60000:Infinity;
  let keep=indexed.filter(function(x){return x.d.getTime()<=limit&&HOURS.includes(x.d.getUTCHours());});
  if(keep.length<5){
    keep=indexed.filter(function(x,idx){return x.d.getTime()<=limit&&idx%6===0;});
  }
  return keep;
}
function hasFiniteSeries(series){return Array.isArray(series)&&series.some(function(v){return Number.isFinite(v);});}


async function fetchMemberEnsemble(model,lat,lon,signal){
  const u=new URL(ENSEMBLE_API);
  u.searchParams.set("latitude",Number(lat).toFixed(4));
  u.searchParams.set("longitude",Number(lon).toFixed(4));
  u.searchParams.set("hourly","temperature_850hPa");
  u.searchParams.set("models",model.api);
  u.searchParams.set("forecast_days",String(model.forecastDays));
  u.searchParams.set("timezone","GMT");
  u.searchParams.set("cell_selection","nearest");
  const r=await fetch(u,{signal:signal,cache:"no-store"});
  if(!r.ok)throw new Error(model.label+" HTTP "+r.status);
  const j=await r.json(),h=j.hourly||{},times=Array.isArray(h.time)?h.time:[];

  const controlKey=Array.isArray(h.temperature_850hPa)?"temperature_850hPa":null;
  const memberKeys=Object.keys(h).filter(function(k){
    return /^temperature_850hPa_member\d+$/.test(k)&&Array.isArray(h[k]);
  });
  if(!times.length||(!controlKey&&!memberKeys.length)){
    throw new Error(model.label+" lieferte keine T850-Ensemblemember.");
  }

  const keep=synopticIndexes(times,model.forecastDays*24);
  const sampledTimes=keep.map(function(x){return x.t;});
  const sample=function(key){return keep.map(function(x){return finite(h[key][x.i]);});};
  const control=controlKey?sample(controlKey):null;
  const members=memberKeys.map(sample);
  const all=(control?[control]:[]).concat(members);
  const finiteCount=all.reduce(function(sum,series){
    return sum+series.filter(Number.isFinite).length;
  },0);
  if(!finiteCount){
    throw new Error(model.label+" liefert aktuell T850-Memberfelder ohne gültige Werte.");
  }
  return {
    model:model,times:sampledTimes,control:control,members:members,
    ensembleCount:all.length,allMembers:all
  };
}

async function fetchIconDeterministicFallback(model,lat,lon,signal){
  const u=new URL(DWD_ICON_API);
  u.searchParams.set("latitude",Number(lat).toFixed(4));
  u.searchParams.set("longitude",Number(lon).toFixed(4));
  u.searchParams.set("hourly","temperature_850hPa");
  u.searchParams.set("models","icon_eu");
  u.searchParams.set("forecast_days",String(model.forecastDays));
  u.searchParams.set("timezone","GMT");
  u.searchParams.set("cell_selection","nearest");
  const r=await fetch(u,{signal:signal,cache:"no-store"});
  if(!r.ok)throw new Error("ICON-EU Hauptlauf HTTP "+r.status);
  const j=await r.json(),h=j.hourly||{},times=Array.isArray(h.time)?h.time:[];
  const raw=Array.isArray(h.temperature_850hPa)?h.temperature_850hPa:null;
  if(!times.length||!raw)throw new Error("ICON-EU Hauptlauf liefert kein T850.");

  const keep=synopticIndexes(times,model.mainHours);
  const sampledTimes=keep.map(function(x){return x.t;});
  const values=keep.map(function(x){return finite(raw[x.i]);});
  if(!hasFiniteSeries(values))throw new Error("ICON-EU Hauptlauf liefert keine gültigen T850-Werte.");

  return {
    model:model,times:sampledTimes,control:null,members:[],
    ensembleCount:0,allMembers:[values],
    precomputedStats:{mean:values,p10:values,p90:values},
    deterministicFallback:true
  };
}

async function fetchEnsemble(model,lat,lon,signal){
  if(model.mode==="iconFallback"){
    try{
      return await fetchMemberEnsemble(model,lat,lon,signal);
    }catch(e){
      if(e.name==="AbortError")throw e;
      console.warn("ICON-EU EPS T850 nicht verfügbar; Hauptlauf-Fallback wird verwendet.",e);
      return fetchIconDeterministicFallback(model,lat,lon,signal);
    }
  }
  return fetchMemberEnsemble(model,lat,lon,signal);
}

async function fetchModelMeta(domain,signal){
  if(!domain)return null;
  const url="https://api.open-meteo.com/data/"+encodeURIComponent(domain)+"/static/meta.json";
  try{
    const r=await fetch(url,{signal:signal,cache:"no-store"});
    if(!r.ok)return null;
    const j=await r.json();
    const ts=Number(j.last_run_initialisation_time);
    if(!Number.isFinite(ts))return null;
    return {
      run:new Date(ts*1000).toISOString().slice(0,13)+":00",
      availability:Number(j.last_run_availability_time)||null
    };
  }catch(e){
    if(e.name==="AbortError")throw e;
    console.warn("T850 Metadaten",domain,e);
    return null;
  }
}
async function fetchMainRunForCycle(model,run,lat,lon,signal){
  const u=new URL(SINGLE_RUN_API);
  u.searchParams.set("latitude",Number(lat).toFixed(4));u.searchParams.set("longitude",Number(lon).toFixed(4));
  u.searchParams.set("hourly","temperature_850hPa");u.searchParams.set("models",model.mainApi);
  u.searchParams.set("run",run);u.searchParams.set("forecast_hours",String(model.mainHours+1));
  u.searchParams.set("timezone","GMT");u.searchParams.set("cell_selection","nearest");
  const r=await fetch(u,{signal:signal,cache:"no-store"});
  if(!r.ok)throw new Error("Hauptlauf HTTP "+r.status);
  const j=await r.json(),h=j.hourly||{},times=Array.isArray(h.time)?h.time:[],key=pressureKey(h);
  if(!times.length||!key)throw new Error("Hauptlauf ohne T850.");
  const keep=synopticIndexes(times,model.mainHours),values=keep.map(function(x){return finite(h[key][x.i]);});
  if(!hasFiniteSeries(values))throw new Error("Hauptlauf ohne gültige T850-Werte.");
  return {run:run,times:keep.map(function(x){return x.t;}),values:values};
}
function alignSeries(source,targetTimes){
  if(!source||!Array.isArray(source.times)||!Array.isArray(source.values))return targetTimes.map(function(){return null;});
  const map=new Map(source.times.map(function(t,i){return [t,source.values[i]];}));
  return targetTimes.map(function(t){return map.has(t)?map.get(t):null;});
}
function quantile(a,q){
  if(!a.length)return null;if(a.length===1)return a[0];
  const p=(a.length-1)*q,b=Math.floor(p),f=p-b;return a[b+1]!==undefined?a[b]+f*(a[b+1]-a[b]):a[b];
}
function stats(result){
  if(result.precomputedStats)return result.precomputedStats;
  const mean=[],p10=[],p90=[];
  for(let i=0;i<result.times.length;i++){
    const a=result.allMembers.map(function(m){return m[i];}).filter(Number.isFinite).sort(function(x,y){return x-y;});
    if(!a.length){mean.push(null);p10.push(null);p90.push(null);continue;}
    mean.push(round(a.reduce(function(s,v){return s+v;},0)/a.length,2));p10.push(round(quantile(a,.1),2));p90.push(round(quantile(a,.9),2));
  }
  return {mean:mean,p10:p10,p90:p90};
}
function commonBounds(results){
  const v=[];
  results.forEach(function(r){
    r.allMembers.forEach(function(m){m.forEach(function(x){if(Number.isFinite(x))v.push(x);});});
    if(r.mainAligned)r.mainAligned.forEach(function(x){if(Number.isFinite(x))v.push(x);});
    if(r.climate)r.climate.values.forEach(function(x){if(Number.isFinite(x))v.push(x);});
  });
  if(!v.length)return {min:-20,max:20};
  let mn=Math.floor((Math.min.apply(null,v)-2)/5)*5,mx=Math.ceil((Math.max.apply(null,v)+2)/5)*5;
  if(mx-mn<15){mn-=5;mx+=5;}return {min:mn,max:mx};
}
function options(bounds){
  return {
    responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:"index",intersect:false},
    scales:{x:{ticks:{maxRotation:0,autoSkip:true,maxTicksLimit:9,font:{size:11}},grid:{display:false}},y:{min:bounds.min,max:bounds.max,title:{display:true,text:"T850 [°C]"},ticks:{callback:function(v){return v+"°";}}}},
    plugins:{
      datalabels:{display:false},
      legend:{position:"bottom",labels:{boxWidth:16,usePointStyle:true,filter:function(item,data){return !data.datasets[item.datasetIndex]._hideLegend;}}},
      tooltip:{filter:function(item){return item.dataset._tooltip!==false;},callbacks:{label:function(ctx){return ctx.dataset.label+": "+fmtTemp(ctx.parsed.y);}}},
      zoom:{pan:{enabled:true,mode:"x",modifierKey:"shift"},zoom:{wheel:{enabled:true},pinch:{enabled:true},mode:"x"}}
    }
  };
}
function modelChart(r,bounds){
  const c=el(r.model.canvas);if(!c)return;if(charts[r.model.key])charts[r.model.key].destroy();
  const labels=r.times.map(fmtTime),sets=[];
  if(!r.deterministicFallback){
    sets.push(
      {label:"10.–90. Perzentil",data:r.stats.p10,borderColor:"rgba(37,99,235,0)",backgroundColor:"rgba(37,99,235,0)",pointRadius:0,borderWidth:0,_hideLegend:true},
      {label:"10.–90. Perzentil",data:r.stats.p90,borderColor:"rgba(37,99,235,0)",backgroundColor:"rgba(37,99,235,.12)",pointRadius:0,borderWidth:0,fill:"-1",_hideLegend:true}
    );
  }
  r.members.forEach(function(m,i){
    sets.push({label:"Member "+(i+1),data:m,borderColor:"rgba(71,85,105,.20)",backgroundColor:"rgba(71,85,105,0)",borderWidth:1,pointRadius:0,tension:.12,spanGaps:true,_hideLegend:true,_tooltip:false});
  });
  if(r.control&&hasFiniteSeries(r.control)){
    sets.push({label:"Kontrolllauf",data:r.control,borderColor:"#4b5563",backgroundColor:"#4b5563",borderDash:[6,4],borderWidth:2,pointRadius:0,tension:.14,spanGaps:true});
  }
  if(r.deterministicFallback){
    sets.push({label:"ICON-EU Hauptlauf (EPS-T850 derzeit nicht verfügbar)",data:r.stats.mean,borderColor:"#111827",backgroundColor:"#111827",borderWidth:4,pointRadius:0,tension:.15,spanGaps:true});
  }else{
    sets.push({label:"Ensemble-Mittel",data:r.stats.mean,borderColor:r.model.color,backgroundColor:r.model.color,borderWidth:3,pointRadius:0,tension:.16,spanGaps:true});
    if(r.mainAligned&&hasFiniteSeries(r.mainAligned)){
      sets.push({label:"Hauptlauf · "+fmtRun(r.main.run),data:r.mainAligned,borderColor:"#111827",backgroundColor:"#111827",borderWidth:4,pointRadius:0,tension:.15,spanGaps:true});
    }
  }
  sets.push({label:"1991–2020 ERA5",data:r.climate.values,borderColor:"#c62828",backgroundColor:"#c62828",borderWidth:4,pointRadius:0,tension:.22,spanGaps:true});
  sets.push({label:"0 °C",data:labels.map(function(){return 0;}),borderColor:"rgba(31,41,55,.45)",borderDash:[6,5],borderWidth:1.3,pointRadius:0,_hideLegend:true,_tooltip:false});
  charts[r.model.key]=new Chart(c.getContext("2d"),{type:"line",data:{labels:labels,datasets:sets},options:options(bounds)});
}
function comparisonChart(results,bounds,lat,lon,c){
  const canvas=el("t850ComparisonChart");if(!canvas)return;if(comparison)comparison.destroy();
  const set=new Set();results.forEach(function(r){r.times.forEach(function(t){set.add(t);});});
  const times=Array.from(set).sort(),map=new Map(times.map(function(t,i){return [t,i];})),sets=[];
  results.filter(function(r){return !r.deterministicFallback;}).forEach(function(r){
    const d=times.map(function(){return null;});
    r.times.forEach(function(t,i){d[map.get(t)]=r.stats.mean[i];});
    sets.push({label:r.model.label,data:d,borderColor:r.model.color,backgroundColor:r.model.color,borderWidth:2.6,pointRadius:0,tension:.16,spanGaps:true});
  });
  sets.push({label:"1991–2020 ERA5",data:climateSeries(c,lat,lon,times).values,borderColor:"#c62828",backgroundColor:"#c62828",borderWidth:4,pointRadius:0,tension:.22,spanGaps:true});
  sets.push({label:"0 °C",data:times.map(function(){return 0;}),borderColor:"rgba(31,41,55,.45)",borderDash:[6,5],borderWidth:1.3,pointRadius:0,_hideLegend:true,_tooltip:false});
  comparison=new Chart(canvas.getContext("2d"),{type:"line",data:{labels:times.map(fmtTime),datasets:sets},options:options(bounds)});
}
function renderPlace(p,cp){
  const n=el("t850ResolvedLocation");if(!n)return;
  n.textContent="";
  const strong=document.createElement("strong");strong.textContent=placeLabel(p);n.appendChild(strong);
  const a=document.createElement("span");a.textContent=Number(p.latitude).toFixed(3)+"°, "+Number(p.longitude).toFixed(3)+"°";n.appendChild(a);
  const b=document.createElement("span");b.textContent=cp?"ERA5-Gitterpunkt "+cp.lat.toFixed(1)+"°, "+cp.lon.toFixed(1)+"°":"ERA5-Klimareferenz außerhalb des derzeitigen Rasters";n.appendChild(b);
}
function applyPanelView(){
  const select=el("t850PanelSelect"),grid=el("t850ModelGrid"),comparisonCard=el("t850ComparisonCard");
  if(!select||!grid)return;
  const value=select.value||"gefs";
  const single=value!=="four";
  grid.classList.toggle("single-model",single);
  grid.querySelectorAll("[data-t850-model]").forEach(function(card){
    card.hidden=single&&card.dataset.t850Model!==value;
  });
  if(comparisonCard)comparisonCard.hidden=single;
  window.setTimeout(function(){
    Object.values(charts).forEach(function(chart){if(chart&&chart.canvas&&chart.canvas.offsetParent!==null)chart.resize();});
    if(comparison&&comparison.canvas.offsetParent!==null)comparison.resize();
  },60);
}
async function buildEnsembleResult(model,p,c,signal){
  const ensemble=await fetchEnsemble(model,p.latitude,p.longitude,signal);
  ensemble.stats=stats(ensemble);
  ensemble.main=null;
  ensemble.mainAligned=ensemble.times.map(function(){return null;});
  ensemble.climate=climateSeries(c,p.latitude,p.longitude,ensemble.times);
  return ensemble;
}
function renderAvailableResults(good,p,c){
  if(!good.length)return;
  const bounds=commonBounds(good);
  good.forEach(function(r){modelChart(r,bounds);});
  comparisonChart(good,bounds,p.latitude,p.longitude,c);
  const cp=gridPoint(c,p.latitude,p.longitude);renderPlace(p,cp);
  applyPanelView();
}
function updateModelMeta(r){
  if(r.deterministicFallback){
    setMeta(
      r.model,
      "EPS-T850 liefert aktuell keine gültigen Werte · zeige ICON-EU Hauptlauf als Fallback · "+
      fmtTime(r.times[0])+" bis "+fmtTime(r.times[r.times.length-1])+
      (r.climate.point?" · Klima geladen":" · Klima fehlt"),
      "warn"
    );
    return;
  }
  const controlText=r.control&&hasFiniteSeries(r.control)?"inkl. Kontrolllauf":"ohne separaten Kontrolllauf";
  setMeta(
    r.model,
    r.ensembleCount+" ENS · "+controlText+" · "+fmtTime(r.times[0])+" bis "+fmtTime(r.times[r.times.length-1])+
      " · Horizont "+r.model.forecastDays+" Tage"+(r.climate.point?" · Klima geladen":" · Klima fehlt"),
    "ok"
  );
}
async function enrichWithRunInfo(r,p,c,good,signal){
  const m=r.model;
  if(r.deterministicFallback){
    const mainMeta=await fetchModelMeta(m.mainMeta,signal);
    if(signal.aborted)return;
    const mainText=mainMeta?fmtRun(mainMeta.run)+" · "+m.mainLabel:"neueste verfügbare ICON-EU-Ausgabe";
    setRun(m,"EPS T850: derzeit nicht verfügbar · Hauptlauf: "+mainText);
    return;
  }
  const [ensMeta,mainMeta]=await Promise.all([
    fetchModelMeta(m.ensembleMeta,signal),
    fetchModelMeta(m.mainMeta,signal)
  ]);
  if(signal.aborted)return;

  const ensembleText=ensMeta?fmtRun(ensMeta.run):"neueste verfügbare Ausgabe";
  setRun(m,"Ensemble: "+ensembleText+" · Hauptlauf wird geladen …");

  let main=null;
  if(mainMeta&&mainMeta.run){
    try{main=await fetchMainRunForCycle(m,mainMeta.run,p.latitude,p.longitude,signal);}
    catch(e){
      if(e.name==="AbortError")throw e;
      console.warn(m.label+" Hauptlauf",e);
    }
  }
  if(signal.aborted)return;

  r.main=main;
  r.mainAligned=main?alignSeries(main,r.times):r.times.map(function(){return null;});
  renderAvailableResults(good,p,c);

  const mainText=main?fmtRun(main.run)+" · "+m.mainLabel:"nicht verfügbar";
  setRun(m,"Ensemble: "+ensembleText+" · Hauptlauf: "+mainText);
}
async function load(q){
  q=String(q||"").trim();if(q.length<2){setStatus("Bitte einen Ort eingeben.","warn");return;}
  if(aborter)aborter.abort();aborter=new AbortController();const signal=aborter.signal;
  const panelSelect=el("t850PanelSelect");if(panelSelect)panelSelect.value="";
  applyPanelView();
  setBusy(true);
  setStatus("Ort wird gesucht; GFS/GEFS wird zuerst geladen …","info");
  MODELS.forEach(function(m){
    setRun(m,"Ensemble-Lauf wird bestimmt … · Hauptlauf folgt");
    setMeta(m,m.key==="gefs"?"GFS/GEFS wird geladen …":"wartet auf GFS-Startansicht …");
  });

  try{
    const p=await resolvePlace(q,signal);lastPlace=p;
    const c=await loadClimate().catch(function(e){console.warn(e);return null;});
    const good=[];
    const defaultModel=MODELS.find(function(m){return m.key==="gefs";})||MODELS[0];

    // GFS/GEFS zuerst laden und sofort darstellen.
    try{
      const first=await buildEnsembleResult(defaultModel,p,c,signal);
      if(signal.aborted)return;
      good.push(first);
      lastResults=good;
      updateModelMeta(first);
      setRun(first.model,"Ensemble: neueste verfügbare Ausgabe · Hauptlauf wird ergänzt …");
      renderAvailableResults(good,p,c);
      setStatus(
        "GFS/GEFS ist geladen und wird groß dargestellt. ECMWF, AIFS und ICON werden jetzt im Hintergrund ergänzt.",
        "ok"
      );
      setBusy(false);
      void enrichWithRunInfo(first,p,c,good,signal).catch(function(e){
        if(e.name!=="AbortError")console.warn(first.model.label+" Laufinfo",e);
      });
    }catch(e){
      if(e.name==="AbortError")throw e;
      setRun(defaultModel,"Ensemble derzeit nicht darstellbar");
      setMeta(defaultModel,e.message,"error");
      setStatus("GFS/GEFS konnte nicht geladen werden; die übrigen Modelle werden trotzdem versucht.","warn");
      setBusy(false);
    }

    // Weitere Modelle parallel im Hintergrund laden. Jedes Panel wird sofort
    // gezeichnet, sobald seine Daten da sind.
    const others=MODELS.filter(function(m){return m.key!==defaultModel.key;});
    void Promise.allSettled(others.map(async function(m){
      try{
        const r=await buildEnsembleResult(m,p,c,signal);
        if(signal.aborted)return;
        good.push(r);
        lastResults=good;
        updateModelMeta(r);
        setRun(r.model,"Ensemble: neueste verfügbare Ausgabe · Hauptlauf wird ergänzt …");
        renderAvailableResults(good,p,c);
        void enrichWithRunInfo(r,p,c,good,signal).catch(function(e){
          if(e.name!=="AbortError")console.warn(r.model.label+" Laufinfo",e);
        });
      }catch(e){
        if(e.name==="AbortError")throw e;
        setRun(m,"Ensemble derzeit nicht darstellbar");
        setMeta(m,e.message,"error");
      }
    })).then(function(){
      if(signal.aborted)return;
      const ensembleCount=good.filter(function(r){return !r.deterministicFallback;}).length;
      const hasIconFallback=good.some(function(r){return r.deterministicFallback;});
      const missing=MODELS.length-good.length;
      setStatus(
        ensembleCount+"/4 Ensemblemodelle mit gültiger T850 geladen"+
        (hasIconFallback?" · ICON-EU wird ersatzweise als Hauptlauf gezeigt":"")+
        (missing?" · "+missing+" Modell(e) ohne Darstellung":"")+
        ". Standardansicht bleibt GFS; weitere Panels können oben ausgewählt werden.",
        (hasIconFallback||missing)?"warn":"ok"
      );
    });
  }catch(e){
    if(e.name!=="AbortError"){
      console.error("T850",e);
      setStatus(e.message||String(e),"error");
      lastPlace=null;
    }
  }finally{
    if(!signal.aborted)setBusy(false);
  }
}
function resetZoom(){Object.values(charts).forEach(function(c){if(c.resetZoom)c.resetZoom();});if(comparison&&comparison.resetZoom)comparison.resetZoom();}
function filename(ext){
  const view=el("t850PanelSelect")?.value||"gefs";
  return "T850_Ensembles_"+view+"_"+String(lastPlace&&lastPlace.name||"Ort").replace(/[^a-z0-9äöüß_-]+/gi,"_")+"."+ext;
}
async function exportCanvas(){
  if(!window.html2canvas)throw new Error("html2canvas ist nicht geladen.");
  return window.html2canvas(el("t850ExportArea"),{backgroundColor:"#fff",scale:2,useCORS:true,logging:false});
}
function saveBlob(blob,name){const u=URL.createObjectURL(blob),a=document.createElement("a");a.href=u;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(function(){URL.revokeObjectURL(u);},1000);}
async function png(){try{const c=await exportCanvas();c.toBlob(function(b){if(b)saveBlob(b,filename("png"));},"image/png");}catch(e){alert("PNG konnte nicht erstellt werden: "+e.message);}}
async function pdf(){
  try{
    const c=await exportCanvas(),J=window.jspdf&&window.jspdf.jsPDF;if(!J)throw new Error("jsPDF ist nicht geladen.");
    const p=new J({orientation:"landscape",unit:"mm",format:"a4"}),pw=p.internal.pageSize.getWidth(),ph=p.internal.pageSize.getHeight(),m=7,s=Math.min((pw-2*m)/c.width,(ph-2*m)/c.height),w=c.width*s,h=c.height*s;
    p.addImage(c.toDataURL("image/jpeg",.93),"JPEG",(pw-w)/2,(ph-h)/2,w,h,undefined,"FAST");p.save(filename("pdf"));
  }catch(e){alert("PDF konnte nicht erstellt werden: "+e.message);}
}
function mount(){
  if(mounted){applyPanelView();setTimeout(function(){Object.values(charts).forEach(function(c){c.resize();});if(comparison)comparison.resize();},40);return;}
  const form=el("t850SearchForm"),input=el("t850LocationInput"),view=el("t850PanelSelect");if(!form||!input)return;mounted=true;
  form.addEventListener("submit",function(e){e.preventDefault();load(input.value);});
  el("t850ResetZoom")?.addEventListener("click",resetZoom);
  el("t850PngDownload")?.addEventListener("click",png);
  el("t850PdfDownload")?.addEventListener("click",pdf);
  view?.addEventListener("change",applyPanelView);
  applyPanelView();
  setStatus("Ort eingeben und „Ensembles laden“ wählen. Danach wird zuerst GFS/GEFS groß gezeigt; weitere Panels wählst du oben gezielt aus.","info");
}
window.mountT850Ensembles=mount;
document.addEventListener("click",function(e){
  const b=e.target.closest&&e.target.closest(".tab-button");
  if(b&&String(b.getAttribute("onclick")||"").includes("switchTab('t850-ensembles')"))setTimeout(mount,0);
});
function watchPanelActivation(){
  const p=el("t850-ensembles");if(!p)return;
  const activate=function(){if(p.classList.contains("active"))mount();};
  activate();
  const observer=new MutationObserver(activate);
  observer.observe(p,{attributes:true,attributeFilter:["class"]});
}
if(document.readyState==="loading"){
  document.addEventListener("DOMContentLoaded",watchPanelActivation);
}else{
  watchPanelActivation();
}
})();