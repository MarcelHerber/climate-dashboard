/* EUMETView AUTO:97004,9001,0,0 — WGS84, geostationary view at 0°E,
 * height 35785831 m, sweep=y. Same parameters as GeoTools Auto97004 and
 * PROJ geos. Coordinates are projected pixel positions, not a spherical
 * orthographic approximation. The northern view is the exact upper half.
 */
(() => {
"use strict";
const SRS="AUTO:97004,9001,0,0";
const regions={
 disk:{bbox:[-6500000,-6500000,6500000,6500000],w:1400,h:1400,srs:SRS},
 north:{bbox:[-6500000,0,6500000,6500000],w:1400,h:700,srs:SRS}
};
const A=6378137,F=1/298.257223563,E2=F*(2-F),B2=A*A*(1-E2);
const H=35785831,S=A+H,RAD=Math.PI/180;
function isDisk(region){return Object.hasOwn(regions,region);}
function validPoint(lon,lat){return Number.isFinite(lon)&&Number.isFinite(lat)&&Math.abs(lat)<=90;}
function project(region,lon,lat,width,height){
 if(!isDisk(region)||!validPoint(lon,lat)||!(width>0&&height>0))return null;
 if(region==="north"&&lat<0)return null;
 const [xmin,ymin,xmax,ymax]=regions[region].bbox;
 const p=lat*RAD,l=lon*RAD,c=Math.cos(p),s=Math.sin(p);
 const N=A/Math.sqrt(1-E2*s*s),X=N*c*Math.cos(l),Y=N*c*Math.sin(l),Z=N*(1-E2)*s;
 // Tangent-plane visibility: a far-side point cannot be seen through Earth.
 if(S*X<A*A)return null;
 const D=S-X,x=H*Math.atan2(Y,D),y=H*Math.atan2(Z,Math.hypot(D,Y));
 if(x<xmin||x>xmax||y<ymin||y>ymax)return null;
 return [(x-xmin)/(xmax-xmin)*width,(ymax-y)/(ymax-ymin)*height];
}
function containsPixel(region,x,y,width,height){
 if(!isDisk(region)||!Number.isFinite(x)||!Number.isFinite(y)||!(width>0&&height>0)||x<0||y<0||x>width||y>height)return false;
 const [xmin,ymin,xmax,ymax]=regions[region].bbox;
 const alpha=(xmin+x/width*(xmax-xmin))/H,beta=(ymax-y/height*(ymax-ymin))/H;
 // Sweep-y ray: (-cos(beta)cos(alpha), cos(beta)sin(alpha), sin(beta)).
 // Test whether it intersects the WGS84 ellipsoid ahead of the satellite.
 const vx=-Math.cos(beta)*Math.cos(alpha),vy=Math.cos(beta)*Math.sin(alpha),vz=Math.sin(beta);
 const qa=vx*vx+vy*vy+vz*vz*(A*A/B2),qb=(S/A)*vx,qc=(S/A)**2-1;
 const det=qb*qb-qa*qc;
 return det>=-1e-12&&qb<0;
}
function paths(region,line,width,height){
 if(!isDisk(region)||!Array.isArray(line)||line.length<2||!(width>0&&height>0))return [];
 const result=[];let part=[],prev=null,prevProjected=null;
 function finish(){if(part.length>=2)result.push(part);part=[];}
 function add(p){if(!part.length||Math.hypot(p[0]-part.at(-1)[0],p[1]-part.at(-1)[1])>1e-8)part.push(p);}
 // Bisect only a visibility transition, retaining the visible end of the
 // interval. It clips both the satellite limb and the equator in north mode.
 function boundary(a,b,ap,bp){
  let good=ap||bp;
  for(let i=0;i<32;i++){
   const m=[(a[0]+b[0])/2,(a[1]+b[1])/2],mp=project(region,m[0],m[1],width,height);
   if(mp){good=mp;if(ap)a=m;else b=m;}
   else{if(ap)b=m;else a=m;}
  }
  return good;
 }
 function next(point){
  const projected=project(region,point[0],point[1],width,height);
  if(prev){
   if(prevProjected&&projected){add(prevProjected);add(projected);}
   else if(prevProjected){add(prevProjected);add(boundary(prev,point,prevProjected,null));finish();}
   else if(projected){add(boundary(prev,point,null,projected));add(projected);}
  }
  prev=point;prevProjected=projected;
 }
 for(const p of line){
  if(!Array.isArray(p)||!validPoint(p[0],p[1])){finish();prev=null;prevProjected=null;continue;}
  if(!prev){next(p);continue;}
  const a=prev,dlon=((p[0]-a[0]+180)%360+360)%360-180,dlat=p[1]-a[1];
  // Follow short geographic segments, not a chord across the invisible
  // hemisphere; subdivide curved projected lines and test every sample.
  const steps=Math.max(1,Math.ceil(Math.max(Math.abs(dlon),Math.abs(dlat))/.5));
  for(let i=1;i<=steps;i++)next([a[0]+dlon*i/steps,a[1]+dlat*i/steps]);
 }
 finish();return result;
}
window.SatelliteProjection={isDisk,regions,project,paths,containsPixel};
})();
