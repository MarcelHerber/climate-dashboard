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

// Grid extrema are physically identified in the 0.25° IFS MSLP array before
// either 2-hPa or 5-hPa contours are drawn.
const GRID_METHODS=new Set(["ifs_mslp_grid_extrema_v1","ifs_mslp_grid_extrema_v2","ifs_mslp_grid_extrema_v3","ifs_mslp_grid_extrema_v4"]);
function modelGridCenters(overlay,viewport,{maxSystems=7,minSeparation=94}={}){
 if(!overlay||!GRID_METHODS.has(overlay.pressure_centers_method)||
    !Array.isArray(overlay.pressure_centers))return null; // legacy run
 if(overlay.pressure_centers.length>40)throw Error("IFS: ungültige Extremaanzahl");
 const proposed=[];
 const v4=overlay.pressure_centers_method==="ifs_mslp_grid_extrema_v4";
 const v3=v4||overlay.pressure_centers_method==="ifs_mslp_grid_extrema_v3";
 for(const item of overlay.pressure_centers){
  const lon=Number(item.lon),lat=Number(item.lat),hpa=Number(item.pressure_hpa);
  if(!["T","H"].includes(item.type)||!Number.isFinite(lon)||!Number.isFinite(lat)||
    lon < -75||lon > 55||lat < 12||lat > 80||hpa<850||hpa>1100||
    !Number.isFinite(item.score)||item.score<0||item.score>300)
   throw Error("IFS: fehlerhafte Druckgitter-Koordinate");
  const p=project([lon,lat],viewport);
  if(p[0]<35||p[0]>965||p[1]<35||p[1]>965)continue;
  const closedSystem=overlay.pressure_centers_method!=="ifs_mslp_grid_extrema_v1"&&item.closed_system===true;
  const area=Number(item.closed_area_km2)||0;
  if(v3&&closedSystem&&area<15000&&(viewport[2]-viewport[0])>=70&&item.prominence_hpa<5)continue;
  if(v3&&!closedSystem&&(viewport[2]-viewport[0])>=70&&item.prominence_hpa<(v4?2:3))continue;
  proposed.push({type:item.type,lon,lat,hpa,pressure_hpa:hpa,
   score:item.score,prominence_hpa:item.prominence_hpa,
   closedSystem,closedArea:area,
   method:overlay.pressure_centers_method,source:"ifs_grid"});
 }
 const rank=c=>c.score+(v3&&c.closedSystem?30+Math.sqrt(c.closedArea)/50:0);
 proposed.sort((a,b)=>rank(b)-rank(a)||a.lon-b.lon);
 const out=[];
 for(const m of proposed){
  const at=project([m.lon,m.lat],viewport);
  if(out.some(q=>distance(project([q.lon,q.lat],viewport),at)<minSeparation&&
    (!(q.closedSystem&&m.closedSystem)||(q.lon===m.lon&&q.lat===m.lat)||
      (v3&&Math.min(q.closedArea,m.closedArea)<15000))))continue;
  out.push(m);
  if(!v3&&out.length>=maxSystems)break;
 }
 return out;
}
// Reference dimensions match the actual regional WMS aspect ratios. Select
// once at reference size, not independently for every export resolution.
function pressureReferenceHeight(viewport){
 const ratios={"-27,24,49,73":850/1300,"-70,15,35,75":850/1400,
  "-37,24,19,53":620/1200,"-2,43,25,58":780/1300,"5,47,16,56":950/1140};
 return 720*(ratios[viewport.join(",")]||1);
}
function pressureLabels(centers,viewport,{width=1000,height=1000,fontSize=40.5}={}){
 const xy=(lon,lat)=>{
  const p=project([lon,lat],viewport);
  return [p[0]*width/1000,p[1]*height/1000];
 };
 const occupied=[];
 const overlaps=(a,b)=>a[0]<b[2]&&a[2]>b[0]&&a[1]<b[3]&&a[3]>b[1];
 const out=[];
 const stable=centers.some(c=>["ifs_mslp_grid_extrema_v3","ifs_mslp_grid_extrema_v4"].includes(c.method));
 const selectionWidth=stable?720:width,selectionHeight=stable?pressureReferenceHeight(viewport):height;
 const selectionFont=stable?29.16:fontSize;
 for(const m of centers){
  const [px,py]=xy(m.lon,m.lat);
  const sx=px*selectionWidth/width,sy=py*selectionHeight/height;
  const box=[sx-selectionFont*.43,sy-selectionFont*.58,sx+selectionFont*.43,sy+selectionFont*.58];
  if(box[0]<3||box[1]<3||box[2]>selectionWidth-3||box[3]>selectionHeight-3||occupied.some(b=>overlaps(box,b)))continue;
  occupied.push(box);
  out.push({...m,anchorX:px,anchorY:py,labelX:px,labelY:py,leader:false});
 }
 return out;
}
// Centers never move. Select the closest collision-free point ON the same
// drawn pressure contour for each numeric annotation; never change the paths.
function layoutPressureAnnotations(centers,groups,viewport,{width=1000,height=1000,fontSize=40.5,labelWidth=36,labelHeight=17,cityAnchors=[]}={}){
 const xy=p=>{const q=project(p,viewport);return [q[0]*width/1000,q[1]*height/1000];};
 const positioned=pressureLabels(centers,viewport,{width,height,fontSize});
 const occupied=positioned.map(c=>[c.anchorX-fontSize*.53,c.anchorY-fontSize*.68,c.anchorX+fontSize*.53,c.anchorY+fontSize*.68]);
 for(const c of cityAnchors){if(!Number.isFinite(c?.lon)||!Number.isFinite(c?.lat))continue;
  const [x,y]=xy([c.lon,c.lat]);occupied.push([x-6,y-19,x+Math.min(width*.23,100),y+7]);}
 const overlap=(a,b)=>a[0]<b[2]&&a[2]>b[0]&&a[1]<b[3]&&a[3]>b[1];
 const annotated=groups.map(g=>{
  if(!g.label)return g;
  const original=xy(g.label);let best=null,dist=Infinity,bestBox=null;
  const originalRun=g.runs.find(run=>run.some(p=>p[0]===g.label[0]&&p[1]===g.label[1]));
  for(const p of [g.label,...(originalRun||[])]){
   const [x,y]=xy(p),d=distance(original,[x,y]);
   if(d>=dist)continue;
   const b=[x-labelWidth/2,y-labelHeight/2,x+labelWidth/2,y+labelHeight/2];
   if(b[0]<3||b[1]<3||b[2]>width-3||b[3]>height-3||occupied.some(o=>overlap(b,o)))continue;
   best=p;dist=d;bestBox=b;
  }
  if(bestBox)occupied.push(bestBox);
  return {...g,label:best};
 });
 return {centers:positioned,groups:annotated};
}

