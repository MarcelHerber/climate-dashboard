(()=>{"use strict";
const $=id=>document.getElementById(id);
const names={GLOBAL:"Weltweit",NA:"Nordatlantik",EP:"Nordost-/Zentralpazifik",WP:"Nordwestpazifik",NI:"Nordindischer Ozean",SI:"Südindischer Ozean",SP:"Südpazifik",atl:"Nordatlantik (NHC)",epac:"Nordostpazifik (NHC)"};
let datasets={},annual=null,daily=null;
const opt={responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:"index",intersect:false},plugins:{legend:{position:"bottom"}}};
async function load(url){const r=await fetch(url,{cache:"no-store"});if(!r.ok)throw Error(url+" HTTP "+r.status);const d=await r.json();if(!d.ready||!d.basins)throw Error(url+" unvollständig");return d;}
function render(keepYear=true){
 const b=datasets[$("aceBasin").value];
 if(!b)return;
 const years=Object.keys(b.years).sort((a,z)=>Number(a)-Number(z));
 const select=$("aceYear"),old=keepYear?select.value:null;
 select.replaceChildren();
 for(const y of [...years].reverse()){const o=document.createElement("option");o.value=y;o.textContent=y;select.append(o);}
 select.value=old&&b.years[old]?old:years[years.length-1];
 const y=select.value, mean=b.reference_mean;
 const totals=years.map(key=>b.years[key].total);
 $("aceKpis").textContent="Zeitraum "+b.first_year+"–"+b.last_year+" · Mittel 1991–2020: "+mean.toFixed(1)+" ACE · "+y+": "+b.years[y].total.toFixed(1)+" ACE";
 $("aceStatus").textContent=b.origin==="ibtracs"?"NOAA IBTrACS · Kalenderjahre · globale Vergleichsmethodik":"NHC HURDAT2 · tropische Hurrikansaisons";
 if(annual)annual.destroy();
 annual=new Chart($("aceAnnual"),{type:"bar",data:{labels:years,datasets:[
  {label:"ACE / Jahr",data:totals,backgroundColor:totals.map(v=>v>=mean?"#c05243":"#3975b6")},
  {type:"line",label:"Mittel 1991–2020",data:years.map(()=>mean),borderColor:"#293647",pointRadius:0,borderWidth:2}
 ]},options:opt});
 renderDaily();
}
function renderDaily(){
 const b=datasets[$("aceBasin").value],y=$("aceYear").value;
 if(!b?.years[y])return;
 $("aceKpis").textContent="Zeitraum "+b.first_year+"–"+b.last_year+" · Mittel 1991–2020: "+b.reference_mean.toFixed(1)+" ACE · "+y+": "+b.years[y].total.toFixed(1)+" ACE";
 if(daily)daily.destroy();
 const axis=Array.from({length:366},(_,i)=>i+1);
 daily=new Chart($("aceDaily"),{type:"line",data:{labels:axis,datasets:[
  {label:y,data:b.years[y].daily_cumulative,borderColor:"#2772b6",pointRadius:0,borderWidth:2},
  {label:"Mittel 1991–2020",data:b.reference_daily,borderColor:"#4f5967",pointRadius:0,borderWidth:2}
 ]},options:{...opt,scales:{x:{title:{display:true,text:"Kalendertag (Schaltjahr-Achse)"}}}}});
}
async function start(){
 const result=await Promise.allSettled([load("ace/global.json"),load("ace/index.json")]);
 const global=result[0].status==="fulfilled"?result[0].value:null;
 const nhc=result[1].status==="fulfilled"?result[1].value:null;
 if(global)for(const [k,v] of Object.entries(global.basins))datasets[k]={...v,origin:"ibtracs"};
 if(nhc)for(const [k,v] of Object.entries(nhc.basins))datasets[k]={...v,origin:"nhc"};
 const select=$("aceBasin");select.replaceChildren();
 for(const key of ["GLOBAL","NA","EP","WP","NI","SI","SP","atl","epac"]){
  if(!datasets[key])continue;
  const option=document.createElement("option");option.value=key;option.textContent=names[key]||key;select.append(option);
 }
 if(!select.options.length){$("aceStatus").textContent="ACE-Archive sind noch nicht importiert. GitHub-Actions-Datenlauf prüfen.";return;}
 select.value=datasets.GLOBAL?"GLOBAL":select.options[0].value;
 select.addEventListener("change",()=>render(false));
 $("aceYear").addEventListener("change",renderDaily);
 render(false);
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",()=>start().catch(e=>{$("aceStatus").textContent=e.message;}));
else start().catch(e=>{$("aceStatus").textContent=e.message;});
})();