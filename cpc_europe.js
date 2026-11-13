/* NOAA CPC 0.5° Europe observation anomalies. No model forecasts or placeholders. */
(() => {
  "use strict";
  const LEVELS = [-8,-7,-6,-5,-4,-3,-2,-1,-0.5,0,0.5,1,2,3,4,5,6,7,8];
  const COLORS = [
    "#3A006F","#51009E","#6B03C6","#5E4FFC","#187DFD",
    "#70B1FB","#C6E4FB","#DDEBF9","#EDF4FA","#FDFCFC",
    "#FDF0BC","#FDE47C","#FDBD3E","#FC691C","#F93A19",
    "#E51B75","#FC579B","#FC83B4","#FDAFCB"
  ];
  const $ = id => document.getElementById(id);
  const el = {
    canvas:$("cpcMap"), boundary:$("cpcBoundaries"), status:$("cpcStatus"),
    range:$("cpcPreset"), start:$("cpcStart"), end:$("cpcEnd"),
    period:$("cpcPeriodLabel"), updated:$("cpcDataStatus"),
    table:$("cpcCountryRows"), selected:$("cpcSelected"),
    legend:$("cpcLegend"), png:$("cpcPng"), pdf:$("cpcPdf"),
    csv:$("cpcCsv"), message:$("cpcMessage"), chart:$("cpcChart")
  };
  if (!el.canvas) return;
  let data=null, binary=null, mask=null, latestStats=null, selectedCountry=null, drawn=false;
  const ZERO = -32768;
  const rgb = x => COLORS[x];
  const dateAdd = (iso,offset) => {
    const d=new Date(iso+"T00:00:00Z");d.setUTCDate(d.getUTCDate()+offset);
    return d.toISOString().slice(0,10);
  };
  const dateDiff = (a,b) => Math.round((Date.parse(b+"T00:00:00Z")-Date.parse(a+"T00:00:00Z"))/86400000);
  function base64ToInt16(s){
    const str=atob(s), buf=new ArrayBuffer(str.length), u=new Uint8Array(buf);
    for(let i=0;i<str.length;i++)u[i]=str.charCodeAt(i);
    return new Int16Array(buf); // GitHub Pages/browser platforms are little-endian.
  }
  function colorIndex(value){
    let index=0;
    for(let i=0;i<LEVELS.length-1;i++){
      if(value>=(LEVELS[i]+LEVELS[i+1])/2)index=i+1;
      else break;
    }
    return index;
  }
  function verify(v){
    if(v.schema!==1 || v.provider!=="NOAA CPC Global Unified Temperature" ||
      !Array.isArray(v.dates) || v.dates.length<30 ||
      !Number.isInteger(v.width) || !Number.isInteger(v.height) ||
      !v.countries || !v.anomaly_q10_b64 || !v.country_mask_b64 ||
      v.reference!=="NOAA CPC daily long-term means 1991–2020") {
      throw new Error("NOAA CPC Datenarchiv ist unvollständig oder inkompatibel.");
    }
    let prev="";
    for(const d of v.dates){
      if(!/^\d{4}-\d\d-\d\d$/.test(d) || (prev && d<=prev))
        throw new Error("Datumsfolge ist nicht gültig.");
      prev=d;
    }
    const n=v.width*v.height;
    binary=base64ToInt16(v.anomaly_q10_b64);
    mask=base64ToInt16(v.country_mask_b64);
    if(mask.length!==n || binary.length!==v.dates.length*n ||
       v.lat.length!==v.height || v.lon.length!==v.width)
      throw new Error("Rasterdimensionen stimmen nicht überein.");
    if(v.data_through!==v.dates[v.dates.length-1])
      throw new Error("Unstimmiger Datenstand.");
  }
  function shade(){
    const html=LEVELS.map((v,i) =>
      '<span title="'+(v>0?"+":"")+v+' K" style="background:'+rgb(i)+'"></span>').join("");
    el.legend.innerHTML='<div class="cpc-spectrum">'+html+'</div>'+
      '<div class="cpc-legend-values"><span>−8 K</span><span>−4</span><span>0</span><span>+4</span><span>+8 K</span></div>'+
      '<small>Dieselben diskreten Farbstufen wie bei ERA5-Land · 0 K neutral</small>';
  }
  function selectedRange(){
    const end=el.end.value, start=el.start.value;
    if(!data || !start || !end || start>end)return null;
    const indices=[];
    for(let i=0;i<data.dates.length;i++)
      if(data.dates[i]>=start && data.dates[i]<=end)indices.push(i);
    if(!indices.length)return null;
    const required=dateDiff(start,end)+1;
    if(indices.length < Math.ceil(required*0.90)) return null;
    return {start,end,indices,required};
  }
  function applyPreset(preset){
    const last=data.data_through;
    let begin=last;
    if(preset==="month")begin=last.slice(0,7)+"-01";
    if(preset==="7")begin=dateAdd(last,-6);
    if(preset==="14")begin=dateAdd(last,-13);
    if(preset==="30")begin=dateAdd(last,-29);
    if(preset==="season"){
      const d=new Date(last+"T00:00:00Z"),m=d.getUTCMonth()+1;
      const startMonth=[12,12,12,3,3,3,6,6,6,9,9,9][m-1];
      const year=(m<3)?d.getUTCFullYear()-1:d.getUTCFullYear();
      begin=year+"-"+String(startMonth).padStart(2,"0")+"-01";
    }
    if(preset!=="custom"){
      el.start.value=begin<data.first_date?data.first_date:begin;
      el.end.value=last;
    }
    render();
  }
  function periodDescription(s){
    return s.start.split("-").reverse().join(".")+" – "+s.end.split("-").reverse().join(".")+
      " · "+s.indices.length+" beobachtete Tage";
  }
  function gridPeriod(s){
    const cells=data.width*data.height, need=Math.ceil(s.required*0.80);
    const result=new Float32Array(cells).fill(NaN);
    for(let cell=0;cell<cells;cell++){
      if(mask[cell]<0)continue;
      let sum=0,valid=0;
      for(const d of s.indices){
        const q=binary[d*cells+cell];
        if(q!==ZERO){sum+=q;valid++;}
      }
      if(valid>=need)result[cell]=sum/(10*valid);
    }
    return result;
  }
  function countryStats(field){
    const sums=new Float64Array(data.countries.length), weights=new Float64Array(data.countries.length), counts=new Int32Array(data.countries.length);
    for(let y=0;y<data.height;y++){
      const w=Math.cos(data.lat[y]*Math.PI/180);
      for(let x=0;x<data.width;x++){
        const k=y*data.width+x, id=mask[k],v=field[k];
        if(id>=0 && Number.isFinite(v)){
          sums[id]+=v*w;weights[id]+=w;counts[id]++;
        }
      }
    }
    return data.countries.map(c=>({
      id:c.id,name:c.name,value:weights[c.id]>0?sums[c.id]/weights[c.id]:NaN,
      cells:counts[c.id], coverage:c.cells?counts[c.id]/c.cells:0
    })).filter(c=>Number.isFinite(c.value) && c.coverage>=0.45)
      .sort((a,b)=>b.value-a.value);
  }
  function drawMap(field){
    const cw=data.width,ch=data.height, px=10;
    const canvas=el.canvas,ctx=canvas.getContext("2d",{alpha:false});
    canvas.width=cw*px;canvas.height=ch*px;
    ctx.fillStyle="#eaf0f3";ctx.fillRect(0,0,canvas.width,canvas.height);
    for(let y=0;y<ch;y++){
      for(let x=0;x<cw;x++){
        const k=y*cw+x,v=field[k];
        if(!Number.isFinite(v))continue;
        ctx.fillStyle=COLORS[colorIndex(v)];
        ctx.fillRect(x*px,y*px,px,px);
      }
    }
    drawn=true;
  }
  function table(stats){
    const rows=stats.map(c=>{
      const cl=c.value>=0?"warm":"cold", sign=c.value>=0?"+":"";
      return '<tr data-country="'+c.id+'" tabindex="0" role="button" aria-label="'+
         c.name+' auswählen"><td>'+c.name+'</td><td class="'+cl+'">'+
         sign+c.value.toFixed(2)+' K</td><td>'+Math.round(c.coverage*100)+' %</td></tr>';
    });
    el.table.innerHTML=rows.length?rows.join(""):'<tr><td colspan="3">Keine ausreichend gut belegten Länder.</td></tr>';
    el.table.querySelectorAll("tr[data-country]").forEach(tr=>{
      const select=()=>{selectedCountry=Number(tr.dataset.country);tableSelect();};
      tr.addEventListener("click",select);
      tr.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();select();}});
    });
    tableSelect();
  }
  function tableSelect(){
    el.table.querySelectorAll("tr[data-country]").forEach(tr=>{
      tr.classList.toggle("active",Number(tr.dataset.country)===selectedCountry);
    });
    const record=latestStats?.find(x=>x.id===selectedCountry);
    el.selected.textContent=record?
      record.name+": "+(record.value>=0?"+":"")+record.value.toFixed(2)+" K":
      "Land in der Tabelle wählen";
    chartCountry();
  }
  function chartCountry(){
    const c=el.chart,ctx=c.getContext("2d"),w=690,h=130;
    c.width=w;c.height=h;
    ctx.fillStyle="#f8fbfd";ctx.fillRect(0,0,w,h);
    ctx.strokeStyle="#ccd9e4";ctx.beginPath();ctx.moveTo(0,h/2);ctx.lineTo(w,h/2);ctx.stroke();
    if(selectedCountry===null || !data)return;
    const cells=data.width*data.height;
    const ys=[];
    for(let day=0;day<data.dates.length;day++){
      let sum=0,weights=0;
      for(let y=0;y<data.height;y++){
        const weight=Math.cos(data.lat[y]*Math.PI/180);
        for(let x=0;x<data.width;x++){
          const k=y*data.width+x;
          if(mask[k]!==selectedCountry)continue;
          const q=binary[day*cells+k];
          if(q!==ZERO){sum+=(q/10)*weight;weights+=weight;}
        }
      }
      ys.push(weights?sum/weights:NaN);
    }
    const range=Math.max(3,Math.ceil(Math.max(...ys.filter(Number.isFinite).map(Math.abs))/2)*2);
    ctx.strokeStyle="#194b81";ctx.lineWidth=2.2;ctx.beginPath();
    let open=false;
    ys.forEach((v,i)=>{
      if(!Number.isFinite(v)){open=false;return;}
      const x=i/(ys.length-1)*(w-20)+10, y=h/2-v/range*(h/2-10);
      if(!open){ctx.moveTo(x,y);open=true;}else ctx.lineTo(x,y);
    });
    ctx.stroke();
  }
  function render(){
    if(!data)return;
    const s=selectedRange();
    if(!s){
      el.message.textContent="Für diesen Zeitraum fehlen zu viele vollständige Beobachtungstage oder das Datum liegt außerhalb des Archivs.";
      el.message.hidden=false;return;
    }
    el.message.hidden=true;
    const field=gridPeriod(s);
    const n=field.reduce((sum,v)=>sum+(Number.isFinite(v)?1:0),0);
    if(n<100) {el.message.hidden=false;el.message.textContent="Zu wenig Messwerte für eine gültige Karte.";return;}
    drawMap(field);
    latestStats=countryStats(field);
    table(latestStats);
    el.period.textContent=periodDescription(s);
    el.status.textContent="NOAA CPC · gemessene Tmax/Tmin · "+s.indices.length+" Tage";
    el.png.disabled=false;el.pdf.disabled=false;el.csv.disabled=false;
  }
  function pngImage(){
    const s=selectedRange();if(!drawn||!s)return null;
    const original=el.canvas,exportCanvas=document.createElement("canvas");
    exportCanvas.width=1400;exportCanvas.height=910;
    const ctx=exportCanvas.getContext("2d");
    ctx.fillStyle="#ffffff";ctx.fillRect(0,0,1400,910);
    ctx.fillStyle="#172c40";ctx.font="bold 30px Arial";
    ctx.fillText("Europa · Temperaturabweichung (NOAA CPC)",36,44);
    ctx.font="20px Arial";ctx.fillStyle="#4c6476";
    ctx.fillText(periodDescription(s)+" · Referenz 1991–2020",36,75);
    ctx.drawImage(original,0,90,1400,760);
    if(el.boundary.complete && el.boundary.naturalWidth)
      ctx.drawImage(el.boundary,0,90,1400,760);
    COLORS.forEach((c,i)=>{ctx.fillStyle=c;ctx.fillRect(175+i*55,866,55,22);});
    ctx.fillStyle="#172c40";ctx.font="15px Arial";
    ctx.fillText("−8 K",123,883);ctx.fillText("0",690,901);ctx.fillText("+8 K",1230,883);
    ctx.font="12px Arial";ctx.fillText("NOAA PSL · Stationsbasiert · (Tmax+Tmin)/2 · 0,5°",36,905);
    return exportCanvas.toDataURL("image/png");
  }
  function download(url,name){
    const a=document.createElement("a");a.href=url;a.download=name;
    document.body.appendChild(a);a.click();a.remove();
  }
  function csvDownload(){
    if(!latestStats)return;
    const s=selectedRange();
    const rows=["Land;Abweichung_K;Rasterabdeckung_Prozent;Start;Ende;Quelle;Referenz"];
    latestStats.forEach(c=>rows.push([
      c.name,c.value.toFixed(3).replace(".",","),Math.round(c.coverage*100),
      s.start,s.end,"NOAA CPC","1991-2020"
    ].join(";")));
    const blob=new Blob(["\ufeff"+rows.join("\r\n")],{type:"text/csv;charset=utf-8"});
    const url=URL.createObjectURL(blob);
    download(url,"cpc_europa_laendermittel_"+s.end+".csv");
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  el.canvas.addEventListener("click",e=>{
    if(!data||!latestStats)return;
    const rect=el.canvas.getBoundingClientRect();
    const x=Math.floor((e.clientX-rect.left)/rect.width*data.width);
    const y=Math.floor((e.clientY-rect.top)/rect.height*data.height);
    if(x<0||y<0||x>=data.width||y>=data.height)return;
    const id=mask[y*data.width+x];
    if(id>=0){selectedCountry=id;tableSelect();}
  });
  el.range.addEventListener("change",()=>applyPreset(el.range.value));
  [el.start,el.end].forEach(node=>node.addEventListener("change",()=>{
    el.range.value="custom";render();
  }));
  el.png.addEventListener("click",()=>{
    const url=pngImage();if(url)download(url,"cpc_europa_anomalie_"+data.data_through+".png");
  });
  el.pdf.addEventListener("click",()=>window.print());
  el.csv.addEventListener("click",csvDownload);
  async function start(){
    shade();
    try{
      const response=await fetch("cpc_europe/index.json?v=1",{cache:"no-store"});
      if(!response.ok)throw new Error("HTTP "+response.status);
      const payload=await response.json();
      verify(payload);data=payload;
      el.start.min=data.first_date;el.start.max=data.data_through;
      el.end.min=data.first_date;el.end.max=data.data_through;
      el.updated.textContent="Messdaten bis "+data.data_through.split("-").reverse().join(".")+
        " · vorläufige Tage können von NOAA nachträglich korrigiert werden";
      applyPreset(el.range.value);
      el.status.setAttribute("aria-busy","false");
    } catch (err){
      el.status.textContent="Aktuell keine geprüften NOAA-CPC-Daten veröffentlicht.";
      el.message.textContent=String(err.message||err);
      el.message.hidden=false;
      el.status.setAttribute("aria-busy","false");
    }
  }
  start();
})();
