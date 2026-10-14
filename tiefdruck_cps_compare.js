/* Side-by-side Hart Cyclone Phase Space: GFS, ECMWF IFS, ECMWF AIFS.
 * All plotted coordinates originate from actual geophysical data. Matches
 * use two or more common valid UTC times and reciprocal storm-track ranking.
 * Missing diagnostics are never backfilled or interpolated in the browser.
 */
(function(root) {
"use strict";
const MODS=["gfs","ifs-atl","aifs-atl"];
const LABELS={gfs:"GFS", "ifs-atl":"IFS", "aifs-atl":"AIFS"};
const COLORS={gfs:"#7c3aed","ifs-atl":"#d14b36","aifs-atl":"#1767b8"};
const VALID=new Set(MODS);
function hasPosition(p) {
 return p && Number.isFinite(p.lat) && Number.isFinite(p.lon) && typeof p.time==="string";
}
function hasCps(p) {
 return p && p.cps && ["b","vt_lower","vt_upper"].every(k=>Number.isFinite(p.cps[k]));
}
function kilometers(a,b) {
 const rad=Math.PI/180,dlat=(a.lat-b.lat)*rad,dlon=(a.lon-b.lon)*rad;
 const x=Math.sin(dlat/2)**2+Math.cos(a.lat*rad)*Math.cos(b.lat*rad)*Math.sin(dlon/2)**2;
 return 12742*Math.asin(Math.sqrt(Math.max(0,Math.min(1,x))));
}
function trackScore(a,b) {
 if(!a||!b||a.model===b.model||!VALID.has(a.model)||!VALID.has(b.model))return null;
 const times=new Map((b.points||[]).filter(hasPosition).map(p=>[p.time,p]));
 const pairs=(a.points||[]).filter(hasPosition).map(p=>{
   const q=times.get(p.time);
   if(!q)return null;
   const km=kilometers(p,q);
   const dp=Number.isFinite(p.mslp_hpa)&&Number.isFinite(q.mslp_hpa)
     ?Math.abs(p.mslp_hpa-q.mslp_hpa):0;
   return {km,dp,time:p.time};
 }).filter(Boolean).sort((x,y)=>x.km-y.km);
 if(pairs.length<2)return null;
 const close=pairs.filter(p=>p.km<=450);
 if(close.length<2 || pairs[Math.floor(pairs.length/2)].km>500)return null;
 const take=close.slice(0,Math.min(close.length,6));
 const value=take.reduce((sum,p)=>sum+p.km+2*p.dp,0)/take.length;
 if(value>400)return null;
 return {score:value,overlap:pairs.length,near:close.length};
}
function ranking(anchor,targetModel,all) {
 return all.filter(t=>t.model===targetModel&&Array.isArray(t.points))
   .map(t=>({track:t,measure:trackScore(anchor,t)}))
   .filter(x=>x.measure)
   .sort((a,b)=>a.measure.score-b.measure.score);
}
function matchModels(anchor,all) {
 const result={gfs:null,"ifs-atl":null,"aifs-atl":null},details={};
 if(!anchor||!VALID.has(anchor.model)||!Array.isArray(all))return {models:result,details};
 result[anchor.model]=anchor;
 const pool=all.filter(t=>VALID.has(t.model)&&Array.isArray(t.points));
 for(const model of MODS) {
   if(model===anchor.model)continue;
   const ranked=ranking(anchor,model,pool);
   if(!ranked.length){details[model]="Keine eindeutig passende Zugbahn";continue;}
   const top=ranked[0],runner=ranked[1];
   if(runner&&runner.measure.score-top.measure.score<40) {
     details[model]="Mehrdeutige Tiefbahn – keine automatische Zuordnung";
     continue;
   }
   const reversed=ranking(top.track,anchor.model,pool);
   if(!reversed.length||reversed[0].track.id!==anchor.id){
     details[model]="Tiefbahnen nicht gegenseitig eindeutig zugeordnet";
     continue;
   }
   result[model]=top.track;
   details[model]={
     meanKm:Math.round(top.measure.score),
     commonTimes:top.measure.overlap,
     closeTimes:top.measure.near
   };
 }
 return {models:result,details};
}
function values(tracks,mode) {
 const out=[];
 for(const t of Object.values(tracks||{})) {
   if(!t)continue;
   for(const p of t.points||[]) {
     if(!hasCps(p))continue;
     out.push({x:p.cps.vt_lower,y:mode==="upper"?p.cps.vt_upper:p.cps.b});
   }
 }
 return out;
}
function axisRanges(tracks,mode) {
 const data=values(tracks,mode);
 const get=(axis,fallback)=>{
   const vals=data.map(p=>p[axis]).filter(Number.isFinite);
   vals.push(...fallback);
   let lo=Math.min(...vals),hi=Math.max(...vals);
   const pad=Math.max(8,(hi-lo)*0.12);
   lo=Math.floor((lo-pad)/10)*10;hi=Math.ceil((hi+pad)/10)*10;
   return {min:lo,max:hi};
 };
 return {x:get("x",[-70,70]),y:get("y",mode==="upper"?[-70,70]:[-12,35])};
}
function seriesPoints(track,mode){
 const raw=(track?.points||[]).filter(hasCps).slice()
   .sort((a,b)=>new Date(a.time)-new Date(b.time));
 const result=[];
 for(let i=0;i<raw.length;i++){
   const p=raw[i],prior=raw[i-1];
   if(prior&&Date.parse(p.time)-Date.parse(prior.time)>18*3600000)
     result.push({x:null,y:null,break:true});
   result.push({x:p.cps.vt_lower,y:mode==="upper"?p.cps.vt_upper:p.cps.b,
     time:p.time,h:p.h,pressure:p.mslp_hpa});
 }
 return result;
}
function formatUtc(x){
 if(!x)return"–";
 const date=new Date(x);
 return Number.isNaN(date.valueOf())?x:date.toLocaleString("de-DE",
   {timeZone:"UTC",day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})+" UTC";
}
function format(n,d=1){return Number.isFinite(n)?n.toLocaleString("de-DE",
  {minimumFractionDigits:d,maximumFractionDigits:d}):"–";}

if(typeof module!=="undefined"&&module.exports) {
 module.exports={trackScore,ranking,matchModels,axisRanges,hasCps,seriesPoints};
}
if(!root||!root.document)return;
const $=id=>document.getElementById(id);
const ID={gfs:"cpsCompareGfs","ifs-atl":"cpsCompareIfs","aifs-atl":"cpsCompareAifs"};
let selection=null,whole=null,matched=null,chartMap={},lastKey=null,lastData=null,validTime=null;
const cpsBackground={
 id:"cpsSharedRegions",
 beforeDraw(chart, _args,options){
  const area=chart.chartArea,scales=chart.scales;
  if(!area||!scales.x||!scales.y)return;
  const {ctx}=chart;
  ctx.save();
  ctx.beginPath();ctx.rect(area.left,area.top,area.width,area.height);ctx.clip();
  const center=Math.max(area.left,Math.min(area.right,scales.x.getPixelForValue(0)));
  const trans=options.upper?0:10;
  const threshold=Math.max(area.top,Math.min(area.bottom,scales.y.getPixelForValue(trans)));
  const regions=[
   [area.left,area.top,center-area.left,threshold-area.top,"rgba(57,87,218,.17)"],
   [center,area.top,area.right-center,threshold-area.top,"rgba(230,80,164,.19)"],
   [area.left,threshold,center-area.left,area.bottom-threshold,"rgba(83,127,198,.08)"],
   [center,threshold,area.right-center,area.bottom-threshold,"rgba(223,74,89,.10)"]
  ];
  for(const [x,y,w,h,c] of regions){ctx.fillStyle=c;ctx.fillRect(x,y,w,h);}
  ctx.strokeStyle="rgba(31,45,65,.48)";ctx.setLineDash([5,4]);ctx.lineWidth=1;
  ctx.beginPath();ctx.moveTo(center,area.top);ctx.lineTo(center,area.bottom);
  ctx.moveTo(area.left,threshold);ctx.lineTo(area.right,threshold);ctx.stroke();
  ctx.restore();
 }
};
function baseOptions(ranges,mode,showLegend){
 return {
  responsive:true,maintainAspectRatio:false,animation:false,parsing:false,
  interaction:{intersect:false,mode:"nearest"},
  plugins:{
   cpsSharedRegions:{upper:mode==="upper"},
   legend:{display:showLegend,position:"bottom",
     labels:{font:{size:11},filter:item=>item.text!=="Ausgewählter Termin"}},
   tooltip:{callbacks:{label:item=>{
     const p=item.raw||{};
     return item.dataset.label+": −VTᴸ "+format(p.x,1)+
       (mode==="upper"?", −VTᵁ ":" , B ")+format(p.y,1)+
       (p.time?" · "+formatUtc(p.time):"")+
       (Number.isFinite(p.pressure)?" · "+format(p.pressure)+" hPa":"");
   }}}
  },
  scales:{
   x:{type:"linear",min:ranges.x.min,max:ranges.x.max,
     title:{display:true,text:"−VTᴸ (900–600 hPa)",color:"#285d9b",font:{weight:"bold",size:11}},
     grid:{color:"rgba(90,105,130,.14)"},ticks:{maxTicksLimit:6}},
   y:{type:"linear",min:ranges.y.min,max:ranges.y.max,
     title:{display:true,text:mode==="upper"?"−VTᵁ (600–300 hPa)":"Asymmetrie B [m]",
       color:"#285d9b",font:{weight:"bold",size:11}},
     grid:{color:"rgba(90,105,130,.14)"},ticks:{maxTicksLimit:7}}
  }
 };
}
function pathData(model,track,mode) {
 return {
  label:LABELS[model],borderColor:COLORS[model],backgroundColor:COLORS[model],
  data:seriesPoints(track,mode),showLine:true,spanGaps:false,tension:0,
  pointRadius:3,pointHoverRadius:6,borderWidth:2.3,
  pointBorderColor:"#fff",pointBorderWidth:0.5
 };
}
function selectedDataset(model) {
 return {label:"Ausgewählter Termin",_timeMarker:true,data:[],
   showLine:false,pointRadius:7,pointHoverRadius:9,
   pointBorderColor:"#111827",pointBorderWidth:2.2,
   backgroundColor:COLORS[model]};
}
function paintPanel(model,track,ranges,mode) {
 const canvas=$(ID[model]);
 const old=chartMap[model];if(old){old.destroy();delete chartMap[model];}
 if(!track){canvas.hidden=true;return;}
 canvas.hidden=false;
 chartMap[model]=new Chart(canvas,{
  type:"scatter",plugins:[cpsBackground],
  data:{datasets:[pathData(model,track,mode),selectedDataset(model)]},
  options:baseOptions(ranges,mode,false)
 });
}
function paintCombined(ranges,mode) {
 if(chartMap.combined){chartMap.combined.destroy();delete chartMap.combined;}
 const datasets=[];
 for(const model of MODS){
  const tr=matched.models[model];if(!tr||!tr.points.some(hasCps))continue;
  datasets.push(pathData(model,tr,mode),selectedDataset(model));
 }
 chartMap.combined=new Chart($("cpsCompareTogether"),{
  type:"scatter",plugins:[cpsBackground],
  data:{datasets},options:baseOptions(ranges,mode,true)
 });
}
function showStates() {
 for(const model of MODS){
  const t=matched.models[model],box=$("cpsCompareStatus"+LABELS[model]);
  const canvas=$(ID[model]);
  let summary;
  if(!t)summary=typeof matched.details[model]==="string"?
    matched.details[model]:"Keine Tiefbahn ausgewählt";
  else {
   const count=t.points.filter(hasCps).length;
   const note=matched.details[model];
   summary=count>0?
     count+" echte CPS-Zeitpunkte · Lauf "+formatUtc(t.run)+
      (note?.commonTimes?" · "+note.commonTimes+" gemeinsame Termine · Zuordnungswert "+note.meanKm+" km":" · Referenzmodell"):
     "Tiefbahn erkannt, aber keine vollständige Hart-CPS-Diagnose";
  }
  box.textContent=summary;
  const valid=t?.points?.some(hasCps);
  canvas.hidden=!valid;
  $("cpsCompareUnavailable"+LABELS[model]).hidden=!!valid;
  if(!valid)$("cpsCompareUnavailable"+LABELS[model]).textContent=summary;
 }
}
function pointAtTime(t,time){
 return t?.points?.find(p=>p.time===time&&hasCps(p))||null;
}
function markTime(){
 if(!matched)return;
 const mode=$("cpsCompareMetric").value;
 const y=p=>mode==="upper"?p.cps.vt_upper:p.cps.b;
 for(const model of MODS) {
  const tr=matched.models[model],p=pointAtTime(tr,validTime);
  const chart=chartMap[model];
  if(chart) {
   chart.data.datasets[1].data=p?[{x:p.cps.vt_lower,y:y(p),
     time:p.time,pressure:p.mslp_hpa}]:[];
   chart.update("none");
  }
  const label=$("cpsCompareNow"+LABELS[model]);
  label.textContent=p?
    "Aktueller Termin: "+formatUtc(validTime)+" · B "+format(p.cps.b)+" m"+
    " · −VTᴸ "+format(p.cps.vt_lower)+" · −VTᵁ "+format(p.cps.vt_upper):
    "Kein CPS-Wert zum gewählten UTC-Termin";
 }
 if(chartMap.combined) {
  for(let i=0;i<chartMap.combined.data.datasets.length;i++) {
   const dataset=chartMap.combined.data.datasets[i];
   if(!dataset._timeMarker)continue;
   const model=chartMap.combined.data.datasets[i-1]?.label;
   const key=MODS.find(k=>LABELS[k]===model);
   const p=pointAtTime(matched.models[key],validTime);
   dataset.data=p?[{x:p.cps.vt_lower,y:y(p),time:p.time,pressure:p.mslp_hpa}]:[];
  }
  chartMap.combined.update("none");
 }
 $("cpsCompareSelectedTime").textContent="Gültiger Termin: "+formatUtc(validTime);
}
function reset() {
 for(const chart of Object.values(chartMap))chart.destroy();
 chartMap={};
 $("cpsCompareEmpty").hidden=false;
 $("cpsCompareContent").hidden=true;
}
function update(selected,allData,hour) {
 selection=selected;whole=allData;
 if(!selection||!VALID.has(selection.model)||!Array.isArray(whole?.tracks)){
  reset();lastKey=null;
  $("cpsCompareEmpty").textContent="Bitte ein GFS-, IFS- oder AIFS-Nordatlantik-Tief auswählen.";
  return;
 }
 const prior=(selection.points||[]).filter(p=>p.h<=hour).at(-1);
 validTime=prior?.time||selection.points?.[0]?.time||null;
 const key=[selection.model,selection.id,selection.run,whole.tracks.length,
   $("cpsCompareMetric").value].join("|");
 if(lastKey===key&&lastData===whole&&matched){
   markTime();return;
 }
 lastKey=key;lastData=whole;
 matched=matchModels(selection,whole.tracks);
 const available=Object.values(matched.models).filter(t=>t?.points?.some(hasCps));
 if(!available.length){
  reset();$("cpsCompareEmpty").textContent="Für dieses Tief ist noch keine echte CPS-Berechnung verfügbar.";
  return;
 }
 $("cpsCompareEmpty").hidden=true;
 $("cpsCompareContent").hidden=false;
 $("cpsCompareStorm").textContent=(selection.name||selection.storm_id||selection.id)+
   " · Referenz: "+LABELS[selection.model]+" · "+formatUtc(selection.run);
 const mode=$("cpsCompareMetric").value;
 const ranges=axisRanges(matched.models,mode);
 showStates();
 for(const model of MODS) {
   const t=matched.models[model];
   paintPanel(model,t?.points.some(hasCps)?t:null,ranges,mode);
 }
 paintCombined(ranges,mode);
 $("cpsCompareAxes").textContent="Identische Achsen: −VTᴸ "+
   format(ranges.x.min,0)+"…"+format(ranges.x.max,0)+", "+
   (mode==="upper"?"−VTᵁ ":"B ")+format(ranges.y.min,0)+"…"+format(ranges.y.max,0)+
   " · Automatische, modellübergreifende Skalierung";
 markTime();
}
function exportPng(){
 const targets=[["GFS",chartMap.gfs],["IFS",chartMap["ifs-atl"]],
                ["AIFS",chartMap["aifs-atl"]],["Gemeinsamer Vergleich",chartMap.combined]]
   .filter(pair=>pair[1]);
 if(!targets.length)return;
 const margin=25,title=58,gap=30;
 const w=Math.max(1100,...targets.map(pair=>pair[1].canvas.width+margin*2));
 const top=targets.slice(0,3),bottom=targets.find(pair=>pair[0]==="Gemeinsamer Vergleich");
 const heightTop=top.length?Math.max(...top.map(x=>x[1].canvas.height)):0;
 const totalHeight=margin*3+title+heightTop+gap+(bottom?bottom[1].canvas.height+34:0);
 const canvas=document.createElement("canvas");
 canvas.width=w;canvas.height=totalHeight;
 const ctx=canvas.getContext("2d");
 ctx.fillStyle="#ffffff";ctx.fillRect(0,0,w,totalHeight);
 ctx.fillStyle="#176198";ctx.font="bold 22px Arial";
 ctx.fillText("Hart-CPS: GFS / IFS / AIFS",margin,34);
 ctx.fillStyle="#35465b";ctx.font="14px Arial";
 ctx.fillText((selection?.name||"Nordatlantik-Tief")+" · "+formatUtc(validTime)+
   " · Nur echte Modellpunkte",margin,56);
 const usable=w-2*margin;
 const cell=top.length?usable/top.length:usable;
 top.forEach(([name,ch],i)=>{
  const ww=Math.min(cell-12,ch.canvas.width);
  ctx.fillStyle="#22354e";ctx.font="bold 16px Arial";
  ctx.fillText(name,margin+i*cell+3,title+22);
  ctx.drawImage(ch.canvas,margin+i*cell,title+27,ww,heightTop);
 });
 if(bottom){
  const y=title+heightTop+gap;
  ctx.fillStyle="#22354e";ctx.font="bold 16px Arial";
  ctx.fillText("Überlagerte Modellverläufe",margin,y);
  const ww=Math.min(bottom[1].canvas.width,usable);
  ctx.drawImage(bottom[1].canvas,margin,y+7,ww,bottom[1].canvas.height);
 }
 const a=document.createElement("a");
 a.download="Hart_CPS_GFS_IFS_AIFS_"+String(selection?.id||"Tief").replace(/[^A-Za-z0-9_-]/g,"_")+".png";
 a.href=canvas.toDataURL("image/png");document.body.append(a);a.click();a.remove();
}
$("cpsCompareMetric").addEventListener("change",()=>{lastKey=null;update(selection,whole,Number($("hour").value));});
$("cpsCompareExport").addEventListener("click",exportPng);
root.CycloneCpsComparison={update};
})(typeof window==="undefined"?null:window);
