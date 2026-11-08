/* DMI Arctic: complete-year long-term trends, seasonal extremes, and labeled exports.
   Fixed per-calendar-day 1958-2002 P10/P90; not a homogenized climate series. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const valid=v=>typeof v==="number"&&Number.isFinite(v);
const leap=y=>y%4===0&&(y%100!==0||y%400===0);
const periodDefs={
  djf:{name:"Winter (DJF)",months:[[-1,12],[0,1],[0,2]]},
  mam:{name:"Frühling (MAM)",months:[[0,3],[0,4],[0,5]]},
  jja:{name:"Sommer (JJA)",months:[[0,6],[0,7],[0,8]]},
  son:{name:"Herbst (SON)",months:[[0,9],[0,10],[0,11]]}
};
const monthNames=["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"];
const fmt=(v,places=1)=>valid(v)?v.toLocaleString("de-DE",{minimumFractionDigits:places,maximumFractionDigits:places}):"–";
const signed=(v,places=1)=>valid(v)?(v>0?"+":"")+fmt(v,places):"–";
const kind=(v,lo,hi)=>!valid(v)||!valid(lo)||!valid(hi)?null:(v>hi?"warm":v<lo?"cold":"neutral");
const colors={warm:"#b95346",cold:"#287eae",neutral:"#d8e1e9",missing:"#8d98a5"};
const complete=a=>a.filter(r=>r.coverage===r.expected);
function seasonDays(doc,year,key){
  const def=periodDefs[key];
  if(!def)throw Error("Unbekannte Saison");
  const result=[];
  for(const [offset,month] of def.months){
    const y=year+offset;
    const series=doc.years[String(y)];
    if(!series)return null;
    for(let i=0;i<doc.days.length;i++){
      const day=doc.days[i];
      if(Number(day.slice(0,2))!==month)continue;
      if(day==="02-29"&&!leap(y))continue;
      result.push({date:y+"-"+day,index:i,value:series[i]});
    }
  }
  return result;
}
function seasonFor(doc,reference,year,key){
  const days=seasonDays(doc,year,key);
  if(!days)return null;
  const expected=days.length;
  if(!expected)return null;
  let warm=0,cold=0,runWarm=0,runCold=0,longestWarm=0,longestCold=0;
  for(const row of days){
    const category=kind(row.value,reference.p10[row.index],reference.p90[row.index]);
    if(category===null)return null; // Full season only, without invented data.
    if(category==="warm"){warm++;runWarm++;runCold=0;}
    else if(category==="cold"){cold++;runCold++;runWarm=0;}
    else{runWarm=0;runCold=0;}
    longestWarm=Math.max(longestWarm,runWarm);
    longestCold=Math.max(longestCold,runCold);
  }
  return {year,season:key,days:expected,warm,cold,longestWarm,longestCold,
    first:days[0].date,last:days.at(-1).date};
}
function seasons(doc,reference){
  const years=Object.keys(doc.years).map(Number).sort((a,b)=>a-b);
  const result={djf:[],mam:[],jja:[],son:[]};
  for(const name of Object.keys(result))
    for(const y of years){const p=seasonFor(doc,reference,y,name);if(p)result[name].push(p);}
  return result;
}
function decadal(annual){
  const map=new Map();
  for(const row of complete(annual)){
    const decade=Math.floor(row.year/10)*10;
    if(!map.has(decade))map.set(decade,{decade,years:0,warmDays:0,coldDays:0,maxWarm:0,maxCold:0});
    const obj=map.get(decade);obj.years++;
    obj.warmDays+=row.warmDays;obj.coldDays+=row.coldDays;
    obj.maxWarm+=row.maxWarm;obj.maxCold+=row.maxCold;
  }
  return [...map.values()].map(v=>({decade:v.decade,years:v.years,
    warmDays:v.warmDays/v.years,coldDays:v.coldDays/v.years,
    maxWarm:v.maxWarm/v.years,maxCold:v.maxCold/v.years})).sort((a,b)=>a.decade-b.decade);
}
function regression(rows,key){
  if(rows.length<3)return null;
  const n=rows.length,mx=rows.reduce((s,r)=>s+r.year,0)/n,
    my=rows.reduce((s,r)=>s+r[key],0)/n;
  let cov=0,xx=0,yy=0;
  for(const r of rows){cov+=(r.year-mx)*(r[key]-my);xx+=(r.year-mx)**2;yy+=(r[key]-my)**2;}
  if(xx===0)return null;
  const slope=cov/xx;
  return {slope,perDecade:slope*10,intercept:my-slope*mx,
    r2:yy>0?cov**2/(xx*yy):0,n,predict:year=>my+slope*(year-mx)};
}
function seasonalRank(items,key,year){
  const sorted=items.slice().sort((a,b)=>b[key]-a[key]||a.year-b.year);
  const row=sorted.find(r=>r.year===year);
  return {sorted,rank:row?1+items.filter(r=>r[key]>row[key]).length:null};
}
function annualFiltered(rows,from,to){
  return complete(rows).filter(r=>r.year>=from&&r.year<=to);
}
function analyze(doc){
  const lib=window.Arctic80StreaksMath;
  if(!lib)throw Error("Serienauswertung noch nicht verfügbar");
  const basic=lib.analyze(doc);
  return {annual:basic.annual,events:basic.events,reference:basic.reference,
    seasons:seasons(doc,basic.reference),decades:decadal(basic.annual)};
}
window.Arctic80LongTermMath={kind,seasonDays,seasonFor,seasons,decadal,regression,seasonalRank,annualFiltered,analyze};
let doc=null,results=null,frequencyChart=null,durationChart=null,seasonChart=null;
const meta="DMI/ECMWF-Temperaturindex nördlich 80° N · P10/P90 1958–2002 · keine homogenisierte Klimareihe";
const valueName={warmDays:"Wärmetage",coldDays:"Kältetage",maxWarm:"Längste Wärmefolge",maxCold:"Längste Kältefolge"};
function tr(cells,head=false){
  const row=document.createElement("tr");
  for(const v of cells){const td=document.createElement(head?"th":"td");td.textContent=String(v);row.append(td);}
  return row;
}
function replaceRows(id,rows){const body=$(id);body.replaceChildren(...rows);}
function yearsRange(){
  const completeYears=complete(results.annual).map(r=>r.year);
  return {first:Math.min(...completeYears),last:Math.max(...completeYears)};
}
function rowSet(){
  const from=Number($("arcticTrendFrom").value),to=Number($("arcticTrendTo").value);
  return annualFiltered(results.annual,Math.min(from,to),Math.max(from,to));
}
function chartsOpts(yLabel){
  return {responsive:true,maintainAspectRatio:false,animation:false,
    interaction:{mode:"index",intersect:false},
    elements:{point:{radius:1,hoverRadius:4},line:{tension:0,spanGaps:false}},
    scales:{x:{grid:{display:false},ticks:{maxTicksLimit:13,color:"#60768a"}},
      y:{beginAtZero:true,title:{display:true,text:yLabel,color:"#60768a"},
        grid:{color:"rgba(110,135,155,.18)"},ticks:{color:"#60768a"}}},
    plugins:{legend:{position:"bottom",labels:{usePointStyle:true,boxWidth:11}},
      datalabels:{display:false}}};
}
function datasets(rows,warmKey,coldKey,includeTrend){
  const values=[
    {label:valueName[warmKey],data:rows.map(r=>r[warmKey]),borderColor:colors.warm,
      backgroundColor:colors.warm,borderWidth:2.5},
    {label:valueName[coldKey],data:rows.map(r=>r[coldKey]),borderColor:colors.cold,
      backgroundColor:colors.cold,borderWidth:2.5}
  ];
  if(includeTrend)for(const [key,color] of [[warmKey,colors.warm],[coldKey,colors.cold]]){
    const fit=regression(rows,key);
    if(fit)values.push({label:"Trend "+valueName[key],data:rows.map(r=>fit.predict(r.year)),
      borderColor:color,backgroundColor:color,borderDash:[6,5],pointRadius:0,borderWidth:1.5});
  }
  return values;
}
function replaceChart(old,id,rows,warm,cold,includeTrend=false){
  if(old)old.destroy();
  return new Chart($(id),{type:"line",data:{labels:rows.map(r=>r.year),
    datasets:datasets(rows,warm,cold,includeTrend)},options:chartsOpts("Tage")});
}
function decadeTable(rows){
  const selectedYears=new Set(rows.map(r=>r.year));
  const bins=results.decades.map(d=>({
    ...d,available:rows.filter(r=>Math.floor(r.year/10)*10===d.decade)
  })).filter(d=>d.available.length);
  const summary=bins.map(d=>{
    const sample=d.available,n=sample.length;
    const avg=k=>sample.reduce((s,r)=>s+r[k],0)/n;
    return {decade:d.decade,count:n,warm:avg("warmDays"),cold:avg("coldDays"),
      longWarm:avg("maxWarm"),longCold:avg("maxCold")};
  });
  replaceRows("arcticDecadeBody",summary.map(d=>tr([
    d.decade+"er",d.count,fmt(d.warm),fmt(d.cold),fmt(d.longWarm),fmt(d.longCold)])));
  return summary;
}
function renderTrend(){
  if(!results||typeof Chart==="undefined")return;
  const all=rowSet();
  const useTrends=$("arcticTrendLines").checked;
  $("arcticTrendStatus").textContent=all.length?
    all.length+" vollständige Jahre ("+all[0].year+"–"+all.at(-1).year+"), feste Vergleichsschwellen P10/P90 1958–2002":
    "In dieser Auswahl liegen keine vollständigen Jahre vor.";
  frequencyChart=replaceChart(frequencyChart,"arcticTrendDaysCanvas",all,"warmDays","coldDays",useTrends);
  durationChart=replaceChart(durationChart,"arcticTrendDurationCanvas",all,"maxWarm","maxCold",useTrends);
  const wf=regression(all,"warmDays"),cf=regression(all,"coldDays");
  $("arcticTrendSlope").textContent=wf&&cf?
    "Lineare Trends der Extremtage: Wärme "+signed(wf.perDecade)+" Tage/Dekade, Kälte "+
      signed(cf.perDecade)+" Tage/Dekade (nur vollständige Jahre, deskriptiv; keine Signifikanzprüfung).":
    "Zu wenige vollständige Jahre für eine lineare Trendberechnung.";
  decadeTable(all);
}
function seasonKey(){return $("arcticSeasonChoose").value;}
function seasonalRows(){return results.seasons[seasonKey()]||[];}
function fillSeasonTable(id,key){
  const rows=seasonalRank(seasonalRows(),key,0).sorted.slice(0,12);
  const body=$(id);body.replaceChildren();
  for(const row of rows){
    const rank=1+seasonalRows().filter(r=>r[key]>row[key]).length;
    const cells=[rank+".",row.year,row[key],row[key==="warm"?"longestWarm":"longestCold"]];
    const elem=tr(cells);
    if(String(row.year)===$("arcticYear").value)elem.className="arctic-selected";
    body.append(elem);
  }
}
function renderSeason(){
  if(!results||typeof Chart==="undefined")return;
  const rows=seasonalRows(),season=periodDefs[seasonKey()];
  const picked=rows.find(r=>String(r.year)===$("arcticYear").value);
  $("arcticSeasonStatus").textContent=season.name+" · "+rows.length+" vollständige Perioden · "+
    (seasonKey()==="djf"?"Winterjahr = Januar/Februar":"Kalenderjahr");
  $("arcticSeasonSelected").textContent=picked?
    "Ausgewähltes Jahr "+picked.year+": "+picked.warm+" Wärmetage, "+picked.cold+
    " Kältetage · längste Folgen "+picked.longestWarm+"/"+picked.longestCold+" Tage.":
    "Für das ausgewählte Jahr liegt keine vollständig erfasste "+season.name+"-Periode vor.";
  if(seasonChart)seasonChart.destroy();
  seasonChart=new Chart($("arcticSeasonCanvas"),{type:"line",
    data:{labels:rows.map(r=>r.year),datasets:datasets(rows,"warm","cold",false).map((ds,i)=>({
      ...ds,label:i?"Kältetage "+season.name:"Wärmetage "+season.name
    }))},options:chartsOpts("Extremtage pro Saison")});
  fillSeasonTable("arcticSeasonWarmBody","warm");
  fillSeasonTable("arcticSeasonColdBody","cold");
}
function initializeYearOptions(){
  const range=yearsRange();
  const first=$("arcticTrendFrom"),last=$("arcticTrendTo");
  first.replaceChildren();last.replaceChildren();
  for(let y=range.first;y<=range.last;y++){
    if(!results.annual.some(a=>a.year===y&&a.coverage===a.expected))continue;
    for(const select of [first,last]){
      const option=document.createElement("option");option.value=String(y);option.textContent=y;
      select.append(option);
    }
  }
  first.value=String(range.first);last.value=String(range.last);
}
function render(){
  renderTrend();renderSeason();
}
function accept(incoming){
  if(!incoming||!incoming.years||incoming.days?.length!==366)return;
  if(doc===incoming&&results)return;
  doc=incoming;results=analyze(doc);
  initializeYearOptions();
  $("arcticLongTermLoad").textContent="Auswertung bereit · Datenstand "+doc.last_date.split("-").reverse().join(".")+
    " · "+results.annual.length+" Jahresreihen";
  render();
}
function csvCell(v){
  if(v==null)return "";
  return String(v).replace(/[\r\n]+/g," ").replace(/"/g,'""');
}
function csv(rows){
  return "\ufeff"+rows.map(row=>row.map(v=>'"'+csvCell(v)+'"').join(";")).join("\r\n")+"\r\n";
}
function csvAnnual(){
  return csv([
    ["DMI Extremtage · P10/P90 1958–2002 · vollständige Jahre; kein homogenisiertes Klimamittel"],
    ["Jahr","Datenabdeckung","Erwartete Tage","Warmtage über P90","Kalttage unter P10","Längste Wärmefolge","Längste Kältefolge","Vollständig"],
    ...results.annual.map(r=>[r.year,r.coverage,r.expected,r.warmDays,r.coldDays,r.maxWarm,r.maxCold,r.coverage===r.expected?"Ja":"Nein"]),
    [],["Dekadenübersicht (nur vollständige Jahre)"],
    ["Dekade","Jahresanzahl","Mittel Warmtage","Mittel Kalttage","Mittel längste Wärmefolge","Mittel längste Kältefolge"],
    ...results.decades.map(d=>[d.decade,d.years,d.warmDays,d.coldDays,d.maxWarm,d.maxCold])
  ]);
}
function csvSeasons(){
  const rows=[["DMI Saisonstatistiken · P10/P90 1958–2002 · nur vollständige Perioden"],
    ["Jahreszeit","Winter-/Kalenderjahr","Beginn","Ende","Tage","Warmtage","Kalttage",
      "Längste Wärmefolge","Längste Kältefolge","Wärmerang","Kälterang"]];
  for(const k of Object.keys(periodDefs))for(const r of results.seasons[k]){
    const series=results.seasons[k];
    rows.push([k,r.year,r.first,r.last,r.days,r.warm,r.cold,
      r.longestWarm,r.longestCold,seasonalRank(series,"warm",r.year).rank,
      seasonalRank(series,"cold",r.year).rank]);
  }
  return csv(rows);
}
function csvSpells(){
  const rows=[["DMI historische Wärme-/Kälteserien · P10/P90 1958–2002"],
    ["Kategorie","Beginn","Ende","Tage","Mittel Überschreitung K","Am letzten Datentag aktiv"]];
  for(const k of ["warm","cold"])for(const e of results.events[k]){
    rows.push([k==="warm"?"Wärme":"Kälte",e.start,e.end,e.days,e.meanExcess,e.latest?"Ja":"Nein"]);
  }
  return csv(rows);
}
function csvHeatmap(){
  const rows=[["DMI Extremtage-Heatmap · feste P10/P90 1958–2002 · 1=warm, -1=kalt, 0=normal, leer=fehlend"],
    ["Datum","Jahr","Temperatur °C","P10 °C","P90 °C","Kategorie"]];
  for(const y of Object.keys(doc.years).map(Number).sort((a,b)=>a-b)){
    for(let i=0;i<doc.days.length;i++){
      if(doc.days[i]==="02-29"&&!leap(y))continue;
      const v=doc.years[String(y)][i],a=results.reference,
        category=kind(v,a.p10[i],a.p90[i]);
      rows.push([y+"-"+doc.days[i],y,valid(v)?v:null,a.p10[i],a.p90[i],
        category==="warm"?1:category==="cold"?-1:category==="neutral"?0:null]);
    }
  }
  return csv(rows);
}
function saveBlob(content,name,type){
  const url=URL.createObjectURL(new Blob([content],{type}));
  const a=document.createElement("a");a.href=url;a.download=name;
  document.body.append(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1500);
}
function saveCanvas(canvas,name){
  canvas.toBlob(blob=>{
    if(blob)saveBlob(blob,name,"image/png");
  },"image/png");
}
function stampCanvas(canvas,width,height,title,subtitle,draw){
  const ratio=2;
  canvas.width=width*ratio;canvas.height=height*ratio;
  const ctx=canvas.getContext("2d");ctx.scale(ratio,ratio);
  ctx.fillStyle="#fff";ctx.fillRect(0,0,width,height);
  ctx.fillStyle="#20384f";ctx.textBaseline="alphabetic";
  ctx.font="bold 22px Arial";ctx.fillText(title,24,34);
  ctx.font="13px Arial";ctx.fillStyle="#53687c";ctx.fillText(subtitle,24,59);
  draw(ctx,24,88,width-48,height-148);
  ctx.fillStyle="#53687c";ctx.font="11px Arial";
  ctx.fillText(meta,24,height-45);
  ctx.fillText("Quelle: DMI / ECMWF · Stand "+doc.last_date+" · Erzeugt mit Climate Dashboard Deutschland",24,height-27);
  return canvas;
}
function chartExport(chart,title,subtitle){
  if(!chart)throw Error("Das Diagramm ist noch nicht verfügbar.");
  const original=chart.canvas,ratio=original.width/original.height;
  const w=1280,h=Math.round(Math.max(480,Math.min(820,1200/ratio)))+148;
  return stampCanvas(document.createElement("canvas"),w,h,title,subtitle,
    (ctx,x,y,availW,availH)=>{ctx.drawImage(original,x,y,availW,availH);});
}
function heatmapExport(){
  // Always render a light, fully annotated, high-resolution image independent of app theme.
  const years=Object.keys(doc.years).map(Number).sort((a,b)=>a-b);
  const cell=3,rowHeight=13,left=52,top=104,plotWidth=366*cell;
  const width=1240,height=top+years.length*rowHeight+115;
  const canvas=document.createElement("canvas");
  canvas.width=width*2;canvas.height=height*2;
  const ctx=canvas.getContext("2d");ctx.scale(2,2);
  ctx.fillStyle="#fff";ctx.fillRect(0,0,width,height);
  ctx.fillStyle="#20384f";ctx.font="bold 23px Arial";
  ctx.fillText("Arktis >80°N · historische Extremtage 1958–"+years.at(-1),22,34);
  ctx.font="12px Arial";ctx.fillStyle="#556b7d";ctx.fillText("P10/P90 je Kalendertag · feste Referenz 1958–2002 · DMI/ECMWF-Index",22,58);
  const legend=[["Über P90",colors.warm],["Unter P10",colors.cold],["P10–P90",colors.neutral],["Fehlend",colors.missing]];
  legend.forEach(([label,color],j)=>{
    const x=23+j*155;ctx.fillStyle=color;ctx.fillRect(x,70,14,10);
    ctx.fillStyle="#20384f";ctx.font="12px Arial";ctx.fillText(label,x+20,80);
  });
  ctx.font="10px Arial";ctx.textBaseline="middle";
  for(let m=1;m<=12;m++){
    const index=doc.days.indexOf(String(m).padStart(2,"0")+"-01");
    ctx.fillStyle="#54697a";ctx.fillText(monthNames[m-1],left+index*cell+1,94);
  }
  for(let j=0;j<years.length;j++){
    const y=years[j],series=doc.years[String(y)]||[];
    const yy=top+j*rowHeight;
    ctx.fillStyle="#455c70";ctx.fillText(String(y),12,yy+5.4);
    for(let i=0;i<366;i++){
      ctx.fillStyle=colors[kind(series[i],results.reference.p10[i],results.reference.p90[i])]||colors.missing;
      ctx.fillRect(left+i*cell,yy,cell,11);
    }
  }
  const bottom=top+years.length*rowHeight;
  ctx.strokeStyle="rgba(40,65,85,.25)";ctx.lineWidth=.6;
  for(let m=2;m<=12;m++){
    const index=doc.days.indexOf(String(m).padStart(2,"0")+"-01");
    ctx.beginPath();ctx.moveTo(left+index*cell,top);ctx.lineTo(left+index*cell,bottom);ctx.stroke();
  }
  ctx.textBaseline="alphabetic";ctx.fillStyle="#556b7d";ctx.font="12px Arial";
  ctx.fillText("Jedes Feld = ein Kalendertag. 29. Februar nur in Schaltjahren.",22,bottom+28);
  ctx.fillText(meta,22,bottom+50);
  ctx.fillText("Quelle: DMI / ECMWF · Datenstand "+doc.last_date+" · Climate Dashboard Deutschland",22,bottom+68);
  return canvas;
}
function pdfPages(canvases,title,name){
  const PDF=window.jspdf?.jsPDF;
  if(!PDF){$("arcticLongTermLoad").textContent="PDF-Bibliothek nicht geladen. Bitte Seite neu laden.";return;}
  const pdf=new PDF({orientation:"landscape",unit:"mm",format:"a4"});
  canvases.forEach((canvas,i)=>{
    if(i)pdf.addPage();
    const img=canvas.toDataURL("image/png");
    const width=270,height=canvas.height/canvas.width*width;
    const scale=Math.min(1,177/height);
    pdf.addImage(img,"PNG",12,13,width*scale,height*scale);
    pdf.setFontSize(8);pdf.setTextColor(70,86,99);
    pdf.text(title+" · Seite "+(i+1)+"/"+canvases.length+" · "+doc.last_date,12,200);
  });
  pdf.save(name);
}
function combineCanvases(canvases){
  const width=Math.max(...canvases.map(c=>c.width)),height=canvases.reduce((sum,c)=>sum+c.height,0)+24*(canvases.length-1);
  const output=document.createElement("canvas");output.width=width;output.height=height;
  const ctx=output.getContext("2d");ctx.fillStyle="#fff";ctx.fillRect(0,0,width,height);
  let top=0;
  for(const c of canvases){ctx.drawImage(c,(width-c.width)/2,top);top+=c.height+24;}
  return output;
}
function tableCanvas(title,subtitle,columns,rows){
  const width=1280,height=Math.max(430,178+rows.length*30);
  return stampCanvas(document.createElement("canvas"),width,height,title,subtitle,
    (ctx,x,y,availW)=>{
      const widths=columns.map((_,i)=>i?120:170);
      ctx.font="bold 15px Arial";ctx.fillStyle="#20384f";
      let offset=0;
      columns.forEach((c,i)=>{ctx.fillText(c,x+offset,y+10);offset+=widths[i];});
      ctx.strokeStyle="#b9c6d2";ctx.beginPath();ctx.moveTo(x,y+19);
      ctx.lineTo(x+availW,y+19);ctx.stroke();
      ctx.font="14px Arial";
      rows.forEach((row,j)=>{
        ctx.fillStyle=j%2===0?"#f3f6f8":"#fff";
        ctx.fillRect(x,y+26+j*30,availW,28);
        ctx.fillStyle="#263d51";let xx=0;
        row.forEach((value,i)=>{ctx.fillText(String(value),x+xx+4,y+46+j*30);xx+=widths[i];});
      });
    });
}
function decadeExport(){
  const from=Number($("arcticTrendFrom").value),to=Number($("arcticTrendTo").value);
  const rows=results.decades.map(d=>({
    name:d.decade+"er",
    selected:rowSet().filter(r=>Math.floor(r.year/10)*10===d.decade)
  })).filter(d=>d.selected.length).map(d=>{
    const sample=d.selected,n=sample.length,avg=key=>sample.reduce((sum,r)=>sum+r[key],0)/n;
    return [d.name,n,fmt(avg("warmDays")),fmt(avg("coldDays")),fmt(avg("maxWarm")),fmt(avg("maxCold"))];
  });
  return tableCanvas("Arktis: Dekadenmittel der Extremtage","Nur vollständige Jahre · Zeitraum "+Math.min(from,to)+"–"+Math.max(from,to),
    ["Dekade","Jahre","Ø warm","Ø kalt","Ø warm Folge","Ø kalt Folge"],rows);
}
function seasonRankingExport(){
  const season=seasonKey(),label=periodDefs[season].name,all=seasonalRows();
  const warm=seasonalRank(all,"warm",0).sorted.slice(0,12),
    cold=seasonalRank(all,"cold",0).sorted.slice(0,12);
  const columns=["Rang","Jahr","Warmtage","Längste Folge","Jahr","Kalttage","Längste Folge"];
  const rows=Array.from({length:Math.max(warm.length,cold.length)},(_,i)=>[
    i+1,warm[i]?.year??"–",warm[i]?.warm??"–",warm[i]?.longestWarm??"–",
    cold[i]?.year??"–",cold[i]?.cold??"–",cold[i]?.longestCold??"–"]);
  return tableCanvas("Arktis: saisonale Rekordranglisten",label+" · nur vollständige Perioden · Referenz 1958–2002",
    columns,rows);
}
function summaryExport(mode){
  const rows=rowSet(),caption=rows.length?rows[0].year+"–"+rows.at(-1).year:"keine vollständigen Jahre";
  const first=chartExport(frequencyChart,"Arktis: ungewöhnlich warme und kalte Tage",caption+" · Vollständige Jahre · P10/P90 1958–2002");
  const second=chartExport(durationChart,"Arktis: längste jährliche Extremfolgen",caption+" · Vollständige Jahre · P10/P90 1958–2002");
  const decades=decadeExport();
  if(mode==="pdf")pdfPages([first,second,decades],"Langzeitstatistik","Arktis_80N_Langzeitstatistik.pdf");
  else saveCanvas(combineCanvases([first,second,decades]),"Arktis_80N_Langzeitstatistik.png");
}
function seasonExport(mode){
  const label=periodDefs[seasonKey()].name;
  const chart=chartExport(seasonChart,"Arktis: Extremtage nach Jahreszeit",label+" · Vollständige Perioden · P10/P90 1958–2002");
  const ranks=seasonRankingExport();
  if(mode==="pdf")pdfPages([chart,ranks],"Saisonstatistik","Arktis_80N_Saison_"+seasonKey()+".pdf");
  else saveCanvas(combineCanvases([chart,ranks]),"Arktis_80N_Saison_"+seasonKey()+".png");
}
function init(){
  if(!$("arcticLongTermLoad"))return;
  for(const id of ["arcticTrendFrom","arcticTrendTo","arcticTrendLines"])
    $(id).addEventListener("change",renderTrend);
  $("arcticSeasonChoose").addEventListener("change",renderSeason);
  $("arcticYear").addEventListener("change",renderSeason);
  const bindings=[
    ["arcticTrendPng",()=>summaryExport("png")],["arcticTrendPdf",()=>summaryExport("pdf")],
    ["arcticSeasonPng",()=>seasonExport("png")],["arcticSeasonPdf",()=>seasonExport("pdf")],
    ["arcticHeatmapPng",()=>saveCanvas(heatmapExport(),"Arktis_80N_Extremtage_Heatmap.png")],
    ["arcticHeatmapPdf",()=>pdfPages([heatmapExport()],"Historische Extremtage","Arktis_80N_Extremtage_Heatmap.pdf")],
    ["arcticAnnualStatsCsv",()=>saveBlob(csvAnnual(),"Arktis_80N_Jahresstatistik.csv","text/csv;charset=utf-8")],
    ["arcticSeasonCsv",()=>saveBlob(csvSeasons(),"Arktis_80N_Saisonstatistik.csv","text/csv;charset=utf-8")],
    ["arcticEventsCsv",()=>saveBlob(csvSpells(),"Arktis_80N_Extremserien.csv","text/csv;charset=utf-8")],
    ["arcticHeatmapCsv",()=>saveBlob(csvHeatmap(),"Arktis_80N_Heatmap_Tageswerte.csv","text/csv;charset=utf-8")]
  ];
  for(const [id,cb] of bindings)
    $(id).addEventListener("click",()=>{if(results)try{cb();}catch(err){
      console.error("DMI download",err);
      $("arcticLongTermLoad").textContent="Exportfehler: "+err.message;
    }});
  window.addEventListener("arctic80:data-ready",event=>accept(event.detail));
  if(window.Arctic80LoadedData)accept(window.Arctic80LoadedData);
  else $("arcticLongTermLoad").textContent="Lade Langzeit- und Saisonstatistiken …";
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});else init();
})();
