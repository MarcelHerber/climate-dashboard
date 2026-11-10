/* Protected ECMWF upper-air dynamics studio. All interactive controls require a valid Worker session. */
const DYNAMICS_SOURCE = "https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/dynamics-data/data/dynamik/";

export async function dynamicsLabData(url, securityHeaders) {
  const rest = url.pathname.replace(/^\/dynamik\/api\/data\//, "");
  if (!/^(?:current\.json|frames\/\d{10}\/(?:tcwv|jet|ascent|pv|iru|irv)_\d{3}\.png)$/.test(rest)) {
    return new Response("Ungültige Datenadresse", { status: 400, headers: securityHeaders({"Content-Type":"text/plain"}) });
  }
  try {
    const response = await fetch(DYNAMICS_SOURCE + rest, {
      cf: {cacheEverything: true, cacheTtl: rest === "current.json" ? 120 : 86400}
    });
    if (!response.ok) {
      return new Response(JSON.stringify({error: "Kein bestätigter ECMWF-Datensatz", upstream: response.status}), {
        status: response.status === 404 ? 404 : 502,
        headers: securityHeaders({"Content-Type":"application/json; charset=utf-8"})
      });
    }
    return new Response(response.body, {
      status: 200,
      headers: securityHeaders({"Content-Type":rest.endsWith(".json") ? "application/json; charset=utf-8" : "image/png"})
    });
  } catch (error) {
    return new Response(JSON.stringify({error:"Modelldaten derzeit nicht erreichbar"}), {
      status:502, headers: securityHeaders({"Content-Type":"application/json; charset=utf-8"})
    });
  }
}

export async function dynamicsBoundaries(securityHeaders) {
  try {
    const response = await fetch("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson", {
      cf:{cacheEverything:true,cacheTtl:86400}
    });
    if(!response.ok) throw Error("Natural Earth HTTP "+response.status);
    return new Response(response.body, {
      headers:securityHeaders({"Content-Type":"application/geo+json; charset=utf-8"})
    });
  } catch (_error) {
    return new Response(JSON.stringify({type:"FeatureCollection",features:[]}), {
      status:502,headers:securityHeaders({"Content-Type":"application/json; charset=utf-8"})
    });
  }
}

const STYLE = [
":root{color-scheme:dark;font-family:Inter,system-ui,sans-serif;background:#0b1524;color:#e9f3ff}",
"*{box-sizing:border-box}body{margin:0}a{color:#acdff9;text-decoration:none}a:hover{text-decoration:underline}",
"header{padding:16px 2.5vw;border-bottom:1px solid #2e4761;background:#101f31;display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}",
"header small{display:block;color:#90b1c9;font-size:11px;letter-spacing:.12em}header strong{font-size:19px}nav{display:flex;gap:12px;align-items:center;flex-wrap:wrap}nav form{margin:0}",
"main{max-width:1620px;margin:auto;padding:22px 2vw 44px}h1{font-size:clamp(21px,3vw,32px);margin:0 0 8px}h2{font-size:17px;margin:0 0 14px}p{line-height:1.55}.lead{color:#b4c8da;font-size:14px;max-width:900px;margin:0 0 20px}",
".layout{display:grid;grid-template-columns:minmax(0,1fr) 305px;gap:15px;align-items:start}",
".card{background:#13263b;border:1px solid #304b65;border-radius:13px;padding:15px;min-width:0;box-shadow:0 8px 30px #0003}",
".map{position:relative;background:#b6d6e7;border:1px solid #46627c;border-radius:9px;overflow:hidden}.map canvas{width:100%;display:block;aspect-ratio:16/9}",
"button,select{font:inherit;background:#203e59;color:#e9f4fb;border:1px solid #46657e;border-radius:8px;padding:9px 11px;cursor:pointer}",
"button:hover:not(:disabled){background:#315575}button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #ffc36a;outline-offset:2px}",
"button:disabled{opacity:.45;cursor:default}button.primary{background:#227aaf;border-color:#4691c1;font-weight:750}",
"label{display:block;color:#d2e7f6;font-size:13px}select{max-width:100%;margin-top:5px}.settings label{display:flex;align-items:center;gap:9px;padding:10px 0;border-bottom:1px solid #2a445e}",
".settings input{width:17px;height:17px;accent-color:#64b9f4}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:space-between;margin:12px 0}",
".row input[type=range]{flex:1;min-width:130px;accent-color:#6fc6f5}.timestamp{font-size:13px;font-variant-numeric:tabular-nums;color:#d1e8f9}",
".status{margin-top:12px;border-radius:9px;padding:12px;background:#1c3750;color:#cfe5f7;font-size:13px;line-height:1.6}",
".status.error{background:#4a2a2d;color:#ffd4cd}.note{color:#a8c1d7;font-size:12px;line-height:1.6}",
".legend{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin-top:12px;font-size:11px;color:#bfd5e6}",
".bar{height:13px;width:min(450px,100%);border-radius:4px;background:linear-gradient(to right,#f7f9fc,#d1f2ff,#83d3d3,#419947,#e8e458,#ec6f28,#9b1a58)}",
".pill{font-size:11px;border:1px solid #345976;border-radius:99px;padding:4px 8px;color:#b7e6ca;background:#183c36}",
"@media(max-width:900px){.layout{grid-template-columns:1fr}.settings{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:12px}.card{padding:12px}}",
"@media(max-width:530px){header{padding:12px}main{padding:13px 8px}.settings{display:block}.row{justify-content:flex-start}.map canvas{aspect-ratio:16/10}}"
].join("");

export function dynamicsLabPage() {
  return '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<meta name="robots" content="noindex,nofollow,noarchive"><title>ECMWF Dynamik-Studio · Privat</title><style>' + STYLE + '</style></head><body>' +
    '<header><div><small>CLIMATE DASHBOARD · GESCHÜTZTES LABOR</small><strong>ECMWF Dynamik- &amp; Jetstream-Studio</strong> <span class="pill">Privat</span></div>' +
    '<nav><a href="/wolkenlabor">Wolkenlabor</a><a href="/">Alpenwetter</a><form action="/logout" method="POST"><button>Abmelden</button></form></nav></header>' +
    '<main><h1>Strömung, Feuchte &amp; Tropopausendynamik</h1><p class="lead">Originale ECMWF-IFS-Ausgangsfelder mit transparent gekennzeichneten Berechnungen. Die Animation zeigt nur bestätigte Modellzeitpunkte; fehlende Daten werden nicht ergänzt.</p>' +
    '<div class="layout"><section class="card"><div class="row"><strong id="run">ECMWF IFS · Datenstand wird geprüft</strong><span class="timestamp" id="valid">–</span></div>' +
    '<div class="map"><canvas id="map" width="1600" height="900" aria-label="ECMWF-Karte mit atmosphärischen Dynamikfeldern" role="img"></canvas></div>' +
    '<div class="legend"><strong>PWAT</strong><span>0 mm</span><div class="bar"></div><span>70+ mm</span></div>' +
    '<div class="row"><button id="play" class="primary" disabled>▶ Start</button>' +
    '<input id="timeline" type="range" min="0" max="0" value="0" aria-label="Prognosestunde" disabled>' +
    '<label>Tempo <select id="speed"><option value="0.5">0,5 ×</option><option value="1" selected>1 ×</option><option value="2">2 ×</option><option value="4">4 ×</option></select></label></div>' +
    '<div class="row"><button id="save" disabled>PNG exportieren</button><button id="record" disabled>WebM aufnehmen</button><button id="refresh">↻ Lauf prüfen</button></div>' +
    '<div class="status" id="status" role="status" aria-live="polite">Suche nach vollständigen ECMWF-Modellfeldern …</div>' +
    '</section><aside class="card"><h2>Karte einstellen</h2><label for="region">Region</label><select id="region">' +
    '<option value="atlantik" selected>Europa &amp; Nordatlantik</option><option value="europa">Europa</option>' +
    '<option value="suedwest">Südwesteuropa · Azoren · Kanaren</option></select>' +
    '<h2 style="margin-top:25px">Ebenen einzeln schalten</h2><div class="settings">' +
    '<label><input id="tcwv" type="checkbox" checked>Niederschlagbares Wasser · mm</label>' +
    '<label><input id="jet" type="checkbox" checked>250-hPa-Jet · schwarze Linien</label>' +
    '<label><input id="ascent" type="checkbox" checked>400–600-hPa-Aufstieg · rot</label>' +
    '<label><input id="pv" type="checkbox" checked>200–300-hPa-PV · violett</label>' +
    '<label><input id="irrot" type="checkbox" checked>Irrotationaler Höhenwind · Pfeile</label></div>' +
    '<p class="note">Feste PWAT-Skala 0–70 mm. Jet-Konturen 30–100 m/s, Aufstieg 0,2–1,0 Pa/s und PV-Konturen 1,5–8 PVU. Die Farben ändern sich nicht zwischen Prognosezeiten.</p>' +
    '<h2>Wissenschaftliche Einordnung</h2><p class="note">PV: dreistufige isobare Ertel-PV-Näherung samt Kipptermen. Irrotationaler Wind: regionale Poisson-Inversion (Neumann-Randbedingungen, vereinfachte Metrik). Beide Diagnosen sind keine Originalfelder und insbesondere am Kartenrand nur eingeschränkt interpretierbar.</p>' +
    '<p class="note">Daten: ECMWF IFS 0,25° Open Data · CC BY 4.0. Kartengrenzen: Natural Earth. Videoexport: WebM (browserabhängig). Die Anmeldung schützt die Oberfläche und den Datenproxy; ECMWF-Rohdaten sind öffentlich.</p>' +
    '</aside></div></main><script>(' + dynamicsClient.toString() + ')();</script></body></html>';
}

function dynamicsClient() {
  "use strict";
  const el = id => document.getElementById(id);
  const canvas = el("map"), ctx = canvas.getContext("2d", {alpha: false});
  const regions = {
    atlantik:{w:-70,e:45,s:12,n:75},
    europa:{w:-27,e:43,s:30,n:73},
    suedwest:{w:-42,e:13,s:20,n:51}
  };
  const stops = [
    [0,[247,249,252]],[.2,[209,242,255]],[.35,[131,211,211]],
    [.48,[65,153,71]],[.65,[232,228,88]],[.82,[236,111,40]],[1,[155,26,88]]
  ];
  const state = {manifest:null, boundaries:null, frame:0, active:false, serial:0,
    caches:new Map(), timer:0, recording:null, chunks:[]};
  const map = () => regions[el("region").value];
  const sc = name => state.manifest.encoding.minmax[name];
  const on = id => el(id).checked;
  const say = (msg, err) => { el("status").textContent=msg; el("status").className="status"+(err?" error":""); };
  const nameUTC = date => new Date(date).toLocaleString("de-DE", {
    timeZone:"UTC", day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"
  })+" UTC";
  const px = lon => (lon-map().w)/(map().e-map().w)*canvas.width;
  const py = lat => (map().n-lat)/(map().n-map().s)*canvas.height;

  function palette(q) {
    if(q>=255) return [240,248,253];
    const t=q/254;
    for(let i=1;i<stops.length;i++){
      if(t<=stops[i][0]){
        const a=stops[i-1],b=stops[i],f=(t-a[0])/(b[0]-a[0]);
        return a[1].map((v,j)=>Math.round(v+(b[1][j]-v)*f));
      }
    }
    return stops[stops.length-1][1];
  }
  function sourceRect(){
    const g=state.manifest.grid,r=map();
    return {x:Math.round((r.w-g.west)/g.step),
      y:Math.round((g.north-r.n)/g.step),
      w:Math.round((r.e-r.w)/g.step)+1,
      h:Math.round((r.n-r.s)/g.step)+1};
  }
  function imgData(rawImage){
    const c=document.createElement("canvas");
    c.width=rawImage.naturalWidth;c.height=rawImage.naturalHeight;
    const x=c.getContext("2d",{willReadFrequently:true});
    x.drawImage(rawImage,0,0);
    const rgba=x.getImageData(0,0,c.width,c.height);
    const data=new Uint8Array(c.width*c.height);
    for(let p=0;p<data.length;p++) data[p]=rgba.data[4*p];
    return {data:data,w:c.width,h:c.height};
  }
  function getField(frame,key){
    const path=frame.images[key];
    if(!path) return Promise.reject(new Error("Fehlendes Feld "+key));
    if(state.caches.has(path)) return Promise.resolve(state.caches.get(path));
    return new Promise((resolve,reject)=>{
      const img=new Image();
      img.onload=()=>{
        try{
          const field=imgData(img),g=state.manifest.grid;
          if(field.w!==g.width||field.h!==g.height) throw Error("Rastergröße ungültig: "+key);
          state.caches.set(path,field);
          while(state.caches.size>22) state.caches.delete(state.caches.keys().next().value);
          resolve(field);
        }catch(e){reject(e)}
      };
      img.onerror=()=>reject(Error("Bildfeld nicht verfügbar: "+key));
      img.src="/dynamik/api/data/"+path;
    });
  }
  function sample(field,x,y,kind){
    if(!field||x<0||y<0||x>=field.w||y>=field.h) return NaN;
    const p=field.data[Math.round(y)*field.w+Math.round(x)];
    if(p===255) return NaN;
    const range=sc(kind);
    return range[0]+(range[1]-range[0])*p/254;
  }
  function baseMap(){
    ctx.fillStyle="#e6f2f8";ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.strokeStyle="#a0bfce";ctx.lineWidth=1;ctx.setLineDash([3,8]);
    ctx.beginPath();
    for(let lon=-70;lon<=50;lon+=10){
      if(lon<map().w||lon>map().e) continue;
      ctx.moveTo(px(lon),0);ctx.lineTo(px(lon),canvas.height);
    }
    for(let lat=10;lat<=80;lat+=10){
      if(lat<map().s||lat>map().n) continue;
      ctx.moveTo(0,py(lat));ctx.lineTo(canvas.width,py(lat));
    }
    ctx.stroke();ctx.setLineDash([]);
  }
  function raster(field){
    const c=document.createElement("canvas");c.width=field.w;c.height=field.h;
    const x=c.getContext("2d");
    const rgba=x.createImageData(field.w,field.h);
    for(let k=0;k<field.data.length;k++){
      const color=palette(field.data[k]);
      rgba.data[k*4]=color[0];rgba.data[k*4+1]=color[1];
      rgba.data[k*4+2]=color[2];rgba.data[k*4+3]=255;
    }
    x.putImageData(rgba,0,0);
    const r=sourceRect();
    ctx.imageSmoothingEnabled=true;
    ctx.drawImage(c,r.x,r.y,r.w,r.h,0,0,canvas.width,canvas.height);
  }
  function borderLine(coords){
    if(!Array.isArray(coords)) return;
    let started=false,previous=NaN;
    for(const pt of coords){
      const lon=pt[0],lat=pt[1];
      if(!Number.isFinite(lon)||!Number.isFinite(lat)){started=false;continue;}
      const x=px(lon),y=py(lat);
      if(!started||Math.abs(x-previous)>canvas.width*.25){ctx.moveTo(x,y);started=true;}
      else ctx.lineTo(x,y);
      previous=x;
    }
  }
  function boundaries(){
    if(!state.boundaries) return;
    ctx.save();ctx.beginPath();ctx.rect(0,0,canvas.width,canvas.height);ctx.clip();
    ctx.lineWidth=1.25;ctx.strokeStyle="#304a61bb";ctx.beginPath();
    for(const feature of state.boundaries.features||[]){
      const g=feature.geometry||{};
      if(g.type==="Polygon"){for(const ring of g.coordinates||[])borderLine(ring);}
      if(g.type==="MultiPolygon"){for(const poly of g.coordinates||[])for(const ring of poly)borderLine(ring);}
    }
    ctx.stroke();ctx.restore();
  }
  function contours(field,kind,levels,color,lineWidth){
    if(!field) return;
    const r=sourceRect(),stride=2;
    const spanx=canvas.width/(r.w-1),spany=canvas.height/(r.h-1);
    ctx.save();ctx.strokeStyle=color;ctx.lineWidth=lineWidth;ctx.lineJoin="round";
    for(const level of levels){
      ctx.beginPath();
      for(let iy=r.y;iy<r.y+r.h-1;iy+=stride){
        for(let ix=r.x;ix<r.x+r.w-1;ix+=stride){
          const corners=[[ix,iy],[Math.min(ix+stride,field.w-1),iy],
                         [Math.min(ix+stride,field.w-1),Math.min(iy+stride,field.h-1)],
                         [ix,Math.min(iy+stride,field.h-1)]];
          const vv=corners.map(p=>sample(field,p[0],p[1],kind));
          if(!vv.every(Number.isFinite))continue;
          const crosses=[];
          for(let e=0;e<4;e++){
            const n=(e+1)%4,a=vv[e],b=vv[n];
            if((a<level)!==(b<level)){
              const t=(level-a)/(b-a);
              crosses.push([corners[e][0]+t*(corners[n][0]-corners[e][0]),
                            corners[e][1]+t*(corners[n][1]-corners[e][1])]);
            }
          }
          for(let e=0;e+1<crosses.length;e+=2){
            ctx.moveTo((crosses[e][0]-r.x)*spanx,(crosses[e][1]-r.y)*spany);
            ctx.lineTo((crosses[e+1][0]-r.x)*spanx,(crosses[e+1][1]-r.y)*spany);
          }
        }
      }
      ctx.stroke();
    }
    ctx.restore();
  }
  function arrows(u,v){
    if(!u||!v)return;
    const r=sourceRect(), stepX=Math.max(7,Math.round(r.w/38)), stepY=Math.max(7,Math.round(r.h/23));
    const scaleX=canvas.width/(r.w-1),scaleY=canvas.height/(r.h-1);
    ctx.save();ctx.strokeStyle="#111b2bdc";ctx.fillStyle="#111b2bdc";ctx.lineWidth=2.3;
    for(let j=r.y+4;j<r.y+r.h-4;j+=stepY)for(let i=r.x+4;i<r.x+r.w-4;i+=stepX){
      const uu=sample(u,i,j,"iru"),vv=sample(v,i,j,"irv");
      const mag=Math.hypot(uu,vv);
      if(!Number.isFinite(mag)||mag<2)continue;
      const len=Math.min(37,12+mag*1.2),angle=Math.atan2(-vv,uu);
      const x=(i-r.x)*scaleX,y=(j-r.y)*scaleY,dx=Math.cos(angle)*len,dy=Math.sin(angle)*len;
      ctx.beginPath();ctx.moveTo(x-dx*.5,y-dy*.5);ctx.lineTo(x+dx*.5,y+dy*.5);
      ctx.lineTo(x+dx*.5-6*Math.cos(angle-.48),y+dy*.5-6*Math.sin(angle-.48));
      ctx.moveTo(x+dx*.5,y+dy*.5);
      ctx.lineTo(x+dx*.5-6*Math.cos(angle+.48),y+dy*.5-6*Math.sin(angle+.48));ctx.stroke();
    }
    ctx.restore();
  }
  function heading(frame){
    ctx.save();
    ctx.fillStyle="#14263dda";ctx.fillRect(0,0,canvas.width,64);
    ctx.fillStyle="#fff";ctx.font="bold 30px system-ui";ctx.fillText("ECMWF IFS  ·  "+nameUTC(frame.valid_utc),22,41);
    ctx.font="17px system-ui";ctx.textAlign="right";ctx.fillText("T+"+frame.hour+" h · Climate Dashboard",canvas.width-24,40);
    ctx.restore();
  }
  async function render(){
    if(!state.manifest) return;
    const token=++state.serial;
    const frame=state.manifest.frames[state.frame];
    el("valid").textContent=nameUTC(frame.valid_utc)+"  ·  +"+frame.hour+" h";
    const keys=[];
    if(on("tcwv")) keys.push("tcwv");
    if(on("jet")) keys.push("jet");
    if(on("ascent")) keys.push("ascent");
    if(on("pv")) keys.push("pv");
    if(on("irrot")) keys.push("iru","irv");
    try{
      const layers={};
      await Promise.all(keys.map(async key=>{layers[key]=await getField(frame,key)}));
      if(token!==state.serial)return;
      baseMap();
      if(on("tcwv"))raster(layers.tcwv);
      boundaries();
      if(on("jet"))contours(layers.jet,"jet",[30,40,50,60,70,80,90,100],"#101925",2.8);
      if(on("ascent"))contours(layers.ascent,"ascent",[.2,.4,.6,.8,1],"#d82d47",2.2);
      if(on("pv"))contours(layers.pv,"pv",[1.5,2,3,4,6,8],"#92257e",2.7);
      if(on("irrot"))arrows(layers.iru,layers.irv);
      heading(frame);
      say("ECMWF "+state.manifest.cycle+" · echte Prognosefelder, vollständig geladen. Diagnosefelder sind im rechten Panel erläutert.",false);
    }catch(error){
      if(token!==state.serial)return;
      baseMap();boundaries();say("Darstellung nicht möglich: "+error.message,true);stop();
    }
  }
  function stop(){
    state.active=false;clearTimeout(state.timer);el("play").textContent="▶ Start";
  }
  async function advance(){
    if(!state.active)return;
    if(state.frame>=state.manifest.frames.length-1){
      stop();
      if(state.recording&&state.recording.state==="recording")state.recording.stop();
      return;
    }
    state.frame++;el("timeline").value=state.frame;await render();
    if(state.active) state.timer=setTimeout(advance,Math.round(700/Number(el("speed").value)));
  }
  function download(blob,filename){
    const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=filename;
    document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),2000);
  }
  function save(){
    if(!state.manifest)return;
    canvas.toBlob(blob=>{if(blob)download(blob,"ecmwf-dynamik-"+state.manifest.cycle+"-t"+state.manifest.frames[state.frame].hour+".png")},"image/png");
  }
  function record(){
    if(state.recording&&state.recording.state==="recording"){
      state.recording.stop();stop();return;
    }
    if(!window.MediaRecorder||!canvas.captureStream){say("Dieser Browser unterstützt keinen WebM-Export.",true);return}
    const types=["video/webm;codecs=vp9","video/webm;codecs=vp8","video/webm"];
    const mime=types.find(t=>MediaRecorder.isTypeSupported(t));
    if(!mime){say("Kein kompatibler WebM-Codec vorhanden.",true);return}
    stop();state.frame=0;el("timeline").value=0;
    render().then(()=>{
      const recorder=new MediaRecorder(canvas.captureStream(12),{mimeType:mime});
      state.recording=recorder;state.chunks=[];
      recorder.ondataavailable=e=>{if(e.data.size)state.chunks.push(e.data)};
      recorder.onstop=()=>{
        if(state.chunks.length)download(new Blob(state.chunks,{type:mime}),"ecmwf-dynamik-"+state.manifest.cycle+".webm");
        state.recording=null;el("record").textContent="WebM aufnehmen";
      };
      recorder.start();el("record").textContent="■ Aufnahme stoppen";
      state.active=true;el("play").textContent="❚❚ Pause";
      state.timer=setTimeout(advance,Math.round(700/Number(el("speed").value)));
    }).catch(e=>say("Aufnahme fehlgeschlagen: "+e.message,true));
  }
  async function boot(){
    stop();state.serial++;state.caches.clear();
    say("Prüfe vollständigen Modelllauf …");
    try{
      const response=await fetch("/dynamik/api/data/current.json",{cache:"no-store"});
      if(!response.ok) throw Error(response.status===404?"Noch kein vollständiger Datenlauf veröffentlicht":"HTTP "+response.status);
      const m=await response.json();
      if(m.schema!==1||!m.grid||!m.encoding||!Array.isArray(m.frames)||m.frames.length<2)
        throw Error("Modellmanifest unvollständig");
      const needed=["tcwv","jet","ascent","pv","iru","irv"];
      if(!m.frames.every(f=>needed.every(k=>typeof f.images?.[k]==="string")))
        throw Error("Modellebene fehlt in einem Zeitschritt");
      state.manifest=m;state.frame=0;el("timeline").max=m.frames.length-1;
      for(const id of ["play","timeline","save","record"])el(id).disabled=false;
      el("run").textContent="ECMWF IFS 0,25° · Start "+nameUTC(m.initialized_utc);
      await render();
    }catch(error){
      state.manifest=null;
      for(const id of ["play","timeline","save","record"])el(id).disabled=true;
      baseMap();boundaries();say(error.message+" – es werden keine künstlichen Prognosebilder gezeigt.",true);
    }
  }
  el("play").addEventListener("click",()=>{
    if(!state.manifest)return;
    if(state.active)stop();
    else{if(state.frame===state.manifest.frames.length-1)state.frame=0;
      state.active=true;el("play").textContent="❚❚ Pause";render();
      state.timer=setTimeout(advance,Math.round(700/Number(el("speed").value)));
    }
  });
  el("timeline").addEventListener("input",()=>{stop();state.frame=Number(el("timeline").value);render()});
  el("region").addEventListener("change",()=>{stop();render()});
  for(const id of ["tcwv","jet","ascent","pv","irrot"])el(id).addEventListener("change",render);
  el("save").addEventListener("click",save);
  el("record").addEventListener("click",record);
  el("refresh").addEventListener("click",boot);
  fetch("/dynamik/api/boundaries").then(r=>{if(!r.ok)throw Error("Grenzen");return r.json()})
    .then(g=>{state.boundaries=g;if(state.manifest)render()})
    .catch(()=>say("Natural-Earth-Grenzen derzeit nicht erreichbar; Wetterfelder bleiben nutzbar.",true));
  baseMap();boot();
}
