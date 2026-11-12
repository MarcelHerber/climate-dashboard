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
const source=byId("satSource"),product=byId("satProduct"),region=byId("satRegion");
if(!stage||!frame||!stack||!quality||!info||!download)return;
const API="https://view.eumetsat.int/geoserver/wms";
const regions={
 europe:[-27,24,49,73,1300,850],atlantic:[-70,15,35,75,1400,850],
 southwest:[-37,24,19,53,1200,620],central:[-2,43,25,58,1300,780],
 germany:[5,47,16,56,1140,950]
};
let scene=null,zoom=1,epoch=0,timer=0,queue=[],busy=0,tiles=new Map(),layout=null,downloadBusy=false;
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
   scale>=2.75?4096:scale>=1.35?2048:0;
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
 download.disabled=!scene||quality.value==="standard"||downloadBusy||source.value!=="mtgi1"||region.value==="disk";
}
function ready(input){
 if(!input?.ready||input.cached||!input.time||input.source!=="mtgi1"||!regions[input.region]||
  typeof input.layer!=="string"||!/^mtg_fd:[a-z0-9_]+$/i.test(input.layer)){
  scene=null;clear(input?.cached?"Archivbild · keine nachladbaren HD-Daten.":"Keine aktuelle Einzelbild-Vorlage für HD.");return;
 }
 scene={time:input.time,source:input.source,region:input.region,product:input.product,layer:input.layer};
 clear("Standardbild geprüft · HD-Kacheln bei Bedarf verfügbar.");
 schedule();
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
function tileUrl(tile,area,grid){
 const box=boundsForTile(tile.col,tile.row,grid.cols,grid.rows,area.slice(0,4));
 const w=tile.col===grid.cols-1?grid.width-(grid.cols-1)*grid.tw:grid.tw;
 const h=tile.row===grid.rows-1?grid.height-(grid.rows-1)*grid.th:grid.th;
 return API+"?"+new URLSearchParams({service:"WMS",version:"1.1.1",request:"GetMap",
  layers:scene.layer,styles:"",format:"image/png",transparent:"false",srs:"EPSG:4326",
  bbox:box.join(","),width:String(w),height:String(h),bgcolor:"0x000000",time:scene.time}).toString();
}
function display(tile){
 if(!tile.ok||tile.node)return;
 const img=tile.img;
 img.className="sat-hd-tile";
 img.style.left=(tile.col/layout.cols*100)+"%";
 img.style.top=(tile.row/layout.rows*100)+"%";
 img.style.width=(100/layout.cols)+"%";
 img.style.height=(100/layout.rows)+"%";
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
 setInfo((quality.value==="standard"?"Detailzoom":"WMS "+(quality.value==="4k"?"4K":"HD"))+
  " · geografisch aufgelöste Kacheln · "+ok+"/"+(layout.cols*layout.rows)+
  " Kacheln geladen"+(errors?" · "+errors+" nicht erreichbar (Standardbild sichtbar)":"")+
  " · Zielraster "+size+(zoom>1?" · Zoom "+Math.round(zoom*100)+" %":""));
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
   if(valid&&img.naturalWidth>0){tile.ok=true;display(tile);}
   else{tile.failed=true;img.removeAttribute("src");}
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
 const area=regions[scene.region];
 let grid;
 try{grid=specs(quality.value,zoom,area);}
 catch(error){clear("HD nicht möglich: "+error.message);return;}
 download.disabled=quality.value==="standard"||downloadBusy;
 if(!grid){clear("Standard · hochauflösende Kacheln werden ab 135 % Zoom automatisch geladen.");return;}
 const key=[scene.time,scene.layer,scene.region,grid.width,grid.height].join("|");
 if(layout?.key!==key){
  clear();
  layout={...grid,key};
 }
 ensureTiles(false);
}
function schedule(){clearTimeout(timer);timer=setTimeout(render,180);}
function cancel(reason){
 scene=null;clear(reason||"HD-Kacheln für Film/Wechsel ausgeblendet.");
}
quality.addEventListener("change",()=>{
 clear();
 if(scene)schedule();
});
async function downloadPNG(){
 if(downloadBusy||!scene||quality.value==="standard")return;
 const gen=epoch,ctxScene={...scene},area=regions[scene.region];
 const grid=layout;
 if(!grid||grid.width!==({hd:2048,"4k":4096}[quality.value])){
  setInfo("Für den Download bitte zunächst das gewählte HD-/4K-Bild laden.");return;
 }
 downloadBusy=true;download.disabled=true;
 try{
  ensureTiles(true);
  const deadline=Date.now()+160000;
  while(Date.now()<deadline){
   if(gen!==epoch||scene.time!==ctxScene.time)throw Error("Kartenauswahl wurde geändert");
   const list=Array.from({length:layout.cols*layout.rows},(_,i)=>tiles.get((i%layout.cols)+"_"+Math.floor(i/layout.cols)));
   if(list.every(t=>t&&(t.ok||t.failed))){
    if(list.some(t=>!t.ok))throw Error("Mindestens eine HD-Kachel wurde nicht übertragen. Kein hochskaliertes Ersatzbild erzeugt.");
    const canvas=document.createElement("canvas");canvas.width=grid.width;canvas.height=grid.height;
    const ctx=canvas.getContext("2d");
    for(const tile of list){
     const x=tile.col*grid.tw,y=tile.row*grid.th;
     ctx.drawImage(tile.img,x,y,Math.min(grid.tw,grid.width-x),Math.min(grid.th,grid.height-y));
    }
    const blob=await new Promise((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(Error("Canvas nicht exportierbar")),"image/png"));
    const url=URL.createObjectURL(blob),a=document.createElement("a");
    a.href=url;a.download="mtg_"+ctxScene.product+"_"+ctxScene.region+"_"+grid.width+"px_"+ctxScene.time.replace(/[:.]/g,"-")+".png";
    document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
    setInfo("Echte "+grid.width+" × "+grid.height+" px WMS-Kacheln als PNG gespeichert · "+fmt(ctxScene.time));
    return;
   }
   await new Promise(resolve=>setTimeout(resolve,150));
  }
  throw Error("HD-Bildabruf nicht rechtzeitig abgeschlossen");
 }catch(error){setInfo("HD-/4K-Export nicht möglich: "+error.message);}
 finally{downloadBusy=false;download.disabled=!scene||quality.value==="standard";}
}
download.addEventListener("click",downloadPNG);
window.SatelliteHD={sync:ready,cancel,viewChanged,boundsForTile};
setInfo("Standard · 800 px Einzelbild; echte HD-Kacheln bei Zoom oder Moduswechsel.");
})();
