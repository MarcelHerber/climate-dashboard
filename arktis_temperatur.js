/* Climate Dashboard Deutschland: DMI +80°N daily temperature visualizations. */
(() => {
"use strict";
const $=id=>document.getElementById(id);
const MONTHS=["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"];
const valid=v=>typeof v==="number"&&Number.isFinite(v);
const round=v=>Math.round(v*1000)/1000;
const fmt=v=>Number(v).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1});
const years=doc=>Object.keys(doc.years||{}).map(Number).sort((a,b)=>b-a);
const diff=(series,climate)=>series.map((v,i)=>valid(v)&&valid(climate[i])?round(v-climate[i]):null);
function smooth(values,windowDays){
  return values.map((_,i)=>{
    if(i<windowDays-1)return null;
    const period=values.slice(i-windowDays+1,i+1);
    return period.every(valid)?round(period.reduce((sum,v)=>sum+v,0)/windowDays):null;
  });
}
function lastIndex(values){
  for(let i=values.length-1;i>=0;i--)if(valid(values[i]))return i;
  return -1;
}
function csv(doc,year,compare){
  const series=doc.years[year],other=compare?doc.years[compare]:null,climate=doc.reference.temperatures;
  const anomaly=diff(series,climate),seven=smooth(anomaly,7),thirty=smooth(anomaly,30);
  const columns=["Kalendertag MM-TT", "Temperatur "+year+" (°C)","Referenz 1958–2002 (°C)","Abweichung (K)","7-Tage-Mittel (K)","30-Tage-Mittel (K)"];
  if(other)columns.push("Temperatur "+compare+" (°C)");
  const number=v=>valid(v)?String(v).replace(".",","):"";
  const lines=[columns.map(v=>'"'+v.replace(/"/g,'""')+'"').join(";")];
  doc.days.forEach((day,i)=>{
    const record=[day,number(series[i]),number(climate[i]),number(anomaly[i]),number(seven[i]),number(thirty[i])];
    if(other)record.push(number(other[i]));
    lines.push(record.join(";"));
  });
  return "\ufeff"+lines.join("\r\n")+"\r\n";
}
window.Arctic80Math={diff,smooth,lastIndex,csv};
let data=null,annualChart=null,anomalyChart=null;
function setStatus(text,error=false){
  if(!$("arcticStatus"))return;
  $("arcticStatus").textContent=text;
  $("arcticStatus").classList.toggle("error",error);
}
function dateText(s){return s?s.split("-").reverse().join("."):"–";}
function selected(){return $("arcticYear").value;}
function compared(){const v=$("arcticCompare").value;return v!==selected()?v:"";}
function tick(value){
  const day=data&&data.days[Number(value)];
  return day&&day.endsWith("-01")?MONTHS[Number(day.slice(0,2))-1]:"";
}
function basicOptions(unit){
  return{
    responsive:true,maintainAspectRatio:false,animation:false,
    interaction:{mode:"index",intersect:false},
    plugins:{
      legend:{display:false},
      tooltip:{
        filter:item=>item.dataset.indexKind!=="history",
        title:items=>{
          const day=items.length&&data.days[items[0].dataIndex];
          return day?day.slice(3)+"."+day.slice(0,2)+".":"";
        },
        callbacks:{label:item=>item.parsed.y===null?"":item.dataset.label+": "+fmt(item.parsed.y)+" "+unit}
      }
    },
    scales:{
      x:{ticks:{autoSkip:false,maxRotation:0,minRotation:0,color:"#587083",font:{size:10},callback:tick},
         grid:{color:"rgba(70,99,125,.10)"},border:{color:"#9cabb6"}},
      y:{ticks:{color:"#587083",font:{size:11}},
         grid:{color:"rgba(70,99,125,.13)"},border:{color:"#9cabb6"}}
    }
  };
}
function line(name,values,color,weight,order,kind,dashes){
  return{type:"line",label:name,data:values,indexKind:kind,pointRadius:0,
    pointHoverRadius:3,borderColor:color,backgroundColor:color,borderWidth:weight,
    borderDash:dashes||[],spanGaps:false,tension:0,order,fill:false};
}
function yearDatasets(){
  const focus=selected(),contrast=compared(),mode=$("arcticHistoryMode").value;
  const background=years(data).filter(y=>{
    if(String(y)===focus||String(y)===contrast||mode==="none")return false;
    if(mode==="reference")return y>=1958&&y<=2002;
    if(mode==="recent")return y>=Number(data.latest_year)-19;
    return true;
  }).map(y=>line(String(y),data.years[y],"rgba(65,105,135,.17)",1,9,"history"));
  if($("arcticReference").checked)
    background.push(line("DMI-Mittel 1958–2002",data.reference.temperatures,"#1e3549",3,4,"reference",[7,3]));
  if(contrast)background.push(line(contrast,data.years[contrast],"#167eaf",2.4,2,"compare"));
  background.push(line(focus,data.years[focus],"#d55146",3.5,1,"focus"));
  return background;
}
function metric(id,value,unit){
  const el=$(id);
  el.textContent=valid(value)?((value>0&&unit==="K"?"+":"")+fmt(value)+" "+unit):"–";
  el.classList.remove("warm","cold");
  if(valid(value)&&unit==="K")el.classList.add(value>=0?"warm":"cold");
}
function draw(){
  if(!data||typeof Chart==="undefined")return;
  const year=selected(),series=data.years[year];
  if(!series)return;
  if(annualChart)annualChart.destroy();
  const yopts=basicOptions("°C");
  yopts.scales.y.min=-50;yopts.scales.y.max=10;
  yopts.scales.y.title={display:true,text:"2-m-Temperatur (°C)",color:"#587083"};
  annualChart=new Chart($("arcticAnnualChart"),{
    type:"line",data:{labels:data.days,datasets:yearDatasets()},options:yopts
  });
  const climate=data.reference.temperatures,delta=diff(series,climate);
  const avg7=smooth(delta,7),avg30=smooth(delta,30);
  const datasets=[{
    type:"bar",label:"Tagesanomalie",data:delta,indexKind:"daily",order:5,
    barPercentage:.95,categoryPercentage:.95,
    backgroundColor:ctx=>valid(ctx.raw)&&ctx.raw>=0?"rgba(213,88,73,.73)":"rgba(63,125,181,.74)",
    borderWidth:0
  }];
  if($("arcticShow7").checked)datasets.push(line("7-Tage-Mittel",avg7,"#233549",2.3,2,"rolling7"));
  if($("arcticShow30").checked)datasets.push(line("30-Tage-Mittel",avg30,"#e6a42f",2.6,1,"rolling30"));
  if(anomalyChart)anomalyChart.destroy();
  const aopts=basicOptions("K");
  aopts.scales.y.suggestedMin=-20;aopts.scales.y.suggestedMax=20;
  aopts.scales.y.title={display:true,text:"Tagesabweichung (K)",color:"#587083"};
  anomalyChart=new Chart($("arcticAnomalyChart"),{
    type:"bar",data:{labels:data.days,datasets},options:aopts
  });
  const idx=lastIndex(series);
  metric("arcticKpiTemp",idx<0?null:series[idx],"°C");
  metric("arcticKpiAnomaly",idx<0?null:delta[idx],"K");
  metric("arcticKpi7",idx<0?null:avg7[idx],"K");
  metric("arcticKpi30",idx<0?null:avg30[idx],"K");
  $("arcticKpiTempNote").textContent=idx<0?"Kein Tageswert":year+" · "+data.days[idx].slice(3)+"."+data.days[idx].slice(0,2)+".";
}
function selectYears(){
  const primary=$("arcticYear"),compare=$("arcticCompare"),all=years(data);
  primary.replaceChildren();compare.replaceChildren();
  const none=document.createElement("option");none.value="";none.textContent="Kein zweites Jahr";compare.appendChild(none);
  all.forEach(y=>{
    const opt=document.createElement("option");opt.value=String(y);opt.textContent=String(y);
    primary.appendChild(opt);compare.appendChild(opt.cloneNode(true));
  });
  primary.value=String(data.latest_year);compare.value=all.includes(2012)?"2012":"";
  primary.disabled=false;compare.disabled=false;
}
function exportCanvas(chart,title){
  if(!chart)throw new Error("Diagramm fehlt");
  const pixelRatio=2,extra=100;
  const canvas=document.createElement("canvas");
  canvas.width=chart.canvas.width*pixelRatio;
  canvas.height=(chart.canvas.height+extra)*pixelRatio;
  const ctx=canvas.getContext("2d");
  ctx.fillStyle="#ffffff";ctx.fillRect(0,0,canvas.width,canvas.height);
  ctx.fillStyle="#19344b";ctx.font="bold 28px Arial";
  ctx.fillText(title,25,45);
  ctx.fillStyle="#607386";ctx.font="15px Arial";
  ctx.fillText("DMI / ECMWF · >80° N · Stand "+dateText(data.last_date)+" · Referenz 1958–2002",25,78);
  ctx.drawImage(chart.canvas,0,100,chart.canvas.width*pixelRatio,chart.canvas.height*pixelRatio);
  ctx.fillText("DMI +80N Temperaturindex · kein flächengewichtetes Arktismittel",25,canvas.height-18);
  return canvas.toDataURL("image/png");
}
function downloadUrl(url,name){
  const a=document.createElement("a");a.href=url;a.download=name;
  document.body.appendChild(a);a.click();a.remove();
}
function downloadBlob(body,name,type){
  const url=URL.createObjectURL(new Blob([body],{type}));
  downloadUrl(url,name);setTimeout(()=>URL.revokeObjectURL(url),2000);
}
function png(which){
  const graph=which==="year"?annualChart:anomalyChart;
  const title=which==="year"?"Arktis >80°N · 2-m-Temperatur":"Arktis >80°N · Temperaturabweichung "+selected();
  downloadUrl(exportCanvas(graph,title),"Arktis_80N_"+which+"_"+selected()+".png");
}
function pdf(){
  const PDF=window.jspdf&&window.jspdf.jsPDF;
  if(!PDF){setStatus("PDF-Bibliothek nicht verfügbar – PNG und CSV funktionieren weiterhin.",true);return;}
  const documentPdf=new PDF({orientation:"landscape",unit:"mm",format:"a4"});
  [[annualChart,"Arktis >80°N · 2-m-Temperatur"],[anomalyChart,"Arktis >80°N · Abweichung "+selected()]]
    .forEach((entry,index)=>{
      if(index)documentPdf.addPage();
      const img=exportCanvas(entry[0],entry[1]);
      const props=documentPdf.getImageProperties(img);
      const w=272,h=Math.min(177,w*props.height/props.width);
      documentPdf.addImage(img,"PNG",12,13,w,h);
      documentPdf.setFontSize(8);documentPdf.setTextColor(65,90,110);
      documentPdf.text("DMI/ECMWF-Temperaturindex · Datenstand "+dateText(data.last_date),12,197);
    });
  documentPdf.save("Arktis_80N_"+selected()+".pdf");
}
async function load(){
  setStatus("Lade die geprüften Original-Tageswerte vom DMI …");
  const paths=["data/arctic80_temperature.json",
    "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/main/data/arctic80_temperature.json"];
  for(const path of paths){
    try{
      const res=await fetch(path,{cache:"no-store"});
      if(!res.ok)continue;
      const incoming=await res.json();
      if(incoming.schema!==1||incoming.product!=="DMI +80N temperature index"
         ||!Array.isArray(incoming.days)||incoming.days.length!==366
         ||!incoming.reference||incoming.reference.temperatures.length!==366
         ||!incoming.years||Object.keys(incoming.years).length<40
         ||!incoming.years[String(incoming.latest_year)])continue;
      data=incoming;
      window.Arctic80LoadedData=data;
      selectYears();
      $("arcticLastDay").textContent=dateText(data.last_date);
      $("arcticUpdated").textContent=Object.keys(data.years).length+" Jahresreihen · DMI Originaldaten";
      ["arcticPngAnnual","arcticPngAnomaly","arcticPdf","arcticCsv"].forEach(id=>$(id).disabled=false);
      const ageDays=Math.floor((Date.now()-Date.parse(data.last_date+"T00:00:00Z"))/86400000);
      if(ageDays>=2)
        setStatus("DMI-Datenstand "+dateText(data.last_date)+" – möglicherweise verzögert ("+ageDays+" Tage). Bitte Datenimport prüfen.",true);
      else
        setStatus("Datenstand "+dateText(data.last_date)+" · "+Object.keys(data.years).length+" Jahresreihen · DMI-Analysen, keine Prognose.");
      // A missing chart CDN must not silently leave blank plots with enabled export buttons.
      if(typeof Chart==="undefined"){
        ["arcticPngAnnual","arcticPngAnomaly","arcticPdf"].forEach(id=>$(id).disabled=true);
        setStatus("DMI-Daten sind vorhanden, aber Chart.js konnte nicht geladen werden. CSV und Statistik bleiben verfügbar.",true);
      }else{
        draw();
      }
      window.dispatchEvent(new CustomEvent("arctic80:data-ready",{detail:data}));
      $("arcticYear").dispatchEvent(new Event("change"));
      return;
    }catch(error){console.warn("DMI +80N:",path,error);}
  }
  $("arcticLastDay").textContent="Daten fehlen noch";
  setStatus("Die DMI-Temperaturdatei konnte noch nicht geladen werden. Der automatische erste Datenimport ist möglicherweise noch nicht abgeschlossen; Originalquelle siehe unten.",true);
}
function init(){
  ["arcticYear","arcticCompare","arcticHistoryMode","arcticReference","arcticShow7","arcticShow30"]
    .forEach(id=>$(id).addEventListener("change",draw));
  $("arcticPngAnnual").addEventListener("click",()=>png("year"));
  $("arcticPngAnomaly").addEventListener("click",()=>png("anomaly"));
  $("arcticCsv").addEventListener("click",()=>downloadBlob(
    csv(data,selected(),compared()),"Arktis_80N_"+selected()+".csv","text/csv;charset=utf-8"));
  $("arcticPdf").addEventListener("click",pdf);
  load();
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});
else init();
})();


