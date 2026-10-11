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
function selectedPeriod(){return el("stateMonthlyPeriod")?.value||"month";}
function selectedMetric(){return el("stateMonthlyMetric")?.value||"absolute";}
function periodDates(){return data?.periods?.[selectedPeriod()]?.dates|| (selectedPeriod()==="month"?data?.dates:[])||[];}
function labels(){return periodDates().map(dateShort);}
function region(){
  const name=el("stateMonthlyRegion")?.value||"Deutschland";
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
  if(!values.length)return{min:-5,max:20};
  const mn=Math.min(...values),mx=Math.max(...values);
  const pad=Math.max(.25,(mx-mn)*.08);
  let min=Math.floor((mn-pad)*2)/2;
  let max=Math.ceil((mx+pad)*2)/2;
  if(max-min<2){min-=1;max+=1;}
  return{min,max};
}
function bandDataset(label,dataArr,bg,fill,target,borderWidth=0){return{label,data:dataArr,borderColor:"rgba(0,0,0,0)",backgroundColor:bg,borderWidth,pointRadius:0,fill:fill?target:false,tension:.15,spanGaps:false};}
function datasetsFor(modelKey,r){
  const m=r.models?.[modelKey];if(!m)return[];
  const s=m.stats||{},p=palette(modelKey),obs=r.observed_running||[],clim=r.climatology_running||[];
  const p05=connectForecast(s.p05,r),p95=connectForecast(s.p95,r),p20=connectForecast(s.p20,r),p80=connectForecast(s.p80,r);
  const min=connectForecast(s.min,r),max=connectForecast(s.max,r),avg=connectForecast(s.mean,r),ctl=connectForecast(m.control,r);
  return[
    {label:"Beobachtetes laufendes Monatsmittel",data:obs,borderColor:"#f57c00",backgroundColor:"#f57c00",borderWidth:2.2,pointRadius:0,tension:.08,spanGaps:false},
    {label:`Klimamittel 1991–2020 (${fmt(r.climatology_month_mean,2)} °C)`,data:clim,borderColor:"#b044d6",borderWidth:2,borderDash:[11,4,2,4],pointRadius:0,tension:.08,spanGaps:false},
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
  if(selectedMetric()!=="anomaly")return datasets;
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
function chartOptions(bounds){const anomaly=selectedMetric()==="anomaly";return{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:"index",intersect:false},
  scales:{x:{grid:{color:"rgba(120,130,140,.18)"},ticks:{maxRotation:0,autoSkip:true,maxTicksLimit:16,font:{size:11}},title:{display:true,text:"Tag"}},y:{min:bounds.min,max:bounds.max,grid:{color:"rgba(120,130,140,.28)"},title:{display:true,text:anomaly?"Abweichung 1991–2020 [K]":"laufendes Mittel [°C]"},ticks:{callback:v=>Number(v).toFixed(1)}}},
  plugins:{legend:{display:false},datalabels:{display:false},tooltip:{callbacks:{label(ctx){const v=num(ctx.raw);if(v===null)return null;return `${ctx.dataset.label}: ${v>0&&anomaly?"+":""}${fmt(v,2)} ${anomaly?"K":"°C"}`;}}}}};}
function destroyCharts(){Object.values(charts).forEach(c=>c?.destroy());charts={};}
function renderLegend(){
  const n=el("stateMonthlyLegend");if(!n)return;
  n.innerHTML=`<span><i class="sm-swatch obs"></i>Beobachtung</span><span><i class="sm-swatch climate"></i>${selectedMetric()==="anomaly"?"0 K Referenz":"1991–2020"}</span><span><i class="sm-band outer"></i>5–95 %</span><span><i class="sm-band inner"></i>20–80 %</span><span><i class="sm-swatch avg"></i>Ensemble-Mittel</span><span><i class="sm-swatch ctl"></i>Kontroll-/Basislauf</span>`;
}
function render(){
  if(!data)return;
  destroyCharts();
  const r=region();
  if(!r){
    setStatus("Die Jahreszeiten- und Jahresdaten werden noch berechnet. Monatsdaten bleiben verfügbar.","warn");
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
  const s=el("stateMonthlyRegion");if(!s||!data)return;const old=s.value||"Deutschland";s.innerHTML="";
  data.regions_order.forEach(name=>{const o=document.createElement("option");o.value=name;o.textContent=name;s.appendChild(o);});s.value=data.regions_order.includes(old)?old:"Deutschland";
}
async function load(force=false){
  if(loading)return loading;setStatus("Bundesland-Monatsensembles werden geladen …","info");
  loading=fetchData(force).then(j=>{data=j;fillRegions();render();return j;}).catch(e=>{console.error(e);setStatus("Monats-Ensembles konnten nicht geladen werden: "+e.message,"error");throw e;}).finally(()=>{loading=null;});
  return loading;
}
function filename(ext){const reg=(el("stateMonthlyRegion")?.value||"Deutschland").replace(/[^a-z0-9äöüß_-]+/gi,"_");return `Ensemble_${selectedPeriod()}_${selectedMetric()}_${data?.year||""}_${String(data?.month||"").padStart(2,"0")}_${reg}.${ext}`;}
function saveBlob(blob,name){const u=URL.createObjectURL(blob),a=document.createElement("a");a.href=u;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),1000);}
async function exportPng(){try{if(!window.html2canvas)throw new Error("html2canvas fehlt");const c=await html2canvas(el("stateMonthlyExportArea"),{backgroundColor:"#fff",scale:2,useCORS:true,logging:false});c.toBlob(b=>b&&saveBlob(b,filename("png")),"image/png");}catch(e){alert("PNG konnte nicht erstellt werden: "+e.message);}}
async function exportPdf(){try{if(!window.html2canvas||!window.jspdf?.jsPDF)throw new Error("PDF-Bibliothek fehlt");const c=await html2canvas(el("stateMonthlyExportArea"),{backgroundColor:"#fff",scale:2,useCORS:true,logging:false}),J=window.jspdf.jsPDF,p=new J({orientation:"landscape",unit:"mm",format:"a4"}),pw=p.internal.pageSize.getWidth(),ph=p.internal.pageSize.getHeight(),m=7,s=Math.min((pw-2*m)/c.width,(ph-2*m)/c.height),w=c.width*s,h=c.height*s;p.addImage(c.toDataURL("image/jpeg",.93),"JPEG",(pw-w)/2,(ph-h)/2,w,h);p.save(filename("pdf"));}catch(e){alert("PDF konnte nicht erstellt werden: "+e.message);}}
function mount(){
  if(!el("state-monthly-ensemble"))return;
  el("stateMonthlyRegion")?.addEventListener("change",render);el("stateMonthlyView")?.addEventListener("change",applyView);
  el("stateMonthlyPeriod")?.addEventListener("change",render);
  el("stateMonthlyMetric")?.addEventListener("change",render);
  el("stateMonthlyReload")?.addEventListener("click",()=>load(true));el("stateMonthlyPng")?.addEventListener("click",exportPng);el("stateMonthlyPdf")?.addEventListener("click",exportPdf);
  const panel=el("state-monthly-ensemble");
  new MutationObserver(()=>{if(panel.classList.contains("active")){if(!data)load(false);window.setTimeout(()=>Object.values(charts).forEach(c=>c?.resize()),80);}}).observe(panel,{attributes:true,attributeFilter:["class"]});
  if(panel.classList.contains("active"))load(false);
}
window.ensureStateMonthlyEnsembleLoaded=function(){return data?Promise.resolve(data):load(false);};
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",mount);else mount();
})();