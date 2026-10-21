(()=>{"use strict";
const ROOT="data/synoptic_charts/";
/* Nur vom Dashboard bereits geprüfte und lokal veröffentlichte Bilddateien.
   Fremde Direkt-URLs werden NICHT ungeprüft eingebettet. */
const PERMITTED=new Set(["dwd","aemet","chmi","knmi","imo","noaa_opc","noaa_full","noaa_west","noaa_24","noaa_48","noaa_96","noaa_pace","noaa_pacw","noaa_pacfull","noaa_pac24","noaa_pac48","noaa_pac96"]);
const EUROPE=new Set(["dwd","aemet","chmi","knmi","imo","noaa_opc","noaa_full","noaa_west","noaa_24","noaa_48","noaa_96"]);
const names={dwd:"DWD · Europa",aemet:"AEMET · Europa",chmi:"ČHMÚ · Europa",knmi:"KNMI · Europa",imo:"IMO · Nordatlantik",noaa_opc:"NOAA · Ostatlantik",noaa_full:"NOAA · Gesamtatlantik",noaa_west:"NOAA · Westatlantik",noaa_24:"NOAA · Atlantik +24 h",noaa_48:"NOAA · Atlantik +48 h",noaa_96:"NOAA · Atlantik +96 h",noaa_pace:"NOAA · Nordostpazifik",noaa_pacw:"NOAA · Nordwestpazifik",noaa_pacfull:"NOAA · Nordpazifik 0 h",noaa_pac24:"NOAA · Pazifik +24 h",noaa_pac48:"NOAA · Pazifik +48 h",noaa_pac96:"NOAA · Pazifik +96 h"};
const stamp=x=>{if(!x)return "–";const d=new Date(x);return Number.isFinite(d.getTime())?new Intl.DateTimeFormat("de-DE",{timeZone:"UTC",day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(d)+" UTC":"–"};
const element=(tag,cls,text)=>{const x=document.createElement(tag);if(cls)x.className=cls;if(text!==undefined)x.textContent=text;return x};
const safeHref=s=>typeof s==="string"&&/^https:\/\/[a-z0-9.-]+\//i.test(s)?s:null;
const safeRecord=rec=>rec&&PERMITTED.has(rec.source_id)&&
 typeof rec.image==="string"&&/^images\/[a-z0-9_]+\.webp$/.test(rec.image)&&
 Number.isFinite(Date.parse(rec.valid_utc))&&
 (rec.kind==="Analyse"||rec.kind==="Prognose"||rec.kind==="0-h-Bodenkarte");
const compare=(a,b)=>Date.parse(b.issued_utc||b.run_utc||b.valid_utc)-Date.parse(a.issued_utc||a.run_utc||a.valid_utc)||
 Date.parse(b.valid_utc)-Date.parse(a.valid_utc);
const identity=x=>x.source_id+"|"+x.kind+"|"+(x.forecast_hours??"0");
function init(root){
 const scope=root.dataset.scope||"world";
 const grid=root.querySelector(".sg-grid"),message=root.querySelector(".sg-status");
 const picker=root.querySelector(".sg-source"),type=root.querySelector(".sg-type"),mode=root.querySelector(".sg-mode");
 const refresh=root.querySelector(".sg-refresh"),columns=root.querySelector(".sg-columns"),
       fullscreen=root.querySelector(".sg-fullscreen");
 let records=[],indexTime=null,sourceInfo=new Map();
 const publisher=id=>sourceInfo.get(id)?.publisher_id||(id.startsWith("noaa_")?"noaa":id);
 const imageRank=x=>({Analyse:3,"0-h-Bodenkarte":2,Prognose:1}[x.kind]||0);
 function latestBy(key,list){
  const map=new Map();
  for(const rec of list){const k=key(rec),prior=map.get(k);
    if(!prior||imageRank(rec)>imageRank(prior)||
      (imageRank(rec)===imageRank(prior)&&compare(rec,prior)<0))map.set(k,rec);
  }
  return [...map.values()];
 }
 function setColumns(){
  if(columns)root.style.setProperty("--sg-columns",columns.value==="auto"?"repeat(auto-fit,minmax(min(100%,340px),1fr))":"repeat("+columns.value+",minmax(0,1fr))");
 }
 function toggleFullscreen(){
  if(document.fullscreenElement===root){document.exitFullscreen?.();return;}
  if(root.requestFullscreen)root.requestFullscreen().catch(()=>{root.classList.toggle("sg-pseudo-fullscreen");});
  else root.classList.toggle("sg-pseudo-fullscreen");
 }
 function refreshOptions(){
  const previous=picker.value;
  const ids=[...new Set(records.map(x=>x.source_id))].sort((a,b)=>(names[a]||a).localeCompare(names[b]||b,"de"));
  picker.replaceChildren(new Option("Alle verfügbaren Kartenquellen",""));
  for(const id of ids)picker.add(new Option(names[id]||id,id));
  if(ids.includes(previous))picker.value=previous;
 }
 function choose(){
  let set=records.filter(x=>(!picker.value||x.source_id===picker.value)&&
   (!type.value||(type.value==="analysis"?(x.kind==="Analyse"||x.kind==="0-h-Bodenkarte"):x.kind==="Prognose")));
  if(mode.value==="latest"){
   const map=new Map();
   for(const rec of set){const k=identity(rec),prior=map.get(k);if(!prior||compare(rec,prior)<0)map.set(k,rec);}
   set=[...map.values()];
  } else if(mode.value==="publishers"){
   set=latestBy(x=>publisher(x.source_id),set);
  }
  return set.sort((a,b)=>{const A=names[a.source_id]||a.source_id,B=names[b.source_id]||b.source_id;return A.localeCompare(B,"de")||((a.forecast_hours||0)-(b.forecast_hours||0))||compare(a,b)});
 }
 function show(){
  grid.replaceChildren();
  const set=choose();
  const until=indexTime?Date.now()-Date.parse(indexTime)>12*3600e3:false;
  message.textContent=set.length+" Originalkarten direkt im gemeinsamen Panel · "+[...new Set(set.map(x=>publisher(x.source_id)))].length+" unabhängige Wetterdienste · "+[...new Set(set.map(x=>x.source_id))].length+" Kartenprodukte · "+
   (mode.value==="latest"?"neuester Stand je Kartenprodukt":mode.value==="publishers"?"eine Karte je Wetterdienst":"alle archivierten Bildstände")+
    (indexTime?" · Kartenindex: "+stamp(indexTime):"")+(until?" · Achtung: Datenindex älter als 12 Stunden":"")+
    " · unterschiedliche UTC-Zeiten sind erlaubt (kein Zeitvergleich).";
  if(!set.length){grid.append(element("p","sg-empty","Keine freigegebene Originalkarte entspricht den Filtern. Weitere Wetterdienste unten als externe Links."));return;}
  for(const rec of set){
   const card=element("article","sg-card");
   const top=element("div","sg-card-head");
   const h=element("strong","sg-name",names[rec.source_id]||rec.source_id);
   const tag=element("span","sg-kind",(rec.kind==="Prognose"?"Prognose":"Bodenanalyse")+
    (rec.forecast_hours&&rec.kind==="Prognose"?" +"+rec.forecast_hours+" h":""));
   top.append(h,tag);
   const imageLink=element("a","sg-image-link");
   imageLink.href=ROOT+rec.image;imageLink.target="_blank";imageLink.rel="noopener noreferrer";imageLink.title="Originalkarte in voller Auflösung öffnen";
   const img=element("img","sg-image");img.loading="lazy";img.decoding="async";
   img.src=ROOT+rec.image;
   img.alt=(names[rec.source_id]||rec.source_id)+" · "+rec.kind+" · gültig "+stamp(rec.valid_utc);
   img.addEventListener("error",()=>{img.remove();imageLink.append(element("p","sg-image-fallback","Originalbild derzeit nicht ladbar – bitte beim Wetterdienst öffnen."));});
   imageLink.append(img);
   const body=element("div","sg-card-details");
   body.append(element("div","sg-time","Gültig: "+stamp(rec.valid_utc)));
   if(rec.run_utc)body.append(element("div","sg-small","Modelllauf: "+stamp(rec.run_utc)));
   if(rec.issued_utc)body.append(element("div","sg-small","Herausgegeben: "+stamp(rec.issued_utc)));
   body.append(element("div","sg-credit",rec.credit||"Amtliche Originalquelle"));
   const srcLicense=sourceInfo.get(rec.source_id)?.license;
   if(srcLicense)body.append(element("div","sg-license",srcLicense));
   const links=element("div","sg-links");
   const original=safeHref(rec.source_page)||safeHref(rec.source_url);
   if(original){const a=element("a","","Zum Wetterdienst ↗");a.href=original;a.target="_blank";a.rel="noopener noreferrer";links.append(a);}
   const download=element("a","","Bild öffnen ↗");download.href=ROOT+rec.image;download.target="_blank";download.rel="noopener noreferrer";links.append(download);
   if(safeHref(rec.license_url)){const lic=element("a","","Lizenz ↗");lic.href=rec.license_url;lic.target="_blank";lic.rel="noopener noreferrer";links.append(lic);}
   body.append(links);card.append(top,imageLink,body);grid.append(card);
  }
 }
 async function load(){
  message.textContent="Prüfe veröffentlichte Bilder und Nutzungsrechte …";refresh.disabled=true;
  try{
   const res=await fetch(ROOT+"index.json?v="+Date.now(),{cache:"no-store"});
   if(!res.ok)throw Error("HTTP "+res.status);
   const data=await res.json();
   if(data.schema_version!==1||data.ready!==true||!Array.isArray(data.charts)||!Array.isArray(data.sources))throw Error("Ungültiges Datenformat");
   const sources=new Map(data.sources.filter(x=>x&&x.type==="auto").map(x=>[x.id,x]));
   sourceInfo=sources;
   records=data.charts.filter(x=>safeRecord(x)&&sources.has(x.source_id)&&
    (scope!=="europe"||EUROPE.has(x.source_id))&&
    (safeHref(x.source_page)||safeHref(x.source_url)));
   indexTime=data.generated_utc;
   refreshOptions();show();
  }catch(e){records=[];indexTime=null;grid.replaceChildren();message.textContent="Kartenindex konnte nicht geladen werden ("+e.message+"). Die offiziellen Quellen sind unten weiter verlinkt.";}
  finally{refresh.disabled=false}
 }
 for(const control of [picker,type,mode])control.addEventListener("change",show);
 if(columns){columns.addEventListener("change",setColumns);setColumns();}
 if(fullscreen)fullscreen.addEventListener("click",toggleFullscreen);
 document.addEventListener("fullscreenchange",()=>{
  if(fullscreen)fullscreen.textContent=document.fullscreenElement===root?"Vollbild schließen":"Panel im Vollbild";
 });
 refresh.addEventListener("click",load);
 load();
}
for(const root of document.querySelectorAll("[data-synoptic-gallery]"))init(root);
})();