/* DMI +80°N: historical records, percentiles, monthly and seasonal rankings. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const good=v=>typeof v==="number"&&Number.isFinite(v);
const mn=["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"];
const fmt=v=>good(v)?v.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1}):"–";
const signed=v=>good(v)?(v>0?"+":"")+fmt(v):"–";
const mean=a=>a.reduce((s,x)=>s+x,0)/a.length;
const quantile=(sorted,p)=>{const pos=(sorted.length-1)*p,lo=Math.floor(pos),hi=Math.ceil(pos);return sorted[lo]+(sorted[hi]-sorted[lo])*(pos-lo);};
const dayIdx=(doc,m,d)=>doc.days.indexOf(String(m).padStart(2,"0")+"-"+String(d).padStart(2,"0"));
const monthSlots=(doc,m)=>doc.days.map((d,i)=>d.startsWith(String(m).padStart(2,"0")+"-")?i:-1).filter(i=>i>=0);
function daily(doc,index,year){
 const values=Object.entries(doc.years).map(([y,series])=>({year:Number(y),value:series[index]})).filter(x=>good(x.value)).sort((a,b)=>a.value-b.value||a.year-b.year);
 const selected=values.find(x=>x.year===Number(year)); const sorted=values.map(x=>x.value);
 return {count:values.length,min:values[0]||null,max:values[values.length-1]||null,
   p10:values.length>=5?quantile(sorted,.10):null,p90:values.length>=5?quantile(sorted,.90):null,
   rank:selected?values.filter(x=>x.value>selected.value).length+1:null,
   selected:selected||null,highest:values.slice(-10).reverse(),lowest:values.slice(0,10)};
}
function period(doc,year,definition){
 const slots=[];
 for(const [offset,month] of definition){
   const y=year+offset, series=doc.years[String(y)];
   if(!series)return null;
   const indices=monthSlots(doc,month).filter(i=>!(doc.days[i]==="02-29"&& !(y%4===0&&(y%100!==0||y%400===0))));
   for(const index of indices){if(!good(series[index]))return null;slots.push(series[index]);}
 }
 return slots.length?mean(slots):null;
}
const periods=[
 ...mn.map((label,i)=>({id:"m"+(i+1),label,def:[[0,i+1]]})),
 {id:"djf",label:"Winter (DJF)",def:[[-1,12],[0,1],[0,2]]},
 {id:"mam",label:"Frühling (MAM)",def:[[0,3],[0,4],[0,5]]},
 {id:"jja",label:"Sommer (JJA)",def:[[0,6],[0,7],[0,8]]},
 {id:"son",label:"Herbst (SON)",def:[[0,9],[0,10],[0,11]]}
];
function periodStats(doc,chosen,year){
 const list=Object.keys(doc.years).map(Number).map(y=>({year:y,value:period(doc,y,chosen.def)})).filter(x=>good(x.value));
 const desc=list.slice().sort((a,b)=>b.value-a.value||a.year-b.year),asc=list.slice().sort((a,b)=>a.value-b.value||a.year-b.year);
 const current=list.find(x=>x.year===Number(year));
 return {count:list.length,selected:current||null,rank:current?list.filter(x=>x.value>current.value).length+1:null,
   mean:list.length?mean(list.map(x=>x.value)):null,warmest:desc.slice(0,10),coldest:asc.slice(0,10)};
}
window.Arctic80StatsMath={daily,period,periodStats,quantile,periods};
let doc;
const tableRows=(list,year)=>list.map((x,i)=>{const rank=list.findIndex(y=>y.value===x.value)+1;return '<tr'+(x.year===Number(year)?' class="arctic-selected"':'')+'><td>'+rank+'.</td><td>'+x.year+'</td><td>'+fmt(x.value)+' °C</td></tr>';}).join("");
function render(){
 if(!doc)return;
 const year=$("arcticYear").value,parts=$("arcticRecordDay").value.split("-").map(Number);
 const index=dayIdx(doc,parts[0],parts[1]);
 if(index<0)return;
 const dailyValues=daily(doc,index,year),picked=dailyValues.selected;
 $("arcticRecordSummary").textContent=picked?
  fmt(picked.value)+" °C · "+dailyValues.rank+". wärmster Wert von "+dailyValues.count+" Jahren":
  "Für "+year+" liegt an diesem Kalendertag kein Wert vor ("+dailyValues.count+" Vergleichsjahre).";
 $("arcticRecordMeta").textContent="Historische Spanne "+(dailyValues.min?fmt(dailyValues.min.value)+" °C ("+dailyValues.min.year+")":"–")+
   " bis "+(dailyValues.max?fmt(dailyValues.max.value)+" °C ("+dailyValues.max.year+")":"–")+
   " · P10 "+fmt(dailyValues.p10)+" °C · P90 "+fmt(dailyValues.p90)+" °C";
 $("arcticRecordHot").innerHTML=tableRows(dailyValues.highest,year);
 $("arcticRecordCold").innerHTML=tableRows(dailyValues.lowest,year);
 const p=periods.find(x=>x.id===$("arcticPeriod").value)||periods[0],s=periodStats(doc,p,year);
 $("arcticPeriodSummary").textContent=s.selected?fmt(s.selected.value)+" °C · Platz "+s.rank+" (warm) von "+s.count+" vollständigen Perioden":
   "Für "+year+" ist diese Periode nicht vollständig verfügbar.";
 $("arcticPeriodMeta").textContent="Historischer Durchschnitt der vollständigen "+p.label+"-Perioden: "+fmt(s.mean)+" °C"+
   (s.selected?" · Abweichung: "+signed(s.selected.value-s.mean)+" K":"")+
   (p.id==="djf"?" · Winterjahr bezeichnet Januar/Februar":"");
 $("arcticPeriodHot").innerHTML=tableRows(s.warmest,year);
 $("arcticPeriodCold").innerHTML=tableRows(s.coldest,year);
}
function acceptData(incoming){
 if(!incoming||!incoming.years||!Array.isArray(incoming.days)||incoming.days.length!==366)return false;
 doc=incoming;
 const year=String(doc.latest_year);
 // Start with the most recent fully observed month, not a still-running month.
 const completeMonth=periods.slice(0,12).filter(p=>good(period(doc,Number(year),p.def))).at(-1);
 if(completeMonth && !$("arcticPeriod").dataset.userSelected){
   $("arcticPeriod").value=completeMonth.id;
 }
 const latest=doc.years[year]||[];
 const last=latest.findLastIndex(v=>good(v));
 const current=$("arcticRecordDay").value;
 if(!current||current==="01-01")$("arcticRecordDay").value=last>=0?doc.days[last]:"11-01";
 render();
 return true;
}
async function init(){
 const ids=["arcticRecordDay","arcticPeriod","arcticYear"];
 if(!ids.every(id=>$(id)))return;
 const sel=$("arcticPeriod");
 periods.forEach(p=>{const o=document.createElement("option");o.value=p.id;o.textContent=p.label;sel.append(o);});
 sel.value="m11";
 for(const id of ids)$(id).addEventListener("change",render);
 $("arcticPeriod").addEventListener("change",()=>{$("arcticPeriod").dataset.userSelected="1";});
 // Existing main charts publish the exact data they already loaded successfully.
 window.addEventListener("arctic80:data-ready",event=>acceptData(event.detail));
 if(acceptData(window.Arctic80LoadedData))return;
 const paths=["data/arctic80_temperature.json",
   "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/main/data/arctic80_temperature.json"];
 for(const path of paths){
   try{
     const response=await fetch(path,{cache:"no-store"});
     if(!response.ok)throw Error("HTTP "+response.status);
     const incoming=await response.json();
     if(acceptData(incoming))return;
   }catch(error){console.warn("DMI stats loading "+path,error);}
 }
 if(!doc){
   $("arcticRecordSummary").textContent="Keine Statistikdaten geladen. Bitte Seite neu laden oder Datenstatus prüfen.";
   $("arcticPeriodSummary").textContent="Keine Statistikdaten geladen. Bitte Seite neu laden oder Datenstatus prüfen.";
 }
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});else init();
})();



/* DMI climate-streak monitor: fixed 1958–2002 calendar-day P10/P90 reference. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const valid=v=>typeof v==="number"&&Number.isFinite(v);
const leap=y=>y%4===0&&(y%100!==0||y%400===0);
const dateLabel=iso=>iso?iso.slice(8,10)+"."+iso.slice(5,7)+"."+iso.slice(0,4):"–";
const number=v=>valid(v)?v.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1}):"–";
const quantile=(values,p)=>{
  if(!values.length)return null;
  const a=values.slice().sort((x,y)=>x-y),q=(a.length-1)*p,lo=Math.floor(q);
  return a[lo]+(a[Math.ceil(q)]-a[lo])*(q-lo);
};
function thresholds(doc,start=1958,end=2002){
  if(!Array.isArray(doc.days)||!doc.years)throw Error("DMI Tageswerte fehlen");
  const p10=[],p90=[],counts=[];
  for(let i=0;i<doc.days.length;i++){
    const sample=[];
    for(let y=start;y<=end;y++){
      const v=doc.years[String(y)]?.[i];
      if(valid(v))sample.push(v);
    }
    const enough=sample.length >= (doc.days[i]==="02-29"?10:30);
    p10.push(enough?quantile(sample,.1):null);
    p90.push(enough?quantile(sample,.9):null);
    counts.push(sample.length);
  }
  return {p10,p90,counts};
}
function analyze(doc,ref=thresholds(doc)){
  const annual=[],allEvents={warm:[],cold:[]};
  const open={warm:null,cold:null};
  const flush=kind=>{
    const e=open[kind];if(!e)return;
    e.meanExcess=e.excess/e.days;
    e.latest=e.end===doc.last_date;
    allEvents[kind].push(e);open[kind]=null;
  };
  let previousDay=null;
  for(const y of Object.keys(doc.years).map(Number).sort((a,b)=>a-b)){
    const values=doc.years[String(y)],row={
      year:y,expected:leap(y)?366:365,coverage:0,
      warmDays:0,coldDays:0,maxWarm:0,maxCold:0,
      currentWarm:0,currentCold:0,months:Array.from({length:12},()=>({warm:0,cold:0,coverage:0}))
    };
    for(let i=0;i<doc.days.length;i++){
      const day=doc.days[i];
      if(day==="02-29"&&!leap(y))continue;
      const iso=String(y).padStart(4,"0")+"-"+day;
      const time=Date.UTC(y,Number(day.slice(0,2))-1,Number(day.slice(3)));
      if(previousDay!==null&&time-previousDay!==86400000){flush("warm");flush("cold");}
      previousDay=time;
      const v=values[i],low=ref.p10[i],high=ref.p90[i];
      const month=row.months[Number(day.slice(0,2))-1];
      if(!valid(v)||!valid(low)||!valid(high)){
        row.currentWarm=0;row.currentCold=0;
        flush("warm");flush("cold");continue;
      }
      row.coverage++;month.coverage++;
      const flags={warm:v>high,cold:v<low};
      for(const kind of ["warm","cold"]){
        const isMatch=flags[kind],counter=kind==="warm"?"warmDays":"coldDays";
        const current=kind==="warm"?"currentWarm":"currentCold";
        const max=kind==="warm"?"maxWarm":"maxCold";
        if(isMatch){
          row[counter]++;month[kind]++;
          row[current]++;row[max]=Math.max(row[max],row[current]);
          const excess=kind==="warm"?v-high:low-v;
          if(!open[kind])open[kind]={start:iso,end:iso,days:0,excess:0};
          open[kind].end=iso;open[kind].days++;open[kind].excess+=excess;
        }else{
          row[current]=0;flush(kind);
        }
      }
    }
    annual.push(row);
  }
  flush("warm");flush("cold");
  const sortEvents=(a,b)=>b.days-a.days||b.meanExcess-a.meanExcess||a.start.localeCompare(b.start);
  allEvents.warm.sort(sortEvents);allEvents.cold.sort(sortEvents);
  return {reference:ref,annual,events:allEvents};
}
function rank(items,metric,target){
  if(!target)return null;
  return 1+items.filter(v=>v[metric]>target[metric]).length;
}
window.Arctic80StreaksMath={quantile,thresholds,analyze,rank,leap};
let data=null,computed=null;
const words={warm:{name:"warmer",label:"Warmtage",threshold:"P90",color:"warm"},cold:{name:"kälter",label:"Kalttage",threshold:"P10",color:"cold"}};
function render(){
  if(!computed)return;
  const kind=$("arcticStreakType").value==="cold"?"cold":"warm";
  const cfg=words[kind],selected=Number($("arcticYear").value);
  const minDays=Number($("arcticStreakMinDays").value)||3;
  const year=computed.annual.find(x=>x.year===selected);
  if(!year)return;
  const key=kind==="warm"?"warmDays":"coldDays",max=kind==="warm"?"maxWarm":"maxCold";
  const full=computed.annual.filter(x=>x.coverage===x.expected);
  const fullSelected=year.coverage===year.expected;
  const yrRank=fullSelected?rank(full,key,year):null;
  const all=computed.events[kind],matching=all.filter(x=>x.days>=minDays);
  const selectedEvents=all.filter(x=>x.start.slice(0,4)===String(selected)||x.end.slice(0,4)===String(selected));
  const maxEvent=selectedEvents.slice().sort((a,b)=>b.days-a.days)[0];
  $("arcticStreakStatus").textContent="Perzentile "+cfg.threshold+" · Referenz 1958–2002 · "+computed.annual.length+" Jahre · "+matching.length+" Serien ab "+minDays+" Tagen";
  $("arcticStreakDays").textContent=year[key]+" "+cfg.label;
  $("arcticStreakCoverage").textContent=year.coverage+" von "+year.expected+" Kalendertagen mit gültiger Auswertung";
  $("arcticStreakLongest").textContent=year[max]+" Tage";
  $("arcticStreakLongestNote").textContent="Längste durchgehende Folge innerhalb von "+selected;
  $("arcticStreakRanking").textContent=fullSelected?"Platz "+yrRank+" / "+full.length:"Nicht eingestuft";
  $("arcticStreakRankingNote").textContent=fullSelected?"Rang nach Anzahl "+cfg.label+" (vollständige Jahre)":"Unvollständiges Jahr – kein unfairer Jahresvergleich";
  $("arcticStreakNotable").textContent=maxEvent?
    "Längste Serie mit Bezug zu "+selected+": "+maxEvent.days+" Tage ("+dateLabel(maxEvent.start)+"–"+dateLabel(maxEvent.end)+")."+
    (maxEvent.latest?" Serie erreicht den jüngsten Datentag.":""):
    "Für "+selected+" wurde keine entsprechende Serie festgestellt.";
  const tbody=$("arcticStreakEvents");
  tbody.replaceChildren();
  if(!matching.length){
    const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=4;td.textContent="Keine Serien für diese Mindestlänge.";tr.append(td);tbody.append(tr);
  }else{
    const frag=document.createDocumentFragment();
    matching.slice(0,15).forEach((e,i)=>{
      const tr=document.createElement("tr");
      tr.tabIndex=0;tr.setAttribute("role","button");
      tr.setAttribute("aria-label","Serie "+dateLabel(e.start)+" bis "+dateLabel(e.end)+", "+e.days+" Tage im Diagramm anzeigen");
      if(e.start.slice(0,4)===String(selected)||e.end.slice(0,4)===String(selected))tr.className="arctic-selected";
      const position=rank(matching,"days",e);
      for(const v of [position+".",dateLabel(e.start)+" – "+dateLabel(e.end)+(e.latest?" *":""),String(e.days),number(e.meanExcess)+" K"]){
        const td=document.createElement("td");td.textContent=v;tr.append(td);
      }
      frag.append(tr);
    });
    tbody.append(frag);
  }
  const ordered=full.slice().sort((a,b)=>b[key]-a[key]||b[max]-a[max]||a.year-b.year);
  const ybody=$("arcticStreakYears");ybody.replaceChildren();
  const tbodyFragment=document.createDocumentFragment();
  ordered.slice(0,15).forEach(row=>{
    const tr=document.createElement("tr");if(row.year===selected)tr.className="arctic-selected";
    for(const v of [rank(full,key,row)+".",String(row.year),String(row[key]),String(row[max])]){
      const td=document.createElement("td");td.textContent=v;tr.append(td);
    }
    tbodyFragment.append(tr);
  });ybody.append(tbodyFragment);
  const histogram=$("arcticStreakMonths");histogram.replaceChildren();
  const monthLabels=["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"];
  const monthsFrag=document.createDocumentFragment();
  year.months.forEach((month,i)=>{
    const cell=document.createElement("div");cell.className="arctic-streak-month";
    const label=document.createElement("span");label.textContent=monthLabels[i];
    const track=document.createElement("span");track.className="arctic-streak-track";
    const bar=document.createElement("span");bar.className="arctic-streak-fill "+cfg.color;
    bar.style.width=month.coverage?((100*month[kind])/month.coverage)+"%":"0%";
    track.append(bar);
    const stat=document.createElement("small");stat.textContent=month[kind]+"/"+month.coverage;
    cell.title=monthLabels[i]+": "+month[kind]+" "+cfg.label+" bei "+month.coverage+" gültigen Tagen";
    cell.append(label,track,stat);monthsFrag.append(cell);
  });histogram.append(monthsFrag);
}
function accept(incoming){
  if(!incoming||!Array.isArray(incoming.days)||incoming.days.length!==366||!incoming.years)return false;
  data=incoming;
  computed=analyze(data);
  render();return true;
}
async function init(){
  if(!$("arcticStreaks")||!$("arcticYear"))return;
  ["arcticStreakType","arcticStreakMinDays","arcticYear"].forEach(id=>$(id).addEventListener("change",render));
  window.addEventListener("arctic80:data-ready",event=>accept(event.detail));
  if(accept(window.Arctic80LoadedData))return;
  for(const path of [
    "data/arctic80_temperature.json",
    "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/main/data/arctic80_temperature.json"
  ]){
    try{
      const res=await fetch(path,{cache:"no-store"});
      if(res.ok&&accept(await res.json()))return;
    }catch(err){console.warn("Arktis-Serien: Datenabruf",err);}
  }
  $("arcticStreakStatus").textContent="Seriendaten konnten nicht geladen werden.";
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});
else init();
})();



/* DMI Arctic interactive extreme spells on both charts + 1958-present heatmap */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const good=x=>typeof x==="number"&&Number.isFinite(x);
const FIXED_COLORS={warm:"#bc554b",cold:"#377baa",neutral:"#d9e1e8",missing:"#969eaa"};
const cfg={top:33,left:48,cell:3,row:13,foot:12};
let archive=null,calc=null,focus=null,hover=null,heatmapYears=[],registered=false;
const kindAt=(value,low,high)=>!good(value)||!good(low)||!good(high)?null:
  value>high?"warm":value<low?"cold":"neutral";
