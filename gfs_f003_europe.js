/* Independent NOAA GFS 0.5° f003 forecast. Strict matching CFSR f003 anomaly baseline. */
(() => {
  "use strict";
  const LEVELS=[-8,-7,-6,-5,-4,-3,-2,-1,-0.5,0,0.5,1,2,3,4,5,6,7,8];
  const COLORS=[
    "#3A006F","#51009E","#6B03C6","#5E4FFC","#187DFD",
    "#70B1FB","#C6E4FB","#DDEBF9","#EDF4FA","#FDFCFC",
    "#FDF0BC","#FDE47C","#FDBD3E","#FC691C","#F93A19",
    "#E51B75","#FC579B","#FC83B4","#FDAFCB"
  ];
  const ABS_STOPS=[-30,-20,-15,-10,-5,0,5,10,15,20,25,30,35];
  const ABS_COLORS=["#301165","#594ba5","#436bc5","#4b9dd9","#9cd4e4","#eaf5f5",
    "#f4f0c9","#f9e39b","#f5c462","#f9a34a","#ed6f3e","#c93c3a","#8d1c45"];
  const $=id=>document.getElementById(id);
  const el={
    map:$("gfsMap"),borders:$("gfsBorders"),metric:$("gfsMetric"),preset:$("gfsPreset"),
    start:$("gfsStart"),end:$("gfsEnd"),legend:$("gfsLegend"),
    warn:$("gfsWarn"),status:$("gfsStatus"),date:$("gfsDatasetDate"),
    reference:$("gfsReferenceStatus"),countries:$("gfsCountries"),
    header:$("gfsMeanHeader"),chart:$("gfsChart"),selected:$("gfsSelected"),
    png:$("gfsPng"),pdf:$("gfsPdf"),csv:$("gfsCsv")
  };
  if(!el.map)return;
  let data=null,mask=null,people=[],absolute=null,anomaly=null;
  let currentStats=[],shownField=null,selection=null,range=null;
  const cells=140*76,fill=-32768;
  const toDate = str => new Date(str+"T00:00:00Z");
  function offset(str,delta){
    const d=toDate(str);d.setUTCDate(d.getUTCDate()+delta);
    return d.toISOString().slice(0,10);
  }
  function daysBetween(a,b){
    return Math.round((toDate(b)-toDate(a))/86400000)+1;
  }
  function unpack(b64,n) {
    const bytes=atob(b64);
    if(bytes.length!==n*2)throw new Error("GFS Rasterdimension oder Kodierung ungültig");
    const view=new DataView(new ArrayBuffer(bytes.length));
    for(let i=0;i<bytes.length;i++)view.setUint8(i,bytes.charCodeAt(i));
    const arr=new Float32Array(n);
    for(let i=0;i<n;i++){
      const v=view.getInt16(i*2,true);arr[i]=v===fill?NaN:v/10;
    }
    return arr;
  }
  function validate(main,cpc){
    if(main.schema!==1 || main.type!=="model_forecast_not_observation" ||
       !main.provider?.includes("GFS") || !main.provider?.includes("f003") || main.width!==140 || main.height!==76 ||
       !Array.isArray(main.dates) || !main.dates.length ||
       main.data_through!==main.dates[main.dates.length-1] ||
       main.grid_degrees!==0.5)throw new Error("GFS-Index ungültig");
    const unique=new Set(main.dates);
    if(unique.size!==main.dates.length || main.dates.some((x,i)=>i>0&&x<=main.dates[i-1]))
      throw new Error("GFS-Datumsfolge nicht chronologisch");
    if(main.reference_ready && !main.anomaly_q10_b64)
      throw new Error("Referenz als vorhanden markiert, aber Anomalien fehlen");
    if(!main.reference_ready && main.anomaly_q10_b64)
      throw new Error("Anomalien ohne geprüfte CFSR/CFSv2-Klimatologie unzulässig");
    if(main.reference_ready && (!main.reference_metadata ||
       main.reference_metadata.forecast_hour!==3 ||
       main.reference_metadata.reference_version!=="cfsr-cfsv2-t2m-f003-v1" ||
       main.reference_metadata.source_months!==360))
      throw new Error("GFS f003 hat keine nachweislich homogene CFSR/CFSv2-f003-Referenz");
    if(cpc.width!==140 || cpc.height!==76 || !Array.isArray(cpc.countries))
      throw new Error("Ländermaske passt nicht zur GFS-Karte");
    data=main;
    mask=unpack(cpc.country_mask_b64,cells); // country ids are int16, re-read exactly below
    const b=atob(cpc.country_mask_b64);
    const v=new DataView(new ArrayBuffer(b.length));
    for(let i=0;i<b.length;i++)v.setUint8(i,b.charCodeAt(i));
    mask=new Int16Array(cells);
    for(let i=0;i<cells;i++)mask[i]=v.getInt16(i*2,true);
    people=cpc.countries;
    absolute=unpack(main.temperature_q10_b64,cells*main.dates.length);
    if(main.reference_ready)anomaly=unpack(main.anomaly_q10_b64,cells*main.dates.length);
    if(mask.length!==cells)throw new Error("Ländermaske ungültig");
  }
  function palette(v,anomalies){
    const stops=anomalies?LEVELS:ABS_STOPS;
    const colors=anomalies?COLORS:ABS_COLORS;
    let i=0;
    while(i<stops.length-2&&v>stops[i+1])i++;
    const t=Math.max(0,Math.min(1,(v-stops[i])/(stops[i+1]-stops[i])));
    const a=colors[i],b=colors[i+1];
    return [1,3,5].map(p=>Math.round(
      parseInt(a.slice(p,p+2),16)*(1-t)+parseInt(b.slice(p,p+2),16)*t
    ));
  }
  function chosenRange(){
    const a=el.start.value,b=el.end.value;
    if(!a||!b||a>b||a<data.first_date||b>data.data_through)return null;
    const ids=[];
    for(let i=0;i<data.dates.length;i++)if(data.dates[i]>=a&&data.dates[i]<=b)ids.push(i);
    if(ids.length<Math.ceil(daysBetween(a,b)*0.80))return null;
    return {a,b,ids};
  }
  function preset(name){
    if(!data)return;
    const latest=data.data_through;
    let start=latest;
    if(name==="month")start=latest.slice(0,7)+"-01";
    if(name==="7")start=offset(latest,-6);
    if(name==="14")start=offset(latest,-13);
    if(name==="30")start=offset(latest,-29);
    if(name==="season"){
      const m=Number(latest.slice(5,7));
      const startMonth=m<=2?12:m<=5?3:m<=8?6:9;
      const y=m<=2?Number(latest.slice(0,4))-1:Number(latest.slice(0,4));
      start=String(y)+"-"+String(startMonth).padStart(2,"0")+"-01";
    }
    if(name!=="custom"){
      el.start.value=start;el.end.value=latest;
    }
    if(name!=="today"&&name!=="custom"&&!chosenRange()){
      // Never pass one or two analysis days off as a complete month.
      el.preset.value="today";el.start.value=latest;el.end.value=latest;
      el.warn.hidden=false;
      el.warn.textContent="Der gewählte Zeitraum ist noch nicht vollständig archiviert. Stattdessen wird der letzte vollständig analysierte Tag gezeigt.";
    }
    render();
  }
  function meanField(sel,source){
    const out=new Float32Array(cells).fill(NaN);
    for(let i=0;i<cells;i++){
      let total=0,valid=0;
      for(const day of sel.ids){
        const x=source[day*cells+i];
        if(Number.isFinite(x)){total+=x;valid++;}
      }
      if(valid>=Math.ceil(sel.ids.length*0.8))out[i]=total/valid;
    }
    return out;
  }
  function countriesFor(field) {
    const sums=new Float64Array(people.length),weights=new Float64Array(people.length);
    const counts=new Int32Array(people.length);
    for(let y=0;y<76;y++){
      const weight=Math.cos((71.75-y*0.5)*Math.PI/180);
      for(let x=0;x<140;x++){
        const k=y*140+x,who=mask[k],v=field[k];
        if(who>=0&&who<people.length&&Number.isFinite(v)){
          sums[who]+=v*weight;weights[who]+=weight;counts[who]++;
        }
      }
    }
    return people.map(c=>({
      id:c.id,name:c.name,value:weights[c.id]?sums[c.id]/weights[c.id]:NaN,
      coverage:c.cells?counts[c.id]/c.cells:0
    })).filter(c=>Number.isFinite(c.value)&&c.coverage>=0.45)
      .sort((a,b)=>b.value-a.value);
  }
  function draw(field,anomalies){
    const c=el.map,ctx=c.getContext("2d",{alpha:false});
    const w=1400,h=760,px=10;
    c.width=w;c.height=h;
    const out=ctx.createImageData(w,h);
    const d=out.data;
    const lut=new Array(1001);
    const min=anomalies?-15:-50,max=anomalies?15:50;
    for(let i=0;i<lut.length;i++)lut[i]=palette(min+(max-min)*i/1000,anomalies);
    for(let y=0;y<h;y++){
      const yy=Math.min(75,Math.floor(y/px));
      const yf=(y+.5)/px-.5, y0=Math.max(0,Math.min(75,Math.floor(yf)));
      const y1=Math.min(75,y0+1),ty=Math.max(0,Math.min(1,yf-y0));
      for(let x=0;x<w;x++){
        const xx=Math.min(139,Math.floor(x/px)),original=field[yy*140+xx];
        const pos=(y*w+x)*4;
        if(!Number.isFinite(original)){
          d[pos]=234;d[pos+1]=240;d[pos+2]=243;d[pos+3]=255;continue;
        }
        const xf=(x+.5)/px-.5, x0=Math.max(0,Math.min(139,Math.floor(xf)));
        const x1=Math.min(139,x0+1),tx=Math.max(0,Math.min(1,xf-x0));
        const a=field[y0*140+x0],b=field[y0*140+x1];
        const cc=field[y1*140+x0],dd=field[y1*140+x1];
        const v=[a,b,cc,dd].every(Number.isFinite)?
          (1-tx)*((1-ty)*a+ty*cc)+tx*((1-ty)*b+ty*dd):original;
        const q=Math.max(0,Math.min(1000,Math.round((v-min)/(max-min)*1000)));
        const rgb=lut[q];d[pos]=rgb[0];d[pos+1]=rgb[1];d[pos+2]=rgb[2];d[pos+3]=255;
      }
    }
    ctx.putImageData(out,0,0);
    const stops=anomalies?LEVELS:ABS_STOPS;
    const cols=anomalies?COLORS:ABS_COLORS;
    el.legend.innerHTML='<div class="cpc-spectrum" style="background:linear-gradient(to right,'+
      cols.map((col,i)=>col+' '+((stops[i]-stops[0])/(stops.at(-1)-stops[0])*100).toFixed(2)+'%').join(",")+
      ')"></div><div class="cpc-legend-values"><span>'+
      stops[0]+(anomalies?" K":" °C")+'</span><span>0</span><span>'+
      "+"+stops.at(-1)+(anomalies?" K":" °C")+'</span></div>'+
      '<small>Weiche Darstellung; wissenschaftliche Datenauflösung weiterhin 0,5°</small>';
  }
  function drawChart(){
    const c=el.chart,ctx=c.getContext("2d"),w=690,h=160;
    c.width=w;c.height=h;
    ctx.fillStyle="#f8fbfd";ctx.fillRect(0,0,w,h);
    if(selection===null||!data)return;
    const source=el.metric.value==="anomaly"?anomaly:absolute;
    const series=data.dates.map((_,di)=>{
      let total=0,weights=0;
      for(let y=0;y<76;y++){
        const weight=Math.cos((71.75-y*0.5)*Math.PI/180);
        for(let x=0;x<140;x++){
          const k=y*140+x;if(mask[k]!==selection)continue;
          const v=source[di*cells+k];
          if(Number.isFinite(v)){total+=v*weight;weights+=weight;}
        }
      }
      return weights>0?total/weights:NaN;
    });
    const vals=series.filter(Number.isFinite);
    if(!vals.length)return;
    let lo=Math.min(...vals),hi=Math.max(...vals);
    const pad=Math.max(1,(hi-lo)*.20);
    lo-=pad;hi+=pad;
    ctx.strokeStyle="#c8d8e3";ctx.lineWidth=1;
    const zeroY=145-(0-lo)/(hi-lo)*120;
    if(zeroY>=15&&zeroY<=145){ctx.beginPath();ctx.moveTo(15,zeroY);ctx.lineTo(675,zeroY);ctx.stroke();}
    ctx.beginPath();ctx.strokeStyle="#245e8b";ctx.lineWidth=2.2;
    let active=false;
    series.forEach((v,i)=>{
      if(!Number.isFinite(v)){active=false;return;}
      const x=15+i/Math.max(1,series.length-1)*660;
      const y=145-(v-lo)/(hi-lo)*120;
      if(!active){ctx.moveTo(x,y);active=true;}else ctx.lineTo(x,y);
    });ctx.stroke();
    ctx.fillStyle="#364d5d";ctx.font="13px Arial";
    ctx.fillText(hi.toFixed(1),10,14);ctx.fillText(lo.toFixed(1),10,158);
  }
  function choose(id){
    selection=id;
    el.countries.querySelectorAll("tr[data-country]").forEach(tr=>tr.classList.toggle("active",Number(tr.dataset.country)===id));
    const found=currentStats.find(x=>x.id===id);
    el.selected.textContent=found?found.name+": "+(found.value>=0?"+":"")+found.value.toFixed(2)+
       (el.metric.value==="anomaly"?" K":" °C"):"Land auswählen";
    drawChart();
  }
  function updateCountries(stats,anomalies){
    currentStats=stats;el.header.textContent=anomalies?"Abweichung (K)":"Temperatur (°C)";
    el.countries.innerHTML=stats.length?stats.map(x=>'<tr tabindex="0" data-country="'+x.id+'"><td>'+
      x.name+'</td><td class="'+(x.value>=0?"warm":"cold")+'">'+
      (x.value>=0?"+":"")+x.value.toFixed(2)+(anomalies?" K":" °C")+
      '</td><td>'+Math.round(x.coverage*100)+' %</td></tr>').join(""):
      '<tr><td colspan="3">Keine ausreichende Rasterabdeckung</td></tr>';
    el.countries.querySelectorAll("tr[data-country]").forEach(tr=>{
      const action=()=>choose(Number(tr.dataset.country));
      tr.addEventListener("click",action);
      tr.addEventListener("keydown",ev=>{if(ev.key==="Enter"||ev.key===" "){ev.preventDefault();action();}});
    });
    if(!stats.some(c=>c.id===selection))selection=stats.length?stats[0].id:null;
    choose(selection);
  }
  function render(){
    if(!data)return;
    const sel=chosenRange();
    if(!sel){
      el.warn.hidden=false;el.warn.textContent="Für diesen Zeitraum fehlen noch vollständige +3-h-GFS-Felder aus 00/06/12/18 UTC. Keine fehlenden Tage ergänzt.";
      [el.png,el.pdf,el.csv].forEach(x=>x.disabled=true);return;
    }
    const anomalies=el.metric.value==="anomaly";
    if(anomalies&&!data.reference_ready){
      el.warn.hidden=false;el.warn.textContent="Noch keine validierte CFSR/CFSv2-Referenz für 1991–2020. Keine ungesicherten Anomalien.";
      return;
    }
    el.warn.hidden=true;
    range=sel;
    shownField=meanField(sel,anomalies?anomaly:absolute);
    draw(shownField,anomalies);
    updateCountries(countriesFor(shownField),anomalies);
    el.status.textContent=sel.a+" bis "+sel.b+" · "+sel.ids.length+
      " vollständige GFS-+3h-Tage · "+(anomalies?"Anomalie 1991–2020":"2-m-Temperatur");
    [el.png,el.pdf,el.csv].forEach(x=>x.disabled=false);
  }
  function saveData(url,filename){
    const a=document.createElement("a");a.href=url;a.download=filename;
    document.body.appendChild(a);a.click();a.remove();
  }
  function imageExport(){
    if(!shownField||!range)return null;
    const c=document.createElement("canvas");c.width=1400;c.height=940;
    const ctx=c.getContext("2d");
    ctx.fillStyle="#fff";ctx.fillRect(0,0,c.width,c.height);
    ctx.fillStyle="#16314a";ctx.font="bold 29px Arial";
    ctx.fillText("Europa · GFS 0,5° Kurzprognose +3 h",35,43);
    ctx.font="20px Arial";ctx.fillText(range.a+" – "+range.b+" · "+
      (el.metric.value==="anomaly"?"CFSR/CFSv2 1991–2020":"Temperatur °C"),35,76);
    ctx.drawImage(el.map,0,105,1400,760);
    if(el.borders.complete&&el.borders.naturalWidth)ctx.drawImage(el.borders,0,105,1400,760);
    ctx.fillStyle="#153752";ctx.font="15px Arial";
    ctx.fillText("NOAA GFS · +3 h · gültig 03/09/15/21 UTC · Raster 0,5°",35,912);
    return c.toDataURL("image/png");
  }
  function csvExport(){
    if(!range||!currentStats.length)return;
    const lines=["Land;Wert;Einheit;Abdeckung_Prozent;Von;Bis;Quelle;Referenz"];
    for(const c of currentStats)lines.push([
      c.name,c.value.toFixed(3).replace(".",","),
      el.metric.value==="anomaly"?"K":"°C",Math.round(c.coverage*100),
      range.a,range.b,"NOAA GFS Prognose f003",
      el.metric.value==="anomaly"?"CFSR/CFSv2 1991-2020":"Keine (Absoluttemperatur)"
    ].join(";"));
    const blob=new Blob(["\ufeff"+lines.join("\r\n")],{type:"text/csv;charset=utf-8"});
    const url=URL.createObjectURL(blob);
    saveData(url,"gfs_f003_europa_laendermittel_"+range.b+".csv");
    setTimeout(()=>URL.revokeObjectURL(url),2000);
  }
  el.preset.addEventListener("change",()=>preset(el.preset.value));
  el.metric.addEventListener("change",render);
  [el.start,el.end].forEach(node=>node.addEventListener("change",()=>{
    el.preset.value="custom";render();
  }));
  el.map.addEventListener("click",evt=>{
    if(!data||!mask)return;
    const r=el.map.getBoundingClientRect();
    const x=Math.floor((evt.clientX-r.left)/r.width*140);
    const y=Math.floor((evt.clientY-r.top)/r.height*76);
    if(x<0||x>=140||y<0||y>=76)return;
    const who=mask[y*140+x];if(who>=0)choose(who);
  });
  el.png.addEventListener("click",()=>{
    const url=imageExport();if(url)saveData(url,"gfs_f003_europa_"+range.b+".png");
  });
  el.pdf.addEventListener("click",()=>window.print());
  el.csv.addEventListener("click",csvExport);
  async function start(){
    try{
      const [a,b]=await Promise.all([
        fetch("gfs_analysis_europe/index_f003.json?v=1",{cache:"no-store"}),
        fetch("cpc_europe/index.json?v=1",{cache:"force-cache"})
      ]);
      if(!a.ok||!b.ok)throw new Error("Noch keine geprüften GFS-+3h-Felder oder keine Ländermasken veröffentlicht.");
      const [main,cpc]=await Promise.all([a.json(),b.json()]);
      validate(main,cpc);
      el.date.textContent="GFS +3 h bis "+data.data_through;
      el.start.min=el.end.min=data.first_date;
      el.start.max=el.end.max=data.data_through;
      if(data.reference_ready){
        el.reference.classList.add("ready");
        el.reference.textContent="Homogene Referenz 1991–2020 vollständig geprüft: CFSR bis März 2011, CFSv2 ab April 2011; alle Felder +3 h.";
        el.metric.value="anomaly";
      }else{
        el.reference.textContent="CFSR/CFSv2-f003-Referenz 1991–2020 noch nicht vollständig geprüft. Bis dahin nur absolute GFS-+3h-Temperaturen; keine Anomalie berechnet.";
        el.metric.querySelector('option[value="anomaly"]').disabled=true;
        el.metric.value="absolute";
      }
      preset(el.preset.value);
    }catch(err){
      el.status.textContent="GFS-+3h-Prognose nicht verfügbar";
      el.reference.textContent="Keine ungeprüften Karten veröffentlicht.";
      el.warn.hidden=false;
      el.warn.textContent=String(err.message||err);
      el.countries.innerHTML='<tr><td colspan="3">Keine verifizierten Daten verfügbar</td></tr>';
    }
  }
  start();
})();
