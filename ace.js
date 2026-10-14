(()=>{"use strict";
const $=id=>document.getElementById(id);
let archive,annual,daily;
const chartOptions={responsive:true,maintainAspectRatio:false,animation:false,plugins:{legend:{position:"bottom"}}};
function draw(){
 const basin=archive.basins[$("aceBasin").value],years=Object.keys(basin.years).sort((a,b)=>+a-+b);
 const select=$("aceYear"),old=select.value;
 select.replaceChildren();
 for(const y of [...years].reverse()){const o=document.createElement("option");o.value=y;o.textContent=y;select.appendChild(o);}
 select.value=basin.years[old]?old:years.at(-1);
 const yr=select.value,totals=years.map(y=>basin.years[y].total);
 $("aceKpis").textContent="Zeitraum: "+basin.first_year+"–"+basin.last_year+" · Klimamittel 1991–2020: "+basin.reference_mean.toFixed(1)+" ACE · "+yr+": "+basin.years[yr].total.toFixed(1)+" ACE";
 $("aceStatus").textContent="NHC HURDAT2 · letzte abgeschlossene Saison: "+basin.last_year;
 if(annual)annual.destroy();if(daily)daily.destroy();
 annual=new Chart($("aceAnnual"),{type:"bar",data:{labels:years,datasets:[{label:"Saisonale ACE",data:totals,backgroundColor:totals.map(v=>v>=basin.reference_mean?"#c05243":"#3975b6")},{type:"line",label:"Mittel 1991–2020",data:years.map(()=>basin.reference_mean),borderColor:"#222",pointRadius:0,borderWidth:2}]},options:chartOptions});
 const curve=basin.years[yr].daily_cumulative;
 daily=new Chart($("aceDaily"),{type:"line",data:{labels:Array.from({length:366},(_,i)=>i+1),datasets:[{label:yr,data:curve,borderColor:"#2474b5",pointRadius:0,borderWidth:2},{label:"Mittel 1991–2020",data:basin.reference_daily,borderColor:"#555",pointRadius:0,borderWidth:2}]},options:chartOptions});
}
async function start(){
 try{
  const response=await fetch("ace/index.json",{cache:"no-store"});
  if(!response.ok)throw Error("ACE-Daten HTTP "+response.status);
  archive=await response.json();if(!archive.ready||!archive.basins?.atl||!archive.basins?.epac)throw Error("ACE-Daten unvollständig");
  $("aceBasin").addEventListener("change",draw);
  $("aceYear").addEventListener("change",()=>{const year=$("aceYear").value;drawYear(year)});
  draw();
 }catch(e){$("aceStatus").textContent="ACE-Archiv noch nicht verfügbar: "+e.message;}
}
function drawYear(year){
 // preserve selected year while rebuilding charts
 const select=$("aceYear");
 const fn=draw;
 const basin=archive.basins[$("aceBasin").value];
 if(!basin.years[year])return;
 const years=Object.keys(basin.years).sort((a,b)=>+a-+b);
 const totals=years.map(y=>basin.years[y].total);
 $("aceKpis").textContent="Zeitraum: "+basin.first_year+"–"+basin.last_year+" · Klimamittel 1991–2020: "+basin.reference_mean.toFixed(1)+" ACE · "+year+": "+basin.years[year].total.toFixed(1)+" ACE";
 if(daily)daily.destroy();
 daily=new Chart($("aceDaily"),{type:"line",data:{labels:Array.from({length:366},(_,i)=>i+1),datasets:[{label:year,data:basin.years[year].daily_cumulative,borderColor:"#2474b5",pointRadius:0,borderWidth:2},{label:"Mittel 1991–2020",data:basin.reference_daily,borderColor:"#555",pointRadius:0,borderWidth:2}]},options:chartOptions});
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start);else start();
})();