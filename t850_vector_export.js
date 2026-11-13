/* T850 Ensemble: editable scientific SVG layers and true PDF vector strokes.
   Source: existing Chart.js data and visible axis limits; never rasterize plots. */
(function(root){
"use strict";
const W=1440,H=930,P={x:115,y:259,w:1210,h:543};
const XMLNS="http://www.inkscape.org/namespaces/inkscape";
const finite=v=>typeof v==="number"&&Number.isFinite(v);
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
function clean(s){return String(s??"").replace(/[^\w-]+/g,"_").slice(0,70);}
function xml(s){return String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&apos;");}
function color(v){
  if(Array.isArray(v))v=v[0];
  const s=String(v||"#334155").trim();
  if(s==="transparent")return {hex:"#2563eb",opacity:.64};
  if(/^#[0-9a-f]{3}$/i.test(s))return {hex:"#"+[...s.slice(1)].map(c=>c+c).join(""),opacity:1};
  if(/^#[0-9a-f]{6}$/i.test(s))return {hex:s,opacity:1};
  const m=s.match(/^rgba?\(([^)]+)\)$/i);
  if(m){
    const a=m[1].split(",").map(Number);
    const rgb=a.slice(0,3).map(n=>clamp(Math.round(n||0),0,255).toString(16).padStart(2,"0")).join("");
    return {hex:"#"+rgb,opacity:a.length>3?clamp(a[3],0,1):1};
  }
  return {hex:"#334155",opacity:1};
}
function rgb(hex){const s=hex.replace("#","");return [0,2,4].map(i=>parseInt(s.slice(i,i+2),16));}
function value(d){if(finite(d))return d;if(d&&typeof d==="object"&&finite(d.y))return d.y;return null;}
function clip(a,b){
  const xmin=P.x,xmax=P.x+P.w,ymin=P.y,ymax=P.y+P.h;
  let t0=0,t1=1;const dx=b[0]-a[0],dy=b[1]-a[1];
  for(const [p,q] of [[-dx,a[0]-xmin],[dx,xmax-a[0]],[-dy,a[1]-ymin],[dy,ymax-a[1]]]){
    if(p===0){if(q<0)return null;continue;}
    const t=q/p;
    if(p<0)t0=Math.max(t0,t);else t1=Math.min(t1,t);
    if(t0>t1)return null;
  }
  return [[a[0]+t0*dx,a[1]+t0*dy],[a[0]+t1*dx,a[1]+t1*dy]];
}
function segments(ds,xa,ya){
  const raw=[],out=[];const data=ds.data||[];
  for(let i=0;i<data.length;i++){
    const v=value(data[i]);
    if(v===null){if(!ds.spanGaps)raw.push(null);continue;}
    raw.push([xa(i),ya(v)]);
  }
  let chain=[];
  function flush(){
    if(chain.length>1)for(let i=1;i<chain.length;i++){
      const pair=clip(chain[i-1],chain[i]);
      if(pair)out.push(pair);
    }
    chain=[];
  }
  for(const p of raw){if(p)chain.push(p);else flush();}
  flush();
  const grouped=[];let current=[];
  for(const pair of out){
    const last=current[current.length-1];
    if(!last||Math.abs(last[0]-pair[0][0])<1e-5&&Math.abs(last[1]-pair[0][1])<1e-5){
      if(!current.length)current.push(pair[0]);
      current.push(pair[1]);
    }else{grouped.push(current);current=[...pair];}
  }
  if(current.length)grouped.push(current);
  return grouped;
}
function buildScene(chart,info){
  if(!chart?.data?.datasets?.length||!chart.scales?.x||!chart.scales?.y)
    throw Error("Bitte zuerst ein gültiges Ensemble-Diagramm laden.");
  const labels=chart.data.labels||[],x=chart.scales.x,y=chart.scales.y;
  const xmin=finite(x.min)?x.min:0,xmax=finite(x.max)?x.max:labels.length-1;
  const ymin=y.min,ymax=y.max;
  if(!finite(ymin)||!finite(ymax)||ymax<=ymin||xmax<=xmin)throw Error("Ungültige Diagrammachsen.");
  const xa=i=>P.x+(i-xmin)/(xmax-xmin)*P.w;
  const ya=v=>P.y+P.h-(v-ymin)/(ymax-ymin)*P.h;
  const series=[];
  chart.data.datasets.forEach((ds,i)=>{
    const visible=typeof chart.isDatasetVisible==="function"?chart.isDatasetVisible(i):!ds.hidden;
    if(!visible)return;
    const label=String(ds.label||"Reihe "+(i+1));
    const percentile=label.includes("Perzentil");
    let paint=color(ds.borderColor||ds.backgroundColor);
    if(percentile)paint={hex:label.includes("25.")?"#5599d2":"#8aa9d6",opacity:.85};
    // Mobile Chart.js opacity is often 0.2; keep members legible on white paper.
    if(label.startsWith("Member "))paint.opacity=.50;
    const points=segments(ds,xa,ya);
    if(!points.length)return;
    series.push({label,points,hex:paint.hex,opacity:paint.opacity,
      width:percentile?1.3:label.startsWith("Member ")?1.15:Math.max(1.4,Number(ds.borderWidth)||2),
      dash:Array.isArray(ds.borderDash)?ds.borderDash:[]});
  });
  if(!series.length)throw Error("Keine sichtbaren Ensemblekurven verfügbar.");
  const ticks=[];
  for(let i=0;i<=6;i++)ticks.push({v:ymin+(ymax-ymin)*i/6,
    py:ya(ymin+(ymax-ymin)*i/6)});
  const dates=[];
  const count=Math.max(1,Math.ceil((xmax-xmin)/8));
  for(let i=Math.ceil(xmin);i<=Math.floor(xmax);i+=count)
    dates.push({text:String(labels[i]||""),px:xa(i)});
  const metadata=(info?.metadata||[]).map(String);
  return {title:String(info?.title||"Ensemblevorhersage"),metadata,
    axis:String(info?.axis||""),series,ticks,dates,plot:P,model:String(info?.model||"")};
}
function legend(scene){
 const out=[],seen=new Set();
 const members=scene.series.filter(s=>s.label.startsWith("Member "));
 if(members.length)out.push({label:"Member ("+members.length+")",hex:"#64748b"});
 for(const series of scene.series){
   const label=series.label;
   const key=label.includes("Perzentil")?"Perzentile":
      label.startsWith("Kontrolllauf")?"Kontrolllauf":
      label.startsWith("Hauptlauf")?"Hauptlauf":
      label.startsWith("Ensemble-Mittel")?"Ensemble-Mittel":
      label.includes("1991–2020")?"ERA5 1991–2020":
      label.startsWith("Member ")?"Member":
      label;
   if(key==="Member"||seen.has(key))continue;
   seen.add(key);
   out.push({label:key,hex:series.hex});
 }
 return out.slice(0,8);
}
function pt(p){return p.map(n=>Number(n.toFixed(3)));}
function path(points){return points.map((p,i)=>(i?"L":"M")+pt(p).join(" ")).join(" ");}
function svgText(x,y,t,size=17,fill="#334155",anchor="start"){
 return '<text x="'+x+'" y="'+y+'" font-family="Arial, sans-serif" font-size="'+size+'" fill="'+fill+'" text-anchor="'+anchor+'">'+xml(t)+"</text>";
}
function svgScene(scene,index){
 const dy=index*H,clipid="plotclip"+index;
 const prefix="panel"+index+"_";
 let s='<defs><clipPath id="'+clipid+'"><rect x="'+P.x+'" y="'+(P.y+dy)+'" width="'+P.w+'" height="'+P.h+'"/></clipPath></defs>';
 s+='<g id="'+prefix+'metadata" inkscape:groupmode="layer" inkscape:label="'+xml(scene.title+' – Angaben')+'">';
 s+=svgText(65,62+dy,scene.title,31,"#152c43");
 s+=svgText(66,95+dy,scene.axis+" · Ensemble-Vektorexport",19,"#41566a");
 scene.metadata.slice(0,5).forEach((v,i)=>s+=svgText(66,127+dy+i*23,v,16,"#475569"));
 const created=scene.metadata.find(line=>line.startsWith("Erstellt: "))||"";
 if(created)s+=svgText(P.x,863+dy,created,15);
 s+=svgText(P.x,887+dy,"Quelle: Open-Meteo Ensemble API / zugrunde liegende Modelle",15);
 s+=svgText(P.x,911+dy,"UTC (Z) · Mess- und Prognosewerte unverändert · Kurven als benannte Vektorebenen",15);
 s+="</g>";
 s+='<g id="'+prefix+'legend" inkscape:groupmode="layer" inkscape:label="'+xml(scene.title+' – Legende')+'">';
 let lx=585;
 for(const item of legend(scene)){
   const width=Math.max(115,Math.min(205,item.label.length*9+33));
   if(lx+width>W-75)break;
   s+='<path d="M'+lx+" "+(242+dy)+" h22"+'" stroke="'+item.hex+'" stroke-width="3" fill="none"/>';
   s+=svgText(lx+28,248+dy,item.label,13);
   lx+=width;
 }
 s+="</g>";
 s+='<g id="'+prefix+'axes" inkscape:groupmode="layer" inkscape:label="'+xml(scene.title+' – Achsen und Gitter')+'">';
 s+='<rect x="'+P.x+'" y="'+(P.y+dy)+'" width="'+P.w+'" height="'+P.h+'" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>';
 for(const t of scene.ticks){
  const y=t.py+dy;
  s+='<path d="M'+P.x+" "+y+" H"+(P.x+P.w)+'" fill="none" stroke="#e3e9ee"/>';
  s+=svgText(P.x-12,y+5,t.v.toLocaleString("de-DE",{maximumFractionDigits:2}),16,"#51667a","end");
 }
 for(const d of scene.dates){
  s+=svgText(d.px,P.y+P.h+32+dy,d.text,15,"#51667a","middle");
 }
 s+="</g>";
 scene.series.forEach((c,i)=>{
   s+='<g id="'+prefix+"series_"+i+"_"+clean(c.label)+'" inkscape:groupmode="layer" inkscape:label="'+xml(scene.title+" – "+c.label)+'" clip-path="url(#'+clipid+')">';
   for(const seg of c.points){
     const shifted=seg.map(p=>[p[0],p[1]+dy]);
     s+='<path d="'+path(shifted)+'" fill="none" stroke="'+c.hex+'" stroke-opacity="'+c.opacity+'" stroke-width="'+c.width+'"'+(c.dash.length?' stroke-dasharray="'+c.dash.join(",")+'"':"")+' stroke-linecap="round" stroke-linejoin="round"/>';
   }
   s+="</g>";
 });
 return s;
}
function toSvg(scenes){
 if(!Array.isArray(scenes)||!scenes.length)throw Error("Keine Diagramme zum SVG-Export.");
 return '<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="'+XMLNS+'" width="'+W+'" height="'+(H*scenes.length)+'" viewBox="0 0 '+W+' '+(H*scenes.length)+'">'+
 scenes.map(svgScene).join("")+"</svg>";
}
function drawPdf(pdf,scene){
 const pw=pdf.internal.pageSize.getWidth(),ph=pdf.internal.pageSize.getHeight();
 const s=Math.min((pw-12)/W,(ph-12)/H),ox=(pw-W*s)/2,oy=(ph-H*s)/2;
 const X=x=>ox+x*s,Y=y=>oy+y*s;
 const ink=(hex)=>{const a=rgb(hex);return a;};
 const text=(str,x,y,size,colorValue="#334155",align="left")=>{
   pdf.setFont("helvetica","normal");pdf.setFontSize(size*s*2.83465);
   pdf.setTextColor(...ink(colorValue));pdf.text(String(str),X(x),Y(y),{align});
 };
 pdf.setFillColor(255,255,255);pdf.rect(0,0,pw,ph,"F");
 text(scene.title,65,62,31,"#152c43");
 text(scene.axis+" · Vektor-PDF",66,95,19,"#41566a");
 scene.metadata.slice(0,5).forEach((m,i)=>text(m,66,127+i*23,16,"#475569"));
 let lx=585;
 for(const item of legend(scene)){
   const width=Math.max(115,Math.min(205,item.label.length*9+33));
   if(lx+width>W-75)break;
   pdf.setDrawColor(...ink(item.hex));pdf.setLineWidth(3*s);
   pdf.line(X(lx),Y(242),X(lx+22),Y(242));
   text(item.label,lx+28,248,13);
   lx+=width;
 }
 const created=scene.metadata.find(line=>line.startsWith("Erstellt: "))||"";
 if(created)text(created,P.x,863,15);
 text("Quelle: Open-Meteo Ensemble API / Modelle",P.x,887,15);
 text("UTC (Z) · einzelne Kurven als Vektorpfade · Daten unverändert",P.x,911,15);
 pdf.setLineWidth(.5);pdf.setDrawColor(196,208,219);pdf.rect(X(P.x),Y(P.y),P.w*s,P.h*s,"S");
 for(const t of scene.ticks){
   pdf.setDrawColor(226,232,239);pdf.setLineWidth(.25);
   pdf.line(X(P.x),Y(t.py),X(P.x+P.w),Y(t.py));
   text(t.v.toLocaleString("de-DE",{maximumFractionDigits:2}),P.x-12,t.py+5,16,"#51667a","right");
 }
 for(const d of scene.dates)text(d.text,d.px,P.y+P.h+32,15,"#51667a","center");
 for(const c of scene.series){
   const base=ink(c.hex);
   // jsPDF core has no alpha stroke guarantee: blend light member curves on white.
   const adjusted=base.map(v=>Math.round(255*(1-c.opacity)+v*c.opacity));
   pdf.setDrawColor(...adjusted);pdf.setLineWidth(c.width*s);
   if(typeof pdf.setLineDashPattern==="function")pdf.setLineDashPattern(c.dash.map(n=>n*s),0);
   for(const seg of c.points){
     if(seg.length<2)continue;
     const first=seg[0];
     const changes=[];
     for(let i=1;i<seg.length;i++)
       changes.push([(seg[i][0]-seg[i-1][0])*s,(seg[i][1]-seg[i-1][1])*s]);
     pdf.lines(changes,X(first[0]),Y(first[1]),[1,1],"S",false);
   }
   if(typeof pdf.setLineDashPattern==="function")pdf.setLineDashPattern([],0);
 }
 return scene.series.length;
}
function saveSvg(scenes,filename){
 const blob=new Blob([toSvg(scenes)],{type:"image/svg+xml;charset=utf-8"});
 const href=URL.createObjectURL(blob),a=document.createElement("a");
 a.href=href;a.download=filename;document.body.appendChild(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(href),1500);
}
root.T850VectorExport=Object.freeze({buildScene,toSvg,drawPdf,saveSvg,W,H});
})(window);
