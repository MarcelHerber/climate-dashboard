/* NOAA CPC indices: transparent official observed data, no synthetic values. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const page = document.body.dataset.climateModule;
  if (!["nao-ao","enso"].includes(page)) return;
  let payload=null, chart=null, currentRows=[], currentTitle="";
  const sourceURL="climate_indices/index.json";
  const COLORS={nao:"#196bb1",ao:"#c77918",roni:"#b84442",oni:"#53718d"};
  const de = new Intl.NumberFormat("de-DE",{minimumFractionDigits:2,maximumFractionDigits:2});
  function fmt(x) {return Number.isFinite(x)?(x>0?"+":"")+de.format(x):"–";}
  function setStatus(s) {$("climateStatus").textContent=s;}
  function humanMonth(value) {
    const [year,month]=value.split("-").map(Number);
    return new Date(Date.UTC(year,month-1,1)).toLocaleDateString("de-DE",{month:"short",year:"numeric",timeZone:"UTC"});
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  }
  function item(label,value,note) {
    return '<div class="kpi"><span>'+esc(label)+'</span><b>'+esc(value)+'</b><small>'+esc(note||"")+'</small></div>';
  }
  function recentRows(rows,years) {
    if(years==="all")return rows;
    const last=rows.at(-1)?.[0]||"";
    const lastYear=Number(last.slice(0,4)), lastMonth=Number(last.slice(5,7))||1;
    const cutoff=new Date(Date.UTC(lastYear, lastMonth-1-Number(years)*12,1)).toISOString().slice(0,7);
    return rows.filter(r=>r[0]>=cutoff);
  }
  function zeroLine(chartCtx) {
    return {
      id:"zeroLineClimate",
      afterDraw(chart) {
        const y=chart.scales.y, area=chart.chartArea;
        if(!area || !y || y.min>0 || y.max<0)return;
        const p=y.getPixelForValue(0);
        const ctx=chart.ctx;ctx.save();ctx.strokeStyle="rgba(51,65,85,.42)";ctx.lineWidth=1.4;
        ctx.beginPath();ctx.moveTo(area.left,p);ctx.lineTo(area.right,p);ctx.stroke();ctx.restore();
      }
    };
  }
  function makeChart(labels,datasets,yTitle) {
    if(!window.Chart)throw new Error("Chart.js konnte nicht geladen werden.");
    if(chart){chart.destroy();chart=null;}
    chart=new Chart($("climateChart"),{
      type:"line",data:{labels,datasets},
      plugins:[zeroLine()],
      options:{
        responsive:true,maintainAspectRatio:false,animation:false,normalized:true,
        interaction:{mode:"index",intersect:false},
        elements:{point:{radius:0,hitRadius:8,hoverRadius:3},line:{tension:0,borderWidth:1.8,spanGaps:false}},
        scales:{
          x:{grid:{display:false},ticks:{
            maxRotation:0,autoSkip:true,maxTicksLimit:window.innerWidth<700?6:13,
            callback:function(value){const label=this.getLabelForValue(value);
              return label.length===10?label.slice(0,7):label;
            }
          }},
          y:{title:{display:true,text:yTitle},grid:{color:"rgba(148,163,184,.2)"},ticks:{
            callback:v=>Number(v).toLocaleString("de-DE",{maximumFractionDigits:1})
          }}
        },
        plugins:{
          datalabels:{display:false},
          legend:{display:true,position:"bottom",labels:{usePointStyle:true,boxWidth:12}},
          tooltip:{callbacks:{
            title:items=>items.length?items[0].label:"",
            label:item=>item.dataset.label+": "+fmt(item.parsed.y)+(page==="enso"?" °C":"")
          }}
        }
      }
    });
    for(const key of ["climatePNG","climatePDF","climateCSV"])$(key).disabled=false;
  }
  function correlation(rows) {
    const xs=rows.filter(row=>Number.isFinite(row[1])&&Number.isFinite(row[2]));
    if(xs.length<10)return null;
    const n=xs.length;
    const mx=xs.reduce((s,r)=>s+r[1],0)/n,my=xs.reduce((s,r)=>s+r[2],0)/n;
    const x=xs.reduce((s,r)=>s+(r[1]-mx)**2,0),y=xs.reduce((s,r)=>s+(r[2]-my)**2,0);
    if(x<=0||y<=0)return null;
    return xs.reduce((s,r)=>s+(r[1]-mx)*(r[2]-my),0)/Math.sqrt(x*y);
  }
  function renderAtmos() {
    const mode=$("climateMode").value,range=$("climateRange").value,which=$("climateIndex").value;
    const type=mode==="daily"?"daily":"monthly";
    const nao=payload.teleconnections.nao[type]||[];
    const ao=payload.teleconnections.ao[type]||[];
    const mapNAO=new Map(nao.map(r=>[r[0],r[1]])), mapAO=new Map(ao.map(r=>[r[0],r[1]]));
    const dates=[...new Set([...mapNAO.keys(),...mapAO.keys()])].sort();
    const rows=recentRows(dates.map(d=>[d,mapNAO.get(d)??null,mapAO.get(d)??null]),range);
    if(!rows.length)throw new Error("Für diesen Zeitraum liegen keine Indexwerte vor.");
    currentRows=[["Datum","NAO","AO"],...rows];
    currentTitle="NAO und AO · "+(mode==="daily"?"Tageswerte":"aus Tageswerten berechnete Monatsmittel")+" · "+rows[0][0]+" bis "+rows.at(-1)[0];
    const datasets=[];
    if(which==="both"||which==="nao")datasets.push({label:"NAO",data:rows.map(r=>r[1]),borderColor:COLORS.nao,backgroundColor:COLORS.nao});
    if(which==="both"||which==="ao")datasets.push({label:"AO",data:rows.map(r=>r[2]),borderColor:COLORS.ao,backgroundColor:COLORS.ao});
    makeChart(rows.map(r=>r[0]),datasets,"Standardisierter Index");
    const ln=payload.teleconnections.nao,la=payload.teleconnections.ao;
    const lastNao=ln[type].at(-1),lastAo=la[type].at(-1);
    const corr=correlation(rows);
    $("climateKpis").innerHTML=
      item("NAO · jüngster "+(mode==="daily"?"Tag":"Monat"),fmt(lastNao?.[1]),lastNao?.[0]||"")+
      item("AO · jüngster "+(mode==="daily"?"Tag":"Monat"),fmt(lastAo?.[1]),lastAo?.[0]||"")+
      item("NAO/AO-Korrelation",corr===null?"–":de.format(corr),"Pearson r · gewählter Zeitraum")+
      item("Datenabdeckung",rows[0][0]+" – "+rows.at(-1)[0],rows.length+" Termine");
    setStatus("NOAA/CPC-Beobachtungen · NAO bis "+ln.latest_date+" · AO bis "+la.latest_date+
      (mode==="monthly"?" · Monatswerte ≥90 % Tagesabdeckung":""));
  }
  function classify(v){return v>=.5?1:v<=-.5?-1:0;}
  function episodes(rows) {
    // Only contiguous, overlapping triple-month seasons count toward >=5.
    let run=[],state=0;const found=[];
    function flush(){
      if(run.length>=5)found.push({
        kind:state===1?"El Niño":"La Niña",
        start:run[0],end:run.at(-1),length:run.length,
        peak:state===1?Math.max(...run.map(r=>r[2])):Math.min(...run.map(r=>r[2]))
      });
      run=[];state=0;
    }
    for(const r of rows){
      const side=classify(r[2]);
      const previous=run.at(-1)?.[0];
      const currentDate=r[0];
      const previousNext=previous
        ?new Date(Date.UTC(Number(previous.slice(0,4)),Number(previous.slice(5,7)),1)).toISOString().slice(0,7)
        :null;
      if(!side||side!==state||(previous&&previousNext!==currentDate))flush();
      if(side){run.push(r);state=side;}
    }
    flush();
    return found;
  }
  function renderEnso() {
    const which=$("climateIndex").value,other=which==="roni"?"oni":"roni";
    const compare=$("climateCompare").checked,range=$("climateRange").value;
    const series=payload.enso[which].seasons,otherSeries=payload.enso[other].seasons;
    const reference=new Map(otherSeries.map(r=>[r[0],r[2]]));
    const visible=recentRows(series,range);
    const rows=visible.map(r=>[r[0],r[1],r[2],reference.get(r[0])??null]);
    if(!rows.length)throw new Error("Keine ENSO-Jahreszeiten im gewählten Zeitraum.");
    currentRows=[["Zentrierter Monat","Jahreszeit",which.toUpperCase(),other.toUpperCase()],...rows];
    currentTitle="ENSO · "+which.toUpperCase()+(compare?" und "+other.toUpperCase():"")+" · "+rows[0][0]+" bis "+rows.at(-1)[0];
    const datasets=[{
      label:which.toUpperCase(),data:rows.map(r=>r[2]),borderColor:COLORS[which],
      backgroundColor:COLORS[which],borderWidth:2.4,
      segment:{borderColor:ctx=>{
        const a=ctx.p0.parsed.y,b=ctx.p1.parsed.y;
        return a>=.5&&b>=.5?"#bb3a39":a<=-.5&&b<=-.5?"#296fb1":COLORS[which];
      }}
    }];
    if(compare)datasets.push({label:other.toUpperCase(),data:rows.map(r=>r[3]),
      borderColor:"#7c8794",backgroundColor:"#7c8794",borderDash:[5,4],borderWidth:1.25});
    datasets.push(
      {label:"+0,5 °C",data:rows.map(()=>0.5),borderColor:"rgba(185,61,59,.48)",borderDash:[6,4],pointRadius:0,borderWidth:1},
      {label:"−0,5 °C",data:rows.map(()=>-0.5),borderColor:"rgba(40,111,177,.48)",borderDash:[6,4],pointRadius:0,borderWidth:1}
    );
    makeChart(rows.map(r=>humanMonth(r[0])),datasets,"Anomalie (°C)");
    // Count events on full NOAA series so a window cannot manufacture
    // an episode by clipping the required five consecutive seasons.
    const confirmed=episodes(series).filter(ep=>ep.end[0]>=rows[0][0] && ep.start[0]<=rows.at(-1)[0]);
    const last=series.at(-1),otherLatest=otherSeries.at(-1);
    $("climateKpis").innerHTML=
      item(which.toUpperCase()+" · jüngste Saison",fmt(last[2])+" °C",last[1]+" "+last[0].slice(0,4))+
      item(other.toUpperCase()+" · jüngste Saison",fmt(otherLatest[2])+" °C",otherLatest[1]+" "+otherLatest[0].slice(0,4))+
      item("Bestätigte Episoden",String(confirmed.length),"≥5 aufeinanderfolgende Dreimonatsperioden")+
      item("Beginn des Archivs",series[0][0],"ERSSTv6 · 1950 bis heute");
    const table=$("climateEpisodes");
    table.innerHTML=confirmed.length?confirmed.slice().reverse().map(ep=>
      "<tr><td>"+esc(ep.kind)+"</td><td>"+esc(ep.start[1]+" "+ep.start[0].slice(0,4))+
      "</td><td>"+esc(ep.end[1]+" "+ep.end[0].slice(0,4))+
      "</td><td>"+ep.length+" Dreimonatsperioden</td><td>"+fmt(ep.peak)+" °C</td></tr>"
    ).join(""):"<tr><td colspan='5'>Im gewählten Zeitraum keine bestätigten Episoden.</td></tr>";
    setStatus("NOAA/CPC · "+which.toUpperCase()+" bis "+last[1]+" "+last[0].slice(0,4)+
      " · ERSSTv6 · jüngste Werte vorläufig und revisionsfähig.");
  }
  function filename(){
    return (page==="enso"?"enso_roni_oni":"nao_ao")+"_"+$("climateRange").value+"_"+
      (new Date().toISOString().slice(0,10));
  }
  function download(blob,ext){
    const url=URL.createObjectURL(blob),link=document.createElement("a");
    link.download=filename()+"."+ext;link.href=url;document.body.appendChild(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1500);
  }
  function exportCanvas(){
    if(!chart)throw new Error("Bitte zuerst Diagramm laden.");
    const source=chart.canvas, ratio=source.width/source.height;
    const w=1500,header=146,pad=45,plotW=w-2*pad,plotH=Math.round(plotW/ratio);
    const c=document.createElement("canvas");
    c.width=w;c.height=header+plotH+58;
    const ctx=c.getContext("2d");
    ctx.fillStyle="#fff";ctx.fillRect(0,0,c.width,c.height);
    ctx.fillStyle="#10233d";ctx.font="bold 32px Arial";
    ctx.fillText(page==="enso"?"ENSO · NOAA CPC":"NAO & AO · NOAA CPC",pad,50);
    ctx.fillStyle="#44556a";ctx.font="18px Arial";
    const t=currentTitle.length>105?currentTitle.slice(0,103)+"…":currentTitle;
    ctx.fillText(t,pad,94);
    ctx.drawImage(source,pad,header,plotW,plotH);
    ctx.fillStyle="#64748b";ctx.font="15px Arial";
    ctx.fillText("Quelle: NOAA Climate Prediction Center · beobachtete und veröffentlichte Indizes",pad,c.height-20);
    return c;
  }
  function exportPNG(){try{exportCanvas().toBlob(b=>b&&download(b,"png"),"image/png");}catch(e){setStatus(e.message);}}
  function exportPDF(){
    try{
      if(!window.jspdf?.jsPDF)throw new Error("PDF-Bibliothek nicht geladen.");
      const canvas=exportCanvas(),pdf=new window.jspdf.jsPDF({unit:"mm",format:"a4",orientation:"landscape"});
      const w=275,h=w*canvas.height/canvas.width;
      pdf.addImage(canvas.toDataURL("image/png"),"PNG",11,12,w,h);
      pdf.save(filename()+".pdf");
    }catch(e){setStatus("PDF-Export: "+e.message);}
  }
  function exportCSV(){
    if(!currentRows.length)return;
    const csv="\uFEFF"+currentRows.map(row=>row.map(v=>'"'+String(v??"").replace(/"/g,'""')+'"').join(";")).join("\r\n");
    download(new Blob([csv],{type:"text/csv;charset=utf-8"}),"csv");
  }
  function render(){
    try{page==="enso"?renderEnso():renderAtmos();}
    catch(e){console.error(e);setStatus("Diagramm konnte nicht erstellt werden: "+e.message);}
  }
  async function start(){
    for(const id of ["climatePNG","climatePDF","climateCSV"]){
      $(id).disabled=true;
    }
    $("climatePNG").addEventListener("click",exportPNG);
    $("climatePDF").addEventListener("click",exportPDF);
    $("climateCSV").addEventListener("click",exportCSV);
    ["climateIndex","climateRange","climateMode","climateCompare"].forEach(id=>{
      if($(id))$(id).addEventListener("change",render);
    });
    try{
      const response=await fetch(sourceURL,{cache:"no-store"});
      if(!response.ok)throw new Error("HTTP "+response.status+" · NOAA-Archiv wird aufgebaut.");
      payload=await response.json();
      if(!payload.ready||!payload.teleconnections?.nao||!payload.teleconnections?.ao||
        !payload.enso?.oni||!payload.enso?.roni)throw new Error("NOAA-Datensatz noch nicht vollständig.");
      $("climateUpdated").textContent="Aktualisiert "+String(payload.generated_at||"").slice(0,16).replace("T"," ")+" UTC";
      render();
    }catch(e){
      console.error("NOAA/CPC index error",e);
      setStatus("NOAA-Daten derzeit nicht verfügbar: "+e.message+" Bitte den Aktualisierungslauf prüfen.");
    }
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start);
  else start();
})();
