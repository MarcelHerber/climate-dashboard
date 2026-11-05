/* Observation-only current-month Gebietsmittel, independent of final DWD monthly data. */
(() => {
  "use strict";
  const ROOT=document.getElementById("monthlyProvisionalPanel");
  if(!ROOT)return;
  const $=id=>document.getElementById(id);
  const DATA_URLS=[
    "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/hyras-data/monthly_current_provisional.json",
    "./monthly_current_provisional.json"
  ];
  const MONTHS=["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"];
  const names={temp:"Temperaturmittel",rain:"Niederschlagssumme",sun:"Sonnenscheindauer"};
  const units={temp:"°C",rain:"mm",sun:"h"};
  let snapshot=null;
  function title(s){ROOT.querySelector(".monthly-provisional-title").textContent=s;}
  function status(s){ROOT.querySelector(".monthly-provisional-status").textContent=s;}
  function parameter(){
    const value=$("paramSelect")?.value||"temp";
    return ({temperature:"temp",precipitation:"rain",sunshine:"sun",tmean:"temp",rr:"rain",sd:"sun"})[value]||value;
  }
  function sameMonth(){
    if(!snapshot)return false;
    const now=new Date(),year=now.getFullYear(),month=String(now.getMonth()+1).padStart(2,"0");
    return snapshot.month===year+"-"+month;
  }
  function matchesMonth(){
    const choice=String($("monthSelect")?.value||"all").toLowerCase();
    const month=Number(snapshot?.month?.slice(5));
    if(["all","0","alle","year","jahr",""].includes(choice))return true;
    const number=Number(choice);
    return number===month || choice===MONTHS[month-1]?.toLowerCase();
  }
  function areaName(){
    const choice=$("monthlyAreaSelect");
    const val=choice?.value||"Deutschland";
    return val==="DE"||val==="de"?"Deutschland":val;
  }
  function draw(){
    if(!snapshot){title("Aktueller Monat · Beobachtungen");return;}
    const month=Number(snapshot.month.slice(5)),param=parameter(),area=areaName();
    ROOT.hidden=!sameMonth()||!matchesMonth();
    if(ROOT.hidden)return;
    title(MONTHS[month-1]+" "+snapshot.month.slice(0,4)+" · vorläufig (nur Messdaten)");
    const record=snapshot.areas?.[area];
    const value=record?.[param],cutoff=record?.data_through?.[param]||snapshot.data_through;
    const shown=ROOT.querySelector(".monthly-provisional-value");
    const numeric=typeof value==="number"&&Number.isFinite(value);
    const formatted=numeric?value.toLocaleString("de-DE",{maximumFractionDigits:1})+" "+units[param]:"nicht verfügbar";
    shown.textContent=(names[param]||param)+": "+formatted;
    const day=Number(cutoff?.slice(8,10))||snapshot.days_observed;
    const total=Number(snapshot.days_in_month)||30;
    const progress=Math.max(0,Math.min(100,100*day/total));
    ROOT.querySelector(".monthly-provisional-coverage").style.width=progress+"%";
    ROOT.querySelector(".monthly-provisional-progress").setAttribute("aria-valuenow",String(day));
    ROOT.querySelector(".monthly-provisional-progress").setAttribute("aria-valuemax",String(total));
    ROOT.querySelector(".monthly-provisional-date").textContent="Datenstand: "+cutoff?.split("-").reverse().join(".")+
        " · "+day+" von "+total+" Kalendertagen";
    const source=snapshot.source?.[param];
    status(numeric
      ? (source||"DWD-Beobachtungen")+" · noch kein vollständiger Monatswert; keine Prognose. Historische Monatsbalken bleiben unverändert."
      : (param==="sun"?"Sonnenscheindauer: Stationsauswertung liegt noch nicht mit ausreichender Datenabdeckung vor.":"Für dieses Gebiet liegen noch keine vollständigen täglichen HYRAS-Werte vor."));
    shown.classList.toggle("missing",!numeric);
  }
  async function load(){
    for(const url of DATA_URLS){
      try{
        const response=await fetch(url+(url.includes("?")?"&":"?")+"t="+Math.floor(Date.now()/300000),{cache:"no-store"});
        if(!response.ok)continue;
        const data=await response.json();
        if(data.schema!==1||data.forecast!==false||!/^\\d{4}-\\d{2}$/.test(data.month)
          ||!/^\\d{4}-\\d{2}-\\d{2}$/.test(data.data_through)||typeof data.areas!=="object")continue;
        snapshot=data;draw();return;
      }catch(error){console.warn("Vorläufige HYRAS-Gebietsmittel:",error);}
    }
    title("Aktueller Monat · Beobachtungen");
    status("Noch kein geprüftes Tagesgebietsmittel-Paket veröffentlicht. Die historischen DWD-Monatswerte bleiben unverändert.");
    ROOT.querySelector(".monthly-provisional-value").textContent="Keine vorläufigen Monatsdaten";
  }
  ["paramSelect","monthlyAreaSelect","monthSelect"].forEach(id=>$(id)?.addEventListener("change",draw));
  // The existing dashboard dynamically switches chart controls and regions.
  new MutationObserver(draw).observe(ROOT.parentElement||ROOT,{attributes:true,subtree:false});
  load();
})();
