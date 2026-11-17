/* Shared arrow geometry for the satellite SVG and PNG/PDF/GIF composites.
 * Wind direction is projected locally; magnitude encodes |advection|.
 */
(() => {
"use strict";
const METHOD="ifs_temperature_advection_v1";
const levels=[925,850,700];
const limits={atlantic:10,europe:8,southwest:6,central:5,germany:3,disk:14,north:10};
function valid(m){return m&&[m.lon,m.lat,m.advection,m.u,m.v].every(Number.isFinite)&&
 Math.abs(m.lon)<=180&&Math.abs(m.lat)<90&&Math.abs(m.advection)>=2&&Math.hypot(m.u,m.v)>=2-1e-6;}
function frameMarkers(frame,level,time){
 if(!frame||frame.advection_method!==METHOD||!levels.includes(Number(level))||
    !Number.isFinite(Date.parse(time))||Math.abs(Date.parse(time)-Date.parse(frame.valid_utc))>300000 ||
    !Number.isFinite(Date.parse(frame.valid_utc)))return null;
 const marks=frame.temperature_advection?.[String(level)];
 return Array.isArray(marks)&&marks.length<=220&&marks.every(valid)?marks:null;
}
function layout(markers,bbox,width,height,max=8,blocked=[],region=null){
 if(!Array.isArray(markers)||!bbox||!width||!height)return [];
 const [west,south,east,north]=bbox, output=[];
 const projection=window.SatelliteProjection;
 const disk=projection?.isDisk?.(region);
 const font=Math.max(9,width*(disk ? .013 : .018));
 const size=Math.max(25,Math.min(width*(disk ? .075 : .11),height*.17));
 const project=m=>disk?projection.project(region,m.lon,m.lat,width,height):
  [(m.lon-west)/(east-west)*width,(north-m.lat)/(north-south)*height];
 const candidates=markers.filter(valid).filter(m=>disk?Boolean(project(m)):m.lon>=west&&m.lon<=east&&m.lat>=south&&m.lat<=north)
  .sort((a,b)=>Math.abs(b.advection)-Math.abs(a.advection));
 // If both types are present, alternate their strongest remaining candidates.
 const warm=candidates.filter(m=>m.advection>0),cold=candidates.filter(m=>m.advection<0);
 const order=[];let turn=candidates[0]?.advection>0;
 while(warm.length||cold.length){const q=turn?warm:cold;const alt=turn?cold:warm;order.push((q.length?q:alt).shift());turn=!turn;}
 for(const m of order){
  const [x,y]=project(m);
  let vx=m.u/Math.cos(m.lat*Math.PI/180)/(east-west)*width,vy=-m.v/(north-south)*height;
  if(disk){
   // Project a small step along the physical east/north wind. The local
   // Jacobian captures limb distortion and meridian convergence.
   const step=.02/Math.hypot(m.u,m.v),dlon=m.u*step/Math.cos(m.lat*Math.PI/180),dlat=m.v*step;
   const ahead=project({lon:m.lon+dlon,lat:m.lat+dlat}),behind=project({lon:m.lon-dlon,lat:m.lat-dlat});
   if(ahead&&behind){vx=ahead[0]-behind[0];vy=ahead[1]-behind[1];}
   else if(ahead){vx=ahead[0]-x;vy=ahead[1]-y;}
   else if(behind){vx=x-behind[0];vy=y-behind[1];}
   else continue;
   if(!Number.isFinite(vx)||!Number.isFinite(vy)||Math.hypot(vx,vy)<1e-7)continue;
  }
  const n=Math.hypot(vx,vy),dx=vx/n,dy=vy/n;
  const length=size*(.5+.5*Math.min(1,Math.abs(m.advection)/10)),half=length/2;
  const start=[x-dx*half,y-dy*half],end=[x+dx*half,y+dy*half];
  const wing=Math.max(5,length*.22),w1=[end[0]-dx*wing-dy*wing*.55,end[1]-dy*wing+dx*wing*.55],
   w2=[end[0]-dx*wing+dy*wing*.55,end[1]-dy*wing-dx*wing*.55];
  const labelX=x,labelY=Math.max(start[1],end[1])+font*1.1;
  const pad=font*.8;
  if(Math.min(start[0],end[0],labelX-font*1.45)<pad||Math.max(start[0],end[0],labelX+font*1.45)>width-pad||
     Math.min(start[1],end[1])<pad||labelY+font*.5>height-pad)continue;
  if(disk&&projection.containsPixel&&![start,end,w1,w2,[labelX-font*1.45,labelY-font*.5],[labelX+font*1.45,labelY-font*.5],
   [labelX-font*1.45,labelY+font*.5],[labelX+font*1.45,labelY+font*.5]].every(p=>projection.containsPixel(region,p[0],p[1],width,height)))continue;
  if(output.some(a=>Math.hypot(x-a.x,y-a.y)<Math.max(size*1.5,font*5))||
     blocked.some(p=>Math.hypot(x-p[0],y-p[1])<size*.85))continue;
  output.push({x,y,start,end,wing1:w1,wing2:w2,labelX,labelY,length,font,
   label:m.advection>0?"WLA":"KLA",color:m.advection>0?"#ff515d":"#53b9ff",advection:m.advection});
  if(output.length>=max)break;
 }
 return output;
}
window.SatelliteAdvection={METHOD,levels,limits,frameMarkers,layout};
})();
