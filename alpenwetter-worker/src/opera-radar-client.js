/* Keep browser script as static literal, not function.toString() after esbuild. */
export const OPERA_RADAR_CLIENT_SOURCE = String.raw`(function operaRadarClient(){
"use strict";
const $=id=>document.getElementById(id),canvas=$("map"),ctx=canvas.getContext("2d",{alpha:false});
const API="/radarlabor/api/opera/";
const VIEWS={
 all:{w:-27,e:47,s:29,n:73},
 central:{w:-12,e:32,s:40,n:62},
 north:{w:-26,e:34,s:45,n:72},
 south:{w:-18,e:39,s:29,n:52},
 balearics:{w:0.1,e:5.25,s:37.9,n:41.15}
};
const MODE={
 dbzh:{name:"CIRRUS · maximale Reflektivität",unit:"dBZ",min:-20,max:75,
        labels:["< −10","−10","0","10","20","30","40","50","60","70+"],
        colors:["#a8d6ee","#66bedc","#2e88cc","#4179cb","#46b97b","#a9d348","#ead34f","#f39a47","#eb5143","#a9288b"],
        stops:[-10,0,10,20,30,40,50,60,70]},
 rate:{name:"NIMBUS · Niederschlagsrate",unit:"mm/h",min:0,max:120,
       labels:["0,1","0,5","1","2","5","10","20","30","50","80","120+"],
       colors:["#a1e6f7","#67c4e3","#2698cf","#3472bd","#50b56b","#abd24c","#e8d245","#f9a346","#eb654b","#cc408f","#8926a6"],
       stops:[.1,.5,1,2,5,10,20,30,50,80,120]}
};
const state={m:null,kind:"dbzh",frame:0,geo:null,cache:new Map(),serial:0,playing:false,timer:null};
const region=()=>VIEWS[$("region").value];
const x=lon=>(lon-region().w)/(region().e-region().w)*canvas.width;
const y=lat=>(region().n-lat)/(region().n-region().s)*canvas.height;
const rgb=hex=>[parseInt(hex.slice(1,3),16),parseInt(hex.slice(3,5),16),parseInt(hex.slice(5,7),16)];
const pal={dbzh:MODE.dbzh.colors.map(rgb),rate:MODE.rate.colors.map(rgb)};
const time=t=>new Date(t).toLocaleString("de-DE",{timeZone:"UTC",
 day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"})+" UTC";
const frames=()=>state.m?.products?.[state.kind]?.frames||[];
function say(message,failed=false){$("status").textContent=message;$("status").className="status"+(failed?" error":"")}
function stop(){state.playing=false;clearTimeout(state.timer);$("play").textContent="▶ Abspielen"}
function base(){
 const r=region();
 ctx.fillStyle="#cce2ed";ctx.fillRect(0,0,canvas.width,canvas.height);
 ctx.strokeStyle="#9bbcd0";ctx.lineWidth=1.2;ctx.setLineDash([6,9]);
 ctx.beginPath();
 for(let lon=-30;lon<=50;lon+=10)if(lon>r.w&&lon<r.e){ctx.moveTo(x(lon),0);ctx.lineTo(x(lon),canvas.height)}
 for(let lat=30;lat<=75;lat+=10)if(lat>r.s&&lat<r.n){ctx.moveTo(0,y(lat));ctx.lineTo(canvas.width,y(lat))}
 ctx.stroke();ctx.setLineDash([]);
}
function geomPath(feature){
 const geo=feature.geometry||{};
 let polys=geo.type==="Polygon"?[geo.coordinates]:geo.type==="MultiPolygon"?geo.coordinates:[];
 for(const poly of polys)for(const ring of poly){
  let prior=NaN;
  for(let j=0;j<ring.length;j++){
    const lon=ring[j][0],lat=ring[j][1],px=x(lon),py=y(lat);
    if(!Number.isFinite(px+py))continue;
    if(j===0||Math.abs(px-prior)>canvas.width*.5)ctx.moveTo(px,py);
    else ctx.lineTo(px,py);
    prior=px;
  }
  ctx.closePath();
 }
}
function mapLand(){
 if(!state.geo)return;
 ctx.save();ctx.beginPath();ctx.rect(0,0,canvas.width,canvas.height);ctx.clip();
 for(const f of state.geo.features||[]){
  ctx.beginPath();geomPath(f);
  ctx.fillStyle="#edf2ed";ctx.fill("evenodd");
 }
 ctx.restore();
}
function mapBorders(){
 if(!state.geo)return;
 ctx.save();ctx.beginPath();ctx.rect(0,0,canvas.width,canvas.height);ctx.clip();
 ctx.beginPath();
 for(const f of state.geo.features||[])geomPath(f);
 ctx.strokeStyle="#30495fd9";ctx.lineWidth=2.1;ctx.stroke();
 ctx.restore();
}
function levelOf(value,kind){
 const list=MODE[kind].stops;
 let i=0;
 for(let j=0;j<list.length;j++)if(value>=list[j])i=j;
 return Math.min(i,pal[kind].length-1);
}
function physical(byte,kind){
 const m=state.m.encoding;
 if(kind==="dbzh")return m.dbzh_range[0]+(byte-1)/253*(m.dbzh_range[1]-m.dbzh_range[0]);
 return m.rate_log_base*Math.expm1((byte-1)/253*Math.log1p(m.rate_max/m.rate_log_base));
}
function coloredImage(image,kind){
 const w=image.naturalWidth,h=image.naturalHeight;
 if(w!==state.m.grid.width||h!==state.m.grid.height)throw Error("Rastergröße des Europakomposits falsch");
 const c=document.createElement("canvas");c.width=w;c.height=h;
 const con=c.getContext("2d",{willReadFrequently:true});
 con.drawImage(image,0,0);
 const id=con.getImageData(0,0,w,h),data=id.data;
 for(let i=0;i<data.length;i+=4){
  const v=data[i];
  if(v===0){data[i+3]=0;continue}
  if(v===255){data[i]=146;data[i+1]=152;data[i+2]=159;data[i+3]=115;continue}
  const color=pal[kind][levelOf(physical(v,kind),kind)];
  data[i]=color[0];data[i+1]=color[1];data[i+2]=color[2];data[i+3]=225;
 }
 con.putImageData(id,0,0);
 return c;
}
function getImage(frame){
 const path=frame.image;
 if(state.cache.has(path))return Promise.resolve(state.cache.get(path));
 return new Promise((resolve,reject)=>{
   const img=new Image();
   img.onload=()=>{
     try{
       const layer=coloredImage(img,path.startsWith("frames/dbzh_")?"dbzh":"rate");
       state.cache.set(path,layer);
       while(state.cache.size>10)state.cache.delete(state.cache.keys().next().value);
       resolve(layer);
     }catch(error){reject(error)}
   };
   img.onerror=()=>reject(Error("Radarbild nicht erreichbar: "+path));
   img.src=API+path;
 });
}
function drawLayer(layer){
 const r=region(),g=state.m.grid;
 const sx=(r.w-g.west)/(g.east-g.west)*layer.width;
 const sy=(g.north-r.n)/(g.north-g.south)*layer.height;
 const sw=(r.e-r.w)/(g.east-g.west)*layer.width;
 const sh=(r.n-r.s)/(g.north-g.south)*layer.height;
 ctx.imageSmoothingEnabled=false;
 ctx.drawImage(layer,sx,sy,sw,sh,0,0,canvas.width,canvas.height);
}
function heading(){
 const frame=frames()[state.frame];
 ctx.save();ctx.fillStyle="#152a42d9";ctx.fillRect(0,0,canvas.width,58);
 ctx.fillStyle="#fff";ctx.font="bold 24px system-ui";
 ctx.fillText("OPERA "+MODE[state.kind].name+" · "+time(frame.utc),14,37);
 ctx.textAlign="right";ctx.font="19px system-ui";
 ctx.fillText("© EUMETNET OPERA · CC BY 4.0",canvas.width-18,36);
 ctx.restore();
}
async function render(){
 if(!state.m)return;
 const seq=++state.serial,frame=frames()[state.frame];
 $("timeline").value=state.frame;
 $("time").textContent=time(frame.utc);
 $("stamp").textContent=MODE[state.kind].name+" · "+time(frame.utc);
 try{
  const layer=await getImage(frame);
  if(seq!==state.serial)return;
  base();mapLand();
  if($("overlay").value==="on")drawLayer(layer);
  mapBorders();heading();
  const delay=Math.max(0,Math.round((Date.now()-Date.parse(frames().at(-1).utc))/60000));
  say("Echtes OPERA-Europakomposit: "+frames().length+" Bilder ("+
    state.m.products[state.kind].cadence_minutes+"-Min-Raster) · letzte Beobachtung vor "+
    delay+" Minuten"+(delay>40?" · Achtung: Datenverzögerung":"")+".");
  const next=frames()[state.frame+1];
  if(next&&!state.cache.has(next.image))getImage(next).catch(()=>{});
 }catch(error){
  if(seq!==state.serial)return;
  stop();base();mapLand();mapBorders();say("OPERA-Bild nicht verfügbar: "+error.message,true);
 }
}
function legend(){
 const kind=state.kind,container=$("legend");
 container.replaceChildren();
 MODE[kind].labels.forEach((str,i)=>{
  const item=document.createElement("div"),sw=document.createElement("div"),text=document.createElement("div");
  item.className="item";sw.className="swatch";sw.style.background=MODE[kind].colors[i];
  text.textContent=str;item.append(sw,text);container.append(item);
 });
 const unit=document.createElement("div");unit.textContent=MODE[kind].unit;unit.style.fontSize="12px";
 container.append(unit);
 $("legendNote").textContent=kind==="dbzh"
 ? "CIRRUS: maximale Radarreflektivität in dBZ, nicht mit mm/h gleichsetzen. Feste Skala: −20 bis +75 dBZ; 1 km / 5 min."
 : "NIMBUS: niederschlagsbezogene Momentanrate in mm/h, nicht die Regensumme von 15 Minuten. Feste Skala bis 120 mm/h; 2 km / 15 min.";
}
function choose(kind){
 if(!state.m)return;
 stop();++state.serial;state.kind=kind;state.frame=frames().length-1;
 for(const k of ["dbzh","rate"])$(k).setAttribute("aria-pressed",String(k===kind));
 $("product").textContent=MODE[kind].name+" · "+state.m.products[kind].native_km+" km";
 $("timeline").max=Math.max(0,frames().length-1);
 legend();render();
}
async function tick(){
 if(!state.playing)return;
 state.frame=(state.frame+1)%frames().length;
 await render();
 if(state.playing)state.timer=setTimeout(tick,Math.round(830/Number($("speed").value)));
}
async function boot(){
 stop();state.serial++;state.cache.clear();say("Prüfe amtliche europäische OPERA-Daten …");
 try{
  const r=await fetch(API+"current.json",{cache:"no-store"});
  if(!r.ok)throw Error(r.status===404?"Erster OPERA-Datenlauf noch nicht veröffentlicht":"HTTP "+r.status);
  const m=await r.json();
  if(m.schema!==1||!m.grid||!m.encoding||m.grid.width!==1480||
     !m.products||!["dbzh","rate"].every(k=>
      Array.isArray(m.products[k]?.frames)&&m.products[k].frames.length>=4&&
      m.products[k].frames.every(f=>/^(?:frames\/(?:dbzh|rate)_\d{12}\.png)$/.test(f.image)))){
    throw Error("Ungültiger oder unvollständiger OPERA-Datensatz");
  }
  state.m=m;
  for(const id of ["previous","play","next","timeline","save"])$(id).disabled=false;
  choose(state.kind);
 }catch(error){
  state.m=null;
  for(const id of ["previous","play","next","timeline","save"])$(id).disabled=true;
  base();mapLand();mapBorders();
  say(error.message+" · keine erfundenen Radarwerte werden gezeigt.",true);
 }
}
$("dbzh").addEventListener("click",()=>choose("dbzh"));
$("rate").addEventListener("click",()=>choose("rate"));
$("region").addEventListener("change",()=>{stop();render()});
$("overlay").addEventListener("change",render);
$("reload").addEventListener("click",boot);
$("timeline").addEventListener("input",()=>{stop();state.frame=Number($("timeline").value);render()});
$("previous").addEventListener("click",()=>{stop();state.frame=Math.max(0,state.frame-1);render()});
$("next").addEventListener("click",()=>{stop();state.frame=Math.min(frames().length-1,state.frame+1);render()});
$("play").addEventListener("click",()=>{
 if(!state.m)return;
 if(state.playing){stop();return}
 state.playing=true;$("play").textContent="❚❚ Pause";
 state.timer=setTimeout(tick,Math.round(830/Number($("speed").value)));
});
$("save").addEventListener("click",()=>{
 if(!state.m)return;
 canvas.toBlob(blob=>{
  if(!blob)return;
  const link=document.createElement("a"),src=URL.createObjectURL(blob);
  link.href=src;link.download="opera-"+state.kind+"-"+frames()[state.frame].utc.replace(/[-:]/g,"").replace("T","_")+".png";
  document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(src),2000);
 },"image/png");
});
fetch("/radarlabor/api/borders_europe.geojson").then(r=>{if(!r.ok)throw Error("Grenzen fehlen");return r.json()})
 .then(geo=>{state.geo=geo;if(state.m)render();else{base();mapLand();mapBorders()}})
 .catch(()=>{});
base();legend();boot();
})();`;
