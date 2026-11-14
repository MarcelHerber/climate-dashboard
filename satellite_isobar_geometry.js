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
// Identify synoptically significant CLOSED, nested model contours, not
// geographic coastlines or a pixel-derived pressure estimate.
// Two DISTINCT surrounding contour levels are required in the correct
// pressure direction. Otherwise a high/low is deliberately unlabelled.
function insidePolygon(point,ring){
 let hit=false;
 for(let i=0,j=ring.length-1;i<ring.length;j=i++){
  const a=ring[i],b=ring[j];
  if((a[1]>point[1])!==(b[1]>point[1])&&
     point[0]<(b[0]-a[0])*(point[1]-a[1])/(b[1]-a[1])+a[0])hit=!hit;
 }
 return hit;
}
function polygonCenter(ring){
 let twice=0,sx=0,sy=0;
 for(let i=0;i<ring.length;i++){
  const a=ring[i],b=ring[(i+1)%ring.length],cross=a[0]*b[1]-b[0]*a[1];
  twice+=cross;sx+=(a[0]+b[0])*cross;sy+=(a[1]+b[1])*cross;
 }
 if(Math.abs(twice)<.001)return null;
 const center=[sx/(3*twice),sy/(3*twice)];
 if(insidePolygon(center,ring))return center;
 // Irregular rings may have a centroid outside; sample inside their
 // bounding box rather than guessing from the outline midpoint.
 let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
 for(const p of ring){minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);
  minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1]);}
 const proposals=[[(minX+maxX)/2,(minY+maxY)/2]];
 for(let x=1;x<=5;x++)for(let y=1;y<=5;y++)
  proposals.push([minX+(maxX-minX)*x/6,minY+(maxY-minY)*y/6]);
 return proposals.find(p=>insidePolygon(p,ring))||null;
}
function detectPressureSystems(contours,bbox,{minRings=3,maxSystems=7,minSeparation=94}={}){
 if(!Array.isArray(contours)||!Array.isArray(bbox)||bbox.length!==4)return [];
 const rings=[];
 for(const level of contours){
  const hpa=Number(level?.hpa);
  if(!Number.isFinite(hpa)||!Array.isArray(level.lines))continue;
  for(const line of level.lines){
   const r=clean(line,bbox);
   if(!r?.closed||r.diameter<32)continue;
   // Do not infer a center from an incomplete ring clipped by the map edge.
   if(r.normalized.some(p=>p[0]<7||p[0]>993||p[1]<7||p[1]>993))continue;
   let area2=0;
   for(let i=0;i<r.normalized.length;i++){
    const a=r.normalized[i],b=r.normalized[(i+1)%r.normalized.length];
    area2+=a[0]*b[1]-b[0]*a[1];
   }
   const area=Math.abs(area2)/2;
   if(area<220||area>600000)continue;
   const center=polygonCenter(r.normalized);
   // The ECMWF/contourpy generator preserves line winding. For these
   // lon/lat contours, anticlockwise positive area encloses HIGHER pressure,
   // clockwise negative area encloses LOWER pressure. Unlike the display
   // projection (inverted y), this sign is measured in geographical coords.
   let geoArea2=0;
   for(let i=0;i<r.points.length;i++){
    const a=r.points[i],b=r.points[(i+1)%r.points.length];
    geoArea2+=a[0]*b[1]-b[0]*a[1];
   }
   if(center)rings.push({hpa,center,outline:r.normalized,area,
    higherInside:geoArea2>0});
  }
 }
 const options=[];
 // Strict 3-ring nesting is excellent for deep lows but misses common broad,
 // relatively flat highs. A sufficiently large, COMPLETE anticlockwise
 // contour at >=1015 hPa is a genuine MSLP high by source contour winding,
 // even when the next 5-hPa threshold is not reached (e.g. 1020-1024 hPa).
 // Do not mark small islands/noise, clipped systems, or a low's outer edge.
 // A single, CLOSED clockwise ECMWF/contourpy ring can already
 // enclose a genuine secondary LOW, just as one anticlockwise 1020-hPa
 // contour can mark a broad high. The previous three-ring minimum missed,
 // for example, the verified 1000-hPa low at 18.8°W / 49.8°N on 14 Nov 2026.
 // This conservative exception only permits pronounced (<1010 hPa)
 // compact lows with a substantial, well-rounded, fully contained polygon.
 // Deep/nested systems still take priority in the score ranking.
 // Winding is read in geographic lon/lat, NOT reversed screen coordinates.
 for(const ring of rings){
  if(ring.higherInside||ring.hpa>1010||ring.area<1250)continue;
  const xs=ring.outline.map(p=>p[0]),ys=ring.outline.map(p=>p[1]);
  const width=Math.max(...xs)-Math.min(...xs);
  const height=Math.max(...ys)-Math.min(...ys);
  const diameter=Math.hypot(width,height);
  const rectangularArea=width*height;
  if(width<30||height<26||diameter<55||
     rectangularArea<=0||ring.area/rectangularArea<.42)continue;
  const smallerHigh=rings.some(inner=>inner!==ring&&inner.higherInside&&
   inner.area<ring.area*.85&&insidePolygon(inner.center,ring.outline));
  if(smallerHigh)continue;
  options.push({type:"T",hpa:ring.hpa,
   score:23+Math.min(14,Math.sqrt(ring.area)/9)+
    Math.max(0,1010-ring.hpa)*.15,
   center:ring.center,rings:1,windingVerified:true,
   detection:"closed-single-low"});
 }
 for(const ring of rings){
  if(!ring.higherInside||ring.hpa<1015||
     ring.area<4500||Math.sqrt(ring.area)<60)continue;
  const smallerLower=rings.some(inner=>inner!==ring&&
   inner.area<ring.area*.85&&inner.hpa<ring.hpa&&
   insidePolygon(inner.center,ring.outline));
  if(smallerLower)continue;
  options.push({type:"H",hpa:ring.hpa,
   score:25+Math.min(24,Math.sqrt(ring.area)/10)+Math.max(0,ring.hpa-1015),
   center:ring.center,rings:1,windingVerified:true});
 }
 for(const inner of rings){
  for(const type of ["T","H"]){
   // Highs have lower-pressure outer contours; lows have higher outer ones.
   const surrounding=rings.filter(outer=>outer!==inner&&
    outer.area>inner.area*1.12&&
    (type==="T"?outer.hpa>inner.hpa:outer.hpa<inner.hpa)&&
    insidePolygon(inner.center,outer.outline));
   const levels=[...new Set(surrounding.map(r=>r.hpa))];
   const ringCount=levels.length+1;
   if(ringCount<minRings)continue;
   // A lower-count, opposite-sign nested system means an ambiguous
   // saddle: do not draw an unjustified H/T marker there.
   const opposite=rings.filter(outer=>outer!==inner&&
    outer.area>inner.area*1.12&&
    (type==="T"?outer.hpa<inner.hpa:outer.hpa>inner.hpa)&&
    insidePolygon(inner.center,outer.outline)).length;
   if(opposite>=levels.length)continue;
   const score=levels.length*18+
    Math.min(25,Math.sqrt(inner.area)/7)+
    Math.min(16,Math.abs(inner.hpa-1013)/3);
   options.push({type,hpa:inner.hpa,score,center:inner.center,
    rings:ringCount});
  }
 }
 options.sort((a,b)=>b.score-a.score||a.hpa-b.hpa);
 const chosen=[],selectedCenters=[];
 for(const p of options){
  if(selectedCenters.some(q=>distance(q,p.center)<minSeparation))continue;
  const [x,y]=p.center;
  if(x<35||x>965||y<35||y>965)continue;
  const lon=bbox[0]+x/1000*(bbox[2]-bbox[0]);
  const lat=bbox[3]-y/1000*(bbox[3]-bbox[1]);
  selectedCenters.push(p.center);
  chosen.push({type:p.type,lon,lat,hpa:p.hpa,score:p.score,rings:p.rings});
  if(chosen.length>=maxSystems)break;
 }
 return chosen;
}
// Detect on the full ECMWF geographic domain rather than only the visible
// map crop. A synoptic high may have its CENTER in Europe while its closing
// ring extends a little beyond the European viewport (e.g. west of Iceland).
// Only place the resulting letter if its true center is inside the viewer.
const MODEL_VIEW_BBOX=[-70.5,14.5,49.5,75.5];
function detectVisiblePressureSystems(contours,viewport,{
 minRings=3,maxSystems=7,minSeparation=94
}={}){
 const opts={minRings,maxSystems:16,minSeparation:55};
 const candidates=[
  ...detectPressureSystems(contours,MODEL_VIEW_BBOX,opts),
  ...detectPressureSystems(contours,viewport,opts)
 ].sort((a,b)=>b.score-a.score);
 const selected=[];
 for(const p of candidates){
  const at=project([p.lon,p.lat],viewport);
  if(at[0]<35||at[0]>965||at[1]<35||at[1]>965)continue;
  if(selected.some(q=>distance(project([q.lon,q.lat],viewport),at)<minSeparation))continue;
  selected.push(p);
  if(selected.length>=maxSystems)break;
 }
 return selected;
}
window.SatelliteIsobarGeometry={detectVisiblePressureSystems,detectPressureSystems,prepare,clean,smooth,project,
 settings:{minLoopDiagonal:MIN_LOOP_DIAGONAL,minLoopArea:MIN_LOOP_AREA,
  minOpenLength:MIN_OPEN_LENGTH,smoothing:SMOOTHING,maxShift:MAX_SHIFT}};
})();
