/* Saharastaub: feste wissenschaftliche Legenden, unabhängig von Kartenzeit/-region. */
(() => {
"use strict";
const DATA_URLS=[
  "./data/saharastaub/current.json",
  "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/saharastaub-data/data/saharastaub/current.json"
];
const BASEMAP="./wettergefahren_basemap_50m.json";
const PARAMS=Object.freeze({
  taod:{name:"Staub-AOD",unit:"dimensionslos",breaks:[0.05,0.1,0.2,0.35,0.5,0.75,1,1.5,2.5]},
  column:{name:"Staubmasse der Luftsäule",unit:"mg/m²",breaks:[25,50,100,200,400,800,1600,2500,4000]},
  surface:{name:"Bodennahe Staubkonzentration",unit:"µg/m³",breaks:[1,2,5,10,20,40,80,150,300]}
});
const COLORS=Object.freeze(["#f2f4f7","#e3e7eb","#d8cfb3","#efe08a","#f7c65a","#f39a3c","#ea6b2d","#d63f2f","#9c2f5f","#5a2875"]);
const REGIONS=Object.freeze({
  europe:{name:"Europa und Nordafrika",west:-28,east:60,south:25,north:74},
  germany:{name:"Deutschland",west:5,east:16,south:47,north:56}
});
const $=id=>document.getElementById(id);
const canvas=$("dustMap"),ctx=canvas.getContext("2d",{alpha:false});
const controls={param:$("dustParameter"),region:$("dustRegion"),time:$("dustTime"),
  prev:$("dustPrevious"),next:$("dustNext"),play:$("dustPlay"),png:$("dustPng"),
  refresh:$("dustRefresh"),hide:$("dustHideBackground")};
let forecast=null,basemap=null,index=0,playing=null,gridCache=new Map(),peakCache=new Map();
function status(message,error=false){$("dustStatus").textContent=message;$("dustStatus").classList.toggle("error",error);}
function formatUtc(date){return new Intl.DateTimeFormat("de-DE",{timeZone:"UTC",day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"}).format(new Date(date))+" UTC";}
function boundsLabel(i,breaks){
  const n=v=>Number(v).toLocaleString("de-DE",{maximumFractionDigits:2});
  if(i===0)return "< "+n(breaks[0]);
  if(i===breaks.length)return "≥ "+n(breaks[breaks.length-1]);
  return n(breaks[i-1])+" – < "+n(breaks[i]);
}
function drawLegend(){
  const param=PARAMS[controls.param.value];
  $("dustLegendHeading").textContent="Feste Legende · "+param.name+" ("+param.unit+")";
  $("dustLegend").replaceChildren();
  COLORS.forEach((color,i)=>{
    const el=document.createElement("div");el.className="legend-item";
    const swatch=document.createElement("span");swatch.className="legend-swatch";swatch.style.background=color;
    const label=document.createElement("span");label.textContent=boundsLabel(i,param.breaks);
    el.append(swatch,label);$("dustLegend").append(el);
  });
}
function validate(data){
  if(!data||data.schema!==1||!data.grid||!Array.isArray(data.frames)||!data.frames.length)throw Error("Unbekanntes oder leeres Kartenformat");
  const g=data.grid;
  if(g.encoding!=="rle-u8-base64"||!Number.isInteger(g.rows)||!Number.isInteger(g.cols)||g.rows<1||g.cols<1||g.rows*g.cols>500000)throw Error("Ungültige Kartengeometrie");
  for(const [key,param] of Object.entries(PARAMS)){
    const server=data.palettes?.[key];
    if(key==="surface"&&!server)continue; // Older published data remain readable.
    if(!server||JSON.stringify(server.breaks)!==JSON.stringify(param.breaks)||JSON.stringify(server.colors)!==JSON.stringify(COLORS))throw Error("Farbskala von "+key+" weicht von der festgelegten Legende ab");
  }
  const hours=new Set();
  for(const frame of data.frames){
    if(!Number.isInteger(frame.hour)||hours.has(frame.hour)||!frame.valid_utc||typeof frame.taod!=="string"||typeof frame.column!=="string")throw Error("Unvollständige Vorhersagezeit");
    hours.add(frame.hour);
  }
  return data;
}
function unpack(encoded,total){
  const binary=atob(encoded);
  if(binary.length%3)throw Error("Ungültige Rasterkodierung");
  const out=new Uint8Array(total);let offset=0;
  for(let i=0;i<binary.length;i+=3){
    const code=binary.charCodeAt(i),count=binary.charCodeAt(i+1)+256*binary.charCodeAt(i+2);
    if(!count||offset+count>total||(code>9&&code!==255))throw Error("Ungültiger Rasterwert");
    out.fill(code,offset,offset+count);offset+=count;
  }
  if(offset!==total)throw Error("Unvollständige Rasterdaten");
  return out;
}
function imageFor(frame,key){
  const hiddenBackground=controls.hide.checked;
  const cacheKey=frame.hour+"|"+key+"|"+hiddenBackground;
  if(gridCache.has(cacheKey))return gridCache.get(cacheKey);
  const {rows,cols}=forecast.grid;
  if(typeof frame?.[key]!=="string")return null;
  const values=unpack(frame[key],rows*cols);
  const off=document.createElement("canvas");off.width=cols;off.height=rows;
  const c=off.getContext("2d");
  const img=c.createImageData(cols,rows);
  const rgb=COLORS.map(hex=>[parseInt(hex.slice(1,3),16),parseInt(hex.slice(3,5),16),parseInt(hex.slice(5,7),16)]);
  for(let i=0;i<values.length;i++){
    const value=values[i],src=4*((rows-1-Math.floor(i/cols))*cols+i%cols);
    // Optional display-only mask. The exported map keeps the identical fixed legend.
    if(value===255 || (hiddenBackground && value<=1)){img.data[src+3]=0;continue;}
    const col=rgb[value];img.data[src]=col[0];img.data[src+1]=col[1];img.data[src+2]=col[2];img.data[src+3]=255;
  }
  c.putImageData(img,0,0);
  gridCache.set(cacheKey,off);if(gridCache.size>8)gridCache.delete(gridCache.keys().next().value);
  return off;
}
function drawBorders(region,rect){
  if(!basemap||!Array.isArray(basemap.countries))return;
  const x=lon=>rect.x+(lon-region.west)/(region.east-region.west)*rect.w;
  const y=lat=>rect.y+(region.north-lat)/(region.north-region.south)*rect.h;
  ctx.save();ctx.beginPath();ctx.rect(rect.x,rect.y,rect.w,rect.h);ctx.clip();
  ctx.lineWidth=region===REGIONS.germany?1.6:.65;ctx.strokeStyle="rgba(43,57,73,.6)";
  for(const country of basemap.countries){
    for(const polygon of (country.p||[])){
      for(const ring of polygon){
        if(!Array.isArray(ring)||ring.length<3)continue;
        ctx.beginPath();
        ring.forEach((point,i)=>{if(i===0)ctx.moveTo(x(point[0]),y(point[1]));else ctx.lineTo(x(point[0]),y(point[1]));});
        ctx.closePath();ctx.stroke();
      }
    }
  }
  ctx.restore();
}
function encodeRuns(values){
  const bytes=[];
  for(let i=0;i<values.length;){let j=i+1;while(j<values.length&&j-i<65535&&values[j]===values[i])j++;
    const n=j-i;bytes.push(values[i],n&255,n>>8);i=j;}
  let binary="";for(let i=0;i<bytes.length;i+=16384)binary+=String.fromCharCode(...bytes.slice(i,i+16384));
  return btoa(binary);
}
function peakFrame(key,hours){
  const cacheKey=forecast.run_utc+"|"+key+"|"+hours;
  if(peakCache.has(cacheKey))return peakCache.get(cacheKey);
  const eligible=forecast.frames.filter(f=>f.hour<=hours&&typeof f[key]==="string");
  if(!eligible.length)return null;
  const length=forecast.grid.rows*forecast.grid.cols;
  const combined=new Uint8Array(length).fill(255);
  for(const frame of eligible){const values=unpack(frame[key],length);
    for(let i=0;i<length;i++)if(values[i]!==255&&(combined[i]===255||values[i]>combined[i]))combined[i]=values[i];}
  const result={hour:hours,valid_utc:eligible[eligible.length-1].valid_utc,[key]:encodeRuns(combined),peak:true};
  peakCache.set(cacheKey,result);return result;
}
function render(){
  drawLegend();
  ctx.fillStyle="#fff";ctx.fillRect(0,0,canvas.width,canvas.height);
  const region=REGIONS[controls.region.value],param=PARAMS[controls.param.value];
  const windowHours=Number($("dustView")?.value||0);
  const frame=forecast?(windowHours?peakFrame(controls.param.value,windowHours):forecast.frames[index]):null;
  const plot={x:90,y:110,w:1100,h:580};
  // Fixed geographic aspect ratio (no distortion when switching to Germany).
  const ratio=(region.east-region.west)/(region.north-region.south),maxRatio=plot.w/plot.h;
  const rect=ratio>maxRatio?{x:plot.x,y:plot.y+(plot.h-plot.w/ratio)/2,w:plot.w,h:plot.w/ratio}:
    {x:plot.x+(plot.w-plot.h*ratio)/2,y:plot.y,w:plot.h*ratio,h:plot.h};
  ctx.fillStyle="#172b41";ctx.font="bold 28px system-ui";ctx.fillText("Saharastaub · "+param.name,80,45);
  ctx.fillStyle="#516478";ctx.font="20px system-ui";ctx.fillText(region.name+(windowHours?" · Maximum 0–"+windowHours+" h (Farbklasse)":""),80,78);
  ctx.textAlign="right";ctx.fillText(frame?formatUtc(frame.valid_utc):"Keine Vorhersagedaten",1200,77);ctx.textAlign="left";
  ctx.fillStyle="#e9eef3";ctx.fillRect(rect.x,rect.y,rect.w,rect.h);
  if(frame){
    const g=forecast.grid,img=imageFor(frame,controls.param.value);
    if(img){const x=(region.west-g.lon_min)/g.step,y=(g.lat_min+g.rows*g.step-region.north)/g.step;
    const w=(region.east-region.west)/g.step,h=(region.north-region.south)/g.step;
    ctx.imageSmoothingEnabled=false;ctx.drawImage(img,x,y,w,h,rect.x,rect.y,rect.w,rect.h);}
  }
  drawBorders(region,rect);
  ctx.strokeStyle="#a7b8c7";ctx.lineWidth=1.5;ctx.strokeRect(rect.x,rect.y,rect.w,rect.h);
  if(controls.hide.checked){
    ctx.fillStyle="#47677b";ctx.font="15px system-ui";
    ctx.fillText("Darstellung: schwacher Hintergrund unter "+param.breaks[1].toLocaleString("de-DE")+" ausgeblendet",82,720);
  }
  ctx.fillStyle="#243c52";ctx.font="18px system-ui";ctx.fillText("Feste Farbskala · "+param.unit+" · kein automatisches Rescaling",82,735);
  const width=1100/COLORS.length;
  COLORS.forEach((color,i)=>{ctx.fillStyle=color;ctx.fillRect(85+i*width,755,width,24);});
  ctx.strokeStyle="#d4dce4";ctx.strokeRect(85,755,1100,24);
  ctx.fillStyle="#314c62";ctx.font="15px system-ui";ctx.textAlign="center";
  COLORS.forEach((c,i)=>ctx.fillText(boundsLabel(i,param.breaks),85+(i+.5)*width,804));ctx.textAlign="left";
  ctx.fillStyle="#576b7c";ctx.font="15px system-ui";
  ctx.fillText("DWD ICON-ART-EU · Modelllauf "+(forecast?formatUtc(forecast.run_utc):"–")+" · 0,2°-Kartenraster",84,835);
  $("dustMapNote").textContent=controls.hide.checked
    ? "Die festen Klassen bleiben unverändert. Die beiden untersten Klassen (< "+param.breaks[1].toLocaleString("de-DE")+" "+param.unit+") werden nur in der Karte ausgeblendet; der PNG-Export übernimmt diese Darstellung. Weiß bzw. graublau außerhalb der Datenregion kennzeichnet fehlende Daten."
    : "Die Farbskala ist für jede Modellstunde und Region fest. Neutrale Grautöne kennzeichnen geringe Staubmengen; fehlende Daten außerhalb des Modellgebiets bleiben ungefärbt.";
  $("dustMapTitle").textContent=param.name+" · "+region.name;
  $("dustValid").textContent=windowHours?"Maximalklasse aus +0 bis +"+windowHours+" h":"Gültigkeit: "+(frame?formatUtc(frame.valid_utc):"–");
  if(forecast&&!frame)status("Für diesen Parameter und Zeitraum sind keine geprüften Daten vorhanden.",true);
}
function stop(){if(playing!==null)clearInterval(playing);playing=null;controls.play.textContent="▶ Film";}
function select(indexNext){if(!forecast)return;index=Math.max(0,Math.min(forecast.frames.length-1,indexNext));controls.time.value=String(index);controls.prev.disabled=index===0;controls.next.disabled=index===forecast.frames.length-1;render();}
function reloadOptions(){
  controls.time.replaceChildren();
  forecast.frames.forEach((frame,i)=>{
    const o=document.createElement("option");o.value=String(i);o.textContent="+"+frame.hour+" h · "+formatUtc(frame.valid_utc);controls.time.appendChild(o);
  });
  controls.time.disabled=false;controls.play.disabled=forecast.frames.length<2;controls.png.disabled=false;
  const age=(Date.now()-Date.parse(forecast.run_utc))/3600000;
  $("dustRun").textContent="ICON-ART-EU-Lauf: "+formatUtc(forecast.run_utc)+" · bis +"+forecast.frames.at(-1).hour+" h · Daten erstellt: "+formatUtc(forecast.generated_utc);
  status((age>18?"Hinweis: Der letzte verfügbare Modelllauf ist älter als 18 Stunden. ":"")+"Echte ICON-ART-EU-Prognose geladen. Die Legendenwerte bleiben unverändert.",age>18);
  select(0);
}
async function load(){
  stop();controls.refresh.disabled=true;status("ICON-ART-EU-Karten werden geprüft …");
  const bust="?cache="+Math.floor(Date.now()/600000);
  try{
    let data=null,errors=[];
    for(const url of DATA_URLS){
      try{
        const response=await fetch(url+bust,{cache:"no-store"});
        if(!response.ok)throw Error("HTTP "+response.status);
        data=validate(await response.json());break;
      }catch(e){errors.push(e.message);}
    }
    if(!data)throw Error("Noch kein gültiger ICON-ART-Datenlauf veröffentlicht ("+errors.join("; ")+")");
    forecast=data;index=0;gridCache.clear();peakCache.clear();reloadOptions();
    document.dispatchEvent(new CustomEvent("sahara-data-ready"));
  }catch(e){
    forecast=null;gridCache.clear();peakCache.clear();document.dispatchEvent(new CustomEvent("sahara-data-ready"));
    controls.time.disabled=true;controls.time.replaceChildren();
    controls.prev.disabled=true;controls.next.disabled=true;controls.play.disabled=true;controls.png.disabled=true;
    $("dustRun").textContent="Letzter Modelllauf: nicht verfügbar";
    status("Keine überprüften Saharastaub-Karten verfügbar: "+e.message,true);render();
  }finally{controls.refresh.disabled=false;}
}
window.SaharaDustAPI={getForecast:()=>forecast,unpack,params:PARAMS};
$("dustView")?.addEventListener("change",()=>{stop();render();document.dispatchEvent(new CustomEvent("sahara-view-change"));});
controls.param.addEventListener("change",()=>{render();document.dispatchEvent(new CustomEvent("sahara-view-change"));});
controls.region.addEventListener("change",render);
controls.hide.addEventListener("change",()=>{gridCache.clear();render();});
controls.time.addEventListener("change",()=>{stop();select(Number(controls.time.value));});
controls.prev.addEventListener("click",()=>{stop();select(index-1);});
controls.next.addEventListener("click",()=>{stop();select(index+1);});
controls.play.addEventListener("click",()=>{
  if(playing!==null){stop();return;}
  if(!forecast||forecast.frames.length<2)return;
  controls.play.textContent="■ Stop";
  playing=setInterval(()=>select((index+1)%forecast.frames.length),1100);
});
controls.refresh.addEventListener("click",load);
controls.png.addEventListener("click",()=>{
  if(!forecast)return;
  render();
  canvas.toBlob(blob=>{
    if(!blob)return status("PNG-Export fehlgeschlagen",true);
    const url=URL.createObjectURL(blob),a=document.createElement("a");
    a.href=url;a.download="saharastaub_"+controls.param.value+"_"+controls.region.value+"_"+forecast.run_utc.slice(0,10)+($("dustView").value==="instant"?"_p"+forecast.frames[index].hour:"_max"+$("dustView").value)+"h.png";
    document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  },"image/png");
});
document.addEventListener("keydown",e=>{
  if(!forecast||e.altKey||e.ctrlKey||e.metaKey||["INPUT","SELECT","TEXTAREA"].includes(document.activeElement?.tagName))return;
  if(e.key==="ArrowLeft"||e.key==="ArrowRight"){e.preventDefault();stop();select(index+(e.key==="ArrowLeft"?-1:1));}
});
document.addEventListener("visibilitychange",()=>{if(document.hidden)stop();});
drawLegend();render();
fetch(BASEMAP).then(r=>{if(!r.ok)throw Error("Grenzen fehlen");return r.json();}).then(data=>{
  if(!Array.isArray(data.countries))throw Error("Ländergrenzen nicht vorhanden");
  basemap=data;render();
}).catch(()=>{status("Hinweis: Ländergrenzen konnten nicht geladen werden.",true);});
load();
})();
