(()=>{"use strict";
const $=id=>document.getElementById(id), module=document.body.dataset.climateModule;
const col={nao:"#1868ae",ao:"#d18b27",scand:"#7b58a3",ea:"#16876f",eawr:"#b64f7b",gbi:"#6b7f91",soi:"#94652b",mei:"#b14c70",u30:"#196db3",u50:"#d58e32"};
let archive=null,chart=null,table=[],title="";
const f=n=>Number.isFinite(n)?n.toLocaleString("de-DE",{maximumFractionDigits:2}):"–";
const sel=id=>$(id)?.value;
const data=k=>{
 if(archive.teleconnections?.[k])return archive.teleconnections[k].monthly.map(a=>a.slice(0,2));
 for(const group of ["europe","enso_extra","qbo"])if(archive[group]?.[k])return archive[group][k].monthly;
 return [];
};
const meta=k=>archive.europe?.[k]||archive.enso_extra?.[k]||archive.qbo?.[k]||null;
const zoom=(rows,num)=>{
 if(num==="all"||!rows.length)return rows;
 const last=rows[rows.length-1][0],d=new Date(last+"-01T00:00:00Z");
 d.setUTCFullYear(d.getUTCFullYear()-Number(num));
 const start=d.toISOString().slice(0,7);return rows.filter(r=>r[0]>=start);
};
function markup(){
 const panel=document.querySelector("main>.panel");
 const types=[["scand","SCAND"],["ea","EA"],["eawr","EA/WR"],["gbi","GBI"]];
 function options(a){return a.map(r=>'<option value="'+r[0]+'">'+r[1]+'</option>').join("");}
 const europe=module==="nao-ao";
 const indices=europe?types:module==="enso"?[["soi","SOI"],["mei","MEI.v2"]]:[["u30","30 hPa"],["u50","50 hPa"]];
 if(module==="nao-ao"||module==="enso"){
  const label=europe?"Europäische Zirkulationsmuster: SCAND · EA · EA/WR · GBI":"ENSO-Erweiterung: SOI und MEI.v2";
  panel?.insertAdjacentHTML("afterend",'<section class="panel"><h2>'+label+'</h2>'+controls(options(indices),europe)+
   '<p class="small">Die Indizes werden aus offiziellen Zeitreihen geladen. Lücken und abweichende Datenstände bleiben sichtbar.</p></section>');
 }
 function controlsLocal(){return controls(options(indices),true);}
 if(module==="qbo"){$("advancedPanel").innerHTML=controlsLocal();}
 if(module==="mjo"){$("advancedPanel").innerHTML=
  '<div class="toolbar"><label>RMM-Zeitraum<select id="advDays"><option value="30">30 Tage</option><option value="60" selected>60 Tage</option><option value="90">90 Tage</option><option value="120">120 Tage</option></select></label>'+
  exportButtons()+'</div><p class="small">RMM1 und RMM2 · Amplitude 1 als Referenzkreis · jüngster Tag orange hervorgehoben. Die acht Phasen sind direkt beschriftet.</p>'+
  '<div class="status" id="advStatus">BOM-RMM-Daten werden geladen …</div><div class="kpis" id="advKpis"></div>'+
  '<div style="max-width:540px;height:540px;margin:auto;position:relative"><canvas id="advChart"></canvas></div>'+
  '<p class="small" id="advInfo"></p>';
 }
 function exportButtons(){return '<div class="right"><button class="btn" id="advPNG" disabled>PNG</button><button class="btn" id="advPDF" disabled>PDF</button><button class="btn" id="advCSV" disabled>CSV</button></div>';}
 function controls(opts,compare){
  return '<div class="toolbar"><label>Index<select id="advIndex">'+opts+'</select></label>'+
   (compare?'<label>Vergleich<select id="advCompare"><option value="none">Kein Vergleich</option>'+
   options(module==="qbo"?[["u30","QBO 30 hPa"],["u50","QBO 50 hPa"]]:[["nao","NAO"],["ao","AO"],["scand","SCAND"],["ea","EA"],["eawr","EA/WR"],["gbi","GBI"]])+'</select></label>':"")+
   '<label>Zeitraum<select id="advRange"><option value="5">5 Jahre</option><option value="10" selected>10 Jahre</option><option value="30">30 Jahre</option><option value="all">Gesamte Messreihe</option></select></label>'+
   exportButtons()+'</div><div class="status" id="advStatus">Daten laden …</div><div class="kpis" id="advKpis"></div>'+
   '<div class="chart-box" style="height:365px"><canvas id="advChart"></canvas></div><p class="small" id="advInfo"></p>';
 }
}
function setStatus(text){if($("advStatus"))$("advStatus").textContent=text;}
function cleanChart(){if(chart){chart.destroy();chart=null;}}
function enable(){["advPNG","advPDF","advCSV"].forEach(k=>{if($(k))$(k).disabled=false;});}
function renderMonthly(){
 const key=sel("advIndex"),compare=sel("advCompare")||"none";
 const base=zoom(data(key),sel("advRange"));
 if(!base.length)throw Error("Keine Monatswerte für "+key);
 const other=new Map(compare==="none"?[]:data(compare).map(r=>[r[0],r[1]]));
 const secondary=base.map(r=>other.get(r[0])??null);
 const unit=key==="gbi"?"σ":key.startsWith("u")?"m/s":"Index";
 const lines=[{label:key.toUpperCase(),data:base.map(r=>r[1]),borderColor:col[key],backgroundColor:col[key],pointRadius:0,borderWidth:2,spanGaps:false}];
 if(compare!=="none")lines.push({label:compare.toUpperCase(),data:secondary,borderColor:"#8c99ab",borderDash:[5,4],pointRadius:0,borderWidth:1.4,spanGaps:false});
 cleanChart();
 chart=new Chart($("advChart"),{type:"line",data:{labels:base.map(r=>r[0]),datasets:lines},options:{
  responsive:true,maintainAspectRatio:false,animation:false,
  interaction:{intersect:false,mode:"index"},
  scales:{x:{ticks:{maxRotation:0,maxTicksLimit:12},grid:{display:false}},y:{title:{display:true,text:unit}}},
  plugins:{datalabels:{display:false},legend:{position:"bottom",labels:{usePointStyle:true}},tooltip:{callbacks:{label:c=>c.dataset.label+": "+f(c.parsed.y)+" "+unit}}}
 }});
 table=[["Monat",key.toUpperCase(),compare.toUpperCase()],...base.map((r,i)=>[r[0],r[1],secondary[i]])];
 title=key.toUpperCase()+" · "+base[0][0]+"–"+base[base.length-1][0];
 const source=meta(key),last=data(key).at(-1);
 $("advInfo").textContent=(source?.method||"")+". Datenstand: "+last[0]+" · Quelle: "+(source?.source_url||"NOAA/CPC")+
 (key==="gbi"?" · GBI ist eine standardisierte Z500-Abweichung und keine EOF-Amplitude.":"")+
 (key==="mei"?" · MEI.v2 bezeichnet überlappende Zweimonatsperioden.":"");
 $("advKpis").innerHTML="<div class='kpi'><span>Jüngster Monatswert</span><b>"+f(last[1])+"</b><small>"+last[0]+"</small></div>"+
 "<div class='kpi'><span>Auswahl</span><b>"+base.length+"</b><small>Monate</small></div>";
 setStatus("Datenquelle geprüft · "+last[0]+(new Date(last[0]+"-01").getUTCFullYear()<new Date().getUTCFullYear()-1?" · Historisches Archiv (nicht aktuell)":""));
 enable();
}
function mjoRender(){
 const n=Number(sel("advDays")||60),history=archive.mjo?.daily;
 if(!history?.length)throw Error("MJO-RMM-Daten fehlen");
 const values=history.slice(-n),maximum=Math.max(2.7,...values.map(r=>Math.max(Math.abs(r[1]),Math.abs(r[2]))))+.3;
 const current=values.at(-1);
 const guide={id:"mjoPhases",beforeDatasetsDraw:c=>{
  const ctx=c.ctx,x=c.scales.x,y=c.scales.y;
  ctx.save();ctx.strokeStyle="#afbdcc";ctx.lineWidth=1;ctx.setLineDash([4,4]);
  for(let i=0;i<8;i++){const a=i*Math.PI/4;
   ctx.beginPath();ctx.moveTo(x.getPixelForValue(0),y.getPixelForValue(0));
   ctx.lineTo(x.getPixelForValue(maximum*Math.cos(a)),y.getPixelForValue(maximum*Math.sin(a)));ctx.stroke();}
  ctx.setLineDash([]);ctx.beginPath();ctx.ellipse(x.getPixelForValue(0),y.getPixelForValue(0),
   Math.abs(x.getPixelForValue(1)-x.getPixelForValue(0)),
   Math.abs(y.getPixelForValue(1)-y.getPixelForValue(0)),0,0,Math.PI*2);ctx.stroke();
  ctx.fillStyle="#51657b";ctx.textAlign="center";ctx.font="bold 12px Arial";
  [202.5,247.5,292.5,337.5,22.5,67.5,112.5,157.5].forEach((d,i)=>{
   const a=d*Math.PI/180,r=maximum*.83;
   ctx.fillText("P"+(i+1),x.getPixelForValue(r*Math.cos(a)),y.getPixelForValue(r*Math.sin(a)));});
  ctx.restore();
 }};
 cleanChart();
 chart=new Chart($("advChart"),{type:"scatter",data:{datasets:[{label:"BOM RMM",type:"line",showLine:true,
  data:values.map(r=>({x:r[1],y:r[2],record:r})),borderColor:"#2166a1",borderWidth:2,
  pointRadius:c=>c.dataIndex===values.length-1?7:2,pointBackgroundColor:c=>c.dataIndex===values.length-1?"#d96531":"#2166a1",
  parsing:false}]},plugins:[guide],options:{responsive:true,maintainAspectRatio:false,animation:false,
  scales:{x:{type:"linear",min:-maximum,max:maximum,title:{display:true,text:"RMM1"}},y:{type:"linear",min:-maximum,max:maximum,title:{display:true,text:"RMM2"}}},
  plugins:{datalabels:{display:false},legend:{display:false},tooltip:{callbacks:{
    title:i=>i[0]?.raw?.record[0]||"",
    label:c=>"Phase "+c.raw.record[3]+", Amplitude "+f(c.raw.record[4])+", RMM1 "+f(c.raw.x)+", RMM2 "+f(c.raw.y)}}}}});
 table=[["Datum","RMM1","RMM2","Phase","Amplitude"],...values];
 title="MJO RMM Phasen · "+values[0][0]+"–"+current[0];
 $("advInfo").textContent="Wheeler–Hendon-RMM-Index aus BOM, Originalwerte ohne Prognose. Quelle: "+archive.mjo.source_url+" · letzter Beobachtungstag "+archive.mjo.latest_date;
 $("advKpis").innerHTML="<div class='kpi'><span>Letzter Wert</span><b>"+current[0]+"</b><small>Phase "+current[3]+"</small></div>"+
 "<div class='kpi'><span>RMM-Amplitude</span><b>"+f(current[4])+"</b><small>"+(current[4]<1?"Schwach / innerhalb Einheitskreis":"Außerhalb Einheitskreis")+"</small></div>";
 setStatus("BOM RMM · "+history[0][0]+" bis "+archive.mjo.latest_date);
 enable();
}
function exportCanvas(){
 if(!chart)throw Error("Kein Diagramm geladen");
 const c=document.createElement("canvas"),source=chart.canvas,w=1300,h=Math.round(1200*source.height/source.width);
 c.width=w;c.height=145+h+55;const g=c.getContext("2d");g.fillStyle="#fff";g.fillRect(0,0,c.width,c.height);
 g.fillStyle="#142b43";g.font="bold 28px Arial";g.fillText(title.slice(0,65),40,56);
 g.fillStyle="#516274";g.font="17px Arial";g.fillText("Climate Dashboard · NOAA CPC / BOM",40,95);
 g.drawImage(source,50,145,1200,h);g.font="15px Arial";g.fillText("Quelle und Datenstand siehe Dashboard",40,c.height-18);return c;
}
function download(blob,ext){const u=URL.createObjectURL(blob),a=document.createElement("a");a.href=u;a.download=module+"_indices."+ext;a.click();setTimeout(()=>URL.revokeObjectURL(u),1500);}
function exportPNG(){try{exportCanvas().toBlob(b=>b&&download(b,"png"),"image/png");}catch(e){setStatus(e.message)}}
function exportPDF(){try{
 if(!window.jspdf?.jsPDF)throw Error("PDF-Bibliothek nicht geladen");
 const c=exportCanvas(),p=new window.jspdf.jsPDF({unit:"mm",format:"a4",orientation:"landscape"});
 const scale=Math.min(277/c.width,184/c.height);p.addImage(c.toDataURL("image/png"),"PNG",9,9,c.width*scale,c.height*scale);p.save(module+"_indices.pdf");
}catch(e){setStatus(e.message)}}
function exportCSV(){if(!table.length)return;const csv="\ufeff"+table.map(r=>r.map(x=>'"'+String(x??"").replace(/"/g,'""')+'"').join(";")).join("\r\n");download(new Blob([csv],{type:"text/csv;charset=utf-8"}),"csv");}
function render(){if(!archive)return;try{module==="mjo"?mjoRender():renderMonthly();}catch(e){console.error(e);setStatus("Auswertung nicht verfügbar: "+e.message);}}
async function init(){
 markup();
 for(const [id,fn] of [["advPNG",exportPNG],["advPDF",exportPDF],["advCSV",exportCSV]])$(id)?.addEventListener("click",fn);
 for(const id of ["advIndex","advCompare","advRange","advDays"])$(id)?.addEventListener("change",render);
 try{const r=await fetch("climate_indices/index.json",{cache:"no-store"});if(!r.ok)throw Error("HTTP "+r.status);
 archive=await r.json();if(!archive.ready)throw Error("Archiv wird aufgebaut");render();
 }catch(e){setStatus("Datenabruf fehlgeschlagen: "+e.message);}
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();