/* Official EUMETSAT WMS only. No fabricated timestamps or MTG-I2 live stream. */
(() => {
"use strict";
const API="https://view.eumetsat.int/geoserver/wms";
const PRODUCTS={
 geocolour:{layer:"mtg_fd:rgb_geocolour",name:"GeoColour",url:"https://view.eumetsat.int/productviewer/productDetails/mtg_fd%3Argb_geocolour",credit:"© EUMETSAT · GeoColour: NASA-Hintergrund"},
 dust:{layer:"mtg_fd:rgb_dust",name:"Dust RGB",url:"https://view.eumetsat.int/productviewer/productDetails/mtg_fd%3Argb_dust",credit:"© EUMETSAT"},
 cloudtype:{layer:"mtg_fd:rgb_cloudtype",name:"Cloud Type RGB",url:"https://view.eumetsat.int/productviewer/productDetails/mtg_fd%3Argb_cloudtype",credit:"© EUMETSAT"}
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
const timeline=id("satTimeline"),timelineLabel=id("satTimelineLabel"),filmImage=id("satFilmStage");
const filmLength=id("satFilmLength"),filmQuality=id("satFilmQuality"),filmSpeed=id("satFilmSpeed");
const filmProgress=id("satFilmProgress"),filmProgressLabel=id("satFilmProgressLabel"),filmProgressWrap=id("satFilmProgressWrap");
let frames=[],index=-1,frameTimer=null,token=0,imageRequest=0,currentUrl="",loaded=false,verified=false,abort=null,metadataSource="";
let filmGeneration=0,filmLoading=false,filmPlaying=false,filmItems=[],filmPosition=0;
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
 play.disabled=!ready||index<1;
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
function drawFrame(t){const seq=token,req=++imageRequest;loaded=false;verified=Boolean(t);currentUrl=imageUrl(t);id("satRawImage").href=currentUrl;id("satRawImage").hidden=false;empty.hidden=true;image.hidden=false;image.alt=description().name+" – "+REGIONS[region.value].name+(t?", "+formatUTC(t):", Zeitpunkt nicht überprüft");
 id("satMapTitle").textContent=description().name+" · "+REGIONS[region.value].name;
 id("satValid").textContent=t?"Beobachtung: "+formatUTC(t):"Beobachtungszeit: nicht überprüft";
 const projection=region.value==="disk"?"AUTO:97004 (geostationär)":"EPSG:4326";
 id("satImageInfo").textContent=t?"WMS · "+projection+" · UTC aus GetCapabilities":"WMS · "+projection+" · serverseitiger Standardzeitpunkt, nicht als live bestätigt";
 image.onload=()=>{if(seq!==token||req!==imageRequest)return;loaded=true;empty.hidden=true;image.hidden=!filmImage.hidden;buttons();if(!filmImage.hidden)return;if(t)setStatus("Bild für "+formatUTC(t)+" geladen · Zeit aus "+(metadataSource==="manifest"?"verifiziertem GitHub-WMS-Check":"WMS-Metadaten")+".","info");else setStatus("Einzelbild geladen. Der Aufnahmezeitpunkt ist noch nicht verifiziert; keine Live-Behauptung.","warning");};
 image.onerror=()=>{if(seq!==token||req!==imageRequest)return;if(!filmImage.hidden)return;loaded=false;image.hidden=true;empty.hidden=false;buttons();setStatus("Der EUMETSAT-Kartendienst konnte das angeforderte Bild nicht liefern. Bitte den offiziellen Produktlink verwenden.","error");};
 buttons();image.src=currentUrl;
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
  setStatus(reason+" Kein brauchbarer GitHub-WMS-Status verfügbar ("+error.message+"). Einzelbild ohne verifizierte Zeit; Animation deaktiviert.","warning");
 }
}
async function refresh(){
 stop();token++;const mine=token;abort?.abort();const controller=new AbortController();abort=controller;frames=[];index=-1;loaded=false;metadataSource="";fillTimes();
 id("satOfficial").href=source.value==="mtgi2"?"https://www.esa.int/articles/about-us/directorates/earth-observation-programmes/meteorological-missions/meteosat-third-generation/mtg-i2-weather-satellite-delivers-first-images":description().url;
 id("satOfficial").textContent=source.value==="mtgi2"?"MTG-I2-Erstbilder bei ESA öffnen ↗":"Produkt bei EUMETView öffnen ↗";
 product.disabled=source.value==="mtgi2";region.disabled=source.value==="mtgi2";id("satAttribution").textContent=source.value==="mtgi2"?"ESA · erste MTG-I2-Aufnahmen":description().credit;
 if(source.value==="mtgi2"){
  id("satRawImage").hidden=true;
  image.hidden=true;empty.hidden=false;empty.textContent="MTG-I2: erste Aufnahmen und die 2,5-Minuten-Animation sind über den ESA-Link abrufbar. Noch keine reguläre Livequelle.";
  id("satMapTitle").textContent="MTG-I2 · Erstaufnahmen (November 2026)";
  id("satValid").textContent="Kein Livestream";id("satImageInfo").textContent="ESA-Erstbilder · keine laufend aktualisierte Datenquelle";
  setStatus("MTG-I2 befindet sich noch in Kalibrierung und Validierung. Bitte die ESA-Erstbilder öffnen.","warning");buttons();return;
 }
 empty.textContent="Keine Satellitenaufnahme geladen. Über den offiziellen EUMETView-Link kannst du die Bilder direkt öffnen.";
 setStatus("Lade EUMETSAT-Bild; prüfe verfügbare UTC-Zeitpunkte …");
 // A server-default frame is never labelled as current.
 drawFrame(null);
 const caps=API+"?"+new URLSearchParams({service:"WMS",version:"1.1.1",request:"GetCapabilities"}).toString();
 const timeout=setTimeout(()=>controller.abort(),16000);
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
  const im=new Image();im.decoding="async";let complete=false;
  const finish=reason=>{
   if(complete)return;
   complete=true;clearTimeout(timeout);im.onload=null;im.onerror=null;
   if(reason!=="ok")im.src="";
   resolve(reason==="ok"?{item:{time:t,img:im,index:ordinal},reason}:{item:null,reason});
  };
  const timeout=setTimeout(()=>finish("timeout"),12000);
  im.onload=()=>finish(im.naturalWidth>0?"ok":"error");
  im.onerror=()=>finish("error");
  im.src=imageUrl(t,width);
 });
}
async function loadedPreview(t,width,ordinal){
 const first=await previewAttempt(t,width,ordinal);
 if(first.item)return first.item;
 // EUMETSAT occasionally responds with HTTP 500 to a particular image
 // size. Try one alternate preview size on a quick error, not on timeout.
 if(first.reason==="error"&&(width===480||width===320)){
  const fallback=await previewAttempt(t,720,ordinal);
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
 stop();filmLoading=true;
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
 setStatus("Lade kompakte Filmbilder (maximal zwei gleichzeitige Anfragen). Die Einzelbildkarte bleibt sichtbar.","info");
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
 filmProgressLabel.textContent=filmItems.length+" von "+clip.length+" Filmbildern bereit ("+size+" px"+(filmItems.some(item=>item.img.naturalWidth>size)?", einzelne Ersatzbilder 720 px":"")+")";
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
async function downloadPNG(){
 if(!loaded||!currentUrl)return;
 png.disabled=true;setStatus("Erstelle PNG mit UTC- und Quellenbeschriftung …");
 try{
  const img=new Image();img.crossOrigin="anonymous";
  await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=()=>reject(new Error("CORS"));img.src=currentUrl;});
  const pad=24,header=96,footer=80,c=document.createElement("canvas");c.width=img.naturalWidth;c.height=img.naturalHeight+header+footer;
  const ctx=c.getContext("2d");ctx.fillStyle="#ffffff";ctx.fillRect(0,0,c.width,c.height);ctx.fillStyle="#162f4a";
  ctx.font="bold 27px Arial";ctx.fillText("MTG / "+description().name+" · "+REGIONS[region.value].name,pad,42);
  ctx.font="19px Arial";ctx.fillText(verified&&frames[index]?"Aufnahme: "+formatUTC(frames[index]):"Aufnahmezeit nicht verifiziert",pad,75);
  ctx.drawImage(img,0,header);ctx.fillStyle="#162f4a";ctx.font="16px Arial";
  ctx.fillText("© EUMETSAT"+(product.value==="geocolour"?" / NASA":""),pad,c.height-48);
  ctx.fillText("Quelle: view.eumetsat.int · Originalprodukt / WMS",pad,c.height-22);
  const blob=await new Promise((resolve,reject)=>c.toBlob(b=>b?resolve(b):reject(new Error("Export nicht zulässig")),"image/png"));
  const u=URL.createObjectURL(blob),link=document.createElement("a");link.href=u;
  link.download="mtg_"+product.value+"_"+region.value+"_"+(verified?frames[index].replace(/[:.]/g,"-"):"zeitpunkt-unbekannt")+".png";
  document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(u),1000);
  setStatus("Beschriftetes PNG erstellt. Herkunft und UTC-Zeit sind im Bild enthalten.","info");
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
window.addEventListener("keydown",event=>{if(document.activeElement?.matches("input,select,textarea,button"))return;if(event.key==="ArrowLeft"&&frames.length){event.preventDefault();stop();show(index-1);}if(event.key==="ArrowRight"&&frames.length){event.preventDefault();stop();show(index+1);}});
document.addEventListener("visibilitychange",()=>{if(document.hidden)stop();});
refresh();
})();