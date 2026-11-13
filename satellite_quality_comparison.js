/* Like-for-like MTG quality comparison.
 * Three observed WMS rasters, one verified UTC, one product, one EPSG:4326
 * BBOX. Samples show precisely the same geographic crop, never sharpened
 * using synthetic detail. Real HD/4K grids are loaded only on user request.
 */
(() => {
"use strict";
const $=id=>document.getElementById(id);
const run=$("satCompareRun"),close=$("satCompareClose"),crop=$("satCompareCrop");
const status=$("satCompareStatus"),grid=$("satCompareGrid"),marker=$("satCompareBox");
const standard=$("satImage"),film=$("satFilmStage");
if(!run||!close||!crop||!status||!grid||!marker||!standard)return;
const srcs=[
 {id:"standard",canvas:$("satCompareStandard"),info:$("satCompareInfoStandard"),label:"Standard"},
 {id:"hd",canvas:$("satCompareHD"),info:$("satCompareInfoHD"),label:"HD"},
 {id:"4k",canvas:$("satCompare4K"),info:$("satCompareInfo4K"),label:"4K"}
];
if(srcs.some(t=>!t.canvas||!t.info))return;
const cropWindow={fractionX:.22,fractionY:.22};
const spots={center:[.5,.5],northwest:[.26,.26],northeast:[.74,.26],southwest:[.26,.74],southeast:[.74,.74]};
let generation=0,working=false,enabled=false,data={},activeScene=null;
const eq=(a,b)=>Date.parse(a)===Date.parse(b);
function message(s){status.textContent=s;}
function location(){
 const at=spots[crop.value]||spots.center;
 return {left:at[0]-cropWindow.fractionX/2,top:at[1]-cropWindow.fractionY/2,
  width:cropWindow.fractionX,height:cropWindow.fractionY};
}
function locateCrop(){
 const c=location();
 marker.style.left=(100*c.left)+"%";
 marker.style.top=(100*c.top)+"%";
 marker.style.width=(100*c.width)+"%";
 marker.style.height=(100*c.height)+"%";
 marker.hidden=!activeScene;
}
function availability(value){
 enabled=Boolean(value);
 run.disabled=!enabled||working;
}
function emptyPanels(){
 grid.hidden=true;
 for(const item of srcs){item.info.textContent="Noch nicht geladen.";item.canvas.hidden=true;}
}
function invalidate(reason){
 generation++;
 working=false;activeScene=null;data={};
 marker.hidden=true;close.disabled=true;
 emptyPanels();
 availability(false);
 if(reason)message(reason);
}
function assertStill(plan){
 const img=standard;
 if(!img.complete||img.naturalWidth<1||img.naturalHeight<1||!img.src)
  throw Error("Das Standardbild ist noch nicht vollständig geladen.");
 if(film&&!film.hidden)throw Error("Qualitätsvergleich nur bei Einzelbildern verfügbar; Film zuerst beenden.");
 const url=new URL(img.currentSrc||img.src);
 if(url.origin!=="https://view.eumetsat.int"||url.pathname!=="/geoserver/wms")
  throw Error("Keine direkt abrufbare EUMETSAT-WMS-Aufnahme (z. B. Archivbild).");
 const p=url.searchParams,box=String(p.get("bbox")||"").split(",").map(Number);
 if(!eq(p.get("time"),plan.scene.time)||
    p.get("layers")!==plan.scene.layer||p.get("srs")!=="EPSG:4326"||
    box.length!==4||box.some((v,i)=>!Number.isFinite(v)||Math.abs(v-plan.bbox[i])>1e-8))
  throw Error("Das Standardbild gehört nicht zu demselben UTC-Zeitpunkt, Produkt oder Gebiet.");
 if(img.naturalWidth!==Number(p.get("width"))||img.naturalHeight!==Number(p.get("height")))
  throw Error("WMS-Standardbild meldet abweichende Pixelmaße.");
 return {image:img,width:img.naturalWidth,height:img.naturalHeight,
  source:"EUMETSAT WMS, vollständig geladen"};
}
function cropCoords(width,height){
 const c=location();
 return {sx:Math.round(c.left*width),sy:Math.round(c.top*height),
  sw:Math.round(c.width*width),sh:Math.round(c.height*height)};
}
function drawPanel(target,item){
 target.canvas.hidden=false;
 const outWidth=620,outHeight=Math.max(1,Math.round(outWidth*item.height/item.width));
 target.canvas.width=outWidth;target.canvas.height=outHeight;
 const ctx=target.canvas.getContext("2d");
 if(!ctx)throw Error("Vergleichskarte kann nicht gezeichnet werden.");
 const {sx,sy,sw,sh}=cropCoords(item.width,item.height);
 ctx.clearRect(0,0,outWidth,outHeight);
 ctx.imageSmoothingEnabled=true;
 ctx.imageSmoothingQuality="high";
 if(item.image){
  ctx.drawImage(item.image,sx,sy,sw,sh,0,0,outWidth,outHeight);
 }else if(Array.isArray(item.tiles)){
  // Do not allocate an additional full 4096px canvas: sample directly from
  // already decoded, contiguous WMS tiles. Rounded destination edges meet
  // exactly, avoiding faint seams at CSS/device pixel boundaries.
  for(const tile of item.tiles){
   const l=Math.max(sx,tile.x),r=Math.min(sx+sw,tile.x+tile.width);
   const t=Math.max(sy,tile.y),b=Math.min(sy+sh,tile.y+tile.height);
   if(r<=l||b<=t)continue;
   const dx=Math.round((l-sx)*outWidth/sw),dy=Math.round((t-sy)*outHeight/sh);
   const dr=Math.round((r-sx)*outWidth/sw),db=Math.round((b-sy)*outHeight/sh);
   if(dr>dx&&db>dy)ctx.drawImage(tile.img,l-tile.x,t-tile.y,r-l,b-t,dx,dy,dr-dx,db-dy);
  }
 }
 const frac=Math.round(cropWindow.fractionX*100);
 target.info.textContent=item.width+" × "+item.height+" WMS-Pixel · gleicher "+
  frac+"-%-Ausschnitt mit "+sw+" × "+sh+" Quellpixeln"+(item.cached?" · vorhandene Kacheln genutzt":"");
}
function show(){
 if(!activeScene)return;
 grid.hidden=false;locateCrop();
 for(const target of srcs){
  if(data[target.id])drawPanel(target,data[target.id]);
 }
}
function parseSameScene(plan,ref){
 return eq(plan.scene.time,ref.time)&&plan.scene.layer===ref.layer&&
  plan.scene.product===ref.product&&plan.scene.region===ref.region;
}
function loadTile(spec,live){
 return new Promise((resolve,reject)=>{
  if(!live()){reject(Error("Kartenansicht hat sich geändert."));return;}
  if(spec.cached&&spec.cached.complete&&spec.cached.naturalWidth===spec.width&&
      spec.cached.naturalHeight===spec.height){resolve(spec.cached);return;}
  const img=new Image();img.crossOrigin="anonymous";img.decoding="async";
  let done=false;
  function finish(err){
   if(done)return;done=true;clearTimeout(timer);img.onload=null;img.onerror=null;
   if(err){img.removeAttribute("src");reject(err);}else resolve(img);
  }
  const timer=setTimeout(()=>finish(Error("WMS-Kachel antwortet nicht innerhalb von 12 Sekunden.")),12000);
  img.onload=()=>{
   if(img.naturalWidth!==spec.width||img.naturalHeight!==spec.height)
    finish(Error("EUMETSAT-Kachel liefert eine andere Pixelgröße."));
   else finish(live()?null:Error("Kartenansicht hat sich geändert."));
  };
  img.onerror=()=>finish(Error("EUMETSAT-WMS-Kachel nicht verfügbar (HTTP/CORS/Bildfehler)."));
  img.src=spec.url;
 });
}
async function mosaic(plan,live,progress){
 let cursor=0,failed=null;
 const images=new Array(plan.tiles.length);
 async function worker(){
  while(cursor<plan.tiles.length&&!failed){
   if(!live())throw Error("Kartenansicht hat sich geändert.");
   const index=cursor++,tile=plan.tiles[index];
   try{images[index]=await loadTile(tile,live);}
   catch(err){failed=err;break;}
   progress(images.filter(Boolean).length,plan.tiles.length);
  }
 }
 await Promise.all([worker(),worker()]);
 if(failed)throw failed;
 if(!live())throw Error("Kartenansicht hat sich geändert.");
 if(images.some(x=>!x))throw Error("Unvollständiges HD-/4K-Mosaik wird nicht als Vergleichsbild angezeigt.");
 // Keep decoded original tiles only; a second full-resolution mosaic canvas
 // would double 4K memory use on mobile devices without adding any detail.
 return {tiles:plan.tiles.map((tile,i)=>({...tile,img:images[i]})),
  width:plan.width,height:plan.height,cached:plan.tiles.every(t=>t.cached),
  source:"EUMETSAT WMS, vollständig geladen"};
}
async function compare(){
 if(working||!enabled)return;
 const id=++generation;
 working=true;run.disabled=true;close.disabled=false;
 data={};activeScene=null;emptyPanels();
 try{
  const hd=window.SatelliteHD?.comparisonPlan("hd"),ultra=window.SatelliteHD?.comparisonPlan("4k");
  if(!hd||!ultra||!parseSameScene(ultra,hd.scene))
   throw Error("Kein gemeinsamer Bildzeitpunkt für den Vergleich.");
  const start=assertStill(hd);
  const ref={...hd.scene},stillUrl=standard.currentSrc||standard.src;
  const live=()=>{
   if(id!==generation||!standard.src||standard.src!==stillUrl||film&&!film.hidden)return false;
   try{
    const current=window.SatelliteHD?.comparisonPlan("hd");
    return Boolean(current&&parseSameScene(current,ref));
   }catch(_){return false;}
  };
  activeScene=ref;
  data.standard=start;
  show();
  message("Standardbild bestätigt ("+start.width+" × "+start.height+
   " px). Lade echte HD-Kacheln für denselben UTC-Zeitpunkt …");
  const errors=[];
  for(const [mode,plan] of [["hd",hd],["4k",ultra]]){
   if(!live())throw Error("Bildwechsel: Vergleich abgebrochen.");
   const target=srcs.find(x=>x.id===mode);
   try{
    data[mode]=await mosaic(plan,live,(done,total)=>{
     if(live())message((mode==="hd"?"HD":"4K")+" · "+done+"/"+total+
      " echte WMS-Kacheln · UTC "+new Date(ref.time).toISOString().slice(0,16).replace("T"," ")+"");
    });
    if(!live())throw Error("Bildwechsel: Vergleich abgebrochen.");
    show();
   }catch(error){
    if(!live())throw Error("Bildwechsel: Vergleich abgebrochen.");
    target.info.textContent="Nicht verfügbar: "+(error?.message||String(error));
    target.canvas.hidden=true;
    errors.push(target.label);
   }
  }
  if(!live())throw Error("Bildwechsel: Vergleich abgebrochen.");
  const available=srcs.filter(x=>data[x.id]).map(x=>x.label);
  const timestamp=new Date(ref.time).toISOString().slice(0,16).replace("T"," ")+" UTC";
  message("Gleicher MTG-Zeitpunkt: "+timestamp+" · "+available.join(", ")+" verifiziert"+
   (errors.length?" · "+errors.join(" und ")+" nicht verfügbar":"")+
   ". Höhere Ausgabe-Pixelzahl beweist keine höhere Sensorauflösung.");
 }catch(error){
  if(id===generation){
   activeScene=null;marker.hidden=true;
   message("Qualitätsvergleich nicht möglich: "+(error?.message||String(error)));
  }
 }finally{
  if(id===generation){working=false;availability(enabled);}
 }
}
run.addEventListener("click",compare);
close.addEventListener("click",()=>{
 invalidate("Vergleich geschlossen. Noch keine neuen Bildanfragen.");
 try{availability(Boolean(window.SatelliteHD?.comparisonPlan("hd")));}catch(_){availability(false);}
});
crop.addEventListener("change",()=>{
 if(activeScene)show();
});
emptyPanels();availability(false);message("Bereit für den opt-in Vergleich nach Laden einer verifizierten MTG-Aufnahme.");
window.SatelliteQualityCompare={invalidate,availability,compare,cropCoords};
})();