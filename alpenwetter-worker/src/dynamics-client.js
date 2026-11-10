/* Pure text JavaScript, NOT a serialized bundler-transformed function.
   This must remain an untransformed template literal: Wrangler injects __name()
   calls in compiled function bodies, which are not available in inline pages. */
export const DYNAMICS_CLIENT_SOURCE = String.raw`(function dynamicsClient() {
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
})();`;