const colorFor=(kind)=>kind===null?FIXED_COLORS.missing:
  kind==="neutral"?FIXED_COLORS.neutral:FIXED_COLORS[kind];
function dateFor(year,day){return String(year)+"-"+day;}
function overlap(event,year){
  // ISO YYYY-MM-DD strings are ordered lexicographically; Math.max/min would coerce them to NaN.
  const yearStart=year+"-01-01",yearEnd=year+"-12-31";
  const start=event.start>yearStart?event.start:yearStart;
  const end=event.end<yearEnd?event.end:yearEnd;
  return start<=end?{start,end}:null;
}
function eventSegments(doc,results,year,kind,minDays=7){
  const kinds=kind==="all"?["warm","cold"]:[kind];
  const selected=String(year),segments=[];
  for(const k of kinds)for(const event of results.events[k]){
    if(event.days<minDays)continue;
    const shared=overlap(event,selected);
    if(!shared)continue;
    const from=doc.days.indexOf(shared.start.slice(5)),to=doc.days.indexOf(shared.end.slice(5));
    if(from>=0&&to>=from)segments.push({kind:k,from,to,event});
  }
  return segments.sort((a,b)=>a.from-b.from);
}
function hitCell(x,y,years,daysCount){
  const col=Math.floor((x-cfg.left)/cfg.cell),row=Math.floor((y-cfg.top)/cfg.row);
  if(row<0||row>=years.length||col<0||col>=daysCount)return null;
  return {year:years[row],index:col};
}
window.Arctic80VisualMath={kindAt,colorFor,overlap,eventSegments,hitCell};
const dayText=iso=>iso?iso.slice(8,10)+"."+iso.slice(5,7)+"."+iso.slice(0,4):"–";
const refCurrent=()=>String($("arcticYear")?.value||"");
const minLength=()=>Number($("arcticVisualMinimum")?.value||7);
const kindsEnabled=()=>["warm","cold"].filter(k=>$("arcticVisual"+(k==="warm"?"Warm":"Cold"))?.checked);
function visible(year=refCurrent()){
  if(!archive||!calc)return [];
  return kindsEnabled().flatMap(k=>eventSegments(archive,calc,year,k,minLength()));
}
window.Arctic80VisualState={
  segments:(year)=>visible(year||refCurrent()).map(s=>({kind:s.kind,from:s.from,to:s.to,start:s.event.start,end:s.event.end,days:s.event.days})),
  focused:()=>focus?{start:focus.start,end:focus.end,days:focus.days}:null,
  loaded:()=>!!archive
};
function selectedEventFor(year,index){
  const iso=dateFor(year,archive.days[index]);
  const matches=visible(year).filter(s=>iso>=s.event.start&&iso<=s.event.end);
  return matches.sort((a,b)=>b.event.days-a.event.days)[0]||null;
}
function info(text){
  if($("arcticVisualInfo"))$("arcticVisualInfo").textContent=text;
}
function chartUpdate(){
  if(typeof Chart==="undefined")return;
  for(const id of ["arcticAnnualChart","arcticAnomalyChart"]){
    const chart=Chart.getChart?.($(id));
    if(chart)chart.update("none");
  }
}
const overlay={
  id:"arcticExtremeOverlay",
  beforeDatasetsDraw(chart){
    if(!archive||!calc||!chart.canvas||!["arcticAnnualChart","arcticAnomalyChart"].includes(chart.canvas.id))return;
    const y=refCurrent(),segments=visible(y),scale=chart.scales.x,box=chart.chartArea;
    if(!scale||!box||!segments.length)return;
    const step=Math.abs(scale.getPixelForValue(1)-scale.getPixelForValue(0));
    if(!Number.isFinite(step)||step===0)return;
    const ctx=chart.ctx;ctx.save();ctx.beginPath();
    ctx.rect(box.left,box.top,box.right-box.left,box.bottom-box.top);ctx.clip();
    for(const segment of segments){
      const left=Math.max(box.left,scale.getPixelForValue(segment.from)-step/2);
      const right=Math.min(box.right,scale.getPixelForValue(segment.to)+step/2);
      if(right<=left)continue;
      const chosen=focus===segment.event;
      ctx.fillStyle=segment.kind==="warm"?(chosen?"rgba(188,85,75,.25)":"rgba(188,85,75,.12)"):
        (chosen?"rgba(55,123,170,.26)":"rgba(55,123,170,.12)");
      ctx.fillRect(left,box.top,right-left,box.bottom-box.top);
      ctx.fillStyle=FIXED_COLORS[segment.kind];
      ctx.fillRect(left,box.top,right-left,chosen?6:3);
      if(chosen){ctx.lineWidth=2.5;ctx.strokeStyle=FIXED_COLORS[segment.kind];
        ctx.strokeRect(left+1,box.top+1,Math.max(1,right-left-2),box.bottom-box.top-2);}
    }
    ctx.restore();
  }
};
function eventCaption(e){
  const kind=calc.events.warm.includes(e)?"Wärme":"Kälte";
  return kind+"serie: "+e.days+" Tage · "+dayText(e.start)+" bis "+dayText(e.end);
}
function chooseEvent(e,navigate=true){
  if(!e)return;
  const preferred=refCurrent();
  const year=(preferred>=e.start.slice(0,4)&&preferred<=e.end.slice(0,4))?preferred:e.start.slice(0,4);
  if(year!==refCurrent()){$("arcticYear").value=year;$("arcticYear").dispatchEvent(new Event("change",{bubbles:true}));}
  focus=e;
  const day=e.start.slice(0,4)===year?e.start.slice(5):"01-01";
  if($("arcticRecordDay")){$("arcticRecordDay").value=day;$("arcticRecordDay").dispatchEvent(new Event("change"));}
  info("Im Diagramm markiert: "+eventCaption(e)+(e.end.slice(0,4)!==e.start.slice(0,4)?" · läuft über den Jahreswechsel":""));
  chartUpdate();paint();
  if(navigate)$("arcticAnnualWrap")?.scrollIntoView({behavior:"smooth",block:"center"});
}
function selectDay(year,index,navigate,origin="dmi"){
  if(!archive||!archive.days[index])return;
  const value=archive.years[String(year)]?.[index];
  if(refCurrent()!==String(year)){
    $("arcticYear").value=String(year);$("arcticYear").dispatchEvent(new Event("change",{bubbles:true}));
  }
  const day=archive.days[index],iso=dateFor(year,day);
  if($("arcticRecordDay")){$("arcticRecordDay").value=day;$("arcticRecordDay").dispatchEvent(new Event("change"));}
  const s=selectedEventFor(year,index);
  focus=s?.event||null;
  const threshold=calc.reference;
  const kind=kindAt(value,threshold.p10[index],threshold.p90[index]);
  info(dayText(iso)+" · "+(good(value)?value.toLocaleString("de-DE",{maximumFractionDigits:1})+" °C":"kein Messwert")+
    " · "+(kind==="warm"?"über P90":kind==="cold"?"unter P10":kind===null?"Datenlücke":"innerhalb P10–P90")+
    (s?" · "+eventCaption(s.event):""));
  chartUpdate();paint();
  window.dispatchEvent(new CustomEvent("arctic80:day-selected",{
    detail:{date:iso,source:origin}
  }));
  if(navigate)$("arcticAnnualWrap")?.scrollIntoView({behavior:"smooth",block:"center"});
}
// The ERA5 viewer can navigate the existing DMI records without recreating charts or
// silently changing the date to a different day. Historical years remain selectable.
window.Arctic80NavigateToDate=(iso,origin="era5")=>{
  if(!archive||!/^\d{4}-\d{2}-\d{2}$/.test(iso||""))return false;
  const year=Number(iso.slice(0,4)),day=iso.slice(5),index=archive.days.indexOf(day);
  if(index<0||!archive.years[String(year)]||(day==="02-29"&&!leap(year)))return false;
  selectDay(year,index,false,origin);
  return true;
};
function chartClick(event){
  if(!archive||!calc||typeof Chart==="undefined")return;
  const chart=Chart.getChart(event.currentTarget),scale=chart?.scales?.x;
  if(!scale)return;
  const rect=chart.canvas.getBoundingClientRect();
  const px=(event.clientX-rect.left)*(chart.canvas.width/rect.width)/chart.currentDevicePixelRatio;
  if(px<chart.chartArea.left||px>chart.chartArea.right)return;
  const index=Math.max(0,Math.min(archive.days.length-1,Math.round(scale.getValueForPixel(px))));
  const year=Number(refCurrent());
  selectDay(year,index,false);
}
function eventRowClick(event){
  const tr=event.target.closest("tr");if(!tr||!calc||!tr.parentNode||!tr.parentNode.id)return;
  const kind=$("arcticStreakType")?.value==="cold"?"cold":"warm";
  const minimum=Number($("arcticStreakMinDays")?.value||7);
  const list=calc.events[kind].filter(e=>e.days>=minimum).slice(0,15);
  const rowIndex=[...tr.parentNode.children].indexOf(tr);
  if(list[rowIndex])chooseEvent(list[rowIndex]);
}
function heatmapSize(){return {w:cfg.left+archive.days.length*cfg.cell+15,
  h:cfg.top+heatmapYears.length*cfg.row+cfg.foot};}
