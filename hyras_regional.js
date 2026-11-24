/* HYRAS regional workshop — native raster, projected boundaries and DWD observations.
 * Boundaries: deutschlandGeoJSON (GIS-DATA, public-domain archive); not a current BKG product.
 * Numerical data are never resampled to invent meteorological resolution. */
(function(root){
"use strict";
const states=["Deutschland","Baden-Württemberg","Bayern","Berlin","Brandenburg","Bremen","Hamburg","Hessen","Mecklenburg-Vorpommern","Niedersachsen","Nordrhein-Westfalen","Rheinland-Pfalz","Saarland","Sachsen","Sachsen-Anhalt","Schleswig-Holstein","Thüringen"];
const geoUrl="https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/1_sehr_hoch.geo.json";
const stationBase="europe_stations/dwd_daily_map/";
const $=id=>document.getElementById(id);
const cache=new Map();
let source=null,revision=0,display=null,stationRequest=null,projectedCache=null;
function get(url,kind="json"){
 const key=kind+":"+url;
 if(!cache.has(key)){
  const p=fetch(url).then(async r=>{
   if(!r.ok)throw Error("HTTP "+r.status+" ("+url.split("/").pop()+")");
   if(kind==="json")return r.json();
   const b=new Uint8Array(await r.arrayBuffer());
   if(b[0]===31&&b[1]===139){
    if(!root.DecompressionStream)throw Error("Browser unterstützt keine gzip-Daten");
    return new Response(new Blob([b]).stream().pipeThrough(new DecompressionStream("gzip"))).json();
   }
   return JSON.parse(new TextDecoder().decode(b));
  }).catch(e=>{cache.delete(key);throw e});
  cache.set(key,p);
 }
 return cache.get(key);
}
function bracket(a,v){
 if(v<=a[0])return [0,1,(v-a[0])/(a[1]-a[0])];
 const n=a.length-1;
 if(v>=a[n])return [n-1,n,(v-a[n-1])/(a[n]-a[n-1])];
 let l=0,h=n;while(h-l>1){const m=(l+h)>>1;if(a[m]<=v)l=m;else h=m}
 return [l,h,(v-a[l])/(a[h]-a[l])];
}
function coordinate(g,x,y){
 const [a,b,u]=bracket(g.x_indices,x),[c,d,v]=bracket(g.y_indices,y);
 const f=t=>(1-u)*(1-v)*t[c][a]+u*(1-v)*t[c][b]+(1-u)*v*t[d][a]+u*v*t[d][b];
 return [f(g.lon),f(g.lat)];
}
// Invert the published HYRAS grid lookup, rather than treating lon/lat as a rectangular image.
function project(g,lon,lat){
 let x=(g.width-1)/2,y=(g.height-1)/2;
 for(let n=0;n<9;n++){
  const a=coordinate(g,x,y),b=coordinate(g,x+1,y),c=coordinate(g,x,y+1);
  const dx=lon-a[0],dy=lat-a[1],p=b[0]-a[0],q=c[0]-a[0],r=b[1]-a[1],s=c[1]-a[1],det=p*s-q*r;
  if(!Number.isFinite(det)||Math.abs(det)<1e-12)return null;
  x+=(s*dx-q*dy)/det;y+=(p*dy-r*dx)/det;
  if(Math.abs(dx)+Math.abs(dy)<1e-8)break;
 }
 const v=coordinate(g,x,y);
 return Number.isFinite(x)&&Number.isFinite(y)&&Math.abs(v[0]-lon)+Math.abs(v[1]-lat)<.001?[x+.5,y+.5]:null;
}
function normalized(s){return String(s||"").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/ß/g,"ss").replace(/[^a-z]/g,"")}
function featureName(f){return f.properties?.name||f.properties?.NAME||f.properties?.GEN||""}
function polygons(f){return f.geometry?.type==="Polygon"?[f.geometry.coordinates]:f.geometry?.type==="MultiPolygon"?f.geometry.coordinates:[]}
function extent(polys,w,h){
 let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
 for(const poly of polys)for(const ring of poly)for(const p of ring){x0=Math.min(x0,p[0]);x1=Math.max(x1,p[0]);y0=Math.min(y0,p[1]);y1=Math.max(y1,p[1])}
 if(!Number.isFinite(x0))throw Error("Keine Regionsgeometrie verfügbar");
 const pad=Math.max(5,.045*Math.max(x1-x0,y1-y0));
 x0=Math.max(0,Math.floor(x0-pad));y0=Math.max(0,Math.floor(y0-pad));x1=Math.min(w,Math.ceil(x1+pad));y1=Math.min(h,Math.ceil(y1+pad));
 if(x1<=x0||y1<=y0)throw Error("Region außerhalb des Rasters");
 return {x:x0,y:y0,w:x1-x0,h:y1-y0};
}
function makePath(ctx,polys){ctx.beginPath();for(const poly of polys)for(const ring of poly){if(ring.length<3)continue;ctx.moveTo(ring[0][0],ring[0][1]);for(let i=1;i<ring.length;i++)ctx.lineTo(ring[i][0],ring[i][1]);ctx.closePath()}}
function isoDates(start,end){
 if(!/^\d{4}-\d{2}-\d{2}$/.test(start||"")||!/^\d{4}-\d{2}-\d{2}$/.test(end||"")||start>end)return [];
 let t=Date.parse(start+"T00:00:00Z"),last=Date.parse(end+"T00:00:00Z");
 if(!Number.isFinite(t)||!Number.isFinite(last)||(last-t)/86400000>366)return [];
 const dates=[];for(;t<=last;t+=86400000)dates.push(new Date(t).toISOString().slice(0,10));return dates;
}
function accumulate(days,field){
 const sums=new Map();
 for(const payload of days){
  const seen=new Set();
  for(const row of payload.rows||[]){
   const i=Number(row[0]),v=row[field];
   if(!Number.isInteger(i)||seen.has(i)||v===null||v===undefined||!Number.isFinite(Number(v)))continue;
   seen.add(i);const a=sums.get(i)||[0,0];a[0]+=Number(v)/10;a[1]++;sums.set(i,a);
  }
 }
 return new Map([...sums].filter(([,a])=>a[1]===days.length).map(([i,a])=>[i,a[0]/a[1]]));
}
function install(){
 if($("hyrasRegionalWorkshop"))return;
 const frame=$("hyrasMapFrame"),card=frame?.closest(".hyras-map-card");if(!card)return;
 const el=document.createElement("details");el.id="hyrasRegionalWorkshop";el.className="hyras-map-card";
 el.innerHTML='<summary style="cursor:pointer;font-weight:800;font-size:18px">Regionale HYRAS-Karten · HD / Stationswerte</summary>'+
 '<p class="note">Eigenständige Kartenausschnitte aus der aktuell ausgewählten HYRAS-Rasterdarstellung. Keine künstliche Erhöhung der meteorologischen Auflösung.</p>'+
 '<div class="hyras-reg-controls">'+
 '<label>Region <select id="hyrasRegRegion">'+states.map(s=>'<option>'+s+'</option>').join("")+'</select></label>'+
 '<label>PNG-Kantenlänge <select id="hyrasRegSize"><option value="2000">2.000 px</option><option value="4000" selected>4.000 px</option><option value="8000">8.000 px</option></select></label>'+
 '<label><input id="hyrasRegStations" type="checkbox" checked> DWD-Stationen</label>'+
 '<label><input id="hyrasRegNames" type="checkbox"> Stationsnamen</label>'+
 '<label><input id="hyrasRegValues" type="checkbox" checked> Messwerte</label>'+
 '<label><input id="hyrasRegNeighbors" type="checkbox"> Umgebung anzeigen</label></div>'+
 '<p id="hyrasRegStatus" class="note" role="status">Zuerst eine numerische HYRAS-Karte laden.</p>'+
 '<div id="hyrasRegPreview" class="hyras-reg-preview"></div>'+
 '<p id="hyrasRegInspection" class="note" aria-live="polite"></p>'+
 '<div class="hyras-map-actions"><button type="button" class="action" id="hyrasRegPng" disabled>PNG herunterladen</button><button type="button" class="action" id="hyrasRegPdf" disabled>PDF herunterladen</button></div>'+
 '<p class="note">Quellen: DWD HYRAS-DE / DWD CDC Tageswerte KL; Grenzen: deutschlandGeoJSON (GIS-DATA, Archivstand 2022 oder älter). Stationswerte nur bei vollständigen Tagesdaten im gewählten Zeitraum und passender Referenz.</p>';
 const style=document.createElement("style");
 style.textContent=".hyras-reg-controls{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;margin:12px 0}.hyras-reg-controls label{display:flex;align-items:center;gap:7px;flex-wrap:wrap;font-size:13px}.hyras-reg-controls select{max-width:100%;padding:6px}.hyras-reg-preview{background:#fff;overflow:hidden;border-radius:7px}.hyras-reg-preview canvas{display:block;width:100%;height:auto;touch-action:pan-y}.hyras-reg-controls input{width:auto}@media(max-width:650px){.hyras-reg-controls label{max-width:100%}}";
 document.head.append(style);card.before(el);
 el.addEventListener("toggle",()=>{if(el.open)refresh()});
 for(const id of ["hyrasRegRegion","hyrasRegStations","hyrasRegNames","hyrasRegValues","hyrasRegNeighbors"]){$(id).addEventListener("change",refresh)}
 $("hyrasRegPng").onclick=()=>download("png");$("hyrasRegPdf").onclick=()=>download("pdf");
 const watch=new MutationObserver(()=>{if(source&&!source.owner?.isConnected){source=null;revision++;display=null;clear("Diese Ansicht besitzt derzeit kein unterstütztes numerisches Raster. Bitte eine andere HYRAS-Karte wählen.")}});
 watch.observe(frame,{childList:true,subtree:true});
}
function clear(message){
 if($("hyrasRegStatus"))$("hyrasRegStatus").textContent=message;
 if($("hyrasRegPreview"))$("hyrasRegPreview").replaceChildren();
 if($("hyrasRegInspection"))$("hyrasRegInspection").textContent="";
 for(const id of ["hyrasRegPng","hyrasRegPdf"])if($(id))$(id).disabled=true;
}
function legendFrom(node){
 return Array.from(node?.querySelectorAll("span")||[]).map(e=>({label:e.textContent.trim(),color:e.querySelector("i")?.style.backgroundColor||e.querySelector("i")?.style.background})).filter(x=>x.color&&x.label);
}
async function loadGeometry(s){
 const [g,j]=await Promise.all([get(s.lookupUrl),get(geoUrl)]);
 if(g.width!==s.canvas.width||g.height!==s.canvas.height)throw Error("Georeferenz und Originalraster stimmen nicht überein.");
 if(projectedCache?.g===g&&projectedCache?.j===j)return projectedCache;
 if(!Array.isArray(j.features)||j.features.length<16)throw Error("Bundeslandgrenzen fehlen");
 const items=j.features.map(f=>({name:featureName(f),polys:polygons(f).map(poly=>poly.map(ring=>ring.map(p=>project(g,p[0],p[1])).filter(Boolean))).filter(poly=>poly[0]?.length>=3)}));
 if(states.slice(1).some(n=>!items.some(f=>normalized(f.name)===normalized(n))))throw Error("Bundesland-Namen stimmen nicht mit dem Grenzdatensatz überein.");
 projectedCache={g,j,items};return projectedCache;
}
async function stationIndex(){
 if(!stationRequest)stationRequest=get(stationBase+"index.json","json").catch(e=>{stationRequest=null;throw e});
 return stationRequest;
}
async function stationData(s,geo,region,wantValues){
 const idx=await stationIndex();
 if(!idx.ready||!Array.isArray(idx.stations)||!Array.isArray(idx.dates))throw Error("DWD-Tagesstationsarchiv nicht verfügbar.");
 let values=new Map(),note="DWD-KL-Stationsstandorte (aktuelles Stationsverzeichnis).";
 const dates=isoDates(s.start,s.end);
 const field={tmean:12,tmax:3,tmin:4}[s.parameter];
 if(wantValues&&field!==undefined&&s.metric==="anomaly"&&s.reference==="1991-2020"&&dates.length&&dates.every(d=>idx.dates.includes(d))){
  const payloads=[];
  for(let i=0;i<dates.length;i+=8){
   const next=await Promise.all(dates.slice(i,i+8).map(d=>get(stationBase+"calendar/"+d.slice(5)+".json.gz?v="+encodeURIComponent(idx.generated_at||""),"gzip")));
   next.forEach((p,k)=>{if(p.date!==dates[i+k]||!Array.isArray(p.rows)||!String(p.reference_period).includes("1991"))throw Error("Falscher DWD-Tagesdatensatz");payloads.push(p)});
  }
  values=accumulate(payloads,field);
  note="DWD: Anomalie aus "+dates.length+" vollständigen Tageswerten je Station, Referenz 1991–2020.";
 }else if(wantValues){
  note=field===undefined?"Nur KL-Stationsstandorte: Niederschlagsmesswerte sind noch nicht angebunden.":s.reference!=="1991-2020"?"Nur Standorte: Stationsreferenz 1961–1990 fehlt.":"Nur Standorte: Für diesen Zeitraum fehlen vollständige passende DWD-Tagesdateien.";
 }
 const stations=idx.stations.flatMap((row,i)=>{
  if(region!=="Deutschland"&&normalized(row[6])!==normalized(region)&&!$("hyrasRegNeighbors").checked)return [];
  const p=project(geo.g,Number(row[4]),Number(row[3]));
  return p?[{name:row[2],id:row[1],elev:row[5],p,value:values.get(i),state:row[6]}]:[];
 });
 return {stations,note};
}
function renderCanvas(d,maxEdge){
 const {s,b,features,selected,region,stations,legend,neighbors,names,values}=d;
 const u=Math.max(1,maxEdge/1000),pad=Math.round(18*u),top=Math.round(76*u);
 const estimatedWidth=Math.min(maxEdge-2*pad,(maxEdge-top-130*u)*b.w/b.h);
 const font=Math.round(12*u),legendCols=Math.max(1,Math.min(5,Math.floor(estimatedWidth/(150*u)))),legendRows=Math.ceil(legend.length/legendCols);
 const footer=Math.round((48+legendRows*22)*u);
 const scale=Math.min((maxEdge-2*pad)/b.w,(maxEdge-top-footer)/b.h);
 const w=Math.max(1,Math.floor(b.w*scale)),h=Math.max(1,Math.floor(b.h*scale));
 const cv=document.createElement("canvas");cv.width=w+2*pad;cv.height=h+top+footer;const ctx=cv.getContext("2d");
 if(!ctx)throw Error("Canvas konnte nicht erzeugt werden");
 ctx.fillStyle="#ffffff";ctx.fillRect(0,0,cv.width,cv.height);ctx.fillStyle="#192630";ctx.font="bold "+Math.round(22*u)+"px sans-serif";
 ctx.fillText("HYRAS · "+region,pad,28*u,cv.width-pad*2);
 ctx.font=Math.round(14*u)+"px sans-serif";ctx.fillText(s.title||"",pad,48*u,cv.width-pad*2);
 ctx.font=Math.round(12*u)+"px sans-serif";ctx.fillText((s.subtitle||"")+" · Raster "+s.resolution+" km",pad,65*u,cv.width-pad*2);
 ctx.save();ctx.translate(pad,top);ctx.scale(w/b.w,h/b.h);ctx.translate(-b.x,-b.y);
 ctx.beginPath();ctx.rect(b.x,b.y,b.w,b.h);ctx.clip();
 if(region!=="Deutschland"&&!neighbors){makePath(ctx,selected);ctx.clip("evenodd")}
 ctx.imageSmoothingEnabled=false;ctx.drawImage(s.canvas,0,0);
 ctx.lineJoin="round";ctx.lineCap="round";
 for(const f of features){makePath(ctx,f.polys);ctx.strokeStyle="#343a40";ctx.lineWidth=(region===f.name?1.5:.65)*u/scale;ctx.stroke()}
 ctx.restore();
 ctx.strokeStyle="#c9cfd4";ctx.lineWidth=u;ctx.strokeRect(pad,top,w,h);
 // Stations use a fixed graphic scale, with deterministic collision avoidance for labels.
 const hits=[],boxes=[];const fmt=v=>(v>0?"+":"")+v.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1});
 ctx.font="bold "+Math.round(12*u)+"px sans-serif";
 const sorted=stations.slice().sort((a,b)=>(Number.isFinite(b.value)?1:0)-(Number.isFinite(a.value)?1:0)||String(a.id).localeCompare(String(b.id)));
 ctx.save();ctx.beginPath();ctx.rect(pad,top,w,h);ctx.clip();
 for(const st of sorted){
  const x=pad+(st.p[0]-b.x)*w/b.w,y=top+(st.p[1]-b.y)*h/b.h;if(x<pad||x>pad+w||y<top||y>top+h)continue;
  const has=Number.isFinite(st.value);ctx.beginPath();ctx.arc(x,y,3.3*u,0,2*Math.PI);ctx.fillStyle=has?"#ffffff":"#d3d9df";ctx.fill();ctx.strokeStyle="#1d242b";ctx.lineWidth=1.2*u;ctx.stroke();
  hits.push({...st,x,y});
  const label=[values&&has?fmt(st.value):"",names?st.name:""].filter(Boolean).join(" · ");
  if(!label)continue;
  const tw=ctx.measureText(label).width,th=15*u;
  for(const [dx,dy] of [[7,-5],[-7,-5],[7,15],[-7,15]]){
   const tx=x+dx*u-(dx<0?tw:0),ty=y+dy*u;
   const box=[tx-2*u,ty-th,tx+tw+2*u,ty+3*u];
   if(box[0]<pad||box[1]<top||box[2]>pad+w||box[3]>top+h||boxes.some(a=>!(a[2]<box[0]||a[0]>box[2]||a[3]<box[1]||a[1]>box[3])))continue;
   boxes.push(box);ctx.strokeStyle="white";ctx.lineWidth=3*u;ctx.strokeText(label,tx,ty);ctx.fillStyle="#182027";ctx.fillText(label,tx,ty);break;
  }
 }
 ctx.restore();ctx.font=font+"px sans-serif";
 legend.forEach((l,i)=>{const col=i%legendCols,row=Math.floor(i/legendCols),x=pad+col*w/legendCols,y=top+h+14*u+row*22*u;ctx.fillStyle=l.color;ctx.fillRect(x,y,15*u,12*u);ctx.strokeStyle="#aaa";ctx.lineWidth=.6*u;ctx.strokeRect(x,y,15*u,12*u);ctx.fillStyle="#26323b";ctx.fillText(l.label,x+20*u,y+11*u,Math.max(10,w/legendCols-24*u))});
 ctx.fillStyle="#45525c";ctx.font=Math.round(11*u)+"px sans-serif";
 ctx.fillText("DWD HYRAS-DE · DWD CDC KL · Grenzen: deutschlandGeoJSON/GIS-DATA",pad,cv.height-24*u,cv.width-2*pad);
 ctx.fillText(d.note||"",pad,cv.height-9*u,cv.width-2*pad);
 return {cv,hits};
}
async function refresh(){
 if(!$("hyrasRegionalWorkshop")?.open)return;
 const rev=++revision,s=source;display=null;
 clear("Regionalkarte wird vorbereitet …");
 if(!s?.owner?.isConnected){clear("Für diese Ansicht ist noch kein numerisches Raster verfügbar.");return}
 try{
  const region=$("hyrasRegRegion").value,neighbors=$("hyrasRegNeighbors").checked,names=$("hyrasRegNames").checked,values=$("hyrasRegValues").checked;
  const geo=await loadGeometry(s);if(rev!==revision)return;
  const features=geo.items;
  const selected=(region==="Deutschland"?features:features.filter(f=>normalized(f.name)===normalized(region))).flatMap(f=>f.polys);
  const b=region==="Deutschland"?{x:0,y:0,w:s.canvas.width,h:s.canvas.height}:extent(selected,s.canvas.width,s.canvas.height);
  let st={stations:[],note:"Stationslayer ausgeschaltet."};
  if($("hyrasRegStations").checked){$("hyrasRegStatus").textContent="DWD-Stationswerte für den Kartenzeitraum werden geprüft …";try{st=await stationData(s,geo,region,values)}catch(e){st.note="Stationsdaten nicht verfügbar: "+e.message}}
  if(rev!==revision||!s.owner.isConnected)return;
  const d={s,b,features,selected,region,stations:st.stations,legend:s.legend||[],neighbors,names,values,note:st.note};
  const out=renderCanvas(d,1100);$("hyrasRegPreview").replaceChildren(out.cv);
  display=d;
  out.cv.addEventListener("pointerup",e=>{
   const r=out.cv.getBoundingClientRect(),x=(e.clientX-r.left)*out.cv.width/r.width,y=(e.clientY-r.top)*out.cv.height/r.height;
   let best=null,dist=22;for(const h of out.hits){const q=Math.hypot(x-h.x,y-h.y);if(q<dist){best=h;dist=q}}
   $("hyrasRegInspection").textContent=best?best.name+" (DWD "+best.id+", "+best.elev+" m) · "+(Number.isFinite(best.value)?best.value.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})+" K":"Kein passender Messwert"):"Stationspunkt antippen, um Details zu sehen.";
  });
  $("hyrasRegStatus").textContent="HYRAS-Raster: "+s.resolution+" km · "+out.hits.length+" Stationspunkte im Ausschnitt. "+st.note;
  $("hyrasRegPng").disabled=false;$("hyrasRegPdf").disabled=false;
 }catch(e){if(rev===revision){clear("Regionalkarte nicht verfügbar: "+e.message);console.warn("HYRAS regional",e)}}
}
async function download(format){
 const d=display;if(!d||!d.s.owner.isConnected)return;
 const button=$(format==="png"?"hyrasRegPng":"hyrasRegPdf");button.disabled=true;
 try{
  const {cv}=renderCanvas(d,Number($("hyrasRegSize").value)||4000);
  const name="hyras_"+d.s.parameter+"_"+normalized(d.region)+"_"+(d.s.start||"")+'_'+(d.s.end||"");
  if(format==="pdf"){
   const Pdf=root.jspdf?.jsPDF;if(!Pdf)throw Error("jsPDF nicht verfügbar");
   const pdf=new Pdf({orientation:cv.width>=cv.height?"landscape":"portrait",unit:"mm",format:"a4",compress:true});
   const pw=pdf.internal.pageSize.getWidth(),ph=pdf.internal.pageSize.getHeight(),scale=Math.min((pw-12)/cv.width,(ph-12)/cv.height);
   pdf.addImage(cv.toDataURL("image/png"),"PNG",(pw-cv.width*scale)/2,(ph-cv.height*scale)/2,cv.width*scale,cv.height*scale);pdf.save(name+".pdf");
  }else{
   const blob=await new Promise((ok,no)=>cv.toBlob(b=>b?ok(b):no(Error("PNG zu groß für den Browser")),"image/png"));
   const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=name+".png";document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2500);
  }
 }catch(e){$("hyrasRegInspection").textContent="Export fehlgeschlagen: "+e.message}
 finally{button.disabled=!display}
}
function setSource(s){
 install();
 if(!s?.canvas||!s.lookupUrl||!s.owner?.isConnected)return;
 source={...s,legend:legendFrom(s.legendNode)};display=null;revision++;
 if($("hyrasRegionalWorkshop")?.open)refresh();else clear("Raster verfügbar. Regionale Kartenwerkstatt öffnen.");
}
const api={project,coordinate,extent,isoDates,accumulate,install,setSource};
if(typeof module==="object"&&module.exports)module.exports=api;else {root.HyrasRegional=api;install()}
})(typeof globalThis==="object"?globalThis:this);
