/* MOSMIX chart vectors: one named group per visible series, no canvas raster in PDF. */
(function(root){
"use strict";
const W=1300,H=750,LEFT=116,RIGHT=1169,BOTTOM=615;
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const num=v=>typeof v==="number"&&Number.isFinite(v);
const n=v=>Number(v.toFixed(3));
const esc=s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&quot;"}[c]));
const slug=s=>String(s||"serie").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"").slice(0,55)||"serie";
const format=v=>new Intl.NumberFormat("de-DE",{maximumFractionDigits:2}).format(v);
function color(value,fallback){
  const raw=String(value||fallback||"#334155").trim();
  let m=raw.match(/^#([a-f0-9]{3}|[a-f0-9]{6})$/i);
  if(m){
    let h=m[1];if(h.length===3)h=h.split("").map(c=>c+c).join("");
    return [0,2,4].map(i=>parseInt(h.slice(i,i+2),16));
  }
  m=raw.match(/^rgba?\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)/i);
  if(m)return m.slice(1,4).map(v=>clamp(Math.round(Number(v)),0,255));
  return [51,65,85];
}
const cssColor=rgb=>"rgb("+rgb.join(",")+")";
function midnightParts(iso){
  const d=new Date(iso);
  if(!Number.isFinite(d.getTime()))return null;
  const obj={};
  new Intl.DateTimeFormat("en-GB",{timeZone:"Europe/Berlin",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",hourCycle:"h23"})
    .formatToParts(d).forEach(p=>obj[p.type]=p.value);
  return {hour:Number(obj.hour),day:obj.day,month:obj.month,
    weekday:new Intl.DateTimeFormat("de-DE",{timeZone:"Europe/Berlin",weekday:"short"}).format(d).replace(/\.$/,"")};
}
function datasetVisible(chart,i){
  return typeof chart.isDatasetVisible==="function"?chart.isDatasetVisible(i):!chart.data.datasets[i].hidden;
}
function scaleFor(chart,ds){
  return chart.scales?.[ds.yAxisID||"y"]||chart.scales?.y;
}
function drawScene(chart,info){
  if(!chart||!chart.data||!chart.scales?.x||!chart.scales?.y)throw Error("Chart.js-Achsen für Vektorexport fehlen.");
  const xScale=chart.scales.x,labels=chart.data.labels||[];
  const minX=num(xScale.min)?xScale.min:0;
  const maxX=num(xScale.max)?xScale.max:labels.length-1;
  if(maxX<=minX)throw Error("Ungültiger Diagrammzeitraum.");
  const visible=chart.data.datasets.map((ds,i)=>({ds,i})).filter(o=>datasetVisible(chart,o.i));
  if(!visible.length)throw Error("Keine sichtbaren Datenreihen.");
  const caption=info.title||"MOSMIX-Diagramm";
  const series=[],axes=[],legend=[];
  let legendX=LEFT,legendY=107;
  visible.forEach(({ds,i})=>{
    const name=String(ds.label||"Datenreihe "+(i+1));
    const size=Math.min(500,Math.max(115,name.length*7+39));
    if(legendX+size>RIGHT){legendX=LEFT;legendY+=25;}
    const rgb=color(ds.borderColor||ds.backgroundColor,"#334155");
    legend.push({kind:"legend",x:legendX,y:legendY,text:name,color:rgb,
      bar:(ds.type||chart.config?.type)==="bar",dash:Array.isArray(ds.borderDash)?ds.borderDash:[]});
    legendX+=size;
  });
  const TOP=Math.max(171,legendY+39);
  const plot={x:LEFT,y:TOP,w:RIGHT-LEFT,h:BOTTOM-TOP};
  const xAt=index=>plot.x+(index-minX)/(maxX-minX)*plot.w;
  const yAt=(v,s)=>plot.y+(1-(v-s.min)/(s.max-s.min))*plot.h;
  axes.push({kind:"rect",x:plot.x,y:plot.y,w:plot.w,h:plot.h,stroke:[203,213,225],fill:null,width:1});
  const yScale=chart.scales.y;
  const yTicks=Array.isArray(yScale.ticks)&&yScale.ticks.length?yScale.ticks:
    Array.from({length:6},(_,i)=>({value:yScale.min+(yScale.max-yScale.min)*i/5}));
  yTicks.filter(t=>num(t.value)).forEach(t=>{
    const y=yAt(t.value,yScale);
    if(y<plot.y-1||y>plot.y+plot.h+1)return;
    axes.push({kind:"line",x1:plot.x,y1:y,x2:RIGHT,y2:y,color:[224,229,235],width:1});
    axes.push({kind:"text",x:plot.x-13,y:y+5,text:format(t.value),size:14,align:"right",color:[82,96,113]});
  });
  if(chart.scales.y?.options?.title?.text)
    axes.push({kind:"text",x:22,y:plot.y+16,text:chart.scales.y.options.title.text,size:15,color:[82,96,113]});
  const rightScales=new Map();
  visible.forEach(({ds})=>{
    const id=ds.yAxisID||"y",scale=scaleFor(chart,ds);
    if(id!=="y"&&scale&&scale.options?.display!==false)rightScales.set(id,scale);
  });
  let rightIndex=0;
  for(const [id,s] of rightScales){
    const x=RIGHT+8+rightIndex*59;
    const ticks=Array.isArray(s.ticks)&&s.ticks.length?s.ticks:
      Array.from({length:5},(_,i)=>({value:s.min+(s.max-s.min)*i/4}));
    ticks.filter(t=>num(t.value)).forEach(t=>{
      const y=yAt(t.value,s);
      if(y<plot.y-1||y>plot.y+plot.h+1)return;
      axes.push({kind:"text",x,y:y+5,text:format(t.value),size:12,align:"left",color:[89,104,122]});
    });
    const label=s.options?.title?.text||id;
    axes.push({kind:"text",x,y:TOP-17,text:label,size:12,color:[89,104,122]});
    rightIndex++;
  }
  const times=Array.isArray(info.timesteps)?info.timesteps:[];
  if(info.key==="sunDaily"){
    const step=Math.max(1,Math.ceil((maxX-minX+1)/10));
    for(let i=Math.ceil(minX);i<=Math.floor(maxX);i+=step){
      const x=xAt(i);
      if(x<plot.x||x>RIGHT)continue;
      axes.push({kind:"text",x,y:BOTTOM+31,text:String(labels[i]||""),size:15,align:"center",color:[85,100,118]});
    }
  }else{
    let dates=0;
    for(let i=Math.max(0,Math.ceil(minX));i<=Math.min(Math.floor(maxX),times.length-1);i++){
      const p=midnightParts(times[i]);
      if(!p||p.hour!==0)continue;
      const x=xAt(i);
      axes.push({kind:"line",x1:x,y1:plot.y,x2:x,y2:BOTTOM,color:[148,163,184],width:1.3});
      if(x<=plot.x+44||x>=RIGHT-44)continue;
      axes.push({kind:"text",x,y:BOTTOM+27,text:p.weekday+" "+p.day+"."+p.month+".",size:15,align:"center",color:[85,100,118]});
      axes.push({kind:"text",x,y:BOTTOM+46,text:"00 Uhr",size:14,align:"center",color:[85,100,118]});
      dates++;
    }
  }
  const getPoints=(ds,s)=>{
    const points=[];
    (ds.data||[]).forEach((v,i)=>{
      if(i<Math.ceil(minX)||i>Math.floor(maxX))return;
      const value=num(v)?v:(v&&typeof v==="object"&&num(v.y)?v.y:null);
      if(value===null){points.push(null);return;}
      const y=yAt(value,s);
      if(!num(y))return;
      points.push([n(xAt(i)),n(clamp(y,plot.y,plot.y+plot.h))]);
    });
    return points;
  };
  visible.forEach(({ds,i})=>{
    const name=String(ds.label||"Datenreihe "+(i+1));
    const s=scaleFor(chart,ds);
    if(!s||!num(s.min)||!num(s.max)||s.max<=s.min)return;
    const rgb=color(ds.borderColor||ds.backgroundColor,"#334155");
    const fill=color(ds.backgroundColor||ds.borderColor,"#64748b");
    const kind=ds.type||chart.config?.type||"line";
    const items=[];
    if(kind==="bar"){
      const thickness=Math.min(18,plot.w/(maxX-minX+1)*.72);
      const base=yAt(clamp(0,s.min,s.max),s);
      const points=getPoints(ds,s);
      points.forEach((p,j)=>{
        if(!p)return;
        const x=clamp(p[0]-thickness/2,plot.x,RIGHT),end=clamp(p[0]+thickness/2,plot.x,RIGHT);
        if(end<=x)return;
        const barIndex=Math.ceil(minX)+j;
        const barFill=Array.isArray(ds.backgroundColor)?
          color(ds.backgroundColor[barIndex],"#f2b01e"):fill;
        items.push({kind:"rect",x,y:Math.min(base,p[1]),w:end-x,h:Math.max(.1,Math.abs(base-p[1])),fill:barFill,stroke:null});
      });
    }else{
      const points=getPoints(ds,s);
      if(ds.showLine===false){
        const style=ds.pointStyle||"circle";
        points.forEach(p=>{
          if(!p)return;
          if(style==="triangle")
            items.push({kind:"poly",points:[[p[0],p[1]-7],[p[0]-7,p[1]+6],[p[0]+7,p[1]+6]],fill:rgb});
          else if(style==="rectRot")
            items.push({kind:"poly",points:[[p[0],p[1]-7],[p[0]-7,p[1]],[p[0],p[1]+7],[p[0]+7,p[1]]],fill:rgb});
          else items.push({kind:"circle",x:p[0],y:p[1],r:4,fill:rgb});
        });
      }else{
        let segment=[];
        function flush(){if(segment.length>1)items.push({kind:"path",points:segment,width:Math.max(1.7,ds.borderWidth||2.2)*1.25,color:rgb,dash:Array.isArray(ds.borderDash)?ds.borderDash:[]});segment=[];}
        points.forEach(p=>{if(p)segment.push(p);else if(!ds.spanGaps)flush();});
        flush();
      }
    }
    series.push({id:"serie-"+(i+1)+"-"+slug(name),name,items});
  });
  if(!series.some(s=>s.items.length))throw Error("Keine sichtbaren Vektordaten im Diagrammzeitraum.");
  const header=[
    {kind:"text",x:LEFT,y:38,text:"DWD MOSMIX-L · "+caption,size:27,bold:true,color:[17,33,55]},
    {kind:"text",x:LEFT,y:68,text:(info.station||"MOSMIX")+" · Lauf "+(info.issue||"–")+" · "+(info.range||"Alle Tage"),size:17,color:[78,92,108]},
    {kind:"line",x1:LEFT,y1:80,x2:RIGHT,y2:80,color:[221,227,234],width:1.2}
  ];
  const footer=[
    {kind:"line",x1:LEFT,y1:679,x2:RIGHT,y2:679,color:[221,227,234],width:1.2},
    {kind:"text",x:LEFT,y:705,text:"Quelle: DWD MOSMIX-L · Rohzeiten UTC (Z), 00-Uhr-Marken MEZ/MESZ · Vektorkurven",size:13,color:[85,100,118]},
    {kind:"text",x:LEFT,y:727,text:"Erstellt: "+new Date().toLocaleString("de-DE")+" · Climate Dashboard Deutschland · Werte unverändert",size:12,color:[85,100,118]}
  ];
  return {width:W,height:H,header,axes,legend,series,footer};
}
function svgEl(item){
  const col=item.color?cssColor(item.color):"none";
  if(item.kind==="text")return '<text x="'+n(item.x)+'" y="'+n(item.y)+'" fill="'+col+'" font-family="Arial,sans-serif" font-size="'+item.size+'" font-weight="'+(item.bold?700:400)+'" text-anchor="'+({right:"end",center:"middle"}[item.align]||"start")+'">'+esc(item.text)+'</text>';
  if(item.kind==="line")return '<path d="M '+n(item.x1)+' '+n(item.y1)+' L '+n(item.x2)+' '+n(item.y2)+'" fill="none" stroke="'+col+'" stroke-width="'+(item.width||1)+'"/>';
  if(item.kind==="rect")return '<rect x="'+n(item.x)+'" y="'+n(item.y)+'" width="'+n(item.w)+'" height="'+n(item.h)+'" fill="'+(item.fill?cssColor(item.fill):"none")+'" stroke="'+(item.stroke?cssColor(item.stroke):"none")+'" stroke-width="'+(item.width||1)+'"/>';
  if(item.kind==="path")return '<path d="'+item.points.map((p,i)=>(i?"L ":"M ")+p[0]+" "+p[1]).join(" ")+'" fill="none" stroke="'+col+'" stroke-linejoin="round" stroke-linecap="round" stroke-width="'+item.width+'"'+(item.dash?.length?' stroke-dasharray="'+item.dash.join(",")+'"':"")+'/>';
  if(item.kind==="poly")return '<polygon points="'+item.points.map(p=>p.join(",")).join(" ")+'" fill="'+cssColor(item.fill)+'"/>';
  if(item.kind==="circle")return '<circle cx="'+item.x+'" cy="'+item.y+'" r="'+item.r+'" fill="'+cssColor(item.fill)+'"/>';
  if(item.kind==="legend"){
    const dash=item.dash?.length?' stroke-dasharray="'+item.dash.join(",")+'"':"";
    return '<path d="M '+item.x+' '+(item.y-5)+' H '+(item.x+22)+'" stroke="'+cssColor(item.color)+'" fill="none" stroke-width="'+(item.bar?9:3)+'"'+dash+'/>'+
      '<text x="'+(item.x+30)+'" y="'+item.y+'" fill="#334155" font-family="Arial,sans-serif" font-size="14">'+esc(item.text)+'</text>';
  }
  return "";
}
function toSvg(scene){
  return '<?xml version="1.0" encoding="UTF-8"?>\n'+
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" viewBox="0 0 '+scene.width+' '+scene.height+'" width="'+scene.width+'" height="'+scene.height+'">'+
    '<desc>Vektorkurven und Balken bleiben getrennte Objekte. Inkscape/Illustrator: je Datenreihe eine benannte Gruppe.</desc>'+
    '<rect width="100%" height="100%" fill="white"/>'+
    '<g id="kopf">'+scene.header.map(svgEl).join("")+'</g>'+
    '<g id="achsen-und-beschriftungen">'+scene.axes.map(svgEl).join("")+'</g>'+
    '<g id="legende">'+scene.legend.map(svgEl).join("")+'</g>'+
    scene.series.map(s=>'<g id="'+esc(s.id)+'" inkscape:groupmode="layer" inkscape:label="'+esc(s.name)+'"><title>'+esc(s.name)+'</title>'+s.items.map(svgEl).join("")+'</g>').join("")+
    '<g id="fuss">'+scene.footer.map(svgEl).join("")+'</g></svg>';
}
function drawPdf(pdf,scene){
  if(typeof pdf.path!=="function")throw Error("PDF-Bibliothek unterstützt keine Vektorpfade.");
  const margin=10,scale=(pdf.internal.pageSize.getWidth()-2*margin)/scene.width;
  const offY=(pdf.internal.pageSize.getHeight()-scene.height*scale)/2;
  const x=v=>margin+v*scale,y=v=>offY+v*scale;
  const colorize=(rgb,isFill)=>{
    if(isFill)pdf.setFillColor(...rgb);
    else pdf.setDrawColor(...rgb);
  };
  function draw(item){
    if(item.kind==="text"){
      pdf.setTextColor(...(item.color||[51,65,85]));
      pdf.setFont("helvetica",item.bold?"bold":"normal");
      pdf.setFontSize(item.size*scale*72/25.4);
      pdf.text(String(item.text).replace(/[–—]/g,"-"),x(item.x),y(item.y),
        {align:item.align==="right"?"right":item.align==="center"?"center":"left"});
    }else if(item.kind==="line"){
      colorize(item.color||[148,163,184],false);
      pdf.setLineWidth(Math.max(.1,(item.width||1)*scale));
      pdf.line(x(item.x1),y(item.y1),x(item.x2),y(item.y2));
    }else if(item.kind==="rect"){
      if(item.fill)colorize(item.fill,true);
      if(item.stroke){colorize(item.stroke,false);pdf.setLineWidth(Math.max(.1,(item.width||1)*scale));}
      pdf.rect(x(item.x),y(item.y),item.w*scale,item.h*scale,item.fill&&item.stroke?"FD":item.fill?"F":"S");
    }else if(item.kind==="path"){
      colorize(item.color,false);
      pdf.setLineWidth(Math.max(.15,item.width*scale));
      if(typeof pdf.setLineDashPattern==="function")pdf.setLineDashPattern((item.dash||[]).map(v=>v*scale),0);
      // One pdf.path invocation per continuous curve, rather than one object per segment.
      pdf.path(item.points.map((p,i)=>({op:i?"l":"m",c:[x(p[0]),y(p[1])]})),"S");
      if(typeof pdf.setLineDashPattern==="function")pdf.setLineDashPattern([],0);
    }else if(item.kind==="poly"){
      colorize(item.fill,true);
      pdf.path(item.points.map((p,i)=>({op:i?"l":"m",c:[x(p[0]),y(p[1])]})).concat([{op:"h",c:[]}]),"F");
    }else if(item.kind==="circle"){
      colorize(item.fill,true);
      pdf.circle(x(item.x),y(item.y),item.r*scale,"F");
    }else if(item.kind==="legend"){
      colorize(item.color,false);
      pdf.setLineWidth((item.bar?8:2.5)*scale);
      pdf.line(x(item.x),y(item.y-5),x(item.x+22),y(item.y-5));
      draw({kind:"text",x:item.x+30,y:item.y,text:item.text,size:14,color:[51,65,85]});
    }
  }
  scene.header.forEach(draw);
  scene.axes.forEach(draw);
  scene.legend.forEach(draw);
  scene.series.forEach(s=>s.items.forEach(draw));
  scene.footer.forEach(draw);
  return scene.series.map(s=>({name:s.name,objects:s.items.length}));
}
function downloadSvg(svg,filename){
  const blob=new Blob([svg],{type:"image/svg+xml;charset=utf-8"});
  const url=URL.createObjectURL(blob);
  const a=document.createElement("a");
  a.href=url;a.download=filename+".svg";
  document.body.appendChild(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
root.MosmixVectorExport={buildScene:drawScene,toSvg,drawPdf,downloadSvg};
})(window);
