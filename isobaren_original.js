(()=>{"use strict";
const ROOT="data/synoptic_charts/";
const $=id=>document.getElementById(id);
const slots=["panel0","panel1","panel2","panel3"];
const INITIAL=["dwd","aemet","noaa_opc","eccc"];
let catalog=null;
const isoDE=s=>{const d=new Date(s);return Number.isFinite(d.getTime())?new Intl.DateTimeFormat("de-DE",{day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit",timeZone:"UTC",hourCycle:"h23"}).format(d)+" UTC":"–";};
const node=(tag,cls,txt)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(txt!==undefined)n.textContent=txt;return n;};
const source=id=>catalog?.sources?.find(s=>s.id===id);
const sourceList=()=>catalog?.sources||[];
const cardsAt=(id,time)=>(catalog?.charts||[]).filter(x=>x.source_id===id&&x.valid_utc===time);
function fillSources(){
 const cat=$("sourceCatalog");cat.replaceChildren();
 for(const s of sourceList()){
  const box=node("article","source"),title=node("strong","",s.name+" · "+s.country);
  box.append(title,node("p","",s.type==="auto"?"Automatischer Originalkarten-Abruf":"Quellenseite – Bild nicht automatisch einbindbar"));
  const count=(catalog.charts||[]).filter(x=>x.source_id===s.id).length;
  box.append(node("p","",s.type==="auto"?count+" geprüfte Karten · "+(catalog.source_status?.[s.id]?.state==="available"?"verfügbar":"Quelle derzeit nicht verfügbar"):s.license));
  const a=node("a","",s.type==="auto"?"Originalangebot öffnen":"Karten beim Wetterdienst öffnen");
  a.href=s.url;a.target="_blank";a.rel="noopener noreferrer";box.append(a);cat.append(box);
 }
}
function fillPickers(){
 const single=$("singleSource");
 single.replaceChildren();
 for(const s of sourceList()){const option=new Option(s.name+" · "+s.country,s.id);single.add(option);}
 single.value="dwd";
 for(let i=0;i<4;i++){
  const select=$(slots[i]);select.replaceChildren();
  for(const s of sourceList())select.add(new Option(s.name,s.id));
  select.value=INITIAL[i];
 }
 const sel=$("validTime");sel.replaceChildren();
 const times=catalog.time_slots||[];
 if(!times.length){sel.add(new Option("Noch keine verifizierten Termine",""));return;}
 const now=Date.now();
 for(const time of times.slice().reverse()){
  const available=new Set(catalog.charts.filter(x=>x.valid_utc===time).map(x=>x.source_id));
  sel.add(new Option(isoDE(time)+" · "+available.size+" Quellen",time));
 }
 // Prefer the nearest available valid time, not the most distant forecast.
 const dwd=times.filter(t=>catalog.charts.some(r=>r.valid_utc===t&&r.source_id==="dwd"));
 const nearest=(dwd.length?dwd:times).slice().sort((a,b)=>Math.abs(Date.parse(a)-now)-Math.abs(Date.parse(b)-now))[0];
 sel.value=nearest;
}
function closestForSources(ids){
 const times=catalog?.time_slots||[];
 if(!times.length)return;
 let now=Date.now();
 const best=times.slice().sort((a,b)=>{
   const count=t=>ids.filter(id=>cardsAt(id,t).length>0).length;
   return (count(b)-count(a))||(Math.abs(Date.parse(a)-now)-Math.abs(Date.parse(b)-now));
 })[0];
 if(best)$("validTime").value=best;
}
function currentProviders(){
 return $("chartMode").value==="four"?slots.map(id=>$(id).value):[$("singleSource").value];
}
function card(provider,time){
 const s=source(provider);
 const record=cardsAt(provider,time)[0];
 const article=node("article","chart");
 const heading=node("div","chart-header");
 heading.append(node("strong","",s?s.name:"Unbekannte Quelle"));
 heading.append(node("small","",record?record.kind+" · "+isoDE(record.valid_utc):"Für diesen Termin nicht vorhanden"));
 article.append(heading);
 const content=node("div","chart-body");
 if(record){
  const img=node("img");
  img.src=ROOT+record.image;
  img.alt=s.name+" Originalkarte · "+record.kind+" · gültig "+isoDE(record.valid_utc);
  img.loading="lazy";
  img.onerror=()=>{content.replaceChildren(node("div","empty","Originalbild derzeit nicht erreichbar."));};
  content.append(img);
 }else{
  const empty=node("div","empty");
  empty.append(node("strong","",s?.type==="external"?"Keine Einbettungsfreigabe":"Kein zeitgleiches Kartenbild"));
  empty.append(node("span","",s?.type==="external"?"Diese Quelle ist ausschließlich über ihre offizielle Website erreichbar.":"Für genau diesen UTC-Termin wurde keine überprüfbare Originalkarte publiziert."));
  content.append(empty);
 }
 article.append(content);
 const footer=node("div","chart-footer");
 footer.append(node("span","",record?record.credit:"Keine Karte für "+isoDE(time)));
 if(s){
  const link=node("a","",record?"Originalquelle":"Beim Wetterdienst ansehen");
  link.href=record?.source_page||s.url;
  link.target="_blank";link.rel="noopener noreferrer";footer.append(link);
 }
 article.append(footer);
 return article;
}
function refreshView(){
 const isFour=$("chartMode").value==="four";
 $("singleSourceWrap").hidden=isFour;$("fourSelectors").hidden=!isFour;
 const grid=$("chartGrid");grid.classList.toggle("four",isFour);grid.replaceChildren();
 const validity=$("validTime").value;
 if(!catalog||!validity){
  grid.append(node("div","empty","Keine geprüften Wetterkarten veröffentlicht."));
  $("exportPng").disabled=true;return;
 }
 const ids=currentProviders();
 let matched=0;
 for(const id of ids){if(cardsAt(id,validity).length)matched++;grid.append(card(id,validity));}
 const total=ids.length;
 $("exportPng").disabled=matched===0;
 const stale=(Date.now()-Date.parse(catalog.generated_utc))/3600000;
 const qualifier=stale>36?" · zuletzt vor "+Math.round(stale)+" Stunden aktualisiert":"";
 $("chartStatus").textContent=isoDE(validity)+" · "+matched+"/"+total+
  " ausgewählte Quellen mit exakt passender UTC-Gültigkeit"+qualifier;
 $("syncHint").textContent=isFour?matched===4?
  "Alle vier Karten besitzen exakt dieselbe Gültigkeitszeit. Die Originalprojektionen können sich unterscheiden.":
  "Der Vierer-Vergleich ist vorbereitet: "+matched+" von vier Plätzen sind mit zeitgleichen Karten belegt. Andere Kacheln bleiben ehrlich leer.":
  matched?"Originalkarte des gewählten Wetterdienstes für den ausgewiesenen UTC-Termin.":"Für diesen Dienst liegt zum gewählten Termin keine automatisch einbettbare Karte vor.";
}
async function pngExport(){
 const validity=$("validTime").value;
 const ids=currentProviders(),four=ids.length===4;
 const W=four?1640:1180,H=four?1320:1010;
 const canvas=document.createElement("canvas");canvas.width=W;canvas.height=H;
 const ctx=canvas.getContext("2d");if(!ctx)return;
 ctx.fillStyle="#fff";ctx.fillRect(0,0,W,H);
 ctx.fillStyle="#172e46";ctx.font="bold 32px Arial";ctx.fillText("Isobaren & Fronten · Originalkarten",35,55);
 ctx.fillStyle="#455f79";ctx.font="19px Arial";ctx.fillText("Gültig: "+isoDE(validity)+" · identische UTC-Gültigkeit",35,87);
 const pad=24,top=118,cellW=(W-pad*3)/(four?2:1),cellH=(H-top-72-pad*(four?2:1))/(four?2:1);
 let loaded=0;
 for(let i=0;i<ids.length;i++){
  const x=pad+(i%(four?2:1))*(cellW+pad),y=top+Math.floor(i/(four?2:1))*(cellH+pad);
  ctx.fillStyle="#f6f8fa";ctx.fillRect(x,y,cellW,cellH);
  ctx.strokeStyle="#cfdae4";ctx.strokeRect(x,y,cellW,cellH);
  const provider=source(ids[i]),record=cardsAt(ids[i],validity)[0];
  ctx.fillStyle="#18364f";ctx.font="bold 21px Arial";ctx.fillText(provider?.name||ids[i],x+15,y+28);
  ctx.fillStyle="#556c7e";ctx.font="14px Arial";ctx.fillText(record?record.kind+" · "+record.credit:"Kein zeitgleiches Bild / Originalseite öffnen",x+15,y+51);
  if(!record)continue;
  try{
   const img=new Image();
   img.src=ROOT+record.image;
   await img.decode();
   const maxW=cellW-24,maxH=cellH-82,scale=Math.min(maxW/img.naturalWidth,maxH/img.naturalHeight);
   const ww=img.naturalWidth*scale,hh=img.naturalHeight*scale;
   ctx.drawImage(img,x+(cellW-ww)/2,y+60+(maxH-hh)/2,ww,hh);loaded++;
  }catch(e){ctx.fillText("Originalbild nicht erreichbar",x+20,y+86);}
 }
 if(!loaded)return;
 ctx.font="14px Arial";ctx.fillStyle="#5a7083";
 ctx.fillText("Quellen: DWD / AEMET / NOAA-NWS · eigene Zusammenstellung, keine gemeinsame amtliche Karte",32,H-34);
 const a=document.createElement("a");
 a.download="Synoptik_Originalkarten_"+validity.slice(0,16).replace(/[-:]/g,"")+(four?"_4er":"")+".png";
 a.href=canvas.toDataURL("image/png");document.body.append(a);a.click();a.remove();
}
async function load(){
 $("chartStatus").textContent="Lade veröffentlichte Originalkarten …";
 try{
  const resp=await fetch(ROOT+"index.json?v="+Date.now(),{cache:"no-store"});
  if(!resp.ok)throw new Error("Kartenindex noch nicht veröffentlicht (HTTP "+resp.status+")");
  const data=await resp.json();
  if(data.schema_version!==1||!data.ready||!Array.isArray(data.charts)||
     !Array.isArray(data.sources)||!Array.isArray(data.time_slots))throw new Error("Quellenindex ungültig");
  for(const rec of data.charts){
   if(!/^(?:dwd|aemet|noaa_opc)$/.test(rec.source_id)||!/^images\/[a-z0-9_]+\.webp$/.test(rec.image))throw new Error("Ungültige Bildreferenz");
   if(Number.isNaN(Date.parse(rec.valid_utc)))throw new Error("Ungültiger Gültigkeitstermin");
  }
  catalog=data;fillSources();fillPickers();refreshView();
 }catch(err){
  catalog=null;$("chartStatus").textContent=err.message;
  $("chartGrid").replaceChildren(node("div","empty","Der erste verifizierte Kartenabruf steht noch aus. Die übrigen Seiten bleiben nutzbar."));
  $("exportPng").disabled=true;
  $("sourceCatalog").replaceChildren();
  for(const s of [
   ["DWD", "https://opendata.dwd.de/weather/charts/analysis/"],
   ["AEMET","https://www.aemet.es/es/eltiempo/prediccion/mapa_frentes"],
   ["Met Office","https://weather.metoffice.gov.uk/maps-and-charts/surface-pressure"],
   ["ČHMÚ","https://www.chmi.cz/predpoved-pocasi/synopticka-situace"],
   ["Met Éireann","https://www.met.ie/latest-reports/surface-analysis"],
   ["IMO","https://en.vedur.is/weather/shipping/atlantic/"],
   ["NOAA OPC","https://ocean.weather.gov/Atl_tab.php"],
   ["ECCC","https://weather.gc.ca/analysis/index_e.html"]]){
   const card=node("div","source"),a=node("a","",s[0]+" · Originalseite");
   a.href=s[1];a.target="_blank";a.rel="noopener noreferrer";card.append(a);
   $("sourceCatalog").append(card);
  }
 }
}
function init(){
 $("reload").addEventListener("click",load);
 $("chartMode").addEventListener("change",()=>{if(catalog)closestForSources(currentProviders());refreshView();});
 $("validTime").addEventListener("change",refreshView);
 $("singleSource").addEventListener("change",()=>{if(catalog)closestForSources(currentProviders());refreshView();});
 slots.forEach(id=>$(id).addEventListener("change",refreshView));
 $("exportPng").addEventListener("click",pngExport);
 load();
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();