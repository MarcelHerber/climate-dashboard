(function(){
"use strict";
const BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/cyclone-tracker-data/data/cyclone-tracker/";
const DATA_URL=BASE+"tracks.json";
const ATLANTIC_URL=BASE+"atlantic.json";
const ECMWF_LOW_URL=BASE+"ecmwf_atlantic.json";
const MODEL_LABEL={gfs:"GFS Nordatlantik / Hart-CPS","ifs-atl":"IFS Nordatlantik-Tiefs","aifs-atl":"AIFS Nordatlantik-Tiefs",ifs:"IFS Tropenzyklonen",aifs:"AIFS Tropenzyklonen",ens:"IFS ENS Tropenzyklonen"};
const COLOR={gfs:"#8b5cf6","ifs-atl":"#bd332a","aifs-atl":"#175aad",ifs:"#f58049",aifs:"#5ba4db",ens:"#288c73"};
const $=id=>document.getElementById(id);
let map,lines,allData=null,visible=[],activeId=null,intensityChart=null,cpsChart=null,cpsUpperChart=null,totalMatching=0;
const number=(v,d=1)=>Number.isFinite(v)?v.toLocaleString("de-DE",{minimumFractionDigits:d,maximumFractionDigits:d}):"–";
function stamp(raw){
  if(!raw)return"–";
  const d=new Date(raw);
  return Number.isNaN(d.getTime())?raw:d.toLocaleString("de-DE",{timeZone:"UTC",day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})+" UTC";
}
function setStatus(message,bad=false){const el=$("status");el.textContent=message;el.className="status"+(bad?" error":"");}
function validTrack(t){
  return Boolean(t&&Array.isArray(t.points)&&t.points.length>1
    &&t.points.some(p=>Number.isFinite(p.lat)&&Number.isFinite(p.lon)));
}
function displayName(t){return String(t.name||t.storm_id||t.id);}
function chosenHour(){return Number($("hour").value);}
function atHour(t){
  const points=t.points.filter(p=>p.h<=chosenHour());
  return points.length?points[points.length-1]:t.points[0];
}
function populate(){
  if(!allData)return;
  const former=$("system").value,model=$("model").value;
  const names=new Map();
  for(const t of allData.tracks){
    if(!validTrack(t)||(model!=="all"&&t.model!==model))continue;
    names.set(String(t.storm_id),String(t.storm_id)+" · "+displayName(t));
  }
  const control=$("system");
  control.replaceChildren();
  const first=document.createElement("option");first.value="all";first.textContent="Alle Systeme";control.add(first);
  for(const [key,name] of [...names].sort((a,b)=>a[1].localeCompare(b[1]))){
    const opt=document.createElement("option");opt.value=key;opt.textContent=name;control.add(opt);
  }
  control.value=names.has(former)?former:"all";
}
function selectedTracks(){
  if(!allData)return[];
  const model=$("model").value,system=$("system").value,showEns=$("ensemble").checked;
  const matching=allData.tracks.filter(t=>validTrack(t)
    &&(model==="all"||t.model===model)
    &&(system==="all"||String(t.storm_id)===system)
    &&(t.model!=="ens"||showEns)
  ).sort((a,b)=>(a.model||"").localeCompare(b.model||"")
       ||String(a.storm_id).localeCompare(String(b.storm_id))
       ||(a.member||0)-(b.member||0));
  totalMatching=matching.length;
  // Avoid rendering thousands of Leaflet shapes when all ENS systems are on.
  // Selecting one storm restores all matching ensemble members.
  return system==="all"&&matching.length>220?matching.slice(0,220):matching;
}
function drawMap(fit){
  if(!map)return;
  lines.clearLayers();
  const bounds=[];
  for(const track of visible){
    const filtered=track.points.filter(p=>p.h<=chosenHour()&&Number.isFinite(p.lat)&&Number.isFinite(p.lon));
    if(!filtered.length)continue;
    const selected=track.id===activeId;
    const color=COLOR[track.model]||"#4c6889";
    const segments=[];let segment=[];
    for(const p of filtered){
      if(segment.length&&Math.abs(p.lon-segment[segment.length-1][1])>180){
        if(segment.length>1)segments.push(segment);
        segment=[];
      }
      segment.push([p.lat,p.lon]);
      if(bounds.length<1200)bounds.push([p.lat,p.lon]);
    }
    if(segment.length>1)segments.push(segment);
    for(const points of segments){
      L.polyline(points,{
        color,weight:selected?4:2,
        opacity:selected?1:(track.model==="ens"?0.35:0.82),
        dashArray:track.model==="ens"?"4,5":null
      }).addTo(lines).on("click",()=>selectTrack(track.id))
        .bindTooltip(displayName(track)+" · "+(MODEL_LABEL[track.model]||track.model),{sticky:true});
    }
    const last=filtered[filtered.length-1];
    L.circleMarker([last.lat,last.lon],{
      radius:selected?6:4,color,fillColor:color,fillOpacity:.9,weight:selected?3:1
    }).addTo(lines).on("click",()=>selectTrack(track.id))
      .bindTooltip(displayName(track)+" +"+last.h+" h");
  }
  $("count").textContent=(totalMatching>visible.length?visible.length+" von "+totalMatching:visible.length)+" Zugbahnen";
  if(fit&&bounds.length)map.fitBounds(bounds,{padding:[25,25],maxZoom:5});
}
function listTracks(){
  const parent=$("tracklist");parent.replaceChildren();
  if(!visible.length){const p=document.createElement("p");p.className="note";p.textContent="Keine passenden Zugbahnen vorhanden.";parent.append(p);return;}
  const fragment=document.createDocumentFragment();
  for(const t of visible.slice(0,280)){
    const btn=document.createElement("button");btn.type="button";btn.className="trackrow"+(t.id===activeId?" active":"");
    const left=document.createElement("span"),title=document.createElement("strong"),detail=document.createElement("span");
    const dot=document.createElement("span");dot.className="dot";dot.style.background=COLOR[t.model]||"#64748b";
    title.append(dot,document.createTextNode(displayName(t)));
    detail.className="detail";detail.textContent=(MODEL_LABEL[t.model]||t.model)+(t.is_ensemble?" · Mitglied "+t.member:"");
    left.append(title,detail);
    const value=document.createElement("b"),p=atHour(t);
    value.textContent=Number.isFinite(p.mslp_hpa)?number(p.mslp_hpa,0)+" hPa":"–";
    btn.append(left,value);btn.addEventListener("click",()=>selectTrack(t.id));fragment.append(btn);
  }
  parent.append(fragment);
}
function details(t){
  if(!t){for(const id of ["vname","vmodel","vtime","vrun","vpressure","vwind"])$(id).textContent="–";$("phaseLabel").textContent="Kernstruktur: –";plotIntensity(null);plotCps(null);if(window.CycloneDiagnostics)window.CycloneDiagnostics.update(null,allData,chosenHour());return;}
  const p=atHour(t);
  $("vname").textContent=displayName(t);
  $("vmodel").textContent=(MODEL_LABEL[t.model]||t.model)+(t.is_ensemble?" · Mitglied "+t.member:"");
  $("vtime").textContent=stamp(p.time);
  $("vrun").textContent="Modellstart: "+stamp(t.run)+" / +"+p.h+" h";
  $("vpressure").textContent=Number.isFinite(p.mslp_hpa)?number(p.mslp_hpa)+" hPa":"–";
  $("vwind").textContent=Number.isFinite(p.vmax_ms)?number(p.vmax_ms*3.6,0)+" km/h":"–";
  const phase=p.phase||"nicht bestimmt";
  $("phaseLabel").textContent=t.model==="gfs"?"GFS-Kernstruktur: "+phase:
    (t.model==="ifs-atl"||t.model==="aifs-atl"?
     "Kernstruktur: ECMWF-MSLP-Tiefbahnen, Hart-CPS noch nicht berechnet":
     "Kernstruktur: Für diesen ECMWF-Tropenzyklonen-Track nicht berechnet");
  plotIntensity(t);plotCps(t);
  if(window.CycloneDiagnostics)window.CycloneDiagnostics.update(t,allData,chosenHour());
}
function plotIntensity(t){
  if(intensityChart){intensityChart.destroy();intensityChart=null;}
  if(!t)return;
  const values=t.points;
  intensityChart=new Chart($("intensityChart"),{
    type:"line",data:{labels:values.map(p=>"+"+p.h+"h"),datasets:[
      {label:"Kerndruck (hPa)",data:values.map(p=>p.mslp_hpa),borderColor:"#235fb2",pointRadius:2,spanGaps:false,yAxisID:"p"},
      {label:"10-m-Maximalwind (km/h)",data:values.map(p=>p.vmax_ms==null?null:p.vmax_ms*3.6),borderColor:"#cc5b2e",pointRadius:2,spanGaps:false,yAxisID:"w"}
    ]},
    options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:"index",intersect:false},
      plugins:{legend:{position:"bottom"}},
      scales:{p:{position:"left",title:{display:true,text:"MSLP [hPa]"}},
        w:{position:"right",title:{display:true,text:"Maximalwind [km/h]"},grid:{drawOnChartArea:false}}}}
  });
}
function plotCps(t){
  if(window.HartPhaseSpace)window.HartPhaseSpace.update(t);
}
function selectTrack(id){activeId=id;drawMap(false);listTracks();details(visible.find(t=>t.id===id)||null);}
function repaint(fit=false){
  visible=selectedTracks();
  if(!visible.some(t=>t.id===activeId))activeId=visible[0]?.id||null;
  $("hour").max=visible.length?Math.ceil(Math.max(24,...visible.flatMap(t=>t.points.map(p=>p.h)))/6)*6:240;
  if(chosenHour()>Number($("hour").max))$("hour").value=$("hour").max;
  $("hourlabel").textContent="+"+chosenHour()+" h";
  drawMap(fit);listTracks();details(visible.find(t=>t.id===activeId)||null);
}
async function load(){
  $("refresh").disabled=true;setStatus("GFS- und ECMWF-Modell-Zugbahnen werden geladen …");
  try{
    async function get(url){
      const response=await fetch(url+"?v="+Date.now(),{cache:"no-store"});
      if(!response.ok)throw Error("HTTP "+response.status);
      const data=await response.json();
      if(data.schema!==1||!Array.isArray(data.models)||!Array.isArray(data.tracks))
        throw Error("Unerwartetes Datenformat");
      return data;
    }
    const result=await Promise.allSettled([get(DATA_URL),get(ATLANTIC_URL),get(ECMWF_LOW_URL)]);
    const success=result.filter(r=>r.status==="fulfilled").map(r=>r.value);
    if(!success.length)throw Error("ECMWF- und GFS-Archiv derzeit nicht erreichbar");
    const issues=result.map((r,i)=>r.status==="rejected"?["ECMWF-TC","GFS","IFS/AIFS-Tiefs"][i]+": "+r.reason.message:null).filter(Boolean);
    allData={schema:1,models:success.flatMap(j=>j.models),tracks:success.flatMap(j=>j.tracks)};
    const latest=success.map(j=>j.updated_utc).filter(Boolean).sort().at(-1);
    $("updated").textContent="Aktuellster Datenabruf: "+stamp(latest);
    $("modelruns").textContent=allData.models.map(m=>(MODEL_LABEL[m.model]||m.model)+": "
      +(m.status==="ok"?stamp(m.run):m.status==="no_storms"?"keine passenden Tiefbahnen":m.status==="stale"?"älterer Datenstand "+stamp(m.run):"nicht verfügbar")).join(" · ");
    if(allData.models.some(m=>m.model==="gfs"))$("model").value="gfs";
    else if($("model").value==="gfs")$("model").value="all";
    populate();$("hour").value=$("model").value==="gfs"?"120":"48";repaint(true);
    if(window.HartPhaseSpace)window.HartPhaseSpace.loadHistory();
    const gfs=success.find(j=>j.models.some(m=>m.model==="gfs"));
    setStatus((gfs?gfs.tracks.length+" GFS-Nordatlantik-Tiefbahnen und "+
      (gfs.cps_points||0)+" berechnete CPS-Zeitpunkte. ":"")+
      allData.tracks.length+" reale Modell-Zugbahnen verfügbar."+
      (issues.length?" Teilweise fehlende Quellen: "+issues.join("; "):""));
  }catch(err){
    allData=null;visible=[];if(lines)lines.clearLayers();repaint(false);
    setStatus("Live-Daten fehlen: "+err.message+". Keine erfundenen Tiefzentren oder CPS-Werte.",true);
    $("updated").textContent="Datenstand: nicht verfügbar";
  }finally{$("refresh").disabled=false;}
}
function savePng(){
  if(!intensityChart||!activeId){setStatus("Bitte zuerst eine Modell-Zugbahn auswählen.",true);return;}
  const original=intensityChart.canvas,canvas=document.createElement("canvas");
  canvas.width=original.width;canvas.height=original.height;
  const ctx=canvas.getContext("2d");if(!ctx)return;
  ctx.fillStyle="#ffffff";ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(original,0,0);
  const a=document.createElement("a");a.download="Zyklone_Intensitaet_"+activeId+".png";
  a.href=canvas.toDataURL("image/png");document.body.append(a);a.click();a.remove();
}
function saveCpsPng(){
  if(window.HartPhaseSpace)window.HartPhaseSpace.exportPng();
}
map=L.map("map",{worldCopyJump:true}).setView([48,-45],4);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{
  attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',maxZoom:9
}).addTo(map);
lines=L.layerGroup().addTo(map);
if(window.CycloneDiagnostics)window.CycloneDiagnostics.setMap(map,L);
$("model").addEventListener("change",()=>{if(allData){if($("model").value==="ens")$("ensemble").checked=true;populate();repaint(true);}});
$("system").addEventListener("change",()=>repaint(true));
$("ensemble").addEventListener("change",()=>repaint(true));
$("hour").addEventListener("input",()=>repaint(false));
$("refresh").addEventListener("click",load);
$("png").addEventListener("click",savePng);
$("cpsPng").addEventListener("click",saveCpsPng);
load();
})();