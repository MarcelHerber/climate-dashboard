/* Hart Phase Space: scientific GFS lagged-run spaghetti and consensus.
   NEVER present deterministic initialization cycles as a true GEFS ensemble. */
(function(){
"use strict";
const BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/cyclone-tracker-data/data/cyclone-tracker/";
const $=id=>document.getElementById(id);
let maps=null, charts=[null,null], source=null, histories=[], chosen=null, loadState="Nicht geladen",lastDrawKey=null;
function num(n,p=0){return Number.isFinite(n)?n.toLocaleString("de-DE",{maximumFractionDigits:p,minimumFractionDigits:p}):"–";}
function iso(x){return new Date(x).toLocaleString("de-DE",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit",timeZone:"UTC"})+" UTC";}
function valid(p){return p&&p.cps&&["b","vt_lower","vt_upper"].every(k=>Number.isFinite(p.cps[k]));}
function dist(a,b){
 const r=Math.PI/180,dlat=(b.lat-a.lat)*r,dlon=(b.lon-a.lon)*r;
 const z=Math.sin(dlat/2)**2+Math.cos(a.lat*r)*Math.cos(b.lat*r)*Math.sin(dlon/2)**2;
 return 12742*Math.atan2(Math.sqrt(z),Math.sqrt(Math.max(0,1-z)));
}
function interpolateAt(points,time){
 const p=points.find(p=>p.time===time&&valid(p));return p||null;
}
function match(base,other){
 // Identify the same low using overlapping valid times AND geographical
 // proximity. Names in different GFS initializations are not stable IDs.
 const byTime=new Map(other.points.filter(valid).map(p=>[p.time,p]));
 const distances=[];
 for(const p of base.points.filter(valid)){
   const q=byTime.get(p.time);if(q)distances.push(dist(p,q));
 }
 distances.sort((a,b)=>a-b);
 if(distances.length<2||distances[0]>350)return null;
 const top=distances.slice(0,Math.min(5,distances.length));
 const mean=top.reduce((a,b)=>a+b,0)/top.length;
 return mean<420?mean:null;
}
function findComparisons(base,archive){
 const out=[base],seen=new Set([String(base.run)]);
 for(const data of archive){
   if(!data||!Array.isArray(data.tracks))continue;
   let best=null,score=Infinity;
   for(const tr of data.tracks){
     if(tr.model!=="gfs"||seen.has(String(tr.run)))continue;
     const s=match(base,tr);
     if(s!==null&&s<score){best=tr;score=s;}
   }
   if(best){out.push(best);seen.add(String(best.run));}
 }
 return out.sort((a,b)=>String(a.run).localeCompare(String(b.run)));
}
function pressureColor(n){
 if(n==null)return"#64748b";
 if(n<960)return"#dd2383";
 if(n<975)return"#f0811f";
 if(n<985)return"#44b84b";
 if(n<995)return"#00a8c5";
 if(n<1005)return"#2e65cf";
 if(n<1015)return"#8061ce";
 return"#374151";
}
function mainValues(tr){return tr.points.filter(valid).map(p=>({x:p.cps.vt_lower,y:p.cps.b,pressure:p.mslp_hpa,p}));}
const phaseBackground={
 id:"phaseQuadrants",
 beforeDraw(chart){
  const {ctx,chartArea:a,scales:{x,y}}=chart;
  if(!a||!x||!y)return;
  const cx=x.getPixelForValue(0),cy=y.getPixelForValue(10);
  ctx.save();
  ctx.beginPath();ctx.rect(a.left,a.top,a.width,a.height);ctx.clip();
  const range=[
   {left:a.left,top:a.top,width:Math.max(0,cx-a.left),height:Math.max(0,cy-a.top),color:"#0d28d7",faded:"#efefff"},
   {left:cx,top:a.top,width:Math.max(0,a.right-cx),height:Math.max(0,cy-a.top),color:"#e75bce",faded:"#ffedf8"},
   {left:a.left,top:cy,width:Math.max(0,cx-a.left),height:Math.max(0,a.bottom-cy),color:"#a1a1a1",faded:"#f8f8f8"},
   {left:cx,top:cy,width:Math.max(0,a.right-cx),height:Math.max(0,a.bottom-cy),color:"#ed404b",faded:"#fff0f0"}
  ];
  range.forEach(q=>{
    const grad=ctx.createLinearGradient(q.left,q.top,q.left+Math.max(1,q.width),q.top);
    grad.addColorStop(0,q.left<cx?q.color:q.faded);
    grad.addColorStop(1,q.left<cx?q.faded:q.color);
    ctx.fillStyle=grad;ctx.fillRect(q.left,q.top,q.width,q.height);
  });
  const grad=ctx.createLinearGradient(0,y.getPixelForValue(40),0,y.getPixelForValue(2));
  grad.addColorStop(0,"rgba(255,255,255,0)");
  grad.addColorStop(.5,"rgba(255,255,255,.38)");
  grad.addColorStop(1,"rgba(255,255,255,.12)");
  ctx.fillStyle=grad;ctx.fillRect(a.left,Math.max(a.top,y.getPixelForValue(40)),a.width,Math.max(0,y.getPixelForValue(2)-y.getPixelForValue(40)));
  ctx.strokeStyle="rgba(17,24,39,.24)";ctx.lineWidth=1;
  ctx.beginPath();ctx.moveTo(cx,a.top);ctx.lineTo(cx,a.bottom);ctx.moveTo(a.left,cy);ctx.lineTo(a.right,cy);ctx.stroke();
  const labels=[
    ["ASYMMETRISCHER KALTKERN",-260,75,"white"],
    ["ASYMMETRISCHER WARMKERN",125,75,"#451a40"],
    ["SYMMETRISCHER KALTKERN",-230,-3,"#252525"],
    ["SYMMETRISCHER WARMKERN",120,-3,"#51171c"]
  ];
  ctx.textAlign="center";ctx.textBaseline="middle";
  const font=Math.max(8,Math.min(12,a.width/65));
  ctx.font="bold "+font+"px Arial, sans-serif";
  labels.forEach(([label,vx,vy,color])=>{
    const px=x.getPixelForValue(vx),py=y.getPixelForValue(vy);
    if(px>a.left+38&&px<a.right-38&&py>a.top+12&&py<a.bottom-13){
      ctx.fillStyle=color;ctx.fillText(label,px,py);
    }
  });
  ctx.restore();
 }
};
const consensusEnvelope={
 id:"laggedRunSpread",
 beforeDatasetsDraw(chart,args,opts){
   if(!opts?.points?.length)return;
   const {ctx,scales:{x,y}}=chart;
   ctx.save();ctx.fillStyle="rgba(75,77,83,.23)";
   for(const p of opts.points){
     if(p.n<2)continue;
     const px=x.getPixelForValue(p.x),py=y.getPixelForValue(p.y);
     const rx=Math.min(110,Math.max(3,Math.abs(x.getPixelForValue(p.x+p.sigmaX)-px)));
     const ry=Math.min(90,Math.max(3,Math.abs(y.getPixelForValue(p.y+p.sigmaY)-py)));
     ctx.beginPath();ctx.ellipse(px,py,rx,ry,0,0,Math.PI*2);ctx.fill();
   }
   ctx.restore();
 }
};
function bounds(runs){
 const pts=runs.flatMap(t=>mainValues(t));
 let xmin=-400,xmax=260,ymin=-20,ymax=130;
 for(const p of pts){
   xmin=Math.min(xmin,p.x-25);xmax=Math.max(xmax,p.x+25);
   ymin=Math.min(ymin,p.y-12);ymax=Math.max(ymax,p.y+12);
 }
 const cap=(n,v)=>Math.max(-1500,Math.min(1500,n));
 return {xmin:cap(xmin),xmax:cap(xmax),ymin:cap(ymin),ymax:cap(ymax)};
}
function consensus(tracks){
 if(tracks.length<2)return[];
 const times=[...new Set(tracks.flatMap(t=>t.points.filter(valid).map(p=>p.time)))].sort();
 const series=[];
 for(const t of times){
   const member=tracks.map(tr=>interpolateAt(tr.points,t)).filter(Boolean);
   if(member.length<2)continue;
   const xs=member.map(p=>p.cps.vt_lower),ys=member.map(p=>p.cps.b);
   const mean=a=>a.reduce((x,y)=>x+y,0)/a.length;
   const x=mean(xs),y=mean(ys);
   series.push({x,y,n:member.length,time:t,
     pressure:mean(member.map(p=>p.mslp_hpa).filter(Number.isFinite)),
     sigmaX:Math.sqrt(mean(xs.map(v=>(v-x)**2))),
     sigmaY:Math.sqrt(mean(ys.map(v=>(v-y)**2)))});
 }
 return series;
}
function makeChart(id,sets,extent,spreads){
 const chart=new Chart($(id),{
   type:"scatter",
   plugins:[phaseBackground,consensusEnvelope],
   data:{datasets:sets},
   options:{
     responsive:true,maintainAspectRatio:false,animation:false,parsing:false,
     plugins:{
       legend:{position:"bottom",labels:{color:"#283141",boxWidth:12,font:{size:11}}},
       tooltip:{callbacks:{label:item=>{
         const pt=item.raw;
         return item.dataset.label+": −VTᴸ "+num(pt.x,1)+", B "+num(pt.y,1)+" m"+
             (Number.isFinite(pt.pressure)?", "+num(pt.pressure)+" hPa":"");
       }}},
       laggedRunSpread:{points:spreads}
     },
     scales:{
       x:{type:"linear",min:extent.xmin,max:extent.xmax,
          title:{display:true,text:"−VTᴸ · 900–600 hPa (Kaltkern ← 0 → Warmkern)",font:{size:12,weight:"bold"},color:"#1850b8"},
          ticks:{color:"#263343"},grid:{color:"rgba(40,45,55,.13)"},border:{color:"#27364d"}},
       y:{type:"linear",min:extent.ymin,max:extent.ymax,
          title:{display:true,text:"B [m] · 900–600 hPa · Asymmetrie",font:{size:12,weight:"bold"},color:"#1850b8"},
          ticks:{color:"#263343"},grid:{color:"rgba(40,45,55,.13)"},border:{color:"#27364d"}}
     }
   }
 });
 return chart;
}
function drawPhase(tracks){
 for(const c of charts)if(c)c.destroy();
 charts=[null,null];
 if(!tracks.length)return;
 const extent=bounds(tracks);
 const dataSets=tracks.map((t,i)=>({
    label:"GFS "+new Date(t.run).toISOString().slice(5,16).replace("T"," " )+" UTC",
    data:mainValues(t).map(({x,y,pressure})=>({x,y,pressure})),
    borderColor:["#067fc2","#08b6aa","#9b59d0","#2c74e0","#65ae44"][i%5],
    backgroundColor:["#067fc2","#08b6aa","#9b59d0","#2c74e0","#65ae44"][i%5],
    pointRadius:2,pointHoverRadius:5,showLine:true,spanGaps:false,tension:0,borderWidth:2
 }));
 charts[0]=makeChart("cpsSpaghettiPlot",dataSets,extent,[]);
 const c=consensus(tracks);
 const ready=c.length>=2&&tracks.length>=2;
 $("cpsConsensusEmpty").hidden=ready;
 $("cpsConsensusPlotWrap").hidden=!ready;
 $("cpsConsensusSubtitle").textContent=ready
   ?tracks.length+" GFS-Läufe · graue Flächen zeigen ±1σ der Phasenposition pro gültigem Zeitpunkt."
   :"Kein statistischer Konsens mit einem einzigen GFS-Lauf. Weitere reale Modellstarts werden benötigt.";
 if(ready){
   const series={
     label:"GFS-Multilauf-Mittel · "+tracks.length+" Läufe",
     data:c.map(p=>({x:p.x,y:p.y,pressure:p.pressure})),
     showLine:true,borderColor:"#111827",borderWidth:3,
     backgroundColor:c.map(p=>pressureColor(p.pressure)),
     pointBackgroundColor:c.map(p=>pressureColor(p.pressure)),
     pointBorderColor:"#101010",pointBorderWidth:1.5,
     pointRadius:7,pointHoverRadius:9,tension:0
   };
   charts[1]=makeChart("cpsConsensusPlot",[series],extent,c);
 }
 $("cpsSummary").textContent=
    tracks.length>1?tracks.length+" übereinstimmende GFS-Modellstarts (zeitversetzt, kein GEFS-Ensemble)"
      :"Nur 1 GFS-Modelllauf dieses Tiefs vorhanden · echter Konsens noch nicht möglich";
 $("cpsPhaseStatus").textContent="Phasenparameter: echte GFS-Geopotenzialfelder · Hart (2003)";
}
function makeMap(node){
 return L.map(node,{zoomControl:false,attributionControl:false,
   scrollWheelZoom:false,dragging:false,doubleClickZoom:false,touchZoom:false,boxZoom:false}).setView([50,-40],3);
}
function geoMapUpdate(tracks){
 if(!maps){maps=[makeMap("cpsMiniMapTop"),makeMap("cpsMiniMapBottom")];
    maps.forEach(map=>{
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:7,crossOrigin:true}).addTo(map);
      map.__tracks=L.layerGroup().addTo(map);
    });
 }
 for(const map of maps){
   map.__tracks.clearLayers();
   const coords=[];
   tracks.forEach((t,i)=>{
     const pts=t.points.filter(p=>valid(p)&&Number.isFinite(p.lat)&&Number.isFinite(p.lon));
     if(!pts.length)return;
     const latlng=pts.map(p=>[p.lat,p.lon]);coords.push(...latlng);
     const color=["#0475bb","#0da6a0","#9853db","#4e89d4","#87b84f"][i%5];
     L.polyline(latlng,{color,weight:2.8,opacity:.9}).addTo(map);
     if(i===tracks.length-1){
       L.circleMarker(latlng[0],{radius:5,color:"#111827",fillColor:"#45c38d",fillOpacity:1}).addTo(map).bindTooltip("Start");
       L.circleMarker(latlng[latlng.length-1],{radius:5,color:"#111827",fillColor:"#ef644e",fillOpacity:1}).addTo(map).bindTooltip("Ende");
     }
   });
   if(coords.length){
     map.invalidateSize();
     map.fitBounds(coords,{padding:[20,20],maxZoom:5});
   }
 }
}
async function loadHistory(){
 loadState="Lade GFS-Multilaufarchiv …";histories=[];
 try{
   const response=await fetch(BASE+"atlantic_history_index.json?v="+Date.now(),{cache:"no-store"});
   if(!response.ok)throw Error("noch kein Multilaufarchiv");
   const index=await response.json();
   if(!Array.isArray(index.runs))throw Error("ungültiger Multilaufindex");
   const candidates=index.runs.filter(p=>/^atlantic_history\/gfs_\d{10}\.json$/.test(p)).slice(0,5);
   const result=await Promise.allSettled(candidates.map(p=>fetch(BASE+p+"?v="+Date.now(),{cache:"no-store"}).then(r=>{if(!r.ok)throw Error(r.status);return r.json();})));
   histories=result.filter(x=>x.status==="fulfilled").map(x=>x.value).filter(x=>Array.isArray(x.tracks));
   loadState=histories.length?histories.length+" historische GFS-Läufe verfügbar":"Noch keine historischen GFS-Läufe";
 }catch(e){loadState="Historische GFS-Läufe noch nicht verfügbar";}
 if(chosen)update(chosen);
}
function update(t){
 chosen=t;
 $("cpsRealNotice").textContent=loadState;
 if(!t||t.model!=="gfs"){
   for(const c of charts)if(c)c.destroy();
   charts=[null,null];
   $("cpsModuleEmpty").hidden=false;
   $("cpsModuleContent").hidden=true;
   lastDrawKey=null;
   $("cpsModuleEmpty").textContent=t&&t.model!=="gfs"
     ?"ECMWF-Zugbahnen besitzen hier noch keine berechnete thermische Kernstruktur. Bitte ein GFS-Nordatlantik-Tief wählen."
     :"Bitte ein GFS-Tief auf der Karte auswählen.";
   return;
 }
 const drawKey=String(t.id)+":"+String(t.run)+":"+histories.length;
 if(drawKey===lastDrawKey&&charts[0])return;
 lastDrawKey=drawKey;
 const tracks=findComparisons(t,histories);
 const points=tracks.flatMap(t=>t.points.filter(valid));
 if(points.length<2){
   $("cpsModuleEmpty").hidden=false;$("cpsModuleContent").hidden=true;
   lastDrawKey=null;
   $("cpsModuleEmpty").textContent="Für dieses Tief sind nicht genügend echte CPS-Werte vorhanden.";
   return;
 }
 $("cpsModuleEmpty").hidden=true;
 $("cpsModuleContent").hidden=false;
 $("cpsStormName").textContent=t.name+" · Hauptlauf "+iso(t.run);
 $("cpsSpaghettiSubtitle").textContent=tracks.length+" tatsächliche GFS-Initialisierungen. Keine Ensemble-Perturbationen.";
 drawPhase(tracks);
 // Leaflet needs visible containers before initialization.
 setTimeout(()=>geoMapUpdate(tracks),0);
}
function exportPng(){
 if(!charts[0])return;
 const gap=25,head=60,width=Math.max(...charts.filter(Boolean).map(c=>c.canvas.width));
 const heights=charts.filter(Boolean).map(c=>c.canvas.height);
 const canvas=document.createElement("canvas");canvas.width=width+gap*2;
 canvas.height=heights.reduce((a,b)=>a+b,0)+gap*(heights.length+1)+head*heights.length;
 const ctx=canvas.getContext("2d");if(!ctx)return;
 ctx.fillStyle="#fff";ctx.fillRect(0,0,canvas.width,canvas.height);
 let y=gap;
 charts.filter(Boolean).forEach((chart,i)=>{
   ctx.fillStyle="#067039";ctx.font="bold 18px Arial";ctx.fillText(
     i===0?"GFS-MULTILAUF · PHASENRAUM":"GFS-MULTILAUF · KONSENS (±1σ)",gap,y+25);
   ctx.fillStyle="#334155";ctx.font="13px Arial";
   ctx.fillText("Hart (2003) | "+String(chosen?.name||"")+
       " | Modelle: "+(1+histories.length)+" ggf. vergleichbare Läufe",gap,y+45);
   y+=head;ctx.drawImage(chart.canvas,gap,y);y+=chart.canvas.height+gap;
 });
 const a=document.createElement("a");a.href=canvas.toDataURL("image/png");
 a.download="Hart_CPS_Multilauf_"+String(chosen?.id||"tief").replace(/[^A-Za-z0-9_-]/g,"_")+".png";
 document.body.appendChild(a);a.click();a.remove();
}
window.HartPhaseSpace={update,loadHistory,exportPng};
})();