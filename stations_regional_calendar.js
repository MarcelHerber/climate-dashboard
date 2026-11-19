/* Regional DWD record calendar. Archive is deliberately separate from Pages;
   immutable commit pins station indices and daily shards to the same version. */
(function(root){
"use strict";
const BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/c74e76375cb7d96ea6011824a3f41b8a2197d8d8/data/rekordlabor/regional_calendar/";
const PARTS=["1750-1900","1901-1920","1921-1940","1941-1960","1961-1980","1981-1990","1991-2000","2001-2010","2011-2020","2021-2026"];
function partitions(first,last){return PARTS.filter(p=>{const [a,b]=p.split("-").map(Number);return a<=last&&b>=first;});}
function rank(parts,{area,metric,md,first,last}){
 const rows=[];
 let dir;
 for(const {manifest:m,day} of parts){
  const spec=m.metrics[metric];
  if(!spec||!m.areas.includes(area)||m.top_k_per_year<50||m.value_scale!==.1)throw Error("Inkompatibles DWD-Archiv");
  if(dir&&dir!==spec.direction)throw Error("Uneinheitliche Rangrichtung");
  dir=spec.direction;
  for(const [year,metrics] of day){
   if(year<first||year>last||(md==="02-29"&&!(year%4===0&&(year%100!==0||year%400===0))))continue;
   for(const [value,index,preliminary] of metrics[metric]?.[area]||[]){
    const station=m.stations[index];
    if(!station||!Number.isFinite(value))throw Error("Ungültige Station oder Messwert im Archiv");
    rows.push({value:value/10,date:year+"-"+md,station,preliminary:!!preliminary});
   }
  }
 }
 rows.sort((a,b)=>(dir==="asc"?a.value-b.value:b.value-a.value)||a.date.localeCompare(b.date)||a.station.id.localeCompare(b.station.id)||a.station.key.localeCompare(b.station.key));
 return rows.slice(0,50).map((r,i)=>({...r,rank:i+1}));
}
const API={rank,partitions,located};
if(typeof module==="object"&&module.exports){module.exports=API;return;}
root.RegionalRecordCalendar=API;
const METRICS={
 tnk_high:["Höchstes Tmin","°C"],txk_low:["Niedrigstes Tmax","°C"],
 tmk_high:["Höchstes Tagesmittel","°C"],tmk_low:["Niedrigstes Tagesmittel","°C"],
 amplitude_high:["Größte Tagesamplitude","K"],rs_high:["Höchster Tagesniederschlag","mm"],
 fx_high:["Stärkste Tageswindböe","km/h"],sdk_high:["Längste Sonnenscheindauer","h"]
};
const AREAS=["Deutschland","Baden-Württemberg","Bayern","Berlin","Brandenburg","Bremen","Hamburg","Hessen","Mecklenburg-Vorpommern","Niedersachsen","Nordrhein-Westfalen","Rheinland-Pfalz","Saarland","Sachsen","Sachsen-Anhalt","Schleswig-Holstein","Thüringen"];
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const format=n=>Number(n).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1});
const dateLabel=md=>new Date("2000-"+md+"T12:00:00Z").toLocaleDateString("de-DE",{day:"numeric",month:"long",timeZone:"UTC"});
const dateFmt=iso=>iso.split("-").reverse().join(".");
const cache=new Map(),manifests=new Map();
let basemap,opened=false,serial=0,current=null;
async function request(url){
 const res=await fetch(url,{signal:AbortSignal.timeout(45000)});
 if(!res.ok)throw Error("HTTP "+res.status+" · "+url.split("/").slice(-2).join("/"));
 return res;
}
function memo(map,key,fn){
 if(!map.has(key)){
  const promise=fn().catch(e=>{map.delete(key);throw e;});
  map.set(key,promise);
 }
 return map.get(key);
}
function loadPart(part,md){
 return memo(cache,part+"/"+md,async()=>{
  const manifest=await memo(manifests,part,async()=>await (await request(BASE+part+"/manifest.json")).json());
  const info=manifest.files[md];
  if(!info)throw Error("Kalendertag im Archiv nicht vorhanden: "+part);
  const bytes=await (await request(BASE+part+"/"+md+".json.gz")).arrayBuffer();
  if(bytes.byteLength!==info.bytes)throw Error("Unvollständige Archivdatei: "+part);
  if(root.crypto?.subtle){
   const hash=Array.from(new Uint8Array(await root.crypto.subtle.digest("SHA-256",bytes)),v=>v.toString(16).padStart(2,"0")).join("");
   if(hash!==info.sha256)throw Error("Prüfsumme stimmt nicht: "+part);
  }
  const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  const day=await new Response(stream).json();
  if(!Array.isArray(day))throw Error("Ungültige Tagesdatei: "+part);
  return {manifest,day};
 });
}
// Keep at most two selected days in memory; manifests remain cached.
function trimCache(md){
 const days=[...new Set([...cache.keys()].map(k=>k.split("/")[1]))].filter(d=>d!==md);
 while(days.length>1){const old=days.shift();for(const key of cache.keys())if(key.endsWith("/"+old))cache.delete(key);}
}
function loadMap(){
 if(!basemap)basemap=request("wettergefahren_basemap_50m.json").then(r=>r.json()).catch(e=>{basemap=null;throw e;});
 return basemap;
}
function option(select,value,label){select.add(new Option(label,value));}
function init(){
 for(let i=0;i<366;i++){
  const md=new Date(Date.UTC(2000,0,i+1)).toISOString().slice(5,10);
  option($("rrDay"),md,dateLabel(md));
 }
 const today=new Date();$("rrDay").value=(today.getMonth()+1+"").padStart(2,"0")+"-"+String(today.getDate()).padStart(2,"0");
 for(const a of AREAS)option($("rrArea"),a,a);
 for(const [k,[label,unit]] of Object.entries(METRICS))option($("rrMetric"),k,label+" ("+unit+")");
 $("rrForm").addEventListener("submit",e=>{e.preventDefault();void load();});
 for(const id of ["rrDay","rrArea","rrMetric","rrFirst","rrLast"])$(id).addEventListener("change",()=>{
  serial++;current=null;$("rrResults").hidden=true;
  $("rrStatus").textContent="Auswahl geändert. Mit „Top 50 anzeigen“ laden.";
 });
 $("rrCsv").addEventListener("click",csv);
 $("rrPng").addEventListener("click",()=>void exportImage(false));
 $("rrPdf").addEventListener("click",()=>void exportImage(true));
}
API.open=()=>{if(!opened){opened=true;init();void load();}};
async function load(){
 const token=++serial;current=null;$("rrResults").hidden=true;
 const q={area:$("rrArea").value,metric:$("rrMetric").value,md:$("rrDay").value,first:Number($("rrFirst").value),last:Number($("rrLast").value)};
 if(!Number.isInteger(q.first)||!Number.isInteger(q.last)||q.first<1750||q.last>2026||q.first>q.last){
  $("rrStatus").textContent="Bitte einen gültigen Zeitraum von 1750 bis 2026 wählen.";return;
 }
 const parts=partitions(q.first,q.last);
 $("rrStatus").textContent="Lade "+parts.length+" DWD-Archivabschnitte …";
 try{
  const data=await Promise.all(parts.map(p=>loadPart(p,q.md)));
  if(token!==serial)return;
  trimCache(q.md);
  const rows=rank(data,q);
  let geo=null;try{geo=await loadMap();}catch(e){/* ranking remains usable without base map */}
  if(token!==serial)return;
  current={q,rows,geo};
  render();
 }catch(e){
  if(token!==serial)return;
  $("rrStatus").textContent="Keine vollständige Rangliste verfügbar. "+e.message+" · Bitte erneut laden.";
 }
}
function label(q){return METRICS[q.metric][0]+" · "+q.area+" · "+dateLabel(q.md);}
function range(q){return q.first+"–"+q.last+" · DWD CDC · Top 50";}
function showDetails(rankNumber){
 const r=current?.rows.find(x=>x.rank===rankNumber);if(!r)return;
 const unit=METRICS[current.q.metric][1];
 $("rrDetail").textContent="Rang "+r.rank+" · "+r.station.name+" ("+r.station.id+") · "+dateFmt(r.date)+" · "+format(r.value)+" "+unit+" · "+r.station.state+" · "+(r.preliminary?"vorläufig":"historisch");
 for(const el of document.querySelectorAll("#rrResults [data-rank]"))el.classList.toggle("rr-active",(el.dataset.ranks||el.dataset.rank).split(",").map(Number).includes(rankNumber));
 const row=$("rrTable").querySelector('tr[data-rank="'+rankNumber+'"]');
 if(row){const container=$("rrTable").closest(".rr-table");const top=row.offsetTop-container.scrollTop;if(top<0||top>container.clientHeight-row.offsetHeight)container.scrollTop=row.offsetTop-container.clientHeight/2;}
}
const colors=["#a71930","#df6133","#34618c"];
function color(rank){return rank<=5?colors[0]:rank<=15?colors[1]:colors[2];}
function located(r){
 const s=r.station;
 return !!s.from&&!!s.to&&s.from<=r.date&&s.to>=r.date&&Number.isFinite(s.lon)&&Number.isFinite(s.lat)&&s.lon>=5.3&&s.lon<=15.7&&s.lat>=46.9&&s.lat<=55.3;
}
function mapSvg(data){
 const {q,rows,geo}=data;
 const project=(lon,lat)=>[48+(lon-5.3)*48,100+(55.3-lat)*73];
 const poly=geo.countries.filter(c=>c.p.some(p=>p.some(r=>r.some(([x,y])=>x>=4&&x<=17&&y>=46&&y<=57))));
 const paths=poly.map(c=>'<path d="'+c.p.map(p=>p.map(r=>r.map(([x,y],i)=>(i?"L":"M")+project(x,y).map(v=>v.toFixed(1)).join(" ")).join(" ")+"Z").join(" ")).join(" ")+'" fill="'+(c.n==="Germany"?"#fdfdf7":"#e5e9e8")+'" stroke="#8395a0" stroke-width="0.85" fill-rule="evenodd"/>').join("");
 const groups=new Map();
 for(const r of rows){
  const {lon,lat}=r.station;
  if(!located(r))continue;
  const key=lon.toFixed(4)+"/"+lat.toFixed(4);
  if(!groups.has(key))groups.set(key,[]);groups.get(key).push(r);
 }
 const points=[...groups.values()].reverse().map(list=>{
  const r=list[0], [x,y]=project(r.station.lon,r.station.lat);
  const detail=list.map(r=>"#"+r.rank+" "+r.station.name+" · "+dateFmt(r.date)+" · "+format(r.value)+" "+METRICS[q.metric][1]).join(" | ");
  return '<g><circle cx="'+x+'" cy="'+y+'" r="'+(list.length>1?9:7)+'" fill="'+color(r.rank)+'" stroke="#fff" stroke-width="1.4" data-rank="'+r.rank+'" data-ranks="'+list.map(x=>x.rank).join(",")+'" tabindex="0" role="button" aria-label="'+esc(detail)+'"><title>'+esc(detail)+'</title></circle><text x="'+x+'" y="'+(y+2.8)+'" font-size="8" font-weight="bold" fill="white" text-anchor="middle" pointer-events="none">'+(list.length>1?list.length:r.rank)+'</text></g>';
 }).join("");
 const legend=colors.map((c,i)=>'<circle cx="'+(48+i*185)+'" cy="765" r="6" fill="'+c+'"/><text x="'+(60+i*185)+'" y="769" font-size="12" fill="#264456">'+["Rang 1–5","Rang 6–15","Rang 16–50"][i]+'</text>').join("");
 return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 590 812" role="img" aria-label="'+esc(label(q))+'" font-family="Arial,sans-serif"><rect width="590" height="812" fill="#f6fafc"/><text x="20" y="27" font-size="17" font-weight="bold" fill="#17364f">'+esc(METRICS[q.metric][0])+'</text><text x="20" y="48" font-size="14" fill="#17364f">'+esc(q.area+" · "+dateLabel(q.md))+'</text><text x="20" y="66" font-size="11" fill="#45647d">'+esc(range(q))+'</text><defs><clipPath id="rrClip"><rect x="20" y="82" width="550" height="662" rx="3"/></clipPath></defs><rect x="20" y="82" width="550" height="662" fill="#dcebf2"/><g clip-path="url(#rrClip)">'+paths+points+'</g>'+legend+'<text x="20" y="788" font-size="10" fill="#45647d">Mehrere Treffer je Standort: Anzahl im Punkt · Quelle DWD CDC</text><text x="20" y="802" font-size="10" fill="#45647d">Kartengrundlage: Natural Earth 1:50m · Klimadashboard Deutschland</text></svg>';
}
function render(){
 const {q,rows,geo}=current,unit=METRICS[q.metric][1];
 $("rrStatus").textContent=rows.length?label(q)+" · "+q.first+"–"+q.last+" · "+rows.length+" Messungen.":label(q)+" · Keine gültigen Messwerte im gewählten Zeitraum.";
 $("rrResults").hidden=false;
 $("rrKpis").innerHTML=rows.length?[
  [format(rows[0].value)+" "+unit,"Rang 1 · "+rows[0].station.name],
  [String(new Set(rows.map(r=>r.date.slice(0,4))).size),"Jahre in den Top 50"],
  [String(rows.filter(r=>r.preliminary).length),"Vorläufige Messungen"]
 ].map(([a,b])=>'<div class="rl-kpi"><strong>'+esc(a)+'</strong><small>'+esc(b)+'</small></div>').join(""):"";
 $("rrTable").innerHTML=rows.map(r=>'<tr data-rank="'+r.rank+'"><td><button type="button" data-rank="'+r.rank+'">'+r.rank+'</button></td><td>'+dateFmt(r.date)+'</td><td>'+esc(r.station.name)+' <small>('+esc(r.station.id)+')</small></td><td><strong>'+format(r.value)+' '+unit+'</strong></td><td>'+(r.preliminary?"Vorläufig":"Historisch")+'</td></tr>').join("");
 $("rrDetail").textContent="Kartenpunkt oder Tabellenrang auswählen.";
 $("rrMap").innerHTML=geo&&rows.length?mapSvg(current):"";
 const unmapped=rows.filter(r=>!located(r)).length;
 $("rrMapNote").textContent=geo?"Nummerierte Punkte markieren historisch zugeordnete DWD-Koordinaten. Mehrere Messungen am selben Standort sind zusammengefasst."+(unmapped?" "+unmapped+" Ranglistenwerte ohne zeitlich passenden Standort bleiben in der Tabelle erhalten.":""):"Kartengrundlage nicht verfügbar; Tabelle und CSV bleiben nutzbar.";
 for(const el of $("rrMap").querySelectorAll("[data-rank]")){
  const select=()=>{const ranks=el.dataset.ranks.split(",").map(Number);showDetails(ranks[0]);if(ranks.length>1){
   $("rrDetail").append(document.createTextNode(" · Weitere Ränge an diesem Standort: "));
   for(const r of ranks.slice(1)){const b=document.createElement("button");b.type="button";b.textContent="#"+r;b.addEventListener("click",()=>showDetails(r));$("rrDetail").append(b);}
  }};
  el.addEventListener("click",select);el.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();select();}});
 }
 for(const b of $("rrTable").querySelectorAll("button"))b.addEventListener("click",()=>showDetails(Number(b.dataset.rank)));
 $("rrCsv").disabled=!rows.length;$("rrPng").disabled=$("rrPdf").disabled=!rows.length||!geo;
}
function filename(q){return "rekordkalender_"+q.area+"_"+q.metric+"_"+q.md+"_"+q.first+"-"+q.last;}
function save(blob,name){const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);}
function csv(){
 if(!current?.rows.length)return;
 const {q,rows}=current,quote=v=>'"'+String(v??"").replace(/"/g,'""')+'"';
 const data=[["Rang","Datum","Gebiet","Rekordart","Messwert ("+METRICS[q.metric][1]+")","DWD-ID","Station","Bundesland","Archivstandort Höhe (m)","Archivstandort Breite","Archivstandort Länge","Standort gültig von","Standort gültig bis","Historisch verortet","Archiv"],...rows.map(r=>[r.rank,r.date,q.area,METRICS[q.metric][0],format(r.value),r.station.id,r.station.name,r.station.state,r.station.height,r.station.lat,r.station.lon,r.station.from,r.station.to,located(r)?"Ja":"Nein",r.preliminary?"Vorläufig":"Historisch"])];
 save(new Blob(["\ufeff"+data.map(r=>r.map(quote).join(";")).join("\r\n")],{type:"text/csv;charset=utf-8"}),filename(q)+".csv");
}
async function exportImage(asPdf){
 const data=current;if(!data?.geo||!data.rows.length)return;
 try{
  const svg=mapSvg(data),url=URL.createObjectURL(new Blob([svg],{type:"image/svg+xml;charset=utf-8"}));
  const image=new Image();image.src=url;
  try{await image.decode();}finally{URL.revokeObjectURL(url);}
  const canvas=document.createElement("canvas");canvas.width=1770;canvas.height=2436;
  canvas.getContext("2d").drawImage(image,0,0,canvas.width,canvas.height);
  const file=filename(data.q);
  if(!asPdf){canvas.toBlob(b=>{if(b)save(b,file+".png");},"image/png");return;}
  const PDF=root.jspdf?.jsPDF;if(!PDF)throw Error("PDF-Bibliothek nicht geladen");
  const pdf=new PDF({orientation:"portrait",unit:"mm",format:"a4"});
  pdf.addImage(canvas.toDataURL("image/png"),"PNG",8,8,194,267);
  const {q,rows}=data;
  for(let offset=0;offset<rows.length;offset+=35){
   pdf.addPage();pdf.setFontSize(13);pdf.text(label(q).slice(0,95),10,13);pdf.setFontSize(9);pdf.text(range(q),10,20);
   pdf.setFontSize(8);pdf.text("Rang   Datum                 Station (DWD-ID)                                         Wert                Archiv",10,29);
   rows.slice(offset,offset+35).forEach((r,i)=>{
    const y=36+i*7;
    pdf.text(String(r.rank),10,y);pdf.text(dateFmt(r.date),22,y);pdf.text((r.station.name+" ("+r.station.id+")").slice(0,45),48,y);
    pdf.text(format(r.value)+" "+METRICS[q.metric][1],145,y);pdf.text(r.preliminary?"Vorläufig":"Historisch",175,y);
   });
  }
  pdf.save(file+".pdf");
 }catch(e){$("rrStatus").textContent="Export nicht möglich: "+e.message;}
}
})(typeof window==="undefined"?globalThis:window);
