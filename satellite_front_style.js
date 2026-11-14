/* Shared conservative synoptic front artwork for screen, Canvas and PDF.
 * WPC CODSUS provides locations/types, NOT the side toward which fronts move.
 * One-sided pips below are schematic visual conventions unless the source
 * explicitly supplies a VERIFIED symbol_side. Never interpret them as motion.
 * All curves pass through the exact original control vertices.
 */
(() => {
"use strict";
const COLORS=Object.freeze({cold:"#5998c9",warm:"#d77a76",occluded:"#a795c5",stationary:"#a795c5"});
const DARK="#122438";
const F=n=>Number(n).toFixed(2);
const pt=(x,y)=>[x,y];
function cmdString(steps){
 return steps.map(s=>s[0]+s.slice(1).map(F).join(" ")).join(" ");
}
function curved(points,unit=1){
 if(!Array.isArray(points)||points.length<2)return [];
 const result=[["M",...points[0]]];
 for(let i=0;i<points.length-1;i++){
  const a=points[i],b=points[i+1],prev=points[Math.max(0,i-1)],
   next=points[Math.min(points.length-1,i+2)];
  const seg=Math.hypot(b[0]-a[0],b[1]-a[1]);
  if(seg<.01)continue;
  // Tiny tangent handles: do not displace NOAA vertices or overshoot corners.
  const before=[b[0]-prev[0],b[1]-prev[1]],after=[next[0]-a[0],next[1]-a[1]],
   norm1=Math.hypot(...before)||1,norm2=Math.hypot(...after)||1;
  const handle=Math.min(3.5*unit,seg*.18);
  result.push(["C",a[0]+before[0]/norm1*handle,a[1]+before[1]/norm1*handle,
   b[0]-after[0]/norm2*handle,b[1]-after[1]/norm2*handle,b[0],b[1]]);
 }
 return result;
}
function pointAt(points,distance){
 let sum=0;
 for(let i=0;i<points.length-1;i++){
  const a=points[i],b=points[i+1],dx=b[0]-a[0],dy=b[1]-a[1],
   seg=Math.hypot(dx,dy);
  if(seg<.01)continue;
  if(sum+seg>=distance){
   const v=(distance-sum)/seg;
   return {x:a[0]+dx*v,y:a[1]+dy*v,tx:dx/seg,ty:dy/seg};
  }
  sum+=seg;
 }
 return null;
}
function arcCommands(g,r,side){
 const nx=-g.ty*side,ny=g.tx*side,t=[g.tx,g.ty],h=1.27*r;
 return [["M",g.x-t[0]*r,g.y-t[1]*r],
  ["C",g.x-t[0]*r+nx*h,g.y-t[1]*r+ny*h,
       g.x+t[0]*r+nx*h,g.y+t[1]*r+ny*h,
       g.x+t[0]*r,g.y+t[1]*r],["Z"]];
}
function triangleCommands(g,r,side){
 const nx=-g.ty*side,ny=g.tx*side;
 return [["M",g.x-g.tx*r,g.y-g.ty*r],
  ["L",g.x+g.tx*r,g.y+g.ty*r],
  ["L",g.x+nx*r*1.23,g.y+ny*r*1.23],["Z"]];
}
function interpolateSegments(points,step,unit){
 // Stationary fronts get alternating uninterrupted red/blue sections.
 const total=points.slice(1).reduce((sum,p,i)=>sum+Math.hypot(p[0]-points[i][0],p[1]-points[i][1]),0);
 const pieces=[];
 if(total<1)return pieces;
 let at=0,index=0;
 while(at<total-.01&&pieces.length<180){
  const finish=Math.min(total,at+step),a=pointAt(points,at+.001),b=pointAt(points,finish-.001);
  if(a&&b)pieces.push({color:index%2?COLORS.warm:COLORS.cold,
   commands:[["M",a.x,a.y],["L",b.x,b.y]]});
  index++;at=finish;
 }
 return pieces;
}
function layout(feature,project,unit=1){
 const raw=feature?.coords||[];
 if(raw.length<2)return null;
 const points=raw.map(project),commands=curved(points,unit);
 const len=points.slice(1).reduce((n,p,i)=>n+Math.hypot(p[0]-points[i][0],p[1]-points[i][1]),0);
 const type=feature.type,r=6.2*unit,space=34*unit;
 const rawSide=feature.symbol_orientation_verified===true&&
  ["left","right"].includes(feature.symbol_side)?(feature.symbol_side==="right"?-1:1):1;
 const verified=feature.symbol_orientation_verified===true&&
  ["left","right"].includes(feature.symbol_side);
 const symbols=[],maxSymbols=Math.min(120,Math.floor(len/space));
 // Endpoint-safe symbols with identical spacing/side in SVG, Canvas and PDF.
 for(let i=0;i<maxSymbols;i++){
  const g=pointAt(points,(i+.5)*space);
  if(!g)continue;
  let shape=type==="warm"?"arc":type==="cold"?"triangle":i%2?"arc":"triangle";
  let side=rawSide,color=COLORS[type];
  if(type==="stationary"){
   shape=i%2?"arc":"triangle";
   side=i%2?-rawSide:rawSide;
   color=i%2?COLORS.warm:COLORS.cold;
  }
  symbols.push({color,shape,commands:shape==="arc"?arcCommands(g,r,side):
   triangleCommands(g,r,side)});
 }
 const sections=type==="stationary"?interpolateSegments(points,space,unit):[];
 return {type,color:COLORS[type],symbols,sections,commands,points,length:len,
  orientationVerified:verified};
}
window.SatelliteFrontStyle={COLORS,DARK,layout,cmdString,curved};
})();