function paint(){
  if(!archive||!calc)return;
  const canvas=$("arcticHeatmapCanvas"),ctx=canvas.getContext("2d");
  const {w,h}=heatmapSize();
  const dpr=Math.min(window.devicePixelRatio||1,2);
  if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){
    canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);
    canvas.style.width=w+"px";canvas.style.height=h+"px";
  }
  ctx.setTransform(dpr,0,0,dpr,0,0);
  const dark=document.documentElement.dataset.theme==="dark"||document.body.classList.contains("dark-mode");
  ctx.clearRect(0,0,w,h);
  ctx.fillStyle=dark?"#162234":"#ffffff";ctx.fillRect(0,0,w,h);
  ctx.font="11px system-ui,Arial";ctx.textBaseline="middle";
  const ink=dark?"#cbd8e7":"#52677c";
  ctx.fillStyle=ink;
  const monthNames=["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"];
  for(let m=1;m<=12;m++){
    const idx=archive.days.indexOf(String(m).padStart(2,"0")+"-01");
    if(idx<0)continue;
    const x=cfg.left+idx*cfg.cell;
    ctx.fillText(monthNames[m-1],x+3,15);
  }
  const yearFocus=refCurrent();
  const selectedIndex=hover?.index??archive.days.indexOf($("arcticRecordDay")?.value||"");
  const rowYears=heatmapYears;
  for(let r=0;r<rowYears.length;r++){
    const year=rowYears[r],arr=archive.years[String(year)]||[];
    const top=cfg.top+r*cfg.row;
    ctx.fillStyle=ink;ctx.fillText(String(year),2,top+5);
    for(let i=0;i<archive.days.length;i++){
      const kind=kindAt(arr[i],calc.reference.p10[i],calc.reference.p90[i]);
      ctx.fillStyle=colorFor(kind);
      ctx.fillRect(cfg.left+i*cfg.cell,top,cfg.cell,11);
    }
    if(String(year)===yearFocus){
      ctx.strokeStyle=dark?"#e4e9f1":"#253d53";ctx.lineWidth=1.6;
      ctx.strokeRect(cfg.left-.6,top-1,archive.days.length*cfg.cell+1.2,13);
      ctx.fillStyle=dark?"#f6cf70":"#1a4c72";ctx.fillText("▶",cfg.left-10,top+5);
      if(selectedIndex>=0){
        ctx.fillStyle=dark?"#f6cf70":"#223e56";
        ctx.fillRect(cfg.left+selectedIndex*cfg.cell,top-2,Math.max(2,cfg.cell),15);
        ctx.fillStyle=colorFor(kindAt(arr[selectedIndex],calc.reference.p10[selectedIndex],calc.reference.p90[selectedIndex]));
        ctx.fillRect(cfg.left+selectedIndex*cfg.cell+.5,top,Math.max(1,cfg.cell-1),11);
      }
    }
  }
  ctx.strokeStyle=dark?"rgba(235,240,248,.30)":"rgba(30,58,82,.22)";
  ctx.lineWidth=.6;
  for(let m=2;m<=12;m++){
    const idx=archive.days.indexOf(String(m).padStart(2,"0")+"-01");
    const x=cfg.left+idx*cfg.cell;
    ctx.beginPath();ctx.moveTo(x,cfg.top);ctx.lineTo(x,cfg.top+rowYears.length*cfg.row);ctx.stroke();
  }
}
function cellFromEvent(event){
  const canvas=$("arcticHeatmapCanvas"),rect=canvas.getBoundingClientRect();
  const {w,h}=heatmapSize();
  return hitCell((event.clientX-rect.left)*w/rect.width,
    (event.clientY-rect.top)*h/rect.height,heatmapYears,archive.days.length);
}
function heatHover(event){
  if(!archive||!calc)return;
  const cell=cellFromEvent(event);
  if(!cell)return;
  hover=cell;
  const day=archive.days[cell.index],val=archive.years[String(cell.year)]?.[cell.index];
  const kind=kindAt(val,calc.reference.p10[cell.index],calc.reference.p90[cell.index]);
  $("arcticHeatmapHover").textContent=dayText(dateFor(cell.year,day))+" · "+
    (good(val)?val.toLocaleString("de-DE",{maximumFractionDigits:1})+" °C":"keine Daten")+
    " · "+(kind==="warm"?"über P90":kind==="cold"?"unter P10":kind===null?"fehlend":"P10–P90");
}
function setupCanvas(){
  const canvas=$("arcticHeatmapCanvas");
  canvas.addEventListener("pointermove",heatHover);
  canvas.addEventListener("click",event=>{
    const cell=cellFromEvent(event);if(cell)selectDay(cell.year,cell.index,true);
  });
  canvas.addEventListener("keydown",event=>{
    const keys={ArrowLeft:[0,-1],ArrowRight:[0,1],ArrowUp:[-1,0],ArrowDown:[1,0]};
    if(!keys[event.key]&&event.key!=="Enter")return;
    event.preventDefault();
    const year=Number(refCurrent()),index=archive.days.indexOf($("arcticRecordDay")?.value||"01-01");
    if(event.key==="Enter"){selectDay(year,Math.max(0,index),true);return;}
    const row=heatmapYears.indexOf(year);
    const delta=keys[event.key];
    const nextYear=heatmapYears[Math.max(0,Math.min(heatmapYears.length-1,row+delta[0]))]||year;
    const nextIndex=Math.max(0,Math.min(365,index+delta[1]));
    selectDay(nextYear,nextIndex,false);
    const x=cfg.left+nextIndex*cfg.cell;
    $("arcticHeatmapScroll").scrollLeft=Math.max(0,x-180);
  });
}
function initData(doc){
  if(!doc?.years||doc.days?.length!==366||!window.Arctic80StreaksMath)return;
  archive=doc;calc=window.Arctic80StreaksMath.analyze(doc);
  heatmapYears=Object.keys(doc.years).map(Number).sort((a,b)=>a-b);
  if(!heatmapYears.length)return;
  $("arcticHeatmapCount").textContent=heatmapYears.length+" Jahre · "+heatmapYears[0]+"–"+heatmapYears.at(-1)+" · Referenz 1958–2002";
  paint();chartUpdate();
}
function init(){
  if(!$("arcticHeatmapCanvas")||!$("arcticAnnualChart"))return;
  if(typeof Chart!=="undefined"&&!registered){Chart.register(overlay);registered=true;}
  setupCanvas();
  ["arcticVisualWarm","arcticVisualCold","arcticVisualMinimum"].forEach(id=>
    $(id).addEventListener("change",()=>{focus=null;chartUpdate();paint();}));
  $("arcticYear").addEventListener("change",()=>{focus=null;paint();chartUpdate();});
  $("arcticRecordDay").addEventListener("change",paint);
  $("arcticStreakEvents").addEventListener("click",eventRowClick);
  $("arcticStreakEvents").addEventListener("keydown",event=>{
    if(event.key==="Enter"||event.key===" "){event.preventDefault();eventRowClick(event);}
  });
  for(const id of ["arcticAnnualChart","arcticAnomalyChart"])$(id).addEventListener("click",chartClick);
  const themeObserver=new MutationObserver(()=>paint());
  themeObserver.observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
  themeObserver.observe(document.body,{attributes:true,attributeFilter:["class"]});
  window.addEventListener("arctic80:data-ready",event=>initData(event.detail));
  if(window.Arctic80LoadedData)initData(window.Arctic80LoadedData);
  else info("Die Heatmap wartet auf die DMI-Tageswerte …");
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});
else init();
})();
