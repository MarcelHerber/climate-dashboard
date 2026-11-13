/* EUMETSAT WMS: real geographic HD tiles. No interpolation-based "4K" claims.
 * Each tile requests its own EPSG:4326 bounding box, preserving the
 * existing satellite, borders, pressure, radar and city coordinate system.
 * Limited network concurrency, partial-failure fallback and exact UTC.
 */
(() => {
"use strict";
const byId=id=>document.getElementById(id);
const stage=byId("satHDTiles"),frame=byId("satPictureFrame"),stack=byId("satImageStack");
const quality=byId("satStillQuality"),info=byId("satHDStatus"),download=byId("satHDDownload");
const pdfButton=byId("satHDPdf"),borderChoice=byId("satHDExportBorders"),cityChoice=byId("satHDExportCities"),isobarChoice=byId("satHDExportIsobars");
const source=byId("satSource"),product=byId("satProduct"),region=byId("satRegion");
if(!stage||!frame||!stack||!quality||!info||!download)return;
const API="https://view.eumetsat.int/geoserver/wms";
const regions={
 europe:[-27,24,49,73,1300,850],atlantic:[-70,15,35,75,1400,850],
 southwest:[-37,24,19,53,1200,620],central:[-2,43,25,58,1300,780],
 germany:[5,47,16,56,1140,950]
};
let scene=null,zoom=1,epoch=0,timer=0,queue=[],busy=0,tiles=new Map(),layout=null,downloadBusy=false;
const AUTO_HD_WIDTH=2048,AUTO_4K_ZOOM=3;
// A verified small still is always shown first; the background WMS upgrade
// must never delay it or masquerade as extra native satellite detail.
const fmt=t=>new Date(t).toISOString().slice(0,16).replace("T"," ")+" UTC";
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
function setInfo(message){info.textContent=message;}
function boundsForTile(col,row,cols,rows,bbox){
 const [west,south,east,north]=bbox;
 const dx=(east-west)/cols,dy=(north-south)/rows;
 const a=west+col*dx,b=west+(col+1)*dx;
 const n=north-row*dy,s=north-(row+1)*dy;
 return [a,s,b,n];
}
function specs(mode,scale,area){
 const native=mode==="4k"?4096:mode==="hd"?2048:
   mode==="standard"?(scale>=AUTO_4K_ZOOM?4096:AUTO_HD_WIDTH):0;
 if(!native)return null;
 const targetH=Math.round(native*area[5]/area[4]);
 const tileLimit=native===4096?1024:700;
 const cols=Math.ceil(native/tileLimit),rows=Math.ceil(targetH/tileLimit);
 if(cols*rows>20)throw Error("Kachellimit für diesen Ausschnitt überschritten");
 return {width:native,height:targetH,cols,rows,tw:Math.ceil(native/cols),th:Math.ceil(targetH/rows)};
}
function clear(reason){
 epoch++;clearTimeout(timer);timer=0;queue=[];
 for(const tile of tiles.values()){
  const img=tile.img;
  if(img){img.onload=null;img.onerror=null;if(!tile.ok)img.removeAttribute("src");}
 }
 tiles.clear();busy=0;layout=null;
 stage.replaceChildren();stage.hidden=true;
 if(reason)setInfo(reason);
 download.disabled=!scene||(quality.value==="standard"||quality.value==="economy")||downloadBusy||source.value!=="mtgi1"||region.value==="disk";
 if(pdfButton)pdfButton.disabled=download.disabled||!isobarChoice?.checked;
}
function ready(input){
 if(!input?.ready||input.cached||!input.time||input.source!=="mtgi1"||!regions[input.region]||
  typeof input.layer!=="string"||!/^mtg_fd:[a-z0-9_]+$/i.test(input.layer)){
  scene=null;clear(input?.cached?"Archivbild · keine nachladbaren HD-Daten.":"Keine aktuelle Einzelbild-Vorlage für HD.");return;
 }
 scene={time:input.time,source:input.source,region:input.region,product:input.product,
  layer:input.layer,previewWidth:Number(input.previewWidth)||800};
 window.SatelliteQualityCompare?.invalidate("Neues Satellitenbild geladen.");
 clear("Schnelle "+scene.previewWidth+"-px-Vorschau sichtbar · automatisch HD wird bei geeignetem WMS nachgeladen.");
 window.SatelliteQualityCompare?.availability(true);
 // Leave the first 800px still responsive, and avoid competing with its decode.
 // Manual HD/4K selections are immediate; auto remains a background request.
 schedule(quality.value==="standard"?750:180);
}
function viewChanged(state){
 zoom=clamp(Number(state?.scale)||1,1,4);
 schedule();
}
function visible(){
 const r=stack.getBoundingClientRect(),f=frame.getBoundingClientRect();
 if(!r.width||!r.height||!f.width||!f.height)return {left:0,right:1,top:0,bottom:1};
 const margin=.06;
 return {left:clamp((f.left-r.left)/r.width-margin,0,1),right:clamp((f.right-r.left)/r.width+margin,0,1),
  top:clamp((f.top-r.top)/r.height-margin,0,1),bottom:clamp((f.bottom-r.top)/r.height+margin,0,1)};
}
function tileUrl(tile,area,grid,selectedScene=scene){
 // Geographic bounds use the EXACT output-pixel fractions. A final tile may
 // be one pixel narrower/shorter than earlier tiles: equally divided lon/lat
 // would otherwise create seams and slight overlay displacement.
 const [west,south,east,north]=area;
 const x0=tile.col*grid.tw,y0=tile.row*grid.th;
 const w=Math.min(grid.tw,grid.width-x0),h=Math.min(grid.th,grid.height-y0);
 const box=[west+(east-west)*x0/grid.width,
  north-(north-south)*(y0+h)/grid.height,
  west+(east-west)*(x0+w)/grid.width,
  north-(north-south)*y0/grid.height];
 return API+"?"+new URLSearchParams({service:"WMS",version:"1.1.1",request:"GetMap",
  layers:selectedScene.layer,styles:"",format:"image/png",transparent:"false",srs:"EPSG:4326",
  bbox:box.join(","),width:String(w),height:String(h),bgcolor:"0x000000",time:selectedScene.time}).toString();
}
function display(tile){
 if(!tile.ok||tile.node)return;
 // At normal zoom expose all 2K pixels together. Until EVERY tile succeeds,
 // keep the already-visible 800px image untouched; never show patchy HD.
 const seamlessAuto=quality.value==="standard"&&zoom<AUTO_4K_ZOOM;
 if(seamlessAuto&&!Array.from(tiles.values()).every(item=>item.ok))return;
 const img=tile.img;
 img.className="sat-hd-tile";
 img.style.left=(tile.col*layout.tw/layout.width*100)+"%";
 img.style.top=(tile.row*layout.th/layout.height*100)+"%";
 img.style.width=(Math.min(layout.tw,layout.width-tile.col*layout.tw)/layout.width*100)+"%";
 img.style.height=(Math.min(layout.th,layout.height-tile.row*layout.th)/layout.height*100)+"%";
 img.style.position="absolute";
 img.style.maxWidth="none";
 img.style.objectFit="fill";
 tile.node=img;stage.append(img);stage.hidden=false;
}
function stats(){
 if(!scene||!layout)return;
 let ok=0,errors=0;
 for(const tile of tiles.values()){if(tile.ok)ok++;if(tile.failed)errors++;}
 const size=layout.width+" × "+layout.height+" px";
 const auto=quality.value==="standard";
 const complete=ok===layout.cols*layout.rows;
 setInfo((auto?(layout.width===4096?"Automatisch · 4K-Detailzoom":"Automatisch · HD nach 800-px-Vorschau"):
  "WMS "+(quality.value==="4k"?"4K":"HD"))+
  " · "+ok+"/"+(layout.cols*layout.rows)+" echte WMS-Kacheln"+(complete?" vollständig":" geladen")+
  (errors?" · "+errors+" nicht erreichbar (Vorschau bleibt sichtbar)":"")+
  " · Zielraster "+size+(zoom>1?" · Zoom "+Math.round(zoom*100)+" %":"")+
  (auto&&layout.width===2048&&!complete?" · Vorschau bleibt bis zum vollständigen HD-Bild sichtbar":""));
}
function pump(){
 if(!scene||!layout)return;
 const gen=epoch;
 while(busy<2&&queue.length){
  const tile=queue.shift();
  if(tile.ok||tile.failed||tile.loading)continue;
  busy++;tile.loading=true;
  const img=new Image();img.crossOrigin="anonymous";img.decoding="async";
  tile.img=img;
  let finished=false;
  const complete=valid=>{
   if(finished)return;finished=true;clearTimeout(timeout);img.onload=null;img.onerror=null;
   if(gen!==epoch)return;
   busy--;tile.loading=false;
   const expectedW=Math.min(layout.tw,layout.width-tile.col*layout.tw);
   const expectedH=Math.min(layout.th,layout.height-tile.row*layout.th);
   if(valid&&img.naturalWidth===expectedW&&img.naturalHeight===expectedH){
    tile.ok=true;
    if(quality.value==="standard"&&zoom<AUTO_4K_ZOOM){
     if(Array.from(tiles.values()).every(item=>item.ok))
      for(const completeTile of tiles.values())display(completeTile);
    }else display(tile);
   }else{tile.failed=true;img.removeAttribute("src");}
   stats();pump();
  };
  const timeout=setTimeout(()=>complete(false),12000);
  img.onload=()=>complete(true);img.onerror=()=>complete(false);
  img.src=tileUrl(tile,regions[scene.region],layout);
 }
}
function ensureTiles(all=false){
 if(!scene||!layout)return;
 const v=all?{left:0,right:1,top:0,bottom:1}:visible();
 const coords=[];
 for(let row=0;row<layout.rows;row++)for(let col=0;col<layout.cols;col++){
  if((col+1)/layout.cols<v.left||col/layout.cols>v.right||
     (row+1)/layout.rows<v.top||row/layout.rows>v.bottom)continue;
  const key=col+"_"+row;
  let tile=tiles.get(key);
  if(!tile){tile={key,col,row,ok:false,loading:false,failed:false,node:null,img:null};tiles.set(key,tile);}
  if(!tile.loading&&!tile.ok&&!tile.failed&&!queue.includes(tile)){coords.push(tile);}
 }
 // Nearest visible tiles first for early perceptual quality.
 const midX=(v.left+v.right)/2,midY=(v.top+v.bottom)/2;
 coords.sort((a,b)=>{
  const dist=t=>Math.abs((t.col+.5)/layout.cols-midX)+Math.abs((t.row+.5)/layout.rows-midY);
  return dist(a)-dist(b);
 });
 queue.push(...coords);
 pump();stats();
}
function render(){
 if(!scene||source.value!=="mtgi1"||product.value!==scene.product||region.value!==scene.region){
  clear("Keine geprüfte Einzelbildansicht für HD aktiv.");return;
 }
 const auto=quality.value==="standard";
 // A 400/320px fallback indicates source instability. Do not intensify the
 // outage with automatic tile requests; explicit HD/4K remains available.
 if(auto&&scene.previewWidth<800){
  if(layout||tiles.size)clear();
  setInfo("Vorschau "+scene.previewWidth+" px · automatisches HD wegen WMS-Rückfall pausiert. HD/4K manuell möglich.");
  return;
 }
 if(quality.value==="economy"){
  if(layout||tiles.size)clear();
  setInfo("Datensparmodus · nur die ursprüngliche "+scene.previewWidth+"-px-Vorschau; keine automatischen Kacheln.");
  return;
 }
 const area=regions[scene.region];
 let grid;
 try{grid=specs(quality.value,zoom,area);}
 catch(error){clear("HD nicht möglich: "+error.message);return;}
 download.disabled=(quality.value==="standard"||quality.value==="economy")||downloadBusy;
 if(pdfButton)pdfButton.disabled=download.disabled||!isobarChoice?.checked;
 if(!grid){clear("Nur die bestätigte Vorschau verfügbar.");return;}
 const key=[scene.time,scene.layer,scene.region,grid.width,grid.height].join("|");
 if(layout?.key!==key){
  clear();
  layout={...grid,key};
 }
 ensureTiles(false);
}
function schedule(delay=180){clearTimeout(timer);timer=setTimeout(render,delay);}
function cancel(reason){
 scene=null;clear(reason||"HD-Kacheln für Film/Wechsel ausgeblendet.");
 window.SatelliteQualityCompare?.invalidate("Film oder Bildauswahl geändert; Vergleich zurückgesetzt.");
 window.SatelliteQualityCompare?.availability(false);
}
quality.addEventListener("change",()=>{
 clear();
 if(scene)schedule();
});

/* Output requires a complete, exact-time collection. Missing/failed WMS
 * tiles NEVER generate a misleading interpolated HD or 4K composite. */
async function prepareFullRaster(gen,ctxScene,grid){
 ensureTiles(true);
 const deadline=Date.now()+160000;
 while(Date.now()<deadline){
  if(gen!==epoch||!scene||scene.time!==ctxScene.time||scene.layer!==ctxScene.layer||
     region.value!==ctxScene.region||product.value!==ctxScene.product||
     layout?.key!==grid.key)throw Error("Kartenauswahl wurde während des Exports geändert");
  const list=Array.from({length:grid.cols*grid.rows},(_,i)=>
   tiles.get((i%grid.cols)+"_"+Math.floor(i/grid.cols)));
  if(list.every(t=>t&&(t.ok||t.failed))){
   if(list.some(t=>!t.ok))throw Error("Eine oder mehrere HD-Kacheln konnten nicht geladen werden. Es wird kein künstlich vergrößertes Ersatzbild ausgegeben.");
   const canvas=document.createElement("canvas");
   canvas.width=grid.width;canvas.height=grid.height;
   const ctx=canvas.getContext("2d");
   if(!ctx)throw Error("Canvas nicht verfügbar.");
   // Pixel-aligned placement prevents seams from rounded tile dimensions.
   for(const tile of list){
    const x=tile.col*grid.tw,y=tile.row*grid.th;
    ctx.drawImage(tile.img,x,y,Math.min(grid.tw,grid.width-x),
      Math.min(grid.th,grid.height-y));
   }
   return {canvas,ctx};
  }
  await new Promise(resolve=>setTimeout(resolve,150));
 }
 throw Error("HD-Bildabruf nicht rechtzeitig abgeschlossen");
}
function stamp(ctx,sceneData,grid,options){
 const size=Math.max(13,Math.round(grid.width/145));
 const h=Math.max(32,Math.round(size*2.25));
 ctx.save();
 ctx.fillStyle="rgba(9,23,38,.88)";
 ctx.fillRect(0,grid.height-h,grid.width,h);
 ctx.fillStyle="#ffffff";ctx.font="700 "+size+"px Arial,sans-serif";
 const title="MTG · "+sceneData.product+" · "+fmt(sceneData.time)+
   " · "+grid.width+" × "+grid.height+" px · © EUMETSAT";
 ctx.fillText(title,Math.round(h*.32),grid.height-Math.round(h*.40),grid.width-h*.64);
 ctx.restore();
}
async function compositeLayers(ctx,sceneData,grid,choice){
 const area={x:0,y:0,width:grid.width,height:grid.height};
 let overlay=null;
 if(choice.borders){
  if(!window.SatelliteOverlay?.paintBorders)throw Error("Natural-Earth-Grenzfunktion ist nicht bereit.");
  window.SatelliteOverlay.paintBorders(ctx,sceneData.region,area);
 }
 if(choice.cities){
  if(!window.SatelliteOverlay?.paintCities)throw Error("Städtefunktion ist nicht bereit.");
  window.SatelliteOverlay.paintCities(ctx,sceneData.region,area);
 }
 if(choice.isobars){
  if(!window.SatelliteIsobars?.exportAt||!window.SatelliteMapExport?.paintIsobars)
   throw Error("ECMWF-Vektorisobaren sind für den Download nicht geladen.");
  const spacing=Number(byId("satIsobarSpacing")?.value)||5;
  overlay=await window.SatelliteIsobars.exportAt(sceneData.time,sceneData.region,spacing);
  if(overlay?.satelliteUTC!==sceneData.time||!overlay?.validUTC)
   throw Error("Die ECMWF-Isobaren passen nicht zum ausgewählten Satellitenzeitpunkt.");
  if(choice.format==="png")
   window.SatelliteMapExport.paintIsobars(ctx,overlay,sceneData.region,area);
 }
 return overlay;
}
async function exportImage(format="png"){
 if(downloadBusy||!scene||quality.value==="standard"||quality.value==="economy")return;
 const gen=epoch,ctxScene={...scene},grid=layout;
 if(!grid||grid.width!==({hd:2048,"4k":4096}[quality.value])){
  setInfo("Für den Download bitte zunächst das gewählte HD-/4K-Bild laden.");return;
 }
 const choice={format,borders:Boolean(borderChoice?.checked),cities:Boolean(cityChoice?.checked),
  isobars:Boolean(isobarChoice?.checked)};
 if(format==="pdf"&&!choice.isobars){
  setInfo("Für ein PDF mit echten Vektor-Isobaren bitte die Isobaren im HD-Export aktivieren.");return;
 }
 downloadBusy=true;download.disabled=true;if(pdfButton)pdfButton.disabled=true;
 try{
  const {canvas,ctx}=await prepareFullRaster(gen,ctxScene,grid);
  const overlay=await compositeLayers(ctx,ctxScene,grid,choice);
  if(gen!==epoch||!scene||scene.time!==ctxScene.time)
   throw Error("Aufnahme wurde während der Beschriftung gewechselt");
  if(format==="pdf"){
   if(!window.SatelliteMapExport?.renderPDF||!window.SatelliteMapExport?.download)
    throw Error("Vektor-PDF-Modul nicht verfügbar.");
   // Raster base: original full-resolution WMS pixels plus selectable
   // Natural Earth and city annotations; Isobars stay editable PDF paths.
   const productName=byId("satProduct")?.selectedOptions?.[0]?.textContent||ctxScene.product;
   const regionName=byId("satRegion")?.selectedOptions?.[0]?.textContent||ctxScene.region;
   const exported=await window.SatelliteMapExport.renderPDF({
    image:canvas,overlay,region:ctxScene.region,regionName,product:ctxScene.product,productName});
   window.SatelliteMapExport.download({
    blob:exported.blob,name:exported.name.replace("_isobaren.pdf","_"+grid.width+"px_hd_vektoren.pdf")});
   setInfo("HD-/4K-PDF aus vollständigen WMS-Kacheln · ECMWF-Isobaren bleiben als Vektoren bearbeitbar · "+fmt(ctxScene.time));
  }else{
   stamp(ctx,ctxScene,grid,choice);
   const blob=await new Promise((resolve,reject)=>{
    try{canvas.toBlob(b=>b?resolve(b):reject(Error("Canvas nicht exportierbar")),"image/png");}
    catch(err){reject(err);}
   });
   const url=URL.createObjectURL(blob),a=document.createElement("a");
   a.href=url;a.download="mtg_"+ctxScene.product+"_"+ctxScene.region+"_"+grid.width+"px_"+
    ctxScene.time.replace(/[:.]/g,"-")+(choice.isobars?"_isobaren":"")+".png";
   document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
   setInfo("Echte "+grid.width+" × "+grid.height+" px WMS-Kacheln exportiert · "+
    (choice.isobars?"ECMWF-Isobaren · ":"")+(choice.borders?"Grenzen · ":"")+
    (choice.cities?"Städte · ":"")+fmt(ctxScene.time));
  }
 }catch(error){
  setInfo("HD-/4K-"+format.toUpperCase()+" nicht möglich: "+(error?.message||String(error)));
 }finally{
  downloadBusy=false;
  download.disabled=!scene||quality.value==="standard"||quality.value==="economy";
  if(pdfButton)pdfButton.disabled=download.disabled||!isobarChoice?.checked;
 }
}
download.addEventListener("click",()=>exportImage("png"));
if(pdfButton)pdfButton.addEventListener("click",()=>exportImage("pdf"));
if(isobarChoice)isobarChoice.addEventListener("change",()=>{
 if(pdfButton)pdfButton.disabled=downloadBusy||(quality.value==="standard"||quality.value==="economy")||!scene||!isobarChoice.checked;
});
/* Read-only verified scene plan for the opt-in, like-for-like comparison.
 * Uses the SAME pixel-aligned tileUrl and grid geometry as HD/4K download.
 * No hidden WMS network requests until comparison is started explicitly. */
function comparisonPlan(mode){
 if(!scene||scene.source!=="mtgi1"||!regions[scene.region]||
    typeof scene.time!=="string"||!Number.isFinite(Date.parse(scene.time)))
  throw Error("Kein verifiziertes geografisches Satellitenbild zum Vergleich.");
 if(mode!=="hd"&&mode!=="4k")throw Error("Ungültige Vergleichsauflösung.");
 const selectedScene={...scene},grid=specs(mode,1,regions[scene.region]);
 const gridKey=[scene.time,scene.layer,scene.region,grid.width,grid.height].join("|");
 const images=Array.from({length:grid.cols*grid.rows},(_,i)=>{
  const col=i%grid.cols,row=Math.floor(i/grid.cols),key=col+"_"+row;
  const native=layout?.key===gridKey?tiles.get(key):null;
  return {
   col,row,x:col*grid.tw,y:row*grid.th,
   width:Math.min(grid.tw,grid.width-col*grid.tw),
   height:Math.min(grid.th,grid.height-row*grid.th),
   url:tileUrl({col,row},regions[scene.region],grid,selectedScene),
   cached:native?.ok?native.img:null
  };
 });
 return {scene:selectedScene,width:grid.width,height:grid.height,bbox:regions[selectedScene.region].slice(0,4),tiles:images};
}
window.SatelliteHD={sync:ready,cancel,viewChanged,boundsForTile,exportImage,comparisonPlan};
setInfo("Automatisch · erst 800 px Vorschau, danach 2048 px im Hintergrund · 4K ab 300 % Zoom.");
})();
