/* Official EUMETSAT WMS only. No fabricated timestamps or MTG-I2 live stream. */
(() => {
"use strict";
const API="https://view.eumetsat.int/geoserver/wms";
const PRODUCTS={
 geocolour:{layer:"mtg_fd:rgb_geocolour",name:"GeoColour",url:"https://view.eumetsat.int/productviewer/productDetails/mtg_fd%3Argb_geocolour",credit:"© EUMETSAT · GeoColour: NASA-Hintergrund"},
 dust:{layer:"mtg_fd:rgb_dust",name:"Dust RGB",url:"https://view.eumetsat.int/productviewer/productDetails/mtg_fd%3Argb_dust",credit:"© EUMETSAT"},
 cloudtype:{layer:"mtg_fd:rgb_cloudtype",name:"Cloud Type RGB",url:"https://view.eumetsat.int/productviewer/productDetails/mtg_fd%3Argb_cloudtype",credit:"© EUMETSAT"},
 ir105:{layer:"mtg_fd:ir105_hrfi",name:"IR 10,5 µm (HRFI)",url:"https://view.eumetsat.int/productviewer/productDetails/mtg_fd%3Air105_hrfi",credit:"© EUMETSAT"},
 firetemperature:{layer:"mtg_fd:rgb_firetemperature",name:"Fire Temperature RGB",url:"https://view.eumetsat.int/productviewer/productDetails/mtg_fd%3Argb_firetemperature",credit:"© EUMETSAT"}
};
const REGIONS={
 europe:{name:"Europa und Nordafrika",bbox:[-27,24,49,73],w:1300,h:850},
 atlantic:{name:"Nordatlantik & Europa",bbox:[-70,15,35,75],w:1400,h:850},
 southwest:{name:"Südwesteuropa · Azoren & Kanaren",bbox:[-37,24,19,53],w:1200,h:620},
 central:{name:"Mitteleuropa",bbox:[-2,43,25,58],w:1300,h:780},
 germany:{name:"Deutschland",bbox:[5,47,16,56],w:1140,h:950},
 disk:{name:"Erdscheibe",bbox:[-6500000,-6500000,6500000,6500000],w:1400,h:1400}
};
const id=x=>document.getElementById(x);
const source=id("satSource"),product=id("satProduct"),region=id("satRegion"),time=id("satTime"),image=id("satImage"),empty=id("satEmpty"),status=id("satStatus");
const prev=id("satPrev"),next=id("satNext"),play=id("satPlay"),png=id("satPng");
const gif=id("satGif"),mp4=id("satMp4");
const timeline=id("satTimeline"),timelineLabel=id("satTimelineLabel"),filmImage=id("satFilmStage");
const filmLength=id("satFilmLength"),filmQuality=id("satFilmQuality"),filmSpeed=id("satFilmSpeed");
const filmProgress=id("satFilmProgress"),filmProgressLabel=id("satFilmProgressLabel"),filmProgressWrap=id("satFilmProgressWrap");
let frames=[],index=-1,frameTimer=null,token=0,imageRequest=0,currentUrl="",loaded=false,verified=false,abort=null,metadataSource="";
let filmGeneration=0,filmLoading=false,filmPlaying=false,filmItems=[],filmPosition=0;
let stillTimeout=null,exportBusy=false,cachedImage=null;
const exporters=window.SatelliteFilmExport;
const description=()=>PRODUCTS[product.value];
function setStatus(message,kind="info"){status.textContent=message;status.dataset.kind=kind;}
function updateTimeline(){
 timeline.max=String(Math.max(0,frames.length-1));
 timeline.disabled=!frames.length||source.value!=="mtgi1";
 timeline.value=String(Math.max(0,index));
 timelineLabel.textContent=frames[index]?formatUTC(frames[index]):"Keine Beobachtungen";
}
function stop(reset=true){
 if(frameTimer!==null){clearTimeout(frameTimer);frameTimer=null;}
 if(stillTimeout!==null){clearTimeout(stillTimeout);stillTimeout=null;}
 filmPlaying=false;
 if(reset){
  filmGeneration++;filmLoading=false;filmItems=[];filmPosition=0;
  filmImage.hidden=true;filmImage.replaceChildren();
  filmProgressWrap.hidden=true;
  if(source.value==="mtgi1")image.hidden=false;
 }
 play.textContent=reset?"▶ Film starten":"▶ Fortsetzen";
 play.setAttribute("aria-label",reset?"Satellitenfilm starten":"Satellitenfilm fortsetzen");
 buttons();
}
function buttons(){
 const ready=source.value==="mtgi1"&&frames.length>1;
 prev.disabled=!ready||index<=0;
 next.disabled=!ready||index>=frames.length-1;
 play.disabled=!ready||index<1||exportBusy;
 gif.disabled=filmItems.length<2||source.value!=="mtgi1"||filmLoading||exportBusy;
 mp4.disabled=filmItems.length<2||source.value!=="mtgi1"||filmLoading||exportBusy||!exporters?.supportsMP4();
 mp4.title=exporters?.supportsMP4()?"Echten MP4/H.264-Film herunterladen":"MP4/H.264 in diesem Browser nicht unterstützt";
 time.disabled=!frames.length||source.value!=="mtgi1";
 png.disabled=!loaded||source.value!=="mtgi1";
 updateTimeline();
}
function formatUTC(t){return new Intl.DateTimeFormat("de-DE",{timeZone:"UTC",day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"}).format(new Date(t))+" UTC";}
function imageUrl(t,previewWidth=0){const layer=description(),r=REGIONS[region.value];
 const w=previewWidth?Math.min(previewWidth,r.w):r.w;
 const h=previewWidth?Math.max(1,Math.round(r.h*w/r.w)):r.h;
 const params=new URLSearchParams({service:"WMS",version:"1.1.1",request:"GetMap",layers:layer.layer,styles:"",format:"image/png",transparent:"false",srs:region.value==="disk"?"AUTO:97004,9001,0,0":"EPSG:4326",bbox:r.bbox.join(","),width:String(w),height:String(h),bgcolor:"0x000000"});
 if(t)params.set("time",t);
 return API+"?"+params.toString();
}
function drawFrame(t, fallbackDepth=0, requestedTime=t){
 const seq=token,req=++imageRequest;
 if(stillTimeout!==null){clearTimeout(stillTimeout);stillTimeout=null;}
 loaded=false;verified=Boolean(t);cachedImage=null;
 empty.hidden=true;image.hidden=false;
 const p=description(),r=REGIONS[region.value];
 image.alt=p.name+" – "+r.name+(t?", "+formatUTC(t):", Zeitpunkt nicht überprüft");
 id("satMapTitle").textContent=p.name+" · "+r.name;
 id("satValid").textContent=t?"Beobachtung: "+formatUTC(t):"Beobachtungszeit: nicht überprüft";
 window.SatelliteIsobars?.sync({time:t,region:region.value,source:source.value});
 const projection=region.value==="disk"?"AUTO:97004 (geostationär)":"EPSG:4326";
 const note=t?"WMS · "+projection+" · UTC aus GetCapabilities":"WMS · "+projection+" · serverseitiger Standardzeitpunkt, nicht als live bestätigt";
 id("satImageInfo").textContent=note;
 // Display light previews first. Only the explicit raw-image/PNG action requests full resolution.
 // Keep geographic bounds and the verified UTC unchanged across size retries.
 const widths=[400,320];
 const fullUrl=imageUrl(t);
 let level=0;
 const current=()=>seq===token&&req===imageRequest;
 async function showCached(reason){
  try{
   const response=await fetch("./data/satellite_cache/index.json",{cache:"no-store"});
   if(!response.ok||!current())return false;
   const doc=await response.json();
   const item=doc.schema===1?doc.entries?.[product.value]?.[region.value]:null;
   const timestamp=Date.parse(item?.time);
   const age=Date.now()-timestamp;
   const path="./data/satellite_cache/"+product.value+"_"+region.value+"_"+
    (typeof item?.time==="string"?item.time.replace(/[-:]/g,""):"")+".png";
   if(!item||!Number.isFinite(timestamp)||age<0||age>7*86400000||
      (requestedTime&&timestamp>Date.parse(requestedTime))||
      !/^\d{8}T\d{6}Z$/.test(item.time.replace(/[-:]/g,""))||
      item.url!==path||item.source!=="EUMETSAT WMS"||item.width!==400)return false;
   if(!current())return false;
   setStatus("Der EUMETSAT-WMS ist gestört ("+reason+"). Lade gespeicherte Aufnahme vom "+formatUTC(item.time)+" …","warning");
   return await new Promise(resolve=>{
    let settled=false;
    const finish=success=>{
     if(settled)return;
     settled=true;clearTimeout(timer);resolve(success);
    };
    const timer=setTimeout(()=>{image.onload=null;image.onerror=null;finish(false);},8000);
    image.onload=()=>{
     if(!current()){finish(false);return;}
     cachedImage={time:item.time,url:path};
     loaded=true;verified=true;empty.hidden=true;image.hidden=false;
     currentUrl=path;id("satRawImage").href=path;id("satRawImage").hidden=false;
     id("satRawImage").textContent="Gespeichertes Archivbild öffnen ↗";
     id("satValid").textContent="Archivaufnahme: "+formatUTC(item.time)+" · nicht live";
     id("satImageInfo").textContent="Gespeicherter EUMETSAT-WMS-Abruf · "+image.naturalWidth+" px · UTC geprüft · kein Livestream";
     image.alt=description().name+" – gespeicherte Satellitenaufnahme "+formatUTC(item.time);
     window.SatelliteIsobars?.sync({time:item.time,region:region.value,source:source.value});
     buttons();
     setStatus("EUMETSAT vorübergehend gestört: gespeicherte "+description().name+"-Aufnahme vom "+formatUTC(item.time)+". Nicht aktuell. PNG verwendet die Archivauflösung.","warning");
     finish(true);
    };
    image.onerror=()=>finish(false);
    image.src=path;
   });
  }catch(_){return false;}
 }
 function fail(reason){
  if(!current()||!filmImage.hidden)return;
  if(stillTimeout!==null){clearTimeout(stillTimeout);stillTimeout=null;}
  // HTTP image errors are usually upstream 500/504, not a size problem.
  // Only a real timeout justifies one smaller retry.
  if(level+1<widths.length&&reason.startsWith("Timeout")){
   level++;
   setStatus("EUMETSAT-Bild "+(level===1?"lädt zu langsam":"nicht verfügbar")+
     " ("+reason+"). Versuche dieselbe Aufnahme mit "+widths[level]+" px …","warning");
   attempt();return;
  }
  // Try at most two earlier WMS-advertised observations; never relabel their timestamps.
  const previous=t?frames.indexOf(t)-1:-1;
  if(previous>=0&&fallbackDepth<1){
   index=previous;time.value=String(index);
   drawFrame(frames[index],fallbackDepth+1,requestedTime);
   setStatus("EUMETSAT-Bild für "+formatUTC(t)+" nicht erreichbar ("+reason+"). Versuche die ältere Aufnahme vom "+formatUTC(frames[index])+" …","warning");
   return;
  }
  // Keep the most recent *successfully downloaded* same-product image first.
  // Only after that fails, switch explicitly to an alternative product.
  void showCached(reason).then(archived=>{
   if(archived||!current())return;
   if(product.value!=="ir105"&&source.value==="mtgi1"){
    const unavailable=description().name;
    product.value="ir105";
    stop();
    refresh();
    setStatus(unavailable+" ist beim EUMETSAT-WMS nicht erreichbar ("+reason+"). Kein geeignetes Archivbild vorhanden; versuche IR 10,5 µm als ausdrücklich anderes Produkt …","warning");
    return;
   }
   loaded=false;image.hidden=true;empty.hidden=false;
   id("satValid").textContent="Kein Satellitenbild · unabhängige ECMWF-Modellprognose";
   window.SatelliteIsobars?.sync({time:null,region:region.value,source:source.value});
   empty.textContent="Weder aktuelle EUMETSAT-Aufnahmen noch ein geprüftes Archivbild verfügbar. Die ECMWF-Isobaren können unabhängig angezeigt werden.";
   buttons();
   setStatus("EUMETSAT-WMS derzeit nicht erreichbar ("+reason+"). Kein geeignetes Archivbild vorhanden.","error");
  });
 }
 function attempt(){
  if(!current()||!filmImage.hidden)return;
  const url=imageUrl(t,widths[level]);
  currentUrl=fullUrl;
  id("satRawImage").href=fullUrl;id("satRawImage").hidden=false;
  id("satRawImage").textContent="Originalbild beim Anbieter öffnen ↗";
  const size=widths[level]||r.w;
  image.onload=()=>{
   if(!current())return;
   if(stillTimeout!==null){clearTimeout(stillTimeout);stillTimeout=null;}
   loaded=true;empty.hidden=true;image.hidden=!filmImage.hidden;
   id("satImageInfo").textContent=note+(level?" · Ersatzbild "+image.naturalWidth+" px":"");
   buttons();
   if(!filmImage.hidden)return;
   if(level||fallbackDepth)setStatus("Bild für "+(t?formatUTC(t):"unbekannte Zeit")+" in "+image.naturalWidth+
     " px geladen"+(fallbackDepth?" · ältere bestätigte Aufnahme":" · reduzierte Vorschau")+". Originalauflösung über Bildlink oder PNG-Download.","warning");
   else if(t)setStatus("Vorschau für "+formatUTC(t)+" geladen ("+image.naturalWidth+" px) · Originalauflösung über Bildlink oder PNG-Download · Zeit aus "+
       (metadataSource==="manifest"?"WMS-Zeitliste im GitHub-Datenstatus":"WMS-Metadaten")+".","info");
   else setStatus("Einzelbild geladen. Der Aufnahmezeitpunkt ist noch nicht verifiziert; keine Live-Behauptung.","warning");
  };
  image.onerror=()=>fail("Bildfehler");
  image.src=url;
  stillTimeout=setTimeout(()=>fail("Timeout bei "+size+" px"),level===0?6500:4000);
  buttons();
 }
 attempt();
}
function parseTimes(text){
 if(!text)return [];
 const values=new Set(),now=Date.now()+600000;
 const add=value=>{const date=new Date(value);if(!Number.isFinite(date.getTime()))return;if(date.getTime()>now)return;values.add(date.toISOString().replace(".000Z","Z"));};
 const parts=text.trim().split(",").map(x=>x.trim()).filter(Boolean);
 for(const part of parts){
  if(part.includes("/")){
   const seg=part.split("/"),start=Date.parse(seg[0]),end=Date.parse(seg[1]);
   const duration=(seg[2]||"").match(/^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/);
   if(!duration||!Number.isFinite(start)||!Number.isFinite(end))continue;
   const ms=((Number(duration[1]||0)*60+Number(duration[2]||0))*60+Number(duration[3]||0))*1000;
   if(ms<30000||end<start)continue;
   for(let j=0;j<72;j++){const ts=end-j*ms;if(ts<start||ts>now)continue;add(new Date(ts).toISOString());}
  }else add(part);
 }
 return [...values].sort().slice(-48);
}
function layerTimes(xml,layerName){
 const doc=new DOMParser().parseFromString(xml,"application/xml");
 if(doc.querySelector("parsererror"))return [];
 const layers=[...doc.getElementsByTagName("*")].filter(n=>n.localName==="Layer");
 const selected=layers.find(n=>[...n.children].some(c=>c.localName==="Name"&&c.textContent.trim()===layerName));
 if(!selected)return [];
 // WMS 1.1.1 often has an empty <Dimension> declaration followed by
 // a populated <Extent name="time">; time can also be inherited.
 let current=selected;
 while(current&&current.localName==="Layer"){
  const candidates=[...current.children].filter(c=>(c.localName==="Dimension"||c.localName==="Extent")&&(c.getAttribute("name")||"").toLowerCase()==="time"&&c.textContent.trim());
  if(candidates.length)return parseTimes(candidates[0].textContent);
  current=current.parentElement;
 }
 return [];
}
function fillTimes(){time.replaceChildren();if(!frames.length){const o=new Option("Keine verifizierten UTC-Zeiten","");time.add(o);index=-1;buttons();return;}
 frames.forEach((t,i)=>time.add(new Option(formatUTC(t),String(i))));
 index=frames.length-1;time.value=String(index);buttons();
}
async function manifestFallback(mine,reason){
 try{
  const result=await fetch("./data/satellite_wms_times.json",{cache:"no-store"});
  if(!result.ok)throw new Error("Statusdatei HTTP "+result.status);
  const doc=await result.json();
  if(mine!==token)return;
  const age=Date.now()-Date.parse(doc.generated_at),layer=doc.products?.[product.value];
  if(!Number.isFinite(age)||age<0||age>4*60*60*1000)throw new Error("Statusdatei fehlt oder ist älter als 4 Stunden");
  if(!doc.capabilities_ok||!layer?.map_ok||!layer.latest_verified_time||!Array.isArray(layer.available_times))throw new Error("Keine überprüften PNG-Aufnahmen für dieses Produkt");
  const times=layer.available_times.filter(t=>Number.isFinite(Date.parse(t))&&Date.parse(t)<=Date.now()+600000);
  if(!times.includes(layer.latest_verified_time))throw new Error("Abgleich zwischen Zeitstempel und Bildprüfung fehlt");
  frames=[...new Set(times)].sort().slice(-48);
  if(!frames.length)throw new Error("Keine bestätigten Zeitpunkte");
  metadataSource="manifest";fillTimes();drawFrame(frames[index]);
  const lastAge=Date.now()-Date.parse(layer.latest_verified_time);
  if(lastAge>90*60000)setStatus("Letzter geprüfter Satellitenzeitpunkt liegt "+Math.round(lastAge/60000)+" Minuten zurück (nicht aktuell). "+reason,"warning");
  else setStatus("UTC-Zeiten aus dem GitHub-WMS-Livetest übernommen; Bild wird geladen. "+reason,"info");
 }catch(error){
  if(mine!==token)return;
  setStatus(reason+" Kein brauchbarer GitHub-WMS-Status verfügbar ("+error.message+"). Versuche ein Einzelbild ohne verifizierte Zeit; Animation deaktiviert.","warning");
  drawFrame(null);
 }
}
// Fast start: the small GitHub Pages manifest contains *actual WMS-advertised*
// observation times. Its map_ok flag is a separate completed-image probe.
// Never wait for the multi-megabyte EUMETSAT GetCapabilities before showing a map.
async function tryFastManifest(mine){
 const request=new AbortController();
 const timer=setTimeout(()=>request.abort(),2500);
 try{
  const response=await fetch("./data/satellite_wms_times.json",{signal:request.signal,cache:"no-store"});
  if(!response.ok)throw Error("HTTP "+response.status);
  const doc=await response.json();
  if(mine!==token)return true;
  const age=Date.now()-Date.parse(doc.generated_at);
  const layer=doc.products?.[product.value];
  if(!doc.capabilities_ok||!Number.isFinite(age)||age<0||age>3*3600000||
     !Array.isArray(layer?.available_times)||layer.available_times.length<1)return false;
  const values=layer.available_times.filter(x=>Number.isFinite(Date.parse(x))&&Date.parse(x)<=Date.now()+600000);
  frames=[...new Set(values)].sort().slice(-48);
  if(!frames.length)return false;
  metadataSource="manifest";
  fillTimes();
  drawFrame(frames[index]);
  const confirmed=Boolean(layer.map_ok&&layer.latest_verified_time===frames[index]);
  setStatus(confirmed
    ?"Zeitachse direkt aus dem letzten erfolgreichen WMS-Bildcheck geladen. Lade Satellitenvorschau …"
    :"Zeitachse aus der echten WMS-Liste geladen. Bildabruf noch nicht bestätigt …",
    confirmed?"info":"warning");
  return true;
 }catch(_){return false;}
 finally{clearTimeout(timer);}
}
async function refresh(){
 stop();token++;const mine=token;abort?.abort();const controller=new AbortController();abort=controller;frames=[];index=-1;loaded=false;metadataSource="";fillTimes();
 id("satOfficial").href=source.value==="mtgi2"?"https://www.esa.int/articles/about-us/directorates/earth-observation-programmes/meteorological-missions/meteosat-third-generation/mtg-i2-weather-satellite-delivers-first-images":description().url;
 id("satOfficial").textContent=source.value==="mtgi2"?"MTG-I2-Erstbilder bei ESA öffnen ↗":"Produkt bei EUMETView öffnen ↗";
 product.disabled=source.value==="mtgi2";region.disabled=source.value==="mtgi2";id("satAttribution").textContent=source.value==="mtgi2"?"ESA · erste MTG-I2-Aufnahmen":description().credit;
 if(source.value==="mtgi2"){
  window.SatelliteIsobars?.sync({time:null,region:region.value,source:source.value});
  id("satRawImage").hidden=true;
  image.hidden=true;empty.hidden=false;empty.textContent="MTG-I2: erste Aufnahmen und die 2,5-Minuten-Animation sind über den ESA-Link abrufbar. Noch keine reguläre Livequelle.";
  id("satMapTitle").textContent="MTG-I2 · Erstaufnahmen (November 2026)";
  id("satValid").textContent="Kein Livestream";id("satImageInfo").textContent="ESA-Erstbilder · keine laufend aktualisierte Datenquelle";
  setStatus("MTG-I2 befindet sich noch in Kalibrierung und Validierung. Bitte die ESA-Erstbilder öffnen.","warning");buttons();return;
 }
 empty.textContent="Keine Satellitenaufnahme geladen. Über den offiziellen EUMETView-Link kannst du die Bilder direkt öffnen.";
 setStatus("Lade EUMETSAT-Bild; prüfe verfügbare UTC-Zeitpunkte …");
 // Avoid a concurrent unverified GetMap request while fetching WMS timestamps.
 image.hidden=true;empty.hidden=false;
 empty.textContent="Lade verfügbare UTC-Aufnahmen aus dem lokalen Status …";
 if(await tryFastManifest(mine))return;
 if(mine!==token)return;
 setStatus("Lokale WMS-Zeitliste fehlt oder ist veraltet. Prüfe EUMETSAT direkt …","warning");
 empty.textContent="EUMETSAT-Zeitpunkte werden direkt überprüft …";
 const caps=API+"?"+new URLSearchParams({service:"WMS",version:"1.1.1",request:"GetCapabilities"}).toString();
 const timeout=setTimeout(()=>controller.abort(),8000);
 try{
  const response=await fetch(caps,{signal:controller.signal,mode:"cors",cache:"no-store"});
  if(!response.ok)throw new Error("HTTP "+response.status);
  const xml=await response.text();if(mine!==token)return;
  const available=layerTimes(xml,description().layer);
  if(!available.length){await manifestFallback(mine,"Der WMS-Dienst meldet im Browser keine verwertbaren Zeitpunkte.");return;}
  metadataSource="live";frames=available;fillTimes();drawFrame(frames[index]);
 }catch(e){if(mine!==token)return;await manifestFallback(mine,"WMS-Metadaten im Browser derzeit nicht lesbar (möglicherweise CORS).");}
 finally{clearTimeout(timeout);}
}
function show(i){
 if(i<0||i>=frames.length)return;
 index=i;time.value=String(index);
 drawFrame(frames[index]);buttons();
}
function previewAttempt(t,width,ordinal){
 return new Promise(resolve=>{
  const im=new Image();im.crossOrigin="anonymous";im.decoding="async";let complete=false;
  const finish=reason=>{
   if(complete)return;
   complete=true;clearTimeout(timeout);im.onload=null;im.onerror=null;
   if(reason!=="ok")im.src="";
   resolve(reason==="ok"?{item:{time:t,img:im,index:ordinal},reason}:{item:null,reason});
  };
  const timeout=setTimeout(()=>finish("timeout"),6500);
  im.onload=()=>finish(im.naturalWidth>0?"ok":"error");
  im.onerror=()=>finish("error");
  im.src=imageUrl(t,width);
 });
}
async function loadedPreview(t,width,ordinal){
 const first=await previewAttempt(t,width,ordinal);
 if(first.item)return first.item;
 // If a small WMS image is rejected quickly, try an even smaller one
 // instead of the former 720px fallback that amplified server work.
 if(first.reason==="error"&&(width===480||width===320)){
  const fallback=await previewAttempt(t,width===480?320:240,ordinal);
  return fallback.item;
 }
 return null;
}
function showFilmFrame(){
 const item=filmItems[filmPosition];if(!item)return;
 index=item.index;
 time.value=String(index);
 currentUrl=imageUrl(item.time);
 id("satRawImage").href=currentUrl;id("satRawImage").hidden=false;
 loaded=true;verified=true;
 filmImage.replaceChildren(item.img);
 filmImage.setAttribute("aria-label",description().name+" · Filmvorschau · "+formatUTC(item.time));
 filmImage.hidden=false;image.hidden=true;empty.hidden=true;
 id("satMapTitle").textContent=description().name+" · "+REGIONS[region.value].name;
 id("satValid").textContent="Beobachtung: "+formatUTC(item.time);
 window.SatelliteIsobars?.sync({time:item.time,region:region.value,source:source.value});
 id("satImageInfo").textContent="Vorgeladener Film · "+item.img.naturalWidth+" px · UTC aus geprüften WMS-Metadaten; PNG in voller Auflösung";
 setStatus("Satellitenfilm · Bild "+(filmPosition+1)+" von "+filmItems.length+" · "+formatUTC(item.time),"info");
 buttons();
}
function filmTick(){
 if(!filmPlaying||filmItems.length<2)return;
 filmPosition=(filmPosition+1)%filmItems.length;
 showFilmFrame();
 frameTimer=setTimeout(filmTick,Number(filmSpeed.value));
}
function playReady(){
 if(filmItems.length<2)return;
 filmPlaying=true;
 play.textContent="Ⅱ Pause";play.setAttribute("aria-label","Satellitenfilm pausieren");
 showFilmFrame();
 frameTimer=setTimeout(filmTick,Number(filmSpeed.value));
}
async function prepareFilm(){
 if(filmLoading||frames.length<2)return;
 stop();
 // Starting a film cancels an unfinished single-frame WMS request before
 // the two preview workers start; otherwise three maps load concurrently.
 if(!loaded){
  imageRequest++;
  image.onload=null;image.onerror=null;
  image.removeAttribute("src");
  image.hidden=true;
  empty.hidden=false;
  empty.textContent="Vorladen der Satellitenfilm-Aufnahmen …";
 }
 filmLoading=true;
 const generation=filmGeneration;
 const maxCount=Math.min(frames.length,Math.max(2,Number(filmLength.value)||8));
 // The current UTC selection is the END of the film, not its start.
 // For example 36 frames at 10-minute intervals show about six hours.
 const last=Math.max(0,index);
 const start=Math.max(0,last-maxCount+1);
 const clip=frames.slice(start,last+1);
 const size=Number(filmQuality.value)||480;
 const results=new Array(clip.length);
 let cursor=0,completed=0;
 filmProgressWrap.hidden=false;
 filmProgress.max=clip.length;filmProgress.value=0;
 filmProgressLabel.textContent="Lade 0 von "+clip.length+" verkleinerten Bildern …";
 play.textContent="✕ Laden abbrechen";play.setAttribute("aria-label","Filmladen abbrechen");
 setStatus("Lade kompakte Filmbilder (maximal zwei gleichzeitige Anfragen). Eine noch laufende Einzelbild-Anfrage wird dafür beendet.","info");
 const worker=async()=>{
  while(cursor<clip.length&&generation===filmGeneration){
   const i=cursor++;
   const result=await loadedPreview(clip[i],size,frames.indexOf(clip[i]));
   if(generation!==filmGeneration)return;
   results[i]=result;
   completed++;
   filmProgress.value=completed;
   filmProgressLabel.textContent="Vorgeladen: "+completed+" / "+clip.length+" · "+results.filter(Boolean).length+" verwendbar";
  }
 };
 await Promise.all([worker(),worker()]);
 if(generation!==filmGeneration)return;
 filmLoading=false;
 filmItems=results.filter(Boolean);
 filmProgressLabel.textContent=filmItems.length+" von "+clip.length+" Filmbildern bereit ("+size+" px"+(filmItems.some(item=>item.img.naturalWidth<size)?", einzelne Bilder nochmals reduziert":"")+")";
 if(filmItems.length<2){
  play.textContent="▶ Erneut versuchen";
  setStatus("Für den Film konnten nicht mindestens zwei Satellitenbilder geladen werden. Bitte kleinere Filmlänge wählen oder erneut versuchen.","warning");
  return;
 }
 filmPosition=0;
 playReady();
}
function startPause(){
 if(filmLoading){
  stop();setStatus("Filmladen abgebrochen; Einzelbildansicht bleibt verfügbar.","warning");return;
 }
 if(filmPlaying){
  stop(false);setStatus("Filmvorschau pausiert. Mit „Fortsetzen“ wird kein Bild erneut heruntergeladen.","info");return;
 }
 if(filmItems.length>=2){playReady();return;}
 prepareFilm();
}
async function exportFilm(format){
 if(exportBusy||filmLoading||filmItems.length<2||!exporters)return;
 if(format==="mp4"&&!exporters.supportsMP4()){
  setStatus("Dieser Browser bietet keinen echten MP4/H.264-Encoder. GIF ist weiterhin verfügbar.","warning");
  return;
 }
 if(filmPlaying)stop(false);
 const images=filmItems.slice();
 const opt={
  frames:images,
  width:format==="gif"?Math.min(480,Number(filmQuality.value)||320):Math.min(720,Number(filmQuality.value)||480),
  delayMs:Number(filmSpeed.value)||750,
  product:product.value,productName:description().name,
  region:region.value,credit:description().credit,
  progress:(done,total)=>setStatus((format==="gif"?"GIF":"MP4")+"-Export · Bild "+done+"/"+total+" · "+formatUTC(images[Math.min(done-1,images.length-1)].time),"info")
 };
 exportBusy=true;buttons();
 setStatus("Erzeuge "+format.toUpperCase()+" aus "+images.length+" bereits vorgeladenen Satellitenbildern …","info");
 try{
  const result=format==="gif"?await exporters.exportGIF(opt):await exporters.exportMP4(opt);
  const bytes=exporters.download(result);
  setStatus(format.toUpperCase()+"-Film gespeichert: "+images.length+" bestätigte UTC-Zeitpunkte · "+
    (bytes/1048576).toFixed(1)+" MB · "+result.name,"info");
 }catch(error){
  setStatus("Filmexport nicht möglich: "+(error?.message||error)+
   ". Bitte erneut starten; der Anbieter muss Bilddaten mit CORS freigeben.","error");
 }finally{exportBusy=false;buttons();}
}
async function downloadPNG(){
 if(!loaded||!currentUrl)return;
 png.disabled=true;setStatus("Erstelle PNG mit UTC- und Quellenbeschriftung …");
 try{
  const img=new Image();img.crossOrigin="anonymous";
  // The preview is deliberately small; only download requests the native WMS size.
  const exportUrl=cachedImage?.url||(verified&&frames[index]?imageUrl(frames[index]):imageUrl(null));
  await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=()=>reject(new Error("CORS or high-resolution WMS unavailable"));img.src=exportUrl;});
  const pad=24,header=96,footer=80,c=document.createElement("canvas");c.width=img.naturalWidth;c.height=img.naturalHeight+header+footer;
  const ctx=c.getContext("2d");ctx.fillStyle="#ffffff";ctx.fillRect(0,0,c.width,c.height);ctx.fillStyle="#162f4a";
  ctx.font="bold 27px Arial";ctx.fillText("MTG / "+description().name+" · "+REGIONS[region.value].name,pad,42);
  ctx.font="19px Arial";ctx.fillText(cachedImage?"Archivaufnahme: "+formatUTC(cachedImage.time):verified&&frames[index]?"Aufnahme: "+formatUTC(frames[index]):"Aufnahmezeit nicht verifiziert",pad,75);
  ctx.drawImage(img,0,header);ctx.fillStyle="#162f4a";ctx.font="16px Arial";
  ctx.fillText("© EUMETSAT"+(product.value==="geocolour"?" / NASA":""),pad,c.height-48);
  ctx.fillText("Quelle: view.eumetsat.int · Originalprodukt / WMS",pad,c.height-22);
  const blob=await new Promise((resolve,reject)=>c.toBlob(b=>b?resolve(b):reject(new Error("Export nicht zulässig")),"image/png"));
  const u=URL.createObjectURL(blob),link=document.createElement("a");link.href=u;
  link.download="mtg_"+product.value+"_"+region.value+"_"+(cachedImage?cachedImage.time.replace(/[:.]/g,"-"):verified&&frames[index]?frames[index].replace(/[:.]/g,"-"):"zeitpunkt-unbekannt")+".png";
  document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(u),1000);
  setStatus(cachedImage?"Gespeichertes Satellitenbild als beschriftetes PNG exportiert (Archivauflösung, keine aktuelle Aufnahme).":"Beschriftetes PNG erstellt. Herkunft und UTC-Zeit sind im Bild enthalten.",cachedImage?"warning":"info");
 }catch(_){setStatus("EUMETSAT erlaubt für diese Browseranfrage keinen direkten PNG-Canvas-Export (CORS). Öffne das Originalbild bzw. den EUMETView-Link; es wurde kein falsches Downloadbild erzeugt.","warning");}
 finally{buttons();}
}
[source,product].forEach(el=>el.addEventListener("change",refresh));
region.addEventListener("change",()=>{
 stop();
 // The UTC dimension is independent of the geographic crop. No capabilities refetch.
 if(source.value==="mtgi1"&&frames.length)drawFrame(frames[index]);
 else refresh();
});
id("satReload").addEventListener("click",refresh);
time.addEventListener("change",()=>{stop();show(Number(time.value));});
timeline.addEventListener("input",()=>{const i=Number(timeline.value);timelineLabel.textContent=frames[i]?formatUTC(frames[i]):"Keine Beobachtungen";});
timeline.addEventListener("change",()=>{stop();show(Number(timeline.value));});
prev.addEventListener("click",()=>{stop();show(index-1);});
next.addEventListener("click",()=>{stop();show(index+1);});
play.addEventListener("click",startPause);
filmLength.addEventListener("change",()=>{
 // For longer films use a smaller WMS raster by default, unless the user
 // explicitly chose the sharper 720 px setting.
 if(Number(filmLength.value)>=20&&filmQuality.value==="480")filmQuality.value="320";
 if(filmItems.length||filmLoading||filmPlaying){stop();if(frames[index])drawFrame(frames[index]);}
});
filmQuality.addEventListener("change",()=>{if(filmItems.length||filmLoading||filmPlaying){stop();if(frames[index])drawFrame(frames[index]);}});
filmSpeed.addEventListener("change",()=>{
 if(!filmPlaying)return;
 clearTimeout(frameTimer);frameTimer=setTimeout(filmTick,Number(filmSpeed.value));
});
png.addEventListener("click",downloadPNG);
gif.addEventListener("click",()=>exportFilm("gif"));
mp4.addEventListener("click",()=>exportFilm("mp4"));
window.addEventListener("keydown",event=>{if(document.activeElement?.matches("input,select,textarea,button"))return;if(event.key==="ArrowLeft"&&frames.length){event.preventDefault();stop();show(index-1);}if(event.key==="ArrowRight"&&frames.length){event.preventDefault();stop();show(index+1);}});
document.addEventListener("visibilitychange",()=>{if(document.hidden)stop();});
refresh();
})();