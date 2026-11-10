/* Raw browser source: do not serialize compiled functions (.toString()).
   Cloudflare bundling can inject helpers not available in inline scripts. */
export const SHAPIRO_CLIENT_SOURCE = String.raw`(function(){
"use strict";
const el=id=>document.getElementById(id);
const cvs=el("synopticMap"),ctx=cvs.getContext("2d",{alpha:false});
const sec=el("crossCanvas"),sx=sec.getContext("2d",{alpha:false});
const API="/dynamik/api/shapiro/";
const regions={
 atlantic:{w:-70,e:45,s:12,n:75},
 europe:{w:-28,e:45,s:32,n:75},
 northeast:{w:-60,e:20,s:35,n:72},
 mediterranean:{w:-25,e:40,s:28,n:56}
};
const config={
 A:{label:"Theta-e 850 hPa",key:"thetae",units:"K",low:260,high:370,
    keys:["thetae","msl","fgen"],text:"Theta-e 850 hPa: farbig. Isobaren alle 4 hPa: schwarz. Kinematische Frontogenese: rot, Frontolyse: blau."},
 B:{label:"850-hPa-Wind",key:"wind850",units:"m/s",low:0,high:85,
    keys:["wind850","wind700","rh700","rh500","u850","v850"],
    text:"Wind 850 hPa: Farben und Pfeile. 700-hPa-Wind: schwarze Konturen. Trockenheit bei 700 und 500 hPa: schwarze Punktschraffur (Hinweis auf Dry Intrusion, kein Sting-Jet-Nachweis)."},
 C:{label:"PV 200–300 hPa",key:"pv",units:"PVU",low:-2,high:15,
    keys:["pv","jet300","gh500","omega700"],
    text:"Näherung der Ertel-PV 200–300 hPa: Farbflächen. Jet 300 hPa: schwarz. Z500: gestrichelt. Aufstieg 700 hPa: rot."}
};
const palettes={
 A:[[0,[37,92,152]],[.18,[91,170,199]],[.37,[151,204,185]],[.52,[241,225,137]],[.71,[233,131,81]],[1,[145,46,85]]],
 B:[[0,[229,244,251]],[.22,[87,183,208]],[.42,[78,175,126]],[.62,[235,223,104]],[.79,[224,111,56]],[1,[143,43,112]]],
 C:[[0,[207,231,247]],[.19,[72,172,205]],[.38,[105,196,155]],[.55,[249,220,119]],[.77,[233,101,79]],[1,[136,35,132]]]
};
const state={m:null,geo:null,mode:"A",frame:0,cache:new Map(),
  serial:0,crossSerial:0,playing:false,timer:null,cross:false,points:[],selected:null};
const fdate=s=>new Date(s).toLocaleString("de-DE",{timeZone:"UTC",day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"})+" UTC";
const view=()=>regions[el("region").value];
const px=lon=>(lon-view().w)/(view().e-view().w)*cvs.width;
const py=lat=>(view().n-lat)/(view().n-view().s)*cvs.height;
const range=name=>state.m.encoding.minmax[name];
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
function status(msg,error=false){el("status").textContent=msg;el("status").className="status"+(error?" error":"")}
function color(phase,q){
 if(q===255||!Number.isFinite(q))return [246,249,252];
 const steps=palettes[phase],v=clamp(q/254,0,1);
 for(let i=1;i<steps.length;i++){
   const a=steps[i-1],b=steps[i];if(v<=b[0]){
     const f=(v-a[0])/(b[0]-a[0]);
     return a[1].map((c,k)=>Math.round(c+(b[1][k]-c)*f));
   }
 }
 return steps[steps.length-1][1];
}
function fieldValue(field,x,y,kind,atlasLevel=null){
 if(!field)return NaN;
 const ix=Math.round(x),iy=Math.round(y),base=atlasLevel===null?0:atlasLevel*state.m.grid.height;
 if(ix<0||ix>=field.w||iy<0||iy>=state.m.grid.height)return NaN;
 const n=field.data[(base+iy)*field.w+ix];
 if(n===255||n===undefined)return NaN;
 const sc=atlasLevel===null?range(kind):state.m.encoding.profile_minmax[kind];
 return sc[0]+(sc[1]-sc[0])*n/254;
}
function getField(path,width,height){
 if(state.cache.has(path))return Promise.resolve(state.cache.get(path));
 return new Promise((resolve,reject)=>{
   const img=new Image();
   img.onload=()=>{
     try{
       if(img.naturalWidth!==width||img.naturalHeight!==height)throw Error("Rasterdimension stimmt nicht");
       const c=document.createElement("canvas");c.width=width;c.height=height;
       const tmp=c.getContext("2d",{willReadFrequently:true});tmp.drawImage(img,0,0);
       const rgba=tmp.getImageData(0,0,width,height).data,mono=new Uint8Array(width*height);
       for(let i=0;i<mono.length;i++)mono[i]=rgba[i*4];
       const field={w:width,h:height,data:mono};
       state.cache.set(path,field);
       while(state.cache.size>40)state.cache.delete(state.cache.keys().next().value);
       resolve(field);
     }catch(error){reject(error)}
   };
   img.onerror=()=>reject(Error("ECMWF-PNG kann nicht geladen werden: "+path));
   img.src=API+path;
 });
}
function rect(){
 const g=state.m.grid,v=view();
 return{x:Math.round((v.w-g.west)/g.step),y:Math.round((g.north-v.n)/g.step),
  w:Math.round((v.e-v.w)/g.step)+1,h:Math.round((v.n-v.s)/g.step)+1};
}
function baseMap(){
 ctx.fillStyle="#e2f0f9";ctx.fillRect(0,0,cvs.width,cvs.height);
 ctx.save();ctx.strokeStyle="#90b3cb";ctx.lineWidth=1;ctx.setLineDash([3,7]);ctx.beginPath();
 for(let lon=-70;lon<=50;lon+=10)if(lon>=view().w&&lon<=view().e){ctx.moveTo(px(lon),0);ctx.lineTo(px(lon),cvs.height)}
 for(let lat=10;lat<=80;lat+=10)if(lat>=view().s&&lat<=view().n){ctx.moveTo(0,py(lat));ctx.lineTo(cvs.width,py(lat))}
 ctx.stroke();ctx.restore();
}
function raster(field,mode){
 const c=document.createElement("canvas");c.width=field.w;c.height=field.h;
 const x=c.getContext("2d"),image=x.createImageData(field.w,field.h);
 for(let i=0;i<field.data.length;i++){
   const rgb=color(mode,field.data[i]);image.data[i*4]=rgb[0];image.data[i*4+1]=rgb[1];image.data[i*4+2]=rgb[2];image.data[i*4+3]=255;
 }
 x.putImageData(image,0,0);
 const r=rect();ctx.imageSmoothingEnabled=true;
 ctx.drawImage(c,r.x,r.y,r.w,r.h,0,0,cvs.width,cvs.height);
}
function borders(){
 if(!state.geo)return;
 ctx.save();ctx.strokeStyle="#3e586aab";ctx.lineWidth=1.2;ctx.beginPath();
 const drawLine=ring=>{
  let lastX=NaN,started=false;
  for(const coord of ring){
    const x=px(coord[0]),y=py(coord[1]);
    if(!Number.isFinite(x+y))continue;
    if(!started||Math.abs(x-lastX)>cvs.width*.35)ctx.moveTo(x,y);
    else ctx.lineTo(x,y);
    started=true;lastX=x;
  }
 };
 for(const feature of state.geo.features||[]){
   const g=feature.geometry||{};
   if(g.type==="Polygon")for(const ring of g.coordinates||[])drawLine(ring);
   if(g.type==="MultiPolygon")for(const poly of g.coordinates||[])for(const ring of poly)drawLine(ring);
 }
 ctx.stroke();ctx.restore();
}
function contour(field,kind,levels,stroke,width=2,dashed=false){
 if(!field)return;
 const r=rect(),stride=3,dx=cvs.width/(r.w-1),dy=cvs.height/(r.h-1);
 const get=(i,j)=>fieldValue(field,i,j,kind);
 ctx.save();ctx.strokeStyle=stroke;ctx.lineWidth=width;ctx.lineJoin="round";
 if(dashed)ctx.setLineDash([8,5]);
 for(const target of levels){
  ctx.beginPath();
  for(let iy=r.y;iy<r.y+r.h-1;iy+=stride){
   for(let ix=r.x;ix<r.x+r.w-1;ix+=stride){
    const ix2=Math.min(ix+stride,field.w-1),iy2=Math.min(iy+stride,field.h-1);
    const pts=[[ix,iy],[ix2,iy],[ix2,iy2],[ix,iy2]];
    const values=pts.map(p=>get(p[0],p[1]));
    if(!values.every(Number.isFinite))continue;
    const intersections=[];
    for(let k=0;k<4;k++){
     const nxt=(k+1)%4,a=values[k],b=values[nxt];
     if((a<target)!==(b<target)){
      const v=(target-a)/(b-a);
      intersections.push([pts[k][0]+v*(pts[nxt][0]-pts[k][0]),
                           pts[k][1]+v*(pts[nxt][1]-pts[k][1])]);
     }
    }
    for(let k=0;k+1<intersections.length;k+=2){
     ctx.moveTo((intersections[k][0]-r.x)*dx,(intersections[k][1]-r.y)*dy);
     ctx.lineTo((intersections[k+1][0]-r.x)*dx,(intersections[k+1][1]-r.y)*dy);
    }
   }
  }
  ctx.stroke();
 }
 ctx.restore();
}
function arrows(u,v){
 if(!u||!v)return;
 const r=rect(),strideX=Math.max(9,Math.round(r.w/36)),strideY=Math.max(9,Math.round(r.h/20));
 const dx=cvs.width/(r.w-1),dy=cvs.height/(r.h-1);
 ctx.save();ctx.strokeStyle="#11273dcf";ctx.lineWidth=2.0;
 for(let y=r.y+5;y<r.y+r.h-4;y+=strideY)for(let x=r.x+5;x<r.x+r.w-4;x+=strideX){
   const uu=fieldValue(u,x,y,"u850"),vv=fieldValue(v,x,y,"v850");
   if(!Number.isFinite(uu+vv)||Math.hypot(uu,vv)<7)continue;
   const a=Math.atan2(-vv,uu),L=clamp(Math.hypot(uu,vv)*.65,9,35);
   const X=(x-r.x)*dx,Y=(y-r.y)*dy;
   ctx.beginPath();ctx.moveTo(X-L*Math.cos(a)/2,Y-L*Math.sin(a)/2);
   ctx.lineTo(X+L*Math.cos(a)/2,Y+L*Math.sin(a)/2);
   for(const sign of [-1,1]){
    ctx.moveTo(X+L*Math.cos(a)/2,Y+L*Math.sin(a)/2);
    ctx.lineTo(X+L*Math.cos(a)/2-6*Math.cos(a+sign*.5),Y+L*Math.sin(a)/2-6*Math.sin(a+sign*.5));
   }
   ctx.stroke();
 }
 ctx.restore();
}
function dryDots(rh700,rh500){
 const r=rect(),dx=cvs.width/(r.w-1),dy=cvs.height/(r.h-1);
 ctx.save();ctx.fillStyle="#243248b8";
 for(let y=r.y+4;y<r.y+r.h;y+=7)for(let x=r.x+4;x<r.x+r.w;x+=7){
  const a=fieldValue(rh700,x,y,"rh700"),b=fieldValue(rh500,x,y,"rh500");
  if(Number.isFinite(a+b)&&a<35&&b<40){
   ctx.beginPath();ctx.arc((x-r.x)*dx,(y-r.y)*dy,2.3,0,Math.PI*2);ctx.fill();
  }
 }
 ctx.restore();
}
function drawMarkers(){
 const frame=state.m?.frames[state.frame];if(!frame)return;
 for(const c of frame.candidates||[]){
  const x=px(c.lon),y=py(c.lat);
  if(x<0||x>cvs.width||y<0||y>cvs.height)continue;
  ctx.save();ctx.lineWidth=3;
  ctx.strokeStyle=state.selected===c.track_id?"#e30069":"#191b2e";
  ctx.fillStyle="#fff3d2";
  ctx.beginPath();ctx.arc(x,y,9,0,7);ctx.fill();ctx.stroke();
  ctx.fillStyle="#171a2d";ctx.font="bold 19px system-ui";
  ctx.fillText("T"+c.track_id+" · "+c.msl_hpa.toFixed(0),x+12,y-11);
  ctx.restore();
 }
 if(state.points.length){
  ctx.save();ctx.strokeStyle="#ee3bba";ctx.fillStyle="#fff";
  ctx.lineWidth=5;ctx.beginPath();
  state.points.forEach((p,i)=>{if(i===0)ctx.moveTo(px(p.lon),py(p.lat));else ctx.lineTo(px(p.lon),py(p.lat))});
  if(state.points.length>1)ctx.stroke();
  for(let i=0;i<state.points.length;i++){
   const p=state.points[i],x=px(p.lon),y=py(p.lat);
   ctx.beginPath();ctx.arc(x,y,9,0,7);ctx.fill();ctx.stroke();
   ctx.font="bold 26px system-ui";ctx.fillStyle="#e90096";ctx.fillText(i?"B":"A",x+13,y-12);
  }
  ctx.restore();
 }
}
function header(){
 const f=state.m.frames[state.frame];
 ctx.save();ctx.fillStyle="#142b40d9";ctx.fillRect(0,0,cvs.width,66);
 ctx.fillStyle="white";ctx.font="bold 28px system-ui";
 ctx.fillText("IFS · "+fdate(f.valid_utc)+" · "+state.mode,18,42);
 ctx.textAlign="right";ctx.font="18px system-ui";ctx.fillText("+"+f.hour+" h  |  Climate Dashboard",cvs.width-20,41);
 ctx.restore();
}
function candidates(){
 const frame=state.m.frames[state.frame];
 const list=el("candidateList");list.replaceChildren();
 if(!frame.candidates?.length){
  list.textContent="Keine auffälligen Druckminima nach den festgelegten Kriterien.";
  el("candidateDetails").textContent="Ohne Hinweis ist ein Shapiro-Keyser-System weder bestätigt noch ausgeschlossen.";
  return;
 }
 for(const c of frame.candidates){
  const b=document.createElement("button");b.type="button";b.className="candidate";
  b.setAttribute("aria-pressed",String(state.selected===c.track_id));
  b.textContent="T"+c.track_id+" · "+c.msl_hpa+" hPa · "+c.lat.toFixed(1)+"°N "+c.lon.toFixed(1)+"°"+
      " · Indikatoren "+c.score+"/4";
  b.addEventListener("click",()=>{
   state.selected=c.track_id;
   const flags=Object.entries(c.criteria).filter(x=>x[1]).map(x=>({
    developed_low:"ausgeprägtes Druckminimum",organized_frontogenesis:"organisierte Frontogenese",
    strong_low_level_wind:"kräftiger 850-hPa-Wind",warm_core_proxy:"wärmerer Theta-e-Kern (Indiz)"
   })[x[0]]||x[0]).join(", ");
   el("candidateDetails").textContent="T"+c.track_id+" · "+c.msl_hpa+" hPa | Tiefdruckausprägung "+
      c.depth_hpa+" hPa | stärkster Wind 850 hPa "+c.wind850_ms+" m/s | Theta-e-Kern minus Umgebung "+
      c.thetae_core_minus_ring_k+" K | Frontogenese "+c.fgen_max_k_100km_3h+
      " K/(100 km·3 h) | Druckänderung seit letztem Treffer "+
      (c.pressure_change_hpa_3h===null?"—":c.pressure_change_hpa_3h+" hPa / 3 h")+
      ". Kriterien: "+flags+". Nur automatische Vorprüfung.";
   candidates();drawUpdated();
  });
  list.appendChild(b);
 }
}
async function render(){
 if(!state.m)return;
 const id=++state.serial,frame=state.m.frames[state.frame],cfg=config[state.mode];
 el("time").textContent=fdate(frame.valid_utc)+" · +"+frame.hour+" h";
 el("legendName").textContent=cfg.label;
 el("legendLow").textContent=cfg.low+" "+cfg.units;
 el("legendHigh").textContent=cfg.high+" "+cfg.units;
 el("panelNote").textContent=cfg.text;
 el("legendBar").style.background="linear-gradient(to right,"+palettes[state.mode].map(p=>"rgb("+p[1].join(",")+") "+Math.round(p[0]*100)+"%").join(",")+")";
 for(const mode of ["A","B","C"])el("view"+mode).setAttribute("aria-pressed",String(mode===state.mode));
 const fields={};
 try{
  await Promise.all(cfg.keys.map(async key=>{
   fields[key]=await getField(frame.maps[key],state.m.grid.width,state.m.grid.height);
  }));
  if(id!==state.serial)return;
  baseMap();raster(fields[cfg.key],state.mode);borders();
  if(state.mode==="A"){
   contour(fields.msl,"msl",Array.from({length:27},(_,i)=>944+4*i),"#111c31",2.1);
   contour(fields.fgen,"fgen",[3,6,10],"#d11c3a",2.4);
   contour(fields.fgen,"fgen",[-3,-6,-10],"#2b4ae6",2.2,true);
  }else if(state.mode==="B"){
   dryDots(fields.rh700,fields.rh500);
   contour(fields.wind700,"wind700",[25,35,45,55,65,75],"#151c2c",2.4);
   arrows(fields.u850,fields.v850);
  }else{
   contour(fields.jet300,"jet300",[30,40,50,60,70,80,90],"#162339",2.5);
   contour(fields.gh500,"gh500",Array.from({length:12},(_,i)=>4800+i*100),"#526a83",1.7,true);
   contour(fields.omega700,"omega700",[-.5,-1,-1.5],"#cb2344",2.3);
  }
  drawMarkers();header();
  status("Echte ECMWF-IFS-Daten · alle benötigten Kartenfelder vollständig geladen.");
 }catch(error){
  if(id!==state.serial)return;
  stop();baseMap();borders();
  status("Diagnosekarte konnte nicht geladen werden: "+error.message,true);
 }
}
function drawUpdated(){if(!state.m)return;render()}
function stop(){state.playing=false;if(state.timer)clearTimeout(state.timer);el("play").textContent="▶ Abspielen"}
async function tick(){
 if(!state.playing)return;
 if(state.frame>=state.m.frames.length-1){stop();return}
 state.frame++;el("slider").value=state.frame;state.selected=null;
 candidates();await render();if(state.points.length===2)renderCross();
 if(state.playing)state.timer=setTimeout(tick,Math.round(1100/Number(el("speed").value)));
}
function sectionPlaceholder(text){
 sx.fillStyle="#edf5fa";sx.fillRect(0,0,sec.width,sec.height);
 sx.fillStyle="#3c5d76";sx.font="22px system-ui";sx.textAlign="center";
 sx.fillText(text,sec.width/2,sec.height/2);sx.textAlign="left";
}
function profileValue(atlas,lon,lat,levelIndex,kind){
 const g=state.m.grid,x=(lon-g.west)/g.step,y=(g.north-lat)/g.step;
 const ix=Math.floor(x),iy=Math.floor(y),tx=x-ix,ty=y-iy;
 if(ix<0||ix+1>=g.width||iy<0||iy+1>=g.height)return NaN;
 const a=fieldValue(atlas,ix,iy,kind,levelIndex),b=fieldValue(atlas,ix+1,iy,kind,levelIndex),
       c=fieldValue(atlas,ix,iy+1,kind,levelIndex),d=fieldValue(atlas,ix+1,iy+1,kind,levelIndex);
 if(![a,b,c,d].every(Number.isFinite))return NaN;
 return (a*(1-tx)+b*tx)*(1-ty)+(c*(1-tx)+d*tx)*ty;
}
async function renderCross(){
 if(!state.m||state.points.length!==2)return;
 const serial=++state.crossSerial,frame=state.m.frames[state.frame],key=el("profile").value;
 el("crossHint").textContent="Lade Profil "+key+" aus echten ECMWF-Druckniveaus …";
 try{
  const g=state.m.grid,levels=state.m.profile_levels_hpa;
  const field=await getField(frame.profiles[key],g.width,g.height*levels.length);
  if(serial!==state.crossSerial||!state.m)return;
  const width=240,height=128,tmp=document.createElement("canvas");
  tmp.width=width;tmp.height=height;const context=tmp.getContext("2d");
  const image=context.createImageData(width,height);
  const a=state.points[0],b=state.points[1],scale=state.m.encoding.profile_minmax[key];
  for(let j=0;j<height;j++){
   const pressure=levels[0]+(levels[levels.length-1]-levels[0])*j/(height-1);
   let upper=0;while(upper<levels.length-2&&levels[upper+1]<pressure)upper++;
   const p0=levels[upper],p1=levels[upper+1],t=(pressure-p0)/(p1-p0);
   for(let i=0;i<width;i++){
    const mix=i/(width-1),lon=a.lon+(b.lon-a.lon)*mix,lat=a.lat+(b.lat-a.lat)*mix;
    const q0=profileValue(field,lon,lat,upper,key),q1=profileValue(field,lon,lat,upper+1,key);
    const good=Number.isFinite(q0)&&Number.isFinite(q1);
    const value=q0*(1-t)+q1*t;
    const n=good?clamp(Math.round((value-scale[0])/(scale[1]-scale[0])*254),0,254):255;
    const rgb=good?color(key==="wind"?"B":key==="theta"?"A":"C",n):[70,77,86];
    const off=(j*width+i)*4;
    image.data[off]=rgb[0];image.data[off+1]=rgb[1];image.data[off+2]=rgb[2];image.data[off+3]=255;
   }
  }
  context.putImageData(image,0,0);
  sx.fillStyle="#ebf3f8";sx.fillRect(0,0,sec.width,sec.height);
  sx.drawImage(tmp,95,24,sec.width-135,sec.height-87);
  sx.strokeStyle="#456078";sx.lineWidth=1.6;sx.font="18px system-ui";sx.fillStyle="#203950";
  for(const hpa of levels){
   const y=24+(hpa-levels[0])/(levels[levels.length-1]-levels[0])*(sec.height-87);
   sx.beginPath();sx.moveTo(95,y);sx.lineTo(sec.width-40,y);sx.stroke();
   sx.fillText(String(hpa)+" hPa",6,y+6);
  }
  sx.font="21px system-ui";
  sx.fillText("A · "+a.lat.toFixed(1)+"°N / "+a.lon.toFixed(1)+"°",95,sec.height-13);
  sx.textAlign="right";sx.fillText("B · "+b.lat.toFixed(1)+"°N / "+b.lon.toFixed(1)+"°",sec.width-35,sec.height-13);
  sx.textAlign="left";
  el("crossHint").textContent="Realer ECMWF-Modellquerschnitt A–B · "+key+
   " · "+fdate(frame.valid_utc)+" · feste Skala "+scale[0]+" bis "+scale[1]+
   " · graue Flächen: unterirdische Druckniveaus / fehlende Werte.";
 }catch(error){
  sectionPlaceholder("Querschnitt nicht verfügbar");
  el("crossHint").textContent="Querschnittfehler: "+error.message;
 }
}
async function boot(){
 stop();state.serial++;state.crossSerial++;state.cache.clear();status("Prüfe vollständigen ECMWF-Datensatz …");
 try{
  const response=await fetch(API+"current.json",{cache:"no-store"});
  if(!response.ok)throw Error(response.status===404?"Noch kein geprüfter Prognoselauf verfügbar":"HTTP "+response.status);
  const m=await response.json();
  const maps=["thetae","msl","fgen","wind850","wind700","rh700","rh500","pv","jet300","gh500","omega700","u850","v850"];
  const profiles=["wind","rh","omega","theta"];
  if(m.schema!==1||!m.grid||!Array.isArray(m.frames)||m.frames.length<2||
     !Array.isArray(m.profile_levels_hpa)||m.profile_levels_hpa.length!==7||
     !m.frames.every(f=>maps.every(k=>typeof f.maps?.[k]==="string")&&profiles.every(k=>typeof f.profiles?.[k]==="string")))
    throw Error("Unvollständiger oder ungültiger ECMWF-Datensatz");
  state.m=m;state.frame=0;state.selected=null;
  el("slider").max=m.frames.length-1;el("slider").value=0;
  for(const id of ["slider","play","save"])el(id).disabled=false;
  el("modelRun").textContent="ECMWF IFS 0,25° · "+fdate(m.initialized_utc);
  candidates();await render();
 }catch(error){
  state.m=null;
  for(const id of ["slider","play","save"])el(id).disabled=true;
  baseMap();borders();
  status(error.message+" · kein Ersatz durch synthetische Wetterfelder.",true);
 }
}
for(const mode of ["A","B","C"])el("view"+mode).addEventListener("click",()=>{
 stop();state.mode=mode;render();
});
el("region").addEventListener("change",()=>{stop();render()});
el("slider").addEventListener("input",()=>{
 stop();state.frame=Number(el("slider").value);state.selected=null;candidates();render();
 if(state.points.length===2)renderCross();
});
el("play").addEventListener("click",()=>{
 if(!state.m)return;
 if(state.playing){stop();return;}
 if(state.frame===state.m.frames.length-1){state.frame=0;el("slider").value=0;}
 state.playing=true;el("play").textContent="❚❚ Pause";render();
 state.timer=setTimeout(tick,Math.round(1100/Number(el("speed").value)));
});
el("reload").addEventListener("click",boot);
el("save").addEventListener("click",()=>{
 if(!state.m)return;
 cvs.toBlob(blob=>{
  if(!blob)return;
  const link=document.createElement("a"),url=URL.createObjectURL(blob);
  link.href=url;link.download="ecmwf-shapiro-"+state.mode+"-"+state.m.cycle+"-t"+state.m.frames[state.frame].hour+".png";
  document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),3000);
 },"image/png");
});
el("crossPick").addEventListener("click",()=>{
 state.cross=!state.cross;el("crossPick").setAttribute("aria-pressed",String(state.cross));
 el("crossHint").textContent=state.cross?"Karte anklicken: "+(state.points.length===0?"Startpunkt A":state.points.length===1?"Endpunkt B":"Neuen Startpunkt A"):
 "Auswahl pausiert. Querschnitt bleibt sichtbar.";
});
el("crossClear").addEventListener("click",()=>{
 state.points=[];state.cross=false;state.crossSerial++;el("crossPick").setAttribute("aria-pressed","false");
 sectionPlaceholder("Zwei Kartenpunkte A und B wählen");el("crossHint").textContent="Linie gelöscht. Auf Karte zwei Punkte für einen neuen Querschnitt wählen.";
 render();
});
el("profile").addEventListener("change",renderCross);
cvs.addEventListener("click",event=>{
 if(!state.cross||!state.m)return;
 const rect=cvs.getBoundingClientRect(),xf=(event.clientX-rect.left)/rect.width,
       yf=(event.clientY-rect.top)/rect.height;
 const r=view(),lon=r.w+clamp(xf,0,1)*(r.e-r.w),lat=r.n-clamp(yf,0,1)*(r.n-r.s);
 if(state.points.length===2)state.points=[];
 state.points.push({lon,lat});
 if(state.points.length===2){
  state.cross=false;el("crossPick").setAttribute("aria-pressed","false");renderCross();
 }else el("crossHint").textContent="Start A gespeichert. Endpunkt B auf Karte wählen.";
 render();
});
fetch("/dynamik/api/boundaries").then(r=>{if(!r.ok)throw Error("Natural Earth");return r.json()})
 .then(g=>{state.geo=g;if(state.m)render()})
 .catch(()=>{});
baseMap();sectionPlaceholder("Zwei Kartenpunkte A und B wählen");boot();
})();`;
