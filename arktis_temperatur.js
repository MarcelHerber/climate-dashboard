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
      selectYears();
      $("arcticLastDay").textContent=dateText(data.last_date);
      $("arcticUpdated").textContent=Object.keys(data.years).length+" Jahresreihen · DMI Originaldaten";
      ["arcticPngAnnual","arcticPngAnomaly","arcticPdf","arcticCsv"].forEach(id=>$(id).disabled=false);
      setStatus("Datenstand "+dateText(data.last_date)+" · "+Object.keys(data.years).length+" Jahresreihen · DMI-Analysen, keine Prognose.");
      draw();return;
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