// Geostationary projection: clip on the actual ellipsoidal limb before
// selecting labels. Runs here are normalized projected (top-down) pixels.
const diskPrepared=new WeakMap();
function prepareDisk(contours,region,spacing=5){
 const projection=window.SatelliteProjection;
 if(!projection?.isDisk(region)||![5,10].includes(Number(spacing)))throw Error("Ungültige Erdscheiben-Isobarendarstellung");
 if(!Array.isArray(contours))throw Error("Ungültige Erdscheiben-Konturen");
 const key=region+'|'+Number(spacing),cached=diskPrepared.get(contours);
 if(cached?.has(key))return cached.get(key);
 const groups=[];
 for(const level of contours||[]){
  if(!Number.isFinite(level.hpa)||level.hpa%Number(spacing)||!Array.isArray(level.lines))continue;
  const runs=[];let label=null,longest=0;
  for(const line of level.lines){
   for(const run of projection.paths(region,line,1000,1000)){
    if(run.length<2)continue;
    const cumulative=[0];for(let i=1;i<run.length;i++)cumulative.push(cumulative[i-1]+distance(run[i-1],run[i]));
    const length=cumulative.at(-1);
    // A wider view needs smaller thresholds in map units; retain clipped edges.
    if(length<4)continue;
    runs.push(run);
    if(length>longest&&length>45){longest=length;label=run[cumulative.findIndex(v=>v>=length/2)];}
   }
  }
  if(runs.length)groups.push({hpa:level.hpa,heavy:level.hpa===1015,runs,label:level.hpa===1015||level.hpa%10===0?label:null});
 }
 // Immutable model frames are reused during animation and resize; weak keys
 // release projected geometry when their bounded source chunks are evicted.
 const variants=cached||new Map();variants.set(key,groups);diskPrepared.set(contours,variants);
 return groups;
}
function diskCenters(overlay,region){
 const method=overlay?.pressure_centers_method,projection=window.SatelliteProjection;
 if(!projection?.isDisk(region)||!GRID_METHODS.has(method)||!Array.isArray(overlay?.pressure_centers))return [];
 if(overlay.pressure_centers.length>40)throw Error("IFS: ungültige Extremaanzahl");
 const out=[];
 for(const m of overlay.pressure_centers){
  const {lon,lat,pressure_hpa:hpa,score}=m;
  if(!['H','T'].includes(m.type)||![lon,lat,hpa,score].every(Number.isFinite)||Math.abs(lon)>180||Math.abs(lat)>90||hpa<850||hpa>1100||score<0||score>300)throw Error("IFS: ungültiges Druckgitter-Extremum");
  if(!projection.project(region,lon,lat,1000,1000))continue;
  const closedSystem=m.closed_system===true,closedArea=Number(m.closed_area_km2)||0;
  if(closedSystem&&closedArea<15000&&m.prominence_hpa<5)continue;
  if(!closedSystem&&m.prominence_hpa<2)continue;
  out.push({...m,hpa,closedSystem,closedArea,method,source:'ifs_grid'});
 }
 const rank=m=>m.score+(m.closedSystem?30+Math.sqrt(m.closedArea)/50:0);
 return out.sort((a,b)=>rank(b)-rank(a)||a.lon-b.lon);
}
function layoutDiskPressureAnnotations(overlay,groups,region,{width=1000,height=1000,fontSize=36,labelWidth=36,labelHeight=17,cityAnchors=[]}={}){
 const projection=window.SatelliteProjection,occupied=[],centers=[];
 const xy=p=>[p[0]*width/1000,p[1]*height/1000];
 const projectGeo=m=>projection.project(region,m.lon,m.lat,width,height);
 const overlaps=(a,b)=>a[0]<b[2]&&a[2]>b[0]&&a[1]<b[3]&&a[3]>b[1];
 const fits=b=>[[b[0],b[1]],[b[2],b[1]],[b[0],b[3]],[b[2],b[3]]].every(p=>projection.containsPixel(region,p[0],p[1],width,height))&&!occupied.some(o=>overlaps(b,o));
 for(const city of cityAnchors){const p=projectGeo(city);if(p)occupied.push([p[0]-5,p[1]-14,p[0]+width*.07,p[1]+5]);}
 for(const m of diskCenters(overlay,region)){
  const [x,y]=projectGeo(m),b=[x-fontSize*.57,y-fontSize*.7,x+fontSize*.57,y+fontSize*.7];
  if(!fits(b)||centers.some(c=>distance([x,y],[c.anchorX,c.anchorY])<fontSize*2))continue;
  occupied.push(b);centers.push({...m,anchorX:x,anchorY:y,labelX:x,labelY:y,leader:false});
  if(centers.length>=(region==='north'?9:14))break;
 }
 const annotated=groups.map(g=>{
  if(!g.label)return g;
  const original=xy(g.label);let best=null,d=Infinity,bestBox=null;
  const run=g.runs.find(r=>r.includes(g.label));
  for(const p of [g.label,...(run||[])]){
   const [x,y]=xy(p),delta=distance(original,[x,y]);
   const b=[x-labelWidth/2,y-labelHeight/2,x+labelWidth/2,y+labelHeight/2];
   if(delta<d&&fits(b)){best=p;d=delta;bestBox=b;}
  }
  if(bestBox)occupied.push(bestBox);
  return {...g,label:best};
 });
 return {centers,groups:annotated};
}

window.SatelliteIsobarGeometry={modelGridCenters,pressureLabels,pressureReferenceHeight,layoutPressureAnnotations,prepareDisk,diskCenters,layoutDiskPressureAnnotations,detectVisiblePressureSystems,detectPressureSystems,prepare,clean,smooth,project,
 settings:{minLoopDiagonal:MIN_LOOP_DIAGONAL,minLoopArea:MIN_LOOP_AREA,
  minOpenLength:MIN_OPEN_LENGTH,smoothing:SMOOTHING,maxShift:MAX_SHIFT}};
})();
