/* ECMWF IFS ENS 50 perturbations + IFS control; strict 10hPa/60N 00-UTC provenance.
   The model comparison uses member fractions, not model-run lag spreads or SSW claims. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const epsTab=$("stratoEpsTab"),epsView=$("stratoEpsView"),compareCanvas=$("stratoCompareCanvas");
if(!epsTab||!epsView||!compareCanvas)return;
const URL_EPS="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/stratosphere-ecmwf-ens-data/data/stratosphere/ecmwf/ens_current.json";
let eps=null,epsChart=null,compareChart=null,epsRows=[],compareRows=[],errorMessage="";
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
    data.member_count!==51||data.perturbed_count!==50||data.valid_hour_utc!==0)
   throw Error("Unbekanntes EPS-Datenformat");
 if(!/^\d{4}-\d\d-\d\dT00:00:00Z$/.test(data.cycle_utc||"")||
    Date.now()-Date.parse(data.cycle_utc)>72*3600000||
    Date.now()<Date.parse(data.cycle_utc))throw Error("ECMWF ENS: kein Lauf aus den letzten 72 Stunden");
 const expected=["c00",...Array.from({length:50},(_,i)=>"p"+String(i+1).padStart(2,"0"))];
 if(!Array.isArray(data.valid_dates)||data.valid_dates.length!==16||
    !Array.isArray(data.forecast_step_hours)||data.forecast_step_hours.length!==16||
    data.forecast_step_hours.some((h,i)=>h!==i*24)||
    Object.keys(data.members||{}).length!==51||
    expected.some(k=>!Object.hasOwn(data.members,k)))throw Error("EPS: nicht alle 50+1 Mitglieder oder 16 Prognosetage vorhanden");
 if(data.valid_dates.some((date,i)=>date!==new Date(Date.parse(data.cycle_utc)+i*86400000).toISOString().slice(0,10)))
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
        title:{display:true,text:"Datum · 00 UTC"}},
     y:{title:{display:true,text:"Zonal gemittelter U-Wind (m/s)"}}}
  }
 });
 const s=compute(eps),peak=s.rows.reduce((a,b)=>b.p>a.p?b:a);
 $("stratoEpsSummary").textContent="ECMWF IFS ENS · "+eps.cycle_utc+
  " · 50 perturbierte Mitglieder + 1 IFS-Kontrolllauf · +0 bis +360 h / 00 UTC · max. Tagesanteil mit U < 0 m/s: "+
  pct(peak.p)+" am "+peak.date+" ("+peak.count+"/51).";
 $("stratoEpsPng").disabled=false;
 $("stratoEpsCsv").disabled=false;
}
function goodGefs(){
 const data=window.stratoGefsEnsemble;
 if(data?.provider!=="NOAA GEFS"||data.member_count!==31||
    !Array.isArray(data.valid_dates)||!data.valid_dates.length||
    !data.members||Object.keys(data.members).length!==31||
    !/^\d{4}-\d\d-\d\dT00:00:00Z$/.test(data.cycle_utc||"")||
    Date.now()-Date.parse(data.cycle_utc)>72*3600000||
    !Object.values(data.members).every(arr=>Array.isArray(arr)&&arr.length===data.valid_dates.length&&arr.every(valid)))
   return null;
 return data;
}
function renderComparison(){
 const gefs=compute(goodGefs()),ecmwf=compute(eps);
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
 $("stratoCompareStatus").textContent=gefs||ecmwf?
   "Täglicher Anteil mit U < 0 m/s (00 UTC). GEFS: 31 inklusive Kontrolle; ECMWF ENS: 50 Störmitglieder inklusive separatem Kontrolllauf = 51. "+
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
       title:{display:true,text:"Gültigkeitsdatum · 00 UTC"}},
    y:{min:0,max:100,ticks:{callback:v=>v+" %"},
       title:{display:true,text:"Mitglieder mit U < 0 m/s (%)"}}}
  }
 });
}
async function load(){
 $("stratoEpsStatus").textContent="Lade originale 50 ECMWF-Störmitglieder und den IFS-Kontrolllauf …";
 $("stratoEpsReload").disabled=true;
 try{
  const response=await fetch(URL_EPS+"?t="+Date.now(),{cache:"no-store"});
  if(!response.ok)throw Error("Noch kein veröffentlichtes ECMWF-ENS-Archiv (HTTP "+response.status+")");
  eps=validData(await response.json());errorMessage="";
  $("stratoEpsStatus").textContent="51/51 vollständige Original-Prognosen · ECMWF "+eps.cycle_utc+
    " · 60°N / 10 hPa · 00 UTC · CC BY 4.0";
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
 renderComparison();
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
$("stratoEpsReload").addEventListener("click",load);
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
window.addEventListener("stratosphere:gefs-loaded",renderComparison);
void load();
})();