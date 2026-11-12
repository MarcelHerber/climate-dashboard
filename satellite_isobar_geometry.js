/* Shared display-only contour hygiene for MTG, PNG, vector PDF and GIF.
 * Works on authenticated ECMWF GRIB-derived contour coordinates; NEVER alters
 * upstream MSLP, forecast validity, or the scientific source archive.
 */
(() => {
"use strict";
const MIN_LOOP_DIAGONAL=26;    // normalized 1000x1000 geographic map units
const MIN_LOOP_AREA=115;       // suppress longer but tiny narrow closed loops
const MAX_NARROW_LOOP=55;
const MIN_OPEN_LENGTH=12;      // only remove minute disconnected remnants
const MAX_SHORT_OPEN_DIAGONAL=13;
const SMOOTHING=.22;           // one cautious Chaikin pass
const MAX_SHIFT=2.4;          // projected units; limit meteorological drift
const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
const inside=(p,b)=>p[0]>=b[0]&&p[0]<=b[2]&&p[1]>=b[1]&&p[1]<=b[3];
function project(p,b){
 return [(p[0]-b[0])/(b[2]-b[0])*1000,(b[3]-p[1])/(b[3]-b[1])*1000];
}
function clean(line,b){
 if(!Array.isArray(line)||line.length<2)return null;
 const pts=[],map=[];
 for(const point of line){
  if(!Array.isArray(point)||point.length<2||
     !Number.isFinite(point[0])||!Number.isFinite(point[1]))return null;
  const projected=project(point,b);
  if(map.length&&distance(map[map.length-1],projected)<.25)continue;
  pts.push(point);map.push(projected);
 }
 if(map.length<2)return null;
 const closed=map.length>=4&&distance(map[0],map[map.length-1])<1.5;
 if(closed&&distance(map[0],map[map.length-1])<.25){
  pts.pop();map.pop();
 }
 if(closed&&map.length<3)return null;
 if(pts.filter(p=>inside(p,b)).length<2)return null;
 let xmin=Infinity,xmax=-Infinity,ymin=Infinity,ymax=-Infinity,total=0,twiceArea=0;
 for(let i=0;i<map.length;i++){
  const a=map[i];xmin=Math.min(xmin,a[0]);xmax=Math.max(xmax,a[0]);
  ymin=Math.min(ymin,a[1]);ymax=Math.max(ymax,a[1]);
  if(i)total+=distance(map[i-1],a);
  if(closed){
   const next=map[(i+1)%map.length];
   twiceArea+=a[0]*next[1]-next[0]*a[1];
  }
 }
 if(closed)total+=distance(map[map.length-1],map[0]);
 const diameter=Math.hypot(xmax-xmin,ymax-ymin),area=Math.abs(twiceArea)/2;
 if(closed&&(diameter<MIN_LOOP_DIAGONAL||
    (area<MIN_LOOP_AREA&&diameter<MAX_NARROW_LOOP)))return null;
 if(!closed&&total<MIN_OPEN_LENGTH&&diameter<MAX_SHORT_OPEN_DIAGONAL)return null;
 return {points:pts,normalized:map,closed,diameter,length:total};
}
function smooth(segment){
 const {points,normalized,closed}=segment;
 if(points.length<3)return points.map(p=>p.slice());
 const out=closed?[]:[points[0].slice()],size=points.length;
 const pairs=closed?size:size-1;
 for(let i=0;i<pairs;i++){
  const j=(i+1)%size,delta=distance(normalized[i],normalized[j]);
  const t=Math.min(SMOOTHING,delta>0?MAX_SHIFT/delta:SMOOTHING);
  const a=points[i],b=points[j];
  out.push([a[0]*(1-t)+b[0]*t,a[1]*(1-t)+b[1]*t]);
  out.push([a[0]*t+b[0]*(1-t),a[1]*t+b[1]*(1-t)]);
 }
 if(closed)out.push(out[0].slice());else out.push(points[size-1].slice());
 return out;
}
function prepare(contours,bbox,spacing=5){
 if(!Array.isArray(contours)||!Array.isArray(bbox)||bbox.length!==4||
    bbox[2]<=bbox[0]||bbox[3]<=bbox[1])throw Error("Ungültige Isobarengeometrie");
 const groups=[];
 for(const level of contours){
  const hpa=Number(level.hpa);
  if(!Number.isFinite(hpa)||hpa%Number(spacing||5)!==0||!Array.isArray(level.lines))continue;
  const runs=[];
  let best=null,bestLength=-1;
  for(const line of level.lines){
   const candidate=clean(line,bbox);
   if(!candidate)continue;
   const smoothed=smooth(candidate);
   runs.push(smoothed);
   if(candidate.length>bestLength){
    const local=smoothed.filter(p=>inside(p,bbox));
    if(local.length>=7){best=local[Math.floor(local.length/2)];bestLength=candidate.length;}
   }
  }
  if(runs.length)groups.push({
   hpa,heavy:hpa===1015,runs,
   label:(hpa===1015||hpa%10===0)?best:null
  });
 }
 return groups;
}
window.SatelliteIsobarGeometry={prepare,clean,smooth,project,
 settings:{minLoopDiagonal:MIN_LOOP_DIAGONAL,minLoopArea:MIN_LOOP_AREA,
  minOpenLength:MIN_OPEN_LENGTH,smoothing:SMOOTHING,maxShift:MAX_SHIFT}};
})();
