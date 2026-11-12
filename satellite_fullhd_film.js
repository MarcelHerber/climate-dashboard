/* Optional true-source 1920px MTG film frames, assembled from CORS-safe
 * EPSG:4326 WMS tiles at individually verified UTC timestamps.
 * Sequential film frames, at most 2 concurrent tile requests per frame.
 * Never enlarge low-res film previews to masquerade as source HD.
 */
(() => {
"use strict";
const API="https://view.eumetsat.int/geoserver/wms";
const AREAS={
 europe:[-27,24,49,73,1300,850],atlantic:[-70,15,35,75,1400,850],
 southwest:[-37,24,19,53,1200,620],central:[-2,43,25,58,1300,780],
 germany:[5,47,16,56,1140,950]
};
const MAX_FRAMES=12,WIDTH=1920,MAX_PARALLEL=2;
function geometry(place){
 const area=AREAS[place];
 if(!area)throw Error("Full HD unterstützt nur die geografisch projizierten MTG-I1-Ausschnitte.");
 const height=Math.round(WIDTH*area[5]/area[4]);
 const cols=Math.ceil(WIDTH/640),rows=Math.ceil(height/640);
 if(cols*rows>12)throw Error("Zu viele WMS-Kacheln für die Videovorschau.");
 return {area,width:WIDTH,height,cols,rows,tw:Math.ceil(WIDTH/cols),th:Math.ceil(height/rows)};
}
function tileRequest({time,layer},g,col,row){
 const [west,south,east,north]=g.area;
 const x=col*g.tw,y=row*g.th,w=Math.min(g.tw,g.width-x),h=Math.min(g.th,g.height-y);
 const b=[
  west+(east-west)*x/g.width,
  north-(north-south)*(y+h)/g.height,
  west+(east-west)*(x+w)/g.width,
  north-(north-south)*y/g.height
 ];
 return API+"?"+new URLSearchParams({
  service:"WMS",version:"1.1.1",request:"GetMap",
  layers:layer,styles:"",format:"image/png",transparent:"false",
  srs:"EPSG:4326",bbox:b.join(","),width:String(w),height:String(h),
  bgcolor:"0x000000",time
 }).toString();
}
function loadTile(url,expectedW,expectedH){
 return new Promise((resolve,reject)=>{
  const img=new Image();img.crossOrigin="anonymous";img.decoding="async";
  let finished=false;
  const end=error=>{
   if(finished)return;finished=true;clearTimeout(timer);
   img.onload=null;img.onerror=null;
   if(error){img.removeAttribute("src");reject(error);}
   else resolve(img);
  };
  const timer=setTimeout(()=>end(Error("WMS-Timeout beim Full-HD-Filmbild (10 Sekunden).")),10000);
  img.onload=()=>{
   if(img.naturalWidth!==expectedW||img.naturalHeight!==expectedH)
    end(Error("WMS-Filmkachel hat nicht die angeforderte Pixelgröße."));
   else end(null);
  };
  img.onerror=()=>end(Error("WMS-Filmkachel nicht lesbar (EUMETSAT-Fehler oder CORS)."));
  img.src=url;
 });
}
async function frameAt(frame,g,validate){
 const tiles=Array.from({length:g.cols*g.rows},(_,i)=>{
  const col=i%g.cols,row=Math.floor(i/g.cols),x=col*g.tw,y=row*g.th;
  return {col,row,x,y,w:Math.min(g.tw,g.width-x),h:Math.min(g.th,g.height-y)};
 });
 const decoded=new Array(tiles.length);let cursor=0;
 const worker=async()=>{
  while(cursor<tiles.length){
   if(validate&&!validate())throw Error("Kartenauswahl während des Full-HD-Exports geändert.");
   const i=cursor++,t=tiles[i];
   decoded[i]=await loadTile(tileRequest(frame,g,t.col,t.row),t.w,t.h);
  }
 };
 await Promise.all(Array.from({length:Math.min(MAX_PARALLEL,tiles.length)},worker));
 if(!decoded.every(Boolean))throw Error("Unvollständiges Full-HD-Satellitenbild.");
 if(validate&&!validate())throw Error("Kartenauswahl während des Full-HD-Exports geändert.");
 const canvas=document.createElement("canvas");canvas.width=g.width;canvas.height=g.height;
 const ctx=canvas.getContext("2d");
 if(!ctx)throw Error("Canvas für den Full-HD-Film fehlt.");
 for(let i=0;i<tiles.length;i++){
  const t=tiles[i];
  ctx.drawImage(decoded[i],t.x,t.y,t.w,t.h);
 }
 return {time:frame.time,index:frame.index,img:canvas};
}
async function loadFrames(input){
 const frames=input?.frames,place=input?.region,layer=input?.layer;
 if(!Array.isArray(frames)||frames.length<2||frames.length>MAX_FRAMES)
  throw Error("Full-HD-Film nur mit 2 bis 12 Einzelbildern möglich.");
 if(typeof layer!=="string"||!/^mtg_fd:[a-z0-9_]+$/i.test(layer))
  throw Error("Full-HD-WMS-Layer nicht verifiziert.");
 if(!frames.every(x=>Number.isFinite(Date.parse(x?.time))))
  throw Error("Full-HD erfordert für jedes Filmbild eine gültige UTC-Zeit.");
 const g=geometry(place);
 const results=[];
 for(let i=0;i<frames.length;i++){
  if(input.validate&&!input.validate())throw Error("Kartenauswahl während des Full-HD-Exports geändert.");
  const f=await frameAt({time:frames[i].time,index:frames[i].index},g,input.validate);
  results.push(f);input.progress?.(i+1,frames.length);
  // Yield to page controls before the next batch of real WMS requests.
  if(i%2===1)await new Promise(resolve=>setTimeout(resolve,0));
 }
 return results;
}
window.SatelliteFHD={loadFrames,geometry,tileRequest,MAX_FRAMES};
})();