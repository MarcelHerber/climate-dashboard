/* Unified satellite viewport: geographic imagery and every vector overlay move together.
 * Optical IR presets are display-only and never represented as calibrated temperatures. */
(() => {
"use strict";
const byId=id=>document.getElementById(id);
const frame=byId("satPictureFrame"),stack=byId("satImageStack");
const zoomOut=byId("satZoomOut"),zoomIn=byId("satZoomIn"),zoomReset=byId("satZoomReset");
const value=byId("satZoomValue"),preset=byId("satIRPreset");
const product=byId("satProduct"),source=byId("satSource"),region=byId("satRegion");
if(!frame||!stack||!zoomIn||!zoomOut||!zoomReset||!value||!preset)return;
let scale=1,x=0,y=0,drag=null;
const clamp=(n,lo,hi)=>Math.max(lo,Math.min(hi,n));
function apply(){
 const maxX=(scale-1)*stack.getBoundingClientRect().width/scale/2;
 const maxY=(scale-1)*stack.getBoundingClientRect().height/scale/2;
 x=clamp(x,-maxX,maxX);y=clamp(y,-maxY,maxY);
 stack.style.transform="translate("+x+"px,"+y+"px) scale("+scale+")";
 stack.style.transformOrigin="center center";
 const active=source.value==="mtgi1";
 zoomOut.disabled=!active||scale<=1;
 zoomIn.disabled=!active||scale>=4;
 zoomReset.disabled=!active||scale===1&&x===0&&y===0;
 value.textContent=Math.round(scale*100)+" %";
 frame.classList.toggle("sat-pannable",active&&scale>1);
}
function setZoom(next){
 const old=scale;
 scale=clamp(Math.round(next*100)/100,1,4);
 if(old!==scale&&scale===1){x=0;y=0;}
 apply();
}
function reset(){scale=1;x=0;y=0;drag=null;apply();}
function palette(){
 const active=source.value==="mtgi1"&&product.value==="ir105";
 preset.disabled=!active;
 stack.dataset.irPreset=active?preset.value:"normal";
}
zoomOut.addEventListener("click",()=>setZoom(scale/1.5));
zoomIn.addEventListener("click",()=>setZoom(scale*1.5));
zoomReset.addEventListener("click",reset);
frame.addEventListener("pointerdown",event=>{
 if(scale<=1||source.value!=="mtgi1"||event.button!==0)return;
 drag={id:event.pointerId,x:event.clientX,y:event.clientY,originX:x,originY:y};
 frame.setPointerCapture?.(event.pointerId);
});
frame.addEventListener("pointermove",event=>{
 if(!drag||drag.id!==event.pointerId)return;
 x=drag.originX+(event.clientX-drag.x);
 y=drag.originY+(event.clientY-drag.y);
 apply();
});
function endDrag(event){
 if(!drag||drag.id!==event.pointerId)return;
 drag=null;
 try{frame.releasePointerCapture?.(event.pointerId);}catch(_){}
}
frame.addEventListener("pointerup",endDrag);
frame.addEventListener("pointercancel",endDrag);
frame.addEventListener("wheel",event=>{
 if(source.value!=="mtgi1"||!event.ctrlKey)return; // no hijacking ordinary page scrolling
 event.preventDefault();
 setZoom(scale*(event.deltaY<0?1.2:1/1.2));
},{passive:false});
for(const el of [region,source])el.addEventListener("change",()=>{reset();palette();});
product.addEventListener("change",palette);
preset.addEventListener("change",palette);
window.addEventListener("resize",apply);
palette();apply();
window.SatelliteViewOptions={reset,setZoom,palette};
})();
