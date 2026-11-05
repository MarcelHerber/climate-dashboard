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
  let monthManuallySelected=false;
  $("monthSelect")?.addEventListener("change",()=>{monthManuallySelected=true;});
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
  // The standard monthly Chart.js graph excludes null years. Add the
  // observation-only current year in memory, never modify data.json.
  function hatchPattern(ctx){
    const tile=document.createElement("canvas");tile.width=16;tile.height=16;
    const pen=tile.getContext("2d");
    pen.fillStyle="rgba(49,117,171,.27)";pen.fillRect(0,0,16,16);
    pen.strokeStyle="rgba(28,91,139,.95)";pen.lineWidth=3;
    pen.beginPath();pen.moveTo(-4,16);pen.lineTo(16,-4);
    pen.moveTo(8,20);pen.lineTo(20,8);pen.stroke();
    return ctx.createPattern(tile,"repeat")||"rgba(49,117,171,.55)";
  }
  function applyToChart(chart){
    if(chart?.canvas?.id!=="monthlyChart"||!snapshot||!sameMonth()||!matchesMonth())return;
    const key=parameter(),area=areaName(),val=snapshot.areas?.[area]?.[key];
    if(!Number.isFinite(val))return;
    const year=snapshot.month.slice(0,4);
    // An already published official complete monthly value always wins.
    if(chart.data.labels.some(item=>String(item)===year))return;
    const bar=chart.data.datasets.find(item=>item.type==="bar"||!item.type);
    if(!bar||!Array.isArray(bar.data))return;
    const before=bar.data.length;
    chart.data.labels.push(year);
    bar.data.push(val);
    if(Array.isArray(bar.backgroundColor))bar.backgroundColor.push(hatchPattern(chart.ctx));
    else bar.backgroundColor=[...Array(before).fill(bar.backgroundColor),hatchPattern(chart.ctx)];
    if(Array.isArray(bar.borderColor))bar.borderColor.push("#205b8c");
    else bar.borderColor=[...Array(before).fill("rgba(0,0,0,0)"),"#205b8c"];
    if(Array.isArray(bar.borderWidth))bar.borderWidth.push(2);
    else bar.borderWidth=[...Array(before).fill(bar.borderWidth||0),2];
    if(key==="temp"&&Number.isFinite(chart.options.scales?.y?.min)&&val<=chart.options.scales.y.min)
      chart.options.scales.y.min=Math.floor((val-.6)*2)/2;
    for(const dataset of chart.data.datasets){
      if(dataset===bar||!Array.isArray(dataset.data))continue;
      const baseline=dataset.type==="line"&&String(dataset.label||"").startsWith("Mittel ")?dataset.data[0]:null;
      dataset.data.push(Number.isFinite(baseline)?baseline:null);
    }
    const tooltip=chart.options.plugins.tooltip||{};
    const previous=tooltip.callbacks?.label;
    const idx=chart.data.labels.length-1;
    tooltip.callbacks={...(tooltip.callbacks||{}),label(context){
      if(context.dataset===bar&&context.dataIndex===idx){
        return "Vorläufig bis "+snapshot.data_through.split("-").reverse().join(".")+": "
           +val.toLocaleString("de-DE",{maximumFractionDigits:1})+" "+units[key]+" (nur Beobachtungen)";
      }
      return typeof previous==="function"?previous(context):context.dataset.label+": "+context.formattedValue;
    }};
    chart.options.plugins.tooltip=tooltip;
  }
  if(typeof Chart!=="undefined"){
    Chart.register({id:"monthlyObservedProvisional",beforeUpdate:applyToChart});
  }
  async function load(){
    for(const url of DATA_URLS){
      try{
        const response=await fetch(url+(url.includes("?")?"&":"?")+"t="+Math.floor(Date.now()/300000),{cache:"no-store"});
        if(!response.ok)continue;
        const data=await response.json();
        if(data.schema!==1||data.forecast!==false||!/^\d{4}-\d{2}$/.test(data.month)
          ||!/^\d{4}-\d{2}-\d{2}$/.test(data.data_through)||typeof data.areas!=="object")continue;
        snapshot=data;
        // The old dashboard defaults to July. Select the current observed month
        // only if the visitor has not already selected a different period.
        const monthControl=$("monthSelect");
        if(monthControl&&!monthManuallySelected&&monthControl.value==="07"){
          const option=[...monthControl.options].find(o=>o.value===data.month.slice(5));
          if(option){monthControl.value=option.value;monthControl.dispatchEvent(new Event("change",{bubbles:true}));}
        }
        draw();
        if(typeof Chart!=="undefined")Chart.getChart($("monthlyChart"))?.update("none");
        return;
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
