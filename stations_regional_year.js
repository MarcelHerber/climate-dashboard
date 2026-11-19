/* Compact calendar-day extremes: archive history vs. comparison year. */
(function(root){
"use strict";
const days=Array.from({length:366},(_,i)=>new Date(Date.UTC(2000,0,i+1)).toISOString().slice(5,10));
const months=["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"];
const dateLabel=md=>md.slice(3)+"."+md.slice(0,2)+".";
const series=(doc,slot)=>doc.rows.map(row=>row[slot]===null?null:row[slot][0]/10);
const fmt=n=>Number(n).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1});
const quote=v=>'"'+String(v??"").replace(/"/g,'""')+'"';
function csvText(doc){
 const head=["Kalendertag","Gebiet","Rekordart","Einheit","Historischer Wert","Rekordjahr","Historische Stations-ID","Historische Station","Historischer Status","Wert "+doc.current_year,"Vergleichsjahr","Aktuelle Stations-ID","Aktuelle Station","Aktueller Status"];
 const cols=r=>r?[fmt(r[0]/10),r[1],r[2],r[3],r[4]?"vorläufig":"historisch"]:["","","","",""];
 return "\ufeff"+[head,...doc.rows.map((r,i)=>[days[i],doc.area,doc.label||doc.metric,doc.unit,...cols(r[0]),...cols(r[1])])].map(row=>row.map(quote).join(";")).join("\r\n");
}
function validate(doc,metric,area){
 if(doc.schema!==1||doc.metric!==metric||doc.area!==area||!Array.isArray(doc.rows)||doc.rows.length!==366)throw Error("Jahresreihen sind unvollständig oder passen nicht zur Auswahl.");
 for(const [i,row] of doc.rows.entries()){
  if(!Array.isArray(row)||row.length!==2||row.some((v,slot)=>v!==null&&(!Array.isArray(v)||v.length!==5||!Number.isFinite(v[0])||!Number.isInteger(v[1])||(slot===1?v[1]!==doc.current_year:v[1]>=doc.current_year))))throw Error("Ungültiger Jahreswert am "+days[i]);
 }
 return doc;
}
const API={days,series,csvText,validate};
if(typeof module==="object"&&module.exports){module.exports=API;return;}
root.RegionalRecordYear=API;
const $=id=>document.getElementById(id);
const cache=new Map();
let chart=null,doc=null,serial=0,started=false;
const currentLabel=d=>String(d.current_year)+" · Tagesextrem";
const historicLabel=d=>"Historischer Rekord bis "+d.historical_end;
const heading=d=>d.label+" · "+d.area;
function save(blob,name){const a=document.createElement("a"),url=URL.createObjectURL(blob);a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);}
function name(d){return "rekord-jahresverlauf_"+d.metric+"_"+d.area+"_"+d.current_year;}
function detail(d,i,slot){
 const r=d.rows[i][slot];
 return r?dateLabel(days[i])+" "+r[1]+" · "+r[3]+" (DWD "+r[2]+") · "+fmt(r[0]/10)+" "+d.unit+(r[4]?" · vorläufig":""):"Keine Messung";
}
function selectDay(i){
 if(!doc||!days[i])return;
 $("rrYearDay").textContent=dateLabel(days[i])+" · "+historicLabel(doc)+": "+detail(doc,i,0)+" | "+doc.current_year+": "+detail(doc,i,1);
 $("rrDay").value=days[i];
 $("rrDay").dispatchEvent(new Event("change",{bubbles:true}));
 $("rrLoad").click();
}
function config(d,exportMode=false){
 const foreground="#263b52";
 const background={id:"rrYearBackground",beforeDraw(c){
   if(exportMode){const {ctx,width,height}=c;ctx.save();ctx.globalCompositeOperation="destination-over";ctx.fillStyle="#fff";ctx.fillRect(0,0,width,height);ctx.restore();}
 }};
 const base={pointRadius:ctx=>ctx.dataset.data[ctx.dataIndex]!=null&&ctx.dataset.data[ctx.dataIndex-1]==null&&ctx.dataset.data[ctx.dataIndex+1]==null?2:0,pointHoverRadius:4,pointHitRadius:10,spanGaps:false,tension:0,borderWidth:2};
 return {type:"line",data:{labels:days,datasets:[
  {...base,label:historicLabel(d),data:series(d,0),borderColor:"#547b9f",backgroundColor:"#547b9f"},
  {...base,label:currentLabel(d),data:series(d,1),borderColor:"#dc492f",backgroundColor:"#dc492f",borderWidth:2.5}
 ]},plugins:[background],options:{responsive:!exportMode,maintainAspectRatio:false,animation:false,devicePixelRatio:exportMode?1:undefined,
  interaction:{mode:"index",intersect:false},
  onClick:exportMode?undefined:(e,_items,c)=>{if(e.x>=c.chartArea.left&&e.x<=c.chartArea.right)selectDay(Math.round(c.scales.x.getValueForPixel(e.x)));},
  layout:{padding:exportMode?22:6},
  plugins:{
   dashboardColorMode:exportMode?false:undefined,
   legend:{labels:{color:foreground,boxWidth:24,font:{size:exportMode?20:12}}},
   title:{display:exportMode,text:heading(d),color:foreground,font:{size:30}},
   subtitle:{display:exportMode,text:"DWD CDC · Historie bis "+d.historical_end+" · Archivstand "+d.data_end,color:foreground,font:{size:18}},
   tooltip:{callbacks:{title:items=>dateLabel(days[items[0].dataIndex]),label:item=>detail(d,item.dataIndex,item.datasetIndex)}}
  },
  scales:{
   x:{ticks:{color:foreground,autoSkip:false,maxRotation:0,minRotation:0,font:{size:exportMode?17:11},callback:(_v,i)=>days[i].endsWith("-01")?months[Number(days[i].slice(0,2))-1]:""},grid:{color:ctx=>days[ctx.index]?.endsWith("-01")?"rgba(120,140,160,.25)":"transparent"}},
   y:{title:{display:true,text:d.unit,color:foreground,font:{size:exportMode?20:13}},ticks:{color:foreground,font:{size:exportMode?17:11}},grid:{color:"rgba(120,140,160,.22)"}}
  }
 }};
}
function buttons(on){for(const id of ["rrYearPng","rrYearPdf","rrYearCsv"])$(id).disabled=!on;}
async function update(){
 const metric=$("rrMetric").value,area=$("rrArea").value,index=$("rrArea").selectedIndex;
 const seq=++serial;doc=null;buttons(false);$("rrYearStatus").textContent="Lade Jahresverlauf …";
 $("rrYearDay").textContent="Klicke einen Kalendertag an, um die Top 50 zu öffnen.";
 if(chart){chart.destroy();chart=null;}
 try{
  const key=metric+"-"+index;
  let data=cache.get(key);
  if(!data){
   const res=await fetch("data/rekordlabor/regional_year/"+key+".json",{signal:AbortSignal.timeout(20000)});
   if(!res.ok)throw Error("HTTP "+res.status);
   data=validate(await res.json(),metric,area);cache.set(key,data);
  }
  if(seq!==serial)return;
  doc=data;
  if(!root.Chart)throw Error("Diagrammbibliothek nicht verfügbar.");
  chart=new root.Chart($("rrYearCanvas"),config(data));
  $("rrYearStatus").textContent=heading(data)+" · Historie bis "+data.historical_end+" · Vergleich "+data.current_year+" · DWD-Archivstand "+data.data_end;
  buttons(true);
 }catch(e){if(seq===serial){doc=null;$("rrYearStatus").textContent="Jahresverlauf nicht verfügbar: "+e.message;}}
}
async function exportImage(pdf){
 const snapshot=doc;if(!snapshot||!root.Chart)return;
 let chartExport;
 try{
  const canvas=document.createElement("canvas");canvas.width=1800;canvas.height=900;
  chartExport=new root.Chart(canvas,config(snapshot,true));
  if(pdf){
   const PDF=root.jspdf?.jsPDF;if(!PDF)throw Error("PDF-Bibliothek nicht verfügbar");
   const out=new PDF({orientation:"landscape",unit:"mm",format:"a4"});
   out.addImage(canvas.toDataURL("image/png"),"PNG",8,18,281,140.5);
   out.save(name(snapshot)+".pdf");
  }else{
   const blob=await new Promise(resolve=>canvas.toBlob(resolve,"image/png"));
   if(!blob)throw Error("PNG-Erstellung fehlgeschlagen");
   save(blob,name(snapshot)+".png");
  }
 }catch(e){$("rrYearStatus").textContent="Export nicht möglich: "+e.message;}
 finally{chartExport?.destroy();}
}
API.open=()=>{
 if(started)return;started=true;
 for(const id of ["rrArea","rrMetric"])$(id).addEventListener("change",()=>void update());
 $("rrYearRetry").addEventListener("click",()=>void update());
 $("rrYearCsv").addEventListener("click",()=>{if(doc)save(new Blob([csvText(doc)],{type:"text/csv;charset=utf-8"}),name(doc)+".csv");});
 $("rrYearPng").addEventListener("click",()=>void exportImage(false));
 $("rrYearPdf").addEventListener("click",()=>void exportImage(true));
 void update();
};
})(typeof window==="undefined"?globalThis:window);
