/* Untransformed inline browser source: avoids Cloudflare esbuild helper leakage. */
export const RADAR_CLIENT_SOURCE = String.raw`(function radarClient(){
"use strict";
const $=id=>document.getElementById(id);
const canvas=$("map"),ctx=canvas.getContext("2d",{alpha:false});
const BASE={w:1,e:19,s:45,n:56};
const REGIONS={
 all:{w:1,e:19,s:45,n:56},
 north:{w:5,e:16.2,s:51.1,n:55.8},
 south:{w:5.2,e:15.8,s:45.6,n:51.6},
 west:{w:4,e:12.5,s:47.5,n:53.5}
};
const LEVELS=[.1,.5,1,2,5,10,20,30,50,80,120];
const COLORS=[
 "#9de3f7","#5dc3e5","#238cce","#2171c7","#53bd67",
 "#bbde43","#f4cc37","#f99b37","#eb5544","#c42692","#8420a4"
];
const st={manifest:null,frame:0,frames:[],geo:null,images:new Map(),serial:0,play:false,timer:0};
function region(){return REGIONS[$("region").value]}
function setStatus(msg,bad=false){$("status").textContent=msg;$("status").className="status"+(bad?" error":"")}
function clock(utc){return new Date(utc).toLocaleString("de-DE",{timeZone:"UTC",
 year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"})+" UTC"}
function lx(lon){return(lon-region().w)/(region().e-region().w)*canvas.width}
function ly(lat){return(region().n-lat)/(region().n-region().s)*canvas.height}
function colorRGB(hex){return [parseInt(hex.slice(1,3),16),parseInt(hex.slice(3,5),16),parseInt(hex.slice(5,7),16)]}
const cRGB=COLORS.map(colorRGB);
function rate(q){
 if(q===255)return NaN;
 if(q===0)return 0;
 const m=st.manifest?.palette||{log_base:.05,max_rate:120};
 return m.log_base*Math.expm1((q-1)/253*Math.log1p(m.max_rate/m.log_base));
}
function bucket(value){for(let i=0;i<LEVELS.length;i++)if(value<LEVELS[i])return Math.max(0,i-1);return LEVELS.length-1}
function fromByte(p){
 if(p===255)return[130,143,157,95];
 if(p===0)return[0,0,0,0];
 const b=bucket(rate(p)),c=cRGB[b];return[c[0],c[1],c[2],212];
}
function graticule(){
 const r=region();
 ctx.fillStyle="#e1eff5";ctx.fillRect(0,0,canvas.width,canvas.height);
 ctx.save();ctx.strokeStyle="#b8d3de";ctx.lineWidth=.7;ctx.setLineDash([4,7]);
 ctx.beginPath();
 for(let lon=2;lon<20;lon+=2)if(lon>=r.w&&lon<=r.e){
  ctx.moveTo(lx(lon),0);ctx.lineTo(lx(lon),canvas.height)}
 for(let lat=46;lat<57;lat+=2)if(lat>=r.s&&lat<=r.n){
  ctx.moveTo(0,ly(lat));ctx.lineTo(canvas.width,ly(lat))}
 ctx.stroke();ctx.restore();
}
function lines(){
 if(!st.geo)return;
 ctx.save();ctx.beginPath();ctx.rect(0,0,canvas.width,canvas.height);ctx.clip();
 for(const feature of st.geo.features||[]){
   const geom=feature.geometry||{},polygons=
    geom.type==="Polygon"?[geom.coordinates]:geom.type==="MultiPolygon"?geom.coordinates:[];
   for(const rings of polygons||[]){
     ctx.beginPath();
     for(const ring of rings||[]){
       let prevX=NaN;
       for(let i=0;i<ring.length;i++){
         const [lon,lat]=ring[i],x=lx(lon),y=ly(lat);
         if(!Number.isFinite(x+y))continue;
         if(i===0||Math.abs(x-prevX)>canvas.width*.45)ctx.moveTo(x,y);
         else ctx.lineTo(x,y);
         prevX=x;
       }
       ctx.closePath();
     }
     ctx.fillStyle="#f0f4f0";ctx.fill("evenodd");
   }
 }
 ctx.restore();
}
function borderOutlines(){
 if(!st.geo)return;
 ctx.save();ctx.beginPath();ctx.rect(0,0,canvas.width,canvas.height);ctx.clip();
 ctx.strokeStyle="#475e72bf";ctx.lineWidth=1.1;ctx.beginPath();
 for(const feature of st.geo.features||[]){
   const geom=feature.geometry||{},polygons=geom.type==="Polygon"?[geom.coordinates]:geom.type==="MultiPolygon"?geom.coordinates:[];
   for(const polygon of polygons||[])for(const ring of polygon||[]){
    let px=NaN;
    for(let k=0;k<ring.length;k++){
      const x=lx(ring[k][0]),y=ly(ring[k][1]);
      if(!Number.isFinite(x+y))continue;
      if(k===0||Math.abs(x-px)>canvas.width*.45)ctx.moveTo(x,y);else ctx.lineTo(x,y);
      px=x;
    }
   }
 }
 ctx.stroke();ctx.restore();
}
function decodeImage(img){
 const c=document.createElement("canvas");c.width=img.naturalWidth;c.height=img.naturalHeight;
 const x=c.getContext("2d",{willReadFrequently:true});x.drawImage(img,0,0);
 const d=x.getImageData(0,0,c.width,c.height).data;
 const b=new Uint8Array(c.width*c.height);
 for(let i=0;i<b.length;i++)b[i]=d[i*4];
 return {bytes:b,w:c.width,h:c.height};
}
function loadField(frame){
 const path=frame.image;
 if(st.images.has(path))return Promise.resolve(st.images.get(path));
 return new Promise((resolve,reject)=>{
  const img=new Image();
  img.onload=()=>{try{
    const field=decodeImage(img),g=st.manifest.grid;
    if(field.w!==g.width||field.h!==g.height)throw Error("Ungültige Rastergröße");
    st.images.set(path,field);
    while(st.images.size>40)st.images.delete(st.images.keys().next().value);
    resolve(field);
  }catch(error){reject(error)}};
  img.onerror=()=>reject(new Error("Radarbild konnte nicht geladen werden: "+path));
  img.src="/radarlabor/api/"+path;
 });
}
function overlay(field){
 const off=document.createElement("canvas");off.width=field.w;off.height=field.h;
 const x=off.getContext("2d");const img=x.createImageData(field.w,field.h);
 for(let p=0;p<field.bytes.length;p++){
  const rgba=fromByte(field.bytes[p]),i=p*4;
  img.data[i]=rgba[0];img.data[i+1]=rgba[1];img.data[i+2]=rgba[2];img.data[i+3]=rgba[3];
 }
 x.putImageData(img,0,0);
 const r=region(),g=st.manifest.grid;
 const x0=(r.w-g.west)/(g.east-g.west)*field.w;
 const y0=(g.north-r.n)/(g.north-g.south)*field.h;
 const sw=(r.e-r.w)/(g.east-g.west)*field.w;
 const sh=(r.n-r.s)/(g.north-g.south)*field.h;
 ctx.imageSmoothingEnabled=true;
 ctx.drawImage(off,x0,y0,sw,sh,0,0,canvas.width,canvas.height);
}
function currentFrame(){return st.frames[st.frame]}
async function render(){
 if(!st.manifest||!st.frames.length)return;
 const serial=++st.serial,frame=currentFrame();
 $("stamp").textContent=clock(frame.end_utc||frame.utc);
 $("mapStamp").textContent="DWD RY · 5-Min-Intervall bis "+clock(frame.end_utc||frame.utc);
 $("timeline").value=st.frame;
 try{
  const field=await loadField(frame);
  if(serial!==st.serial)return;
  graticule();lines();
  if($("overlay").value==="rain")overlay(field);
  borderOutlines();
  const stampAge=(Date.now()-Date.parse(st.manifest.frames.at(-1).end_utc||st.manifest.frames.at(-1).utc))/60000;
  setStatus("DWD RY · echtes 5-Minuten-Radarkomposit geladen · "+
    st.frames.length+" Bilder · letzter Datenstand "+Math.round(stampAge)+" min zurück"+
    (stampAge>25?" · Achtung: verspäteter Datenstand":"")+".");
  const next=st.frames[st.frame+1];
  if(next&&!st.images.has(next.image))loadField(next).catch(()=>{});
 }catch(e){
  if(serial!==st.serial)return;
  stop();graticule();lines();borderOutlines();
  setStatus("Radarbild nicht verfügbar: "+e.message,true);
 }
}
function setFrames(){
 if(!st.manifest)return;
 stop();
 const n=parseInt($("history").value,10);
 st.frames=st.manifest.frames.slice(-n);
 st.frame=Math.max(0,st.frames.length-1);
 $("timeline").max=String(Math.max(0,st.frames.length-1));
 render();
}
function stop(){st.play=false;clearTimeout(st.timer);$("play").textContent="▶ Animation"}
async function advance(){
 if(!st.play)return;
 st.frame=(st.frame+1)%st.frames.length;
 await render();
 if(st.play)st.timer=setTimeout(advance,Math.round(650/Number($("speed").value)));
}
function initLegend(){
 const box=$("legend");box.replaceChildren();
 LEVELS.forEach((n,i)=>{
  const el=document.createElement("div"),sw=document.createElement("div"),label=document.createElement("div");
  el.className="swatch";sw.className="color";sw.style.background=COLORS[i];
  label.textContent=String(n).replace(".",",");
  el.append(sw,label);box.append(el);
 });
 const label=document.createElement("div");label.textContent="mm/h";
 label.style.padding="4px";box.append(label);
}
async function boot(){
 stop();++st.serial;st.images.clear();
 setStatus("Prüfe aktuelle Radarbilder beim DWD …");
 try{
  const r=await fetch("/radarlabor/api/current.json",{cache:"no-store"});
  if(!r.ok)throw Error(r.status===404?"Der erste DWD-Datenlauf ist noch nicht veröffentlicht":"HTTP "+r.status);
  const m=await r.json();
  if(m.schema!==1||m.product!=="DWD RADOLAN RY / ODIM HDF5"||!m.grid||
     !Array.isArray(m.frames)||m.frames.length<12||
     !m.frames.every(f=>/^[0-9]{12}$/.test(f.image?.split("/").at(-1).split(".")[0]||"")))
    throw Error("Ungültiger oder unvollständiger Radardatensatz");
  st.manifest=m;
  $("product").textContent="DWD RADOLAN RY · 1 km · 5 min";
  for(const id of ["play","prev","next","timeline","png"])$(id).disabled=false;
  setFrames();
 }catch(e){
  st.manifest=null;st.frames=[];
  for(const id of ["play","prev","next","timeline","png"])$(id).disabled=true;
  graticule();lines();borderOutlines();
  setStatus(e.message+" – es werden keine Ersatzbilder erzeugt.",true);
 }
}
$("history").addEventListener("change",setFrames);
$("region").addEventListener("change",render);
$("overlay").addEventListener("change",render);
$("timeline").addEventListener("input",()=>{stop();st.frame=Number($("timeline").value);render()});
$("prev").addEventListener("click",()=>{stop();st.frame=Math.max(0,st.frame-1);render()});
$("next").addEventListener("click",()=>{stop();st.frame=Math.min(st.frames.length-1,st.frame+1);render()});
$("play").addEventListener("click",()=>{
 if(!st.manifest)return;
 if(st.play){stop();return;}
 st.play=true;$("play").textContent="❚❚ Pause";
 st.timer=setTimeout(advance,Math.round(650/Number($("speed").value)));
});
$("refresh").addEventListener("click",boot);
$("png").addEventListener("click",()=>{
 if(!st.manifest)return;
 canvas.toBlob(blob=>{
  if(!blob)return;
  const a=document.createElement("a"),url=URL.createObjectURL(blob);
  a.href=url;a.download="dwd-ry-radar-"+currentFrame().utc.replace(/[-:]/g,"").replace("T","_")+".png";
  document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),3000);
 },"image/png");
});
fetch("/dynamik/api/boundaries").then(r=>{if(!r.ok)throw Error("Grenzen fehlen");return r.json()})
 .then(geo=>{st.geo=geo;if(st.manifest)render();else{graticule();lines();borderOutlines()}})
 .catch(()=>{});
initLegend();graticule();boot();
})();`;
