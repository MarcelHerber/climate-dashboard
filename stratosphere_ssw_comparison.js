/* Event-aligned SSW comparison: ERA5 polar-cap temperature and NASA 60N wind.
   Only verified data, no interpolation or simulated historical profiles. */
(() => {
"use strict";
const $=id=>document.getElementById(id);
const EVENTS=[
 {id:"2010feb",label:"09.02.2010",date:"2010-02-09",season:2009,color:"#2563eb"},
 {id:"2010mar",label:"24.03.2010",date:"2010-03-24",season:2009,color:"#7c3aed"},
 {id:"2018feb",label:"12.02.2018",date:"2018-02-12",season:2017,color:"#059669"},
 {id:"2019jan",label:"02.01.2019",date:"2019-01-02",season:2018,color:"#d97706"}
];
const LEVELS=[10,30,50,100], ROOT="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/stratosphere-data/data/stratosphere/";
const offsets=Array.from({length:81},(_,i)=>i-40);
let archive=null,archiveRows=new Map(),winds=new Map(),loading=false,tempChart=null,windChart=null,currentLevel=10;
const time=s=>Date.parse(s+"T00:00:00Z"), iso=n=>new Date(n).toISOString().slice(0,10);
const shifted=(s,days)=>iso(time(s)+days*86400000);
const fmt=(n,d=1)=>Number.isFinite(n)?n.toLocaleString("de-DE",{maximumFractionDigits:d,minimumFractionDigits:d}):"–";
const observed=(obj,k)=>Number.isFinite(obj?.[k])?obj[k]:null;
function parseNASA(txt){
 const out=new Map();
 for(const line of txt.split(/\r?\n/)){
  const c=line.trim().split(/\s+/);
  if(!/^\d{4}-\d\d-\d\d$/.test(c[0]||"")||c.length<9)continue;
  const lead=c.length>=10?Number(c[9]):0,value=Number(c[1]);
  if(lead===0&&Number.isFinite(value)&&value>-9000)out.set(c[0],value);
 }
 return out;
}
async function fetchNASA(season,level){
 const res=await fetch(ROOT+"u60n_"+level+"_"+season+"_merra2.txt?hour="+Math.floor(Date.now()/3600000),{cache:"no-store"});
 if(!res.ok)throw Error("NASA "+season+" "+level+" hPa HTTP "+res.status);
 return parseNASA(await res.text());
}
async function fetchERA(){
 const base=["era5_stratosphere/index.json","https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/main/era5_stratosphere/index.json"];
 let problem=null;
 for(const url of base){
  try{
   const res=await fetch(url+"?v="+Math.floor(Date.now()/300000),{cache:"no-store"});
   if(!res.ok)throw Error("ERA5 HTTP "+res.status);
   const j=await res.json();
   if(j.schema_version!==1||!Array.isArray(j.series))throw Error("Ungültiger ERA5-Index");
   return j;
  }catch(error){problem=error;}
 }
 throw problem||Error("ERA5 fehlt");
}
function getWind(event,level,offset){
 return winds.get(event.season+"-"+level)?.get(shifted(event.date,offset))??null;
}
function getTemp(event,level,offset){
 const day=shifted(event.date,offset);
 return observed(archiveRows.get(day),"tcap_"+level);
}
function getRef(event,level,offset){
 const day=shifted(event.date,offset),val=archive?.reference?.["tcap_"+level]?.[day.slice(5)]?.mean;
 return Number.isFinite(val)?val:null;
}
function getValue(event,level,offset,kind,mode){
 const value=kind==="temp"?getTemp(event,level,offset):getWind(event,level,offset);
 if(value===null||mode!=="anomaly")return value;
 const ref=kind==="temp"?getRef(event,level,offset):null;
 return ref!==null?value-ref:null;
}
function eventStats(event,level){
 const T0=getTemp(event,level,0),T7=getTemp(event,level,-7),T14=getTemp(event,level,-14);
 const peak=offsets.filter(x=>x>=-14&&x<=14).map(offset=>({offset,value:getTemp(event,level,offset)}))
  .filter(x=>Number.isFinite(x.value)).sort((a,b)=>b.value-a.value)[0]||null;
 const minimum=offsets.filter(x=>x>=-7&&x<=30).map(offset=>({offset,value:getWind(event,level,offset)}))
  .filter(x=>Number.isFinite(x.value)).sort((a,b)=>a.value-b.value)[0]||null;
 return {T0,delta7:T0!==null&&T7!==null?T0-T7:null,
  delta14:T0!==null&&T14!==null?T0-T14:null,peak,minimum,
  ERAcount:offsets.filter(x=>getTemp(event,level,x)!==null).length,
  windCount:offsets.filter(x=>getWind(event,level,x)!==null).length};
}
function selected(){
 const keys=[...document.querySelectorAll(".ssw-compare-event:checked")].map(x=>x.value);
 return EVENTS.filter(e=>keys.includes(e.id));
}
const marker={id:"ssw-central-date",afterDraw(c){
 const axis=c.scales.x,chartArea=c.chartArea;
 if(!axis||!chartArea)return;
 const x=axis.getPixelForValue(40),ctx=c.ctx;
 ctx.save();ctx.strokeStyle="#334155";ctx.setLineDash([4,4]);ctx.lineWidth=1;
 ctx.beginPath();ctx.moveTo(x,chartArea.top);ctx.lineTo(x,chartArea.bottom);ctx.stroke();
 ctx.setLineDash([]);ctx.font="11px Arial";ctx.fillStyle="#475569";ctx.textAlign="center";
 ctx.fillText("Tag 0 · Windumkehr",x,chartArea.top+12);ctx.restore();
}};
function buildChart(id,which,mode,levels){
 const canvas=$(id),data=selected().map(e=>({
  label:e.label+" · "+(e.date.startsWith("2010")?"2010":e.date.slice(0,4)),
  data:offsets.map(d=>getValue(e,levels,d,which,mode)),
  borderColor:e.color,backgroundColor:e.color,borderWidth:2.2,
  borderDash:which==="wind"?[5,3]:[],
  pointRadius:0,pointHoverRadius:3,spanGaps:false,tension:.12
 }));
 const any=data.some(d=>d.data.some(Number.isFinite));
 if(!any){
  $(id==="sswCompareTemp"?"sswCompareTempMissing":"sswCompareWindMissing").textContent=
   which==="temp"?"Für die aktuelle Auswahl liegen noch keine vollständigen echten ERA5-Temperaturen bzw. zulässigen Anomalien vor.":
   "Noch keine zugehörigen NASA-Analysewerte veröffentlicht.";
 }else $(id==="sswCompareTemp"?"sswCompareTempMissing":"sswCompareWindMissing").textContent="";
 const ytext=which==="temp"?(mode==="anomaly"?"Temperaturanomalie [K]":"Polkappentemperatur [°C]"):"Zonalwind 60° N [m/s]";
 return new Chart(canvas,{type:"line",data:{labels:offsets.map(String),datasets:data},
  plugins:[marker],options:{responsive:true,maintainAspectRatio:false,animation:false,
   interaction:{mode:"index",intersect:false},
   plugins:{legend:{position:"bottom",labels:{boxWidth:18}},tooltip:{callbacks:{
    title:items=>"Tag "+offsets[items[0]?.dataIndex]+" relativ zur Windumkehr",
    label:ctx=>ctx.dataset.label+": "+fmt(ctx.parsed.y,2)+(which==="temp"?(mode==="anomaly"?" K":" °C"):" m/s")
   }}},
   scales:{x:{ticks:{autoSkip:false,callback:(value,index)=>offsets[index]%10===0?offsets[index]:"",maxRotation:0},
    title:{display:true,text:"Tage relativ zum Zentraldatum · Tag 0 = Windumkehr"},grid:{display:false}},
    y:{title:{display:true,text:ytext}}}
  }});
}
function addCell(row,value){
 const cell=document.createElement("td");cell.textContent=value;row.appendChild(cell);
}
function render(){
 const level=Number($("sswCompareLevel").value),mode=$("sswCompareMode").value;
 currentLevel=level;
 if(tempChart){tempChart.destroy();tempChart=null;}
 if(windChart){windChart.destroy();windChart=null;}
 if(typeof Chart!=="undefined"){
  tempChart=buildChart("sswCompareTemp","temp",mode,level);
  // Wind remains absolute so the reversal is always evaluated against the physical 0 m/s line.
  windChart=buildChart("sswCompareWind","wind","absolute",level);
 }
 const table=$("sswCompareBody");table.replaceChildren();
 let countT=0,countW=0;
 for(const event of selected()){
  const stats=eventStats(event,level),tr=document.createElement("tr");
  const name=document.createElement("td");name.textContent=event.label;
  name.style.color=event.color;name.style.fontWeight="700";tr.appendChild(name);
  addCell(tr,stats.delta7===null?"–":fmt(stats.delta7,1)+" K");
  addCell(tr,stats.delta14===null?"–":fmt(stats.delta14,1)+" K");
  addCell(tr,stats.peak?fmt(stats.peak.value,1)+" °C (T"+(stats.peak.offset>=0?"+":"")+stats.peak.offset+")":"–");
  addCell(tr,stats.minimum?fmt(stats.minimum.value,1)+" m/s (T"+(stats.minimum.offset>=0?"+":"")+stats.minimum.offset+")":"–");
  addCell(tr,stats.ERAcount+"/81");
  table.appendChild(tr);countT+=stats.ERAcount;countW+=stats.windCount;
 }
 $("sswCompareStatus").textContent="Druckniveau "+level+" hPa · "+countT+" echte ERA5-Temperaturtage und "+countW+
  " NASA-Analysetage über die gewählten Ereignisfenster · keine interpolierten Daten.";
 $("sswCompareCsv").disabled=!selected().length;
}
function saveCsv(){
 if(!selected().length)return;
 const lines=["Ereignis;Zentraldatum;Druckniveau_hPa;Relativer_Tag;Datum_UTC;ERA5_Temperatur_C;ERA5_Anomalie_1991_2020_K;NASA_Wind_m_s;Temperaturaenderung_7_Tage_K;Temperaturaenderung_14_Tage_K"];
 const num=v=>v===null?"":Number(v.toFixed(3));
 for(const event of selected()){
  const level=currentLevel,stats=eventStats(event,level);
  for(const offset of offsets){
   const T=getTemp(event,level,offset),ref=getRef(event,level,offset),w=getWind(event,level,offset);
   lines.push([event.label,event.date,level,offset,shifted(event.date,offset),num(T),
    num(T!==null&&ref!==null?T-ref:null),num(w),
    offset===0?num(stats.delta7):"",offset===0?num(stats.delta14):""].join(";"));
  }
 }
 const blob=new Blob([String.fromCharCode(65279)+lines.join("\r\n")],{type:"text/csv;charset=utf-8"});
 const url=URL.createObjectURL(blob),link=document.createElement("a");
 link.href=url;link.download="SSW_Historischer_Vergleich_"+currentLevel+"hPa.csv";
 document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),3000);
}
async function load(){
 if(loading)return;loading=true;
 $("sswCompareStatus").textContent="Lade historische NASA-Analysen und ERA5-Temperaturen …";
 try{
  const [eraResult,...pairs]=await Promise.allSettled([
   fetchERA(),...Array.from(new Set(EVENTS.map(e=>e.season))).flatMap(season=>
    LEVELS.map(level=>fetchNASA(season,level).then(rows=>({season,level,rows}))))
  ]);
  if(eraResult.status==="fulfilled"){
   archive=eraResult.value;archiveRows=new Map(archive.series.map(x=>[x.date,x]));
  }else{
   $("sswCompareNote").textContent="ERA5-Index nicht erreichbar: keine Temperaturen verfügbar ("+
    (eraResult.reason?.message||"Fehler")+"). NASA-Windreihen bleiben unabhängig nutzbar.";
  }
  for(const p of pairs)if(p.status==="fulfilled"){
   winds.set(p.value.season+"-"+p.value.level,p.value.rows);
  }
  render();
 }catch(error){$("sswCompareStatus").textContent="Ereignisvergleich konnte nicht geladen werden: "+error.message;}
 finally{loading=false;}
}
function mount(){
 const anchor=$("polarTemperatureCard")||$("sswEventsCard");if(!anchor||$("sswCompareCard"))return;
 const style=document.createElement("style");
 style.textContent=".ssw-compare-controls{display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px;margin:12px 0}"+
 ".ssw-compare-controls label{display:flex;flex-direction:column;gap:4px;font-size:13px;font-weight:700;color:#4b5563}"+
 ".ssw-compare-choice{display:flex;flex-wrap:wrap;gap:14px;margin:8px 0 16px;font-size:13px}"+
 ".ssw-compare-choice label{display:inline-flex;align-items:center;gap:5px;cursor:pointer}"+
 ".ssw-compare-frame{height:320px;position:relative;margin:10px 0 7px}"+
 ".ssw-compare-scroll{overflow:auto}"+
 ".ssw-compare-table{border-collapse:collapse;font-size:12px;min-width:650px;width:100%}"+
 ".ssw-compare-table th,.ssw-compare-table td{border-bottom:1px solid #dbe3ed;padding:8px;text-align:left}"+
 ".ssw-compare-table th{background:#eef3f8}"+
 ".ssw-compare-muted{font-size:12px;color:#64748b;margin:5px 0}";
 document.head.appendChild(style);
 const section=document.createElement("section");section.className="card";section.id="sswCompareCard";
 section.innerHTML=[
 '<div class="levels-heading"><div><h2>SSW-Ereignisse im Vergleich · 2010 / 2018 / 2019</h2>',
 '<p>Alle Kurven relativ zum Datum der 10-hPa-Windumkehr (T0). Polkappentemperatur aus ERA5, zonaler Wind aus NASA MERRA-2.</p></div>',
 '<button id="sswCompareCsv" class="btn" type="button" disabled>Vergleich als CSV</button></div>',
 '<div class="ssw-compare-controls"><label>Druckniveau<select id="sswCompareLevel">',
 '<option value="10">10 hPa</option><option value="30">30 hPa</option><option value="50">50 hPa</option><option value="100">100 hPa</option>',
 '</select></label><label>Temperatur<select id="sswCompareMode">',
 '<option value="absolute">Absoluttemperatur (°C)</option><option value="anomaly">Anomalie 1991–2020 (K)</option>',
 '</select></label></div>',
 '<div class="ssw-compare-choice"><label><input class="ssw-compare-event" type="checkbox" value="2010feb" checked>09.02.2010</label>',
 '<label><input class="ssw-compare-event" type="checkbox" value="2010mar">24.03.2010</label>',
 '<label><input class="ssw-compare-event" type="checkbox" value="2018feb" checked>12.02.2018</label>',
 '<label><input class="ssw-compare-event" type="checkbox" value="2019jan" checked>02.01.2019</label></div>',
 '<div id="sswCompareStatus" class="info" role="status">Lade Ereignisdaten …</div>',
 '<h3>Polkappentemperatur 60–90° N · relative Ereignistage</h3>',
 '<div class="ssw-compare-frame"><canvas id="sswCompareTemp"></canvas></div>',
 '<p id="sswCompareTempMissing" class="ssw-compare-muted"></p>',
 '<h3>Zonaler Wind 60° N · gleiche Zeitachse</h3>',
 '<div class="ssw-compare-frame"><canvas id="sswCompareWind"></canvas></div>',
 '<p id="sswCompareWindMissing" class="ssw-compare-muted"></p>',
 '<h3>Temperaturanstieg und Windminimum</h3>',
 '<div class="ssw-compare-scroll"><table class="ssw-compare-table"><thead><tr>',
 '<th>SSW-Zentraldatum</th><th>Erwärmung −7 bis T0</th><th>Erwärmung −14 bis T0</th>',
 '<th>Maximum T−14 bis T+14</th><th>Windminimum T−7 bis T+30</th><th>ERA5-Tage</th>',
 '</tr></thead><tbody id="sswCompareBody"></tbody></table></div>',
 '<p id="sswCompareNote" class="ssw-compare-muted">Fehlende historische ERA5-Temperaturen erscheinen als Lücken. Änderungen sind nur aus zwei exakt datierten Originalwerten berechnet. Der Wind ist bei der Anomaliewahl weiterhin absolut, damit 0 m/s die reale Windumkehr markiert. Die SSW-Zentraldaten sind windbasiert und keine ursächliche Aussage.</p>',
 '<p class="source">Quellen: ERA5 Copernicus Climate Data Store und NASA Ozone Watch/MERRA-2. Historische SSW-Zentraldaten: windbasierte Ereignisdefinition nach Charlton–Polvani.</p>'
 ].join("");
 anchor.insertAdjacentElement("afterend",section);
 $("sswCompareLevel").addEventListener("change",render);
 $("sswCompareMode").addEventListener("change",render);
 $("sswCompareCsv").addEventListener("click",saveCsv);
 for(const el of document.querySelectorAll(".ssw-compare-event"))el.addEventListener("change",render);
 load();
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",mount,{once:true});else mount();
})();