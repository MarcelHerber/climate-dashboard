/* ECMWF IFS ENS 50 perturbations + IFS control; strict 10hPa/60N 00-UTC provenance.
   The model comparison uses member fractions, not model-run lag spreads or SSW claims. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const epsTab=$("stratoEpsTab"),epsView=$("stratoEpsView"),compareCanvas=$("stratoCompareCanvas");
if(!epsTab||!epsView||!compareCanvas)return;
const EPS_BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/stratosphere-ecmwf-ens-data/data/stratosphere/ecmwf/";
const URL_EPS=EPS_BASE+"ens_current.json", EPS_INDEX=EPS_BASE+"ens_index.json";
const GEFS_BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/stratosphere-ensemble-data/data/stratosphere/ensemble/";
const GEFS_INDEX=GEFS_BASE+"gefs_index.json";
let eps=null,epsChart=null,compareChart=null,epsRows=[],compareRows=[],errorMessage="",epsCycles=[],compareGefs=null,compareEps=null;
const valid=v=>typeof v==="number"&&Number.isFinite(v)&&v>-160&&v<170;
const mean=values=>values.reduce((a,b)=>a+b,0)/values.length;
function pct(x){return Math.round(x)+" %";}
function percentile(values,p){
 const arr=[...values].sort((a,b)=>a-b),pos=(arr.length-1)*p,lo=Math.floor(pos);
 return arr[lo]+(arr[Math.min(arr.length-1,lo+1)]-arr[lo])*(pos-lo);
}
function validData(data){
 if(!data||data.schema_version!==1||data.provider!=="ECMWF IFS ENS"||
    data.latitude_deg!==60||data.level_hpa!==10||data.units!=="m/s"||
    data.stream_ensemble!=="enfo/ef"||data.stream_control!=="oper/fc"||
    data.member_count!==51||data.perturbed_count!==50||![0,12].includes(data.valid_hour_utc))
   throw Error("Unbekanntes EPS-Datenformat");
 if(!/^\d{4}-\d\d-\d\dT(?:00|12):00:00Z$/.test(data.cycle_utc||"")||
    Date.now()-Date.parse(data.cycle_utc)>72*3600000||
    Date.now()<Date.parse(data.cycle_utc))throw Error("ECMWF ENS: kein Lauf aus den letzten 72 Stunden");
 const expected=["c00",...Array.from({length:50},(_,i)=>"p"+String(i+1).padStart(2,"0"))];
 if(!Array.isArray(data.valid_dates)||data.valid_dates.length!==16||
    !Array.isArray(data.forecast_step_hours)||data.forecast_step_hours.length!==16||
    data.forecast_step_hours.some((h,i)=>h!==i*24)||
    Object.keys(data.members||{}).length!==51||
    expected.some(k=>!Object.hasOwn(data.members,k)))throw Error("EPS: nicht alle 50+1 Mitglieder oder 16 Prognosetage vorhanden");
 if(Number(data.cycle_utc.slice(11,13))!==data.valid_hour_utc||data.valid_dates.some((date,i)=>date!==new Date(Date.parse(data.cycle_utc)+i*86400000).toISOString().slice(0,10)))
   throw Error("EPS: ungültige 00-UTC-Zeitachse");
 for(const id of expected){
  const values=data.members[id];
  if(!Array.isArray(values)||values.length!==16||!values.every(valid))
   throw Error("Unvollständige Originalwerte: "+id);
 }
 return data;
}
function compute(data){
 if(!data)return null;
 const vals=Object.values(data.members);
 const total=vals.length;
 const rows=data.valid_dates.map((date,i)=>{
  const points=vals.map(r=>r[i]);
  const count=points.filter(v=>v<0).length;
  return {date,count,total,p:100*count/total,mean:mean(points),
    p05:percentile(points,.05),p25:percentile(points,.25),
    p75:percentile(points,.75),p95:percentile(points,.95),control:data.members.c00[i],idx:i};
 });
 const crossed=vals.filter(arr=>arr.some((v,i)=>i>0&&arr[i-1]>=0&&v<0)).length;
 return {rows,crossed,total,cycle:data.cycle_utc};
}
const line=(name,data,color,width=2,other={})=>({
 label:name,data,borderColor:color,backgroundColor:color,borderWidth:width,
 pointRadius:0,pointHoverRadius:4,tension:0,spanGaps:false,fill:false,...other
});
function bands(rows,low,high,label,color){
 return [
  line("_"+label+" min",rows.map(r=>r[low]),"transparent",0),
  line("_"+label+" max",rows.map(r=>r[high]),"transparent",0,
       {fill:{target:"-1",above:color,below:color}})
 ];
}
function drawEPS(){
 if(!eps||typeof Chart!=="function")return;
 const all=compute(eps).rows;
 const horizon=$("stratoEpsHorizon").value;
 epsRows=horizon==="7"?all.slice(0,8):all;
 const labels=epsRows.map(r=>r.date);
 const datasets=[];
 if($("stratoEpsBands").checked){
  datasets.push(...bands(epsRows,"p05","p95","_90%","rgba(71,126,183,.18)"));
  datasets.push(...bands(epsRows,"p25","p75","_50%","rgba(71,126,183,.30)"));
 }
 if($("stratoEpsMembers").checked){
  for(let number=1;number<=50;number++){
   const id="p"+String(number).padStart(2,"0");
   datasets.push(line("_EPS "+id,epsRows.map(r=>eps.members[id][r.idx]),
     "rgba(51,77,113,.40)",1));
  }
 }
 datasets.push(line("EPS-Mittel",epsRows.map(r=>r.mean),"#d62828",3.2));
 datasets.push(line("Kontrolllauf (IFS)",epsRows.map(r=>r.control),"#e59318",2.4,
                  {borderDash:[7,5]}));
 datasets.push(line("0 m/s · Ostwindschwelle",labels.map(()=>0),"#273746",1.3,
                  {borderDash:[4,4]}));
 if(epsChart)epsChart.destroy();
 epsChart=new Chart($("stratoEpsCanvas"),{
  type:"line",data:{labels,datasets},
  options:{responsive:true,maintainAspectRatio:false,animation:false,normalized:true,
   interaction:{mode:"index",intersect:false},
   plugins:{legend:{display:false},tooltip:{filter:item=>
      !item.dataset.label.startsWith("_")&&Number.isFinite(item.parsed.y),
     callbacks:{label:item=>item.dataset.label+": "+item.parsed.y.toFixed(1)+" m/s"}}},
   scales:{x:{ticks:{maxTicksLimit:12,maxRotation:0},grid:{display:false},
        title:{display:true,text:"Datum · "+String(eps.valid_hour_utc).padStart(2,"0")+" UTC"}},
     y:{title:{display:true,text:"Zonal gemittelter U-Wind (m/s)"}}}
  }
 });
 const s=compute(eps),peak=s.rows.reduce((a,b)=>b.p>a.p?b:a);
 $("stratoEpsSummary").textContent="ECMWF IFS ENS · "+eps.cycle_utc+
  " · 50 perturbierte Mitglieder + 1 IFS-Kontrolllauf · +0 bis +360 h / "+String(eps.valid_hour_utc).padStart(2,"0")+" UTC · max. Tagesanteil mit U < 0 m/s: "+
  pct(peak.p)+" am "+peak.date+" ("+peak.count+"/51).";
 $("stratoEpsPng").disabled=false;
 $("stratoEpsCsv").disabled=false;
}
function goodGefs(candidate){
 const data=candidate||window.stratoGefsEnsemble;
 if(data?.provider!=="NOAA GEFS"||data.member_count!==31||
    !Array.isArray(data.valid_dates)||!data.valid_dates.length||
    !data.members||Object.keys(data.members).length!==31||
    !/^\d{4}-\d\d-\d\dT(?:00|06|12|18):00:00Z$/.test(data.cycle_utc||"")||
    Date.now()-Date.parse(data.cycle_utc)>72*3600000||
    !Object.values(data.members).every(arr=>Array.isArray(arr)&&arr.length===data.valid_dates.length&&arr.every(valid)))
   return null;
 return data;
}
async function indexRuns(url,provider,hours){
 try{
  const response=await fetch(url+"?t="+Date.now(),{cache:"no-store"});
  if(!response.ok)return [];
  const index=await response.json();
  if(index.provider!==provider||!Array.isArray(index.runs))return [];
  return index.runs.filter(x=>{
   const cycle=x.cycle_utc||"",path=x.path||"";
   return /^\d{4}-\d\d-\d\dT(?:00|06|12|18):00:00Z$/.test(cycle)&&
    /^runs\/\d{8}_\d{6}\.json$/.test(path)&&
    hours.includes(Number(cycle.slice(11,13)))&&Date.parse(cycle)<=Date.now()&&
    Date.now()-Date.parse(cycle)<72*3600000;
  }).sort((a,b)=>b.cycle_utc.localeCompare(a.cycle_utc));
 }catch(error){console.info("Ensemble-Laufindex nicht verfügbar",error);return [];}
}
async function updateEpsCycles(){
 const select=$("stratoEpsCycle"),old=select.value;
 epsCycles=await indexRuns(EPS_INDEX,"ECMWF IFS ENS",[0,12]);
 select.replaceChildren();
 if(!epsCycles.length){
  const o=document.createElement("option");o.value="current";
  o.textContent="Neuester verfügbarer ECMWF-Lauf";select.add(o);
 }else{
  for(const x of epsCycles){
   const o=document.createElement("option");o.value=x.cycle_utc;
   o.textContent=x.cycle_utc.slice(0,16).replace("T"," ")+" UTC · +360 h";
   select.add(o);
  }
  select.value=epsCycles.some(x=>x.cycle_utc===old)?old:epsCycles[0].cycle_utc;
 }
}
async function getEps(){
 const selection=$("stratoEpsCycle").value,run=epsCycles.find(x=>x.cycle_utc===selection);
 const response=await fetch((run?EPS_BASE+run.path:URL_EPS)+"?t="+Date.now(),{cache:"no-store"});
 if(!response.ok)throw Error("Noch kein veröffentlichtes ECMWF-ENS-Archiv (HTTP "+response.status+")");
 const found=validData(await response.json());
 if(run&&found.cycle_utc!==run.cycle_utc)throw Error("ECMWF-ENS-Daten und Laufindex widersprechen sich");
 return found;
}
async function compareData(model,hour){
 const isG=model==="gefs",indexUrl=isG?GEFS_INDEX:EPS_INDEX;
 const base=isG?GEFS_BASE:EPS_BASE,provider=isG?"NOAA GEFS":"ECMWF IFS ENS";
 const runs=await indexRuns(indexUrl,provider,[hour]);
 const latestUrl=isG?GEFS_BASE+"gefs_current.json":URL_EPS;
 const url=runs.length?base+runs[0].path:latestUrl;
 try{
  const response=await fetch(url+"?t="+Date.now(),{cache:"no-store"});
  if(!response.ok)return null;
  const raw=await response.json();
  const data=isG?goodGefs(raw):validData(raw);
  if(!data||Number(data.cycle_utc.slice(11,13))!==hour||
    runs.length&&data.cycle_utc!==runs[0].cycle_utc)return null;
  return data;
 }catch(error){console.info(provider+" Vergleich nicht verfügbar",error);return null;}
}
async function refreshComparison(){
 const hour=Number($("stratoCompareHour").value);
 $("stratoCompareStatus").textContent="Lade GEFS und ECMWF ENS mit übereinstimmenden "+String(hour).padStart(2,"0")+"-UTC-Zeitpunkten …";
 const result=await Promise.allSettled([compareData("gefs",hour),compareData("eps",hour)]);
 // Prevent stale network results from replacing a newly chosen comparison hour.
 if(Number($("stratoCompareHour").value)!==hour)return;
 compareGefs=result[0].status==="fulfilled"?result[0].value:null;
 compareEps=result[1].status==="fulfilled"?result[1].value:null;
 renderComparison();
}
function renderComparison(){
 const gefs=compute(compareGefs),ecmwf=compute(compareEps);
 const sG=$("stratoCompareGefs"),sE=$("stratoCompareEps");
 sG.textContent=gefs?pct(gefs.crossed/gefs.total*100)+" ("+gefs.crossed+"/"+gefs.total+")":"–";
 sE.textContent=ecmwf?pct(ecmwf.crossed/ecmwf.total*100)+" ("+ecmwf.crossed+"/"+ecmwf.total+")":"–";
 $("stratoCompareRuns").textContent=
   "GEFS: "+(gefs?gefs.cycle:"nicht verfügbar")+
   " · ECMWF ENS: "+(ecmwf?ecmwf.cycle:"nicht verfügbar");
 const gmap=new Map((gefs?.rows||[]).map(r=>[r.date,r]));
 const emap=new Map((ecmwf?.rows||[]).map(r=>[r.date,r]));
 const days=[...new Set([...gmap.keys(),...emap.keys()])].sort();
 compareRows=days.map(date=>({date,g:gmap.get(date)?.p??null,
  gc:gmap.get(date)?.count??null,e:emap.get(date)?.p??null,
  ec:emap.get(date)?.count??null}));
 const overlap=compareRows.filter(r=>r.g!==null&&r.e!==null).length;
 const utc=String($("stratoCompareHour").value).padStart(2,"0");
 $("stratoCompareStatus").textContent=gefs||ecmwf?
   "Täglicher Anteil mit U < 0 m/s ("+utc+" UTC). GEFS: 31 inklusive Kontrolle; ECMWF ENS: 50 Störmitglieder inklusive separatem Kontrolllauf = 51. "+
   overlap+" gemeinsame Gültigkeitstage. Das ist keine Major-SSW-Wahrscheinlichkeit."+
   (errorMessage?" EPS: "+errorMessage:""):
   "Noch keine verifizierten Ensembleläufe. "+(errorMessage||"");
 $("stratoCompareCsv").disabled=!compareRows.length;
 if(compareChart){compareChart.destroy();compareChart=null;}
 if(!compareRows.length||typeof Chart!=="function")return;
 compareChart=new Chart(compareCanvas,{
  type:"line",data:{labels:days,datasets:[
   line("GEFS · 31 Mitglieder",compareRows.map(r=>r.g),"#1976bc",2.8,
        {pointRadius:2,spanGaps:false}),
   line("ECMWF ENS · 51 Mitglieder",compareRows.map(r=>r.e),"#c54a25",2.8,
        {pointRadius:2,spanGaps:false})
  ]},
  options:{responsive:true,maintainAspectRatio:false,animation:false,
   interaction:{mode:"index",intersect:false},
   plugins:{legend:{position:"bottom"},tooltip:{callbacks:{
    label:ctx=>{
     const row=compareRows[ctx.dataIndex],isG=ctx.datasetIndex===0;
     return ctx.dataset.label+": "+ctx.parsed.y.toFixed(1)+" % ("+
       (isG?row.gc+"/31":row.ec+"/51")+")";
    }}}},
   scales:{x:{ticks:{maxTicksLimit:12,maxRotation:0},grid:{display:false},
       title:{display:true,text:"Gültigkeitsdatum · "+utc+" UTC"}},
    y:{min:0,max:100,ticks:{callback:v=>v+" %"},
       title:{display:true,text:"Mitglieder mit U < 0 m/s (%)"}}}
  }
 });
}
async function load(refreshIndex=true){
 $("stratoEpsStatus").textContent="Lade originale 50 ECMWF-Störmitglieder und den IFS-Kontrolllauf …";
 $("stratoEpsReload").disabled=true;
 if(refreshIndex)await updateEpsCycles();
 try{
  eps=await getEps();errorMessage="";
  $("stratoEpsStatus").textContent="51/51 vollständige Original-Prognosen · ECMWF "+eps.cycle_utc+
    " · 60°N / 10 hPa · "+String(eps.valid_hour_utc).padStart(2,"0")+" UTC · CC BY 4.0";
  drawEPS();
 }catch(error){
  eps=null;errorMessage=error.message||String(error);
  $("stratoEpsStatus").textContent="ECMWF ENS noch nicht verfügbar: "+errorMessage+
     ". Es werden keine IFS-Laufkurven als Ensemble ausgegeben.";
  $("stratoEpsSummary").textContent="Die EPS-Grafik erscheint erst nach erfolgreichem 51/51-Datenimport.";
  $("stratoEpsPng").disabled=true;$("stratoEpsCsv").disabled=true;
  if(epsChart){epsChart.destroy();epsChart=null;}
 }
 $("stratoEpsReload").disabled=false;
 void refreshComparison();
}
function file(name,content,type){
 const blob=new Blob([content],{type}),url=URL.createObjectURL(blob),a=document.createElement("a");
 a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(url),3500);
}
function activate(which){
 const active=which==="eps";
 epsView.hidden=!active;
 epsTab.setAttribute("aria-pressed",String(active));
 if(active){
  $("stratoGefsView").hidden=true;
  $("stratoEcmwfView").hidden=true;
  $("stratoGefsTab").setAttribute("aria-pressed","false");
  $("stratoEcmwfTab").setAttribute("aria-pressed","false");
  if(eps)drawEPS();
 }
}
epsTab.addEventListener("click",()=>activate("eps"));
for(const id of ["stratoGefsTab","stratoEcmwfTab"]){
 $(id).addEventListener("click",()=>activate("other"));
}
$("stratoEpsReload").addEventListener("click",()=>load(true));
$("stratoEpsCycle").addEventListener("change",()=>load(false));
$("stratoCompareHour").addEventListener("change",refreshComparison);
for(const id of ["stratoEpsHorizon","stratoEpsMembers","stratoEpsBands"]){
 $(id).addEventListener("change",drawEPS);
}
$("stratoEpsPng").addEventListener("click",()=>{
 if(!epsChart)return;
 const a=document.createElement("a");a.href=epsChart.toBase64Image("image/png",1);
 a.download="ECMWF_ENS_60N_10hPa_50plusKontrolle.png";a.click();
});
$("stratoEpsCsv").addEventListener("click",()=>{
 if(!epsRows.length)return;
 const keys=Object.keys(eps.members);
 const head=["Datum_UTC","EPS_Mittel","P05","P25","P75","P95",...keys].join(";");
 const rows=epsRows.map(r=>[r.date,r.mean,r.p05,r.p25,r.p75,r.p95,
  ...keys.map(key=>eps.members[key][r.idx])].join(";"));
 file("ECMWF_ENS_60N_10hPa.csv","\ufeff"+[head,...rows].join("\r\n"),"text/csv;charset=utf-8");
});
$("stratoCompareCsv").addEventListener("click",()=>{
 if(!compareRows.length)return;
 const rows=["Datum_UTC;GEFS_U_negativ_n;GEFS_Mitglieder;GEFS_Prozent;EPS_U_negativ_n;EPS_Mitglieder;EPS_Prozent",
 ...compareRows.map(r=>[r.date,r.gc??"",r.g===null?"":31,r.g??"",
  r.ec??"",r.e===null?"":51,r.e??""].join(";"))];
 file("Stratosphaere_GEFS_ECMWF_ENS_Windumkehr_00UTC.csv","\ufeff"+rows.join("\r\n"),"text/csv;charset=utf-8");
});
window.addEventListener("stratosphere:gefs-loaded",()=>{});
void load();
})();