/* In-browser MTG film export; official PNGs and verified UTC only.
 * Native GIF89a RGB332+LZW, and MP4 only with an actual supported codec.
 * No network libraries, no masquerading WebM data as MP4.
 */
(() => {
"use strict";
const rgb332=(r,g,b)=>(r&224)|((g&224)>>>3)|(b>>>6);
const write16=(a,n)=>{a.push(n&255,(n>>8)&255);};
const palette=(()=>{
 const p=new Uint8Array(768);
 for(let i=0;i<256;i++){
  p[i*3]=Math.round(((i>>5)&7)*255/7);
  p[i*3+1]=Math.round(((i>>2)&7)*255/7);
  p[i*3+2]=Math.round((i&3)*255/3);
 }return p;
})();
function lzw(indices){
 if(!indices?.length)throw new Error("GIF-Daten fehlen");
 const CLEAR=256,END=257;
 let bits=9,next=258,dict=new Map(),current=0,used=0;
 const out=[];
 function emit(code){
  current|=code<<used;used+=bits;
  while(used>=8){out.push(current&255);current>>>=8;used-=8;}
 }
 emit(CLEAR);
 let prefix=indices[0];
 for(let i=1;i<indices.length;i++){
  const symbol=indices[i],key=(prefix<<8)|symbol;
  if(dict.has(key)){prefix=dict.get(key);continue;}
  emit(prefix);
  if(next<4096){
   dict.set(key,next++);
   // GIF decoder's dictionary trails the encoder by one code.
   if(next===(1<<bits)+1&&bits<12)bits++;
  }else{
   emit(CLEAR);dict=new Map();bits=9;next=258;
  }
  prefix=symbol;
 }
 emit(prefix);emit(END);
 if(used)out.push(current&255);
 return new Uint8Array(out);
}
function indexedGIF({width,height,frames,delayCs=75}){
 if(!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||width>1024||height>1024)
  throw new Error("Ungültige GIF-Größe");
 if(!Array.isArray(frames)||frames.length<2||frames.length>48)
  throw new Error("GIF benötigt 2 bis 48 Bilder");
 const head=[71,73,70,56,57,97];write16(head,width);write16(head,height);head.push(247,0,0);
 const chunks=[new Uint8Array(head),palette,
   new Uint8Array([33,255,11,78,69,84,83,67,65,80,69,50,46,48,3,1,0,0,0])];
 const delay=Math.max(4,Math.min(65535,Math.round(delayCs)));
 for(const frame of frames){
  if(!ArrayBuffer.isView(frame)||frame.BYTES_PER_ELEMENT!==1||frame.length!==width*height)
   throw new Error("Falsche GIF-Bildlänge");
  const chunk=[33,249,4,4];write16(chunk,delay);chunk.push(0,0,44);
  write16(chunk,0);write16(chunk,0);write16(chunk,width);write16(chunk,height);chunk.push(0,8);
  chunks.push(new Uint8Array(chunk));
  const data=lzw(frame);
  for(let i=0;i<data.length;i+=255){
   const part=data.subarray(i,i+255);
   chunks.push(new Uint8Array([part.length]),part);
  }
  chunks.push(new Uint8Array([0]));
 }
 chunks.push(new Uint8Array([59]));
 return new Blob(chunks,{type:"image/gif"});
}
function supportsMP4(){
 return typeof MediaRecorder==="function"&&typeof HTMLCanvasElement!=="undefined"&&
   typeof HTMLCanvasElement.prototype.captureStream==="function"&&
   ["video/mp4;codecs=avc1.42E01E","video/mp4"].some(x=>MediaRecorder.isTypeSupported(x));
}
function filename(input,extension){
 const stamp=String(input.frames.at(-1)?.time||"").replace(/[-:]/g,"").replace("T","_").replace(".000Z","Z");
 return "mtg_"+String(input.product||"satellite").replace(/[^a-z0-9_-]/gi,"_")+"_"+String(input.region||"map").replace(/[^a-z0-9_-]/gi,"_")+"_"+stamp+"."+extension;
}
function renderer(input,width){
 const first=input.frames[0]?.img;
 const ratio=(first?.naturalHeight||first?.height)/(first?.naturalWidth||first?.width);
 if(!Number.isFinite(ratio)||ratio<=0)throw new Error("Filmbilder nicht bereit");
 const fullHD=Boolean(input.fullHD);
 const header=44,footer=input.isobarOverlays?(input.frontOverlays?68:52):32;
 const mapWidth=fullHD?Math.min(width,Math.floor((1080-header-footer)/ratio)):width;
 const mapHeight=Math.round(mapWidth*ratio);
 const mapX=fullHD?Math.round((width-mapWidth)/2):0;
 const canvas=document.createElement("canvas");
 canvas.width=width;canvas.height=fullHD?1080:header+mapHeight+footer;
 const ctx=canvas.getContext("2d",{willReadFrequently:true});
 if(!ctx)throw new Error("Canvas fehlt");
 function draw(frame,frameIndex=0){
  if(!frame.time||!Number.isFinite(Date.parse(frame.time)))throw new Error("Kein gültiger UTC-Zeitpunkt");
  ctx.fillStyle="#12263d";ctx.fillRect(0,0,canvas.width,canvas.height);
  ctx.drawImage(frame.img,mapX,header,mapWidth,mapHeight);
  if(input.isobarOverlays){
   const pressure=input.isobarOverlays[frameIndex];
   if(!pressure||pressure.satelliteUTC!==frame.time)
    throw new Error("Keine zum Filmzeitpunkt passenden Isobaren vorhanden.");
   if(!window.SatelliteMapExport?.paintIsobars)
    throw new Error("Isobaren-Zeichner für GIF-Export fehlt.");
   window.SatelliteMapExport.paintIsobars(ctx,pressure,input.region,{x:mapX,y:header,width:mapWidth,height:mapHeight});
  }
  if(input.frontOverlays){
   if(input.frontOverlays.length!==input.frames.length)
    throw new Error("NOAA-Frontenfolge stimmt nicht mit den UTC-Filmbildern überein.");
   const front=input.frontOverlays[frameIndex];
   if(front){
    if(!window.SatelliteMapExport?.paintFronts)
     throw new Error("NOAA-Frontenzeichner für GIF-Export fehlt.");
    window.SatelliteMapExport.paintFronts(ctx,front,input.region,
     {x:mapX,y:header,width:mapWidth,height:mapHeight},frame.time);
   }
  }
  ctx.fillStyle="#ffffff";
  ctx.font="bold "+Math.max(12,Math.round(width/23))+"px Arial,sans-serif";
  ctx.fillText("MTG · "+input.productName,12,Math.round(header*.65),width-24);
  ctx.font=Math.max(10,Math.round(width/34))+"px Arial,sans-serif";
  ctx.fillText(new Date(frame.time).toISOString().replace(".000Z"," UTC"),12,fullHD?canvas.height-15:header+mapHeight+20,width-24);
  ctx.fillText(input.credit||"© EUMETSAT",Math.max(12,width-175),fullHD?canvas.height-15:header+mapHeight+20,170);
  if(input.isobarOverlays){
   const layer=input.isobarOverlays[frameIndex];
   ctx.fillStyle="#ff4fcf";
   ctx.fillText("ECMWF IFS · "+(layer.spacing||5)+" hPa · "+layer.method+" · "+new Date(layer.validUTC).toISOString().slice(11,16)+" UTC",12,header+mapHeight+39,width-24);
  }
  const front=input.frontOverlays?.[frameIndex];
  if(front){
   ctx.fillStyle="#aee4ff";
   ctx.fillText("NOAA WPC · Frontanalyse "+new Date(front.valid_utc).toISOString().slice(11,16)+" UTC",12,header+mapHeight+56,width-24);
  }
 }
 return {canvas,ctx,draw};
}
async function exportGIF(input){
 const width=Math.min(480,Math.max(160,Math.round(input.width||320)));
 const {canvas,ctx,draw}=renderer(input,width),frames=[];
 for(let n=0;n<input.frames.length;n++){
  draw(input.frames[n],n);
  const rgba=ctx.getImageData(0,0,canvas.width,canvas.height).data;
  const indexed=new Uint8Array(canvas.width*canvas.height);
  for(let k=0,i=0;k<indexed.length;k++,i+=4)indexed[k]=rgb332(rgba[i],rgba[i+1],rgba[i+2]);
  frames.push(indexed);
  input.progress?.(n+1,input.frames.length);
  if(n%3===2)await new Promise(resolve=>setTimeout(resolve,0));
 }
 return {blob:indexedGIF({width:canvas.width,height:canvas.height,frames,
   delayCs:Math.max(6,Math.round((input.delayMs||750)/10))}),name:filename(input,"gif")};
}
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function exportMP4(input){
 if(!supportsMP4())throw new Error("MP4/H.264 wird von diesem Browser nicht unterstützt");
 const mime=["video/mp4;codecs=avc1.42E01E","video/mp4"].find(x=>MediaRecorder.isTypeSupported(x));
 const {canvas,draw}=renderer(input,input.fullHD?1920:Math.min(720,Math.max(160,Math.round(input.width||480))));
 const stream=canvas.captureStream(0),track=stream.getVideoTracks()[0];
 let recorder;
 try{recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:input.fullHD?8000000:1500000});}
 catch(error){track?.stop();throw error;}
 const parts=[];
 const done=new Promise((resolve,reject)=>{
  recorder.ondataavailable=event=>{if(event.data.size)parts.push(event.data);};
  recorder.onerror=event=>reject(new Error("Videocodierung: "+(event.error?.message||"unbekannter Fehler")));
  recorder.onstop=()=>resolve();
 });
 try{
  recorder.start();
  const step=Math.max(150,Math.min(1500,Number(input.delayMs)||750));
  for(let n=0;n<input.frames.length;n++){
   draw(input.frames[n],n);track?.requestFrame?.();
   input.progress?.(n+1,input.frames.length);
   await wait(step);
  }
  recorder.stop();await done;
 }finally{if(recorder.state!=="inactive")recorder.stop();track?.stop();}
 const blob=new Blob(parts,{type:recorder.mimeType});
 // A .mp4 extension is ONLY allowed if the payload has a true MP4 ftyp box.
 const magic=new Uint8Array(await blob.slice(4,8).arrayBuffer());
 if(String.fromCharCode(...magic)!=="ftyp")throw new Error("Browser hat kein gültiges MP4 erzeugt");
 return {blob,name:filename(input,"mp4")};
}
function download(result){
 if(!result?.blob?.size)throw new Error("Export ist leer");
 const url=URL.createObjectURL(result.blob),a=document.createElement("a");
 a.href=url;a.download=result.name;document.body.appendChild(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(url),60000);
 return result.blob.size;
}
window.SatelliteFilmExport={indexedGIF,exportGIF,exportMP4,supportsMP4,download};
})();