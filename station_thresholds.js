(() => {
  "use strict";
  const DIR = "station_threshold_daily/";
  const MISSING = -32768;
  const cache = new Map();
  let chart = null;
  let lastAnalysis = null;
  let sequence = 0;
  const fmt = new Intl.DateTimeFormat("de-DE", {day:"2-digit",month:"2-digit",year:"numeric",timeZone:"UTC"});

  function iso(d) { return d.toISOString().slice(0,10); }
  function utc(dateText) { return new Date(dateText+"T00:00:00Z"); }
  function advance(d) { return new Date(d.getTime()+86400000); }
  function dayIndex(d) {
    return Math.round((d - Date.UTC(d.getUTCFullYear(),0,1))/86400000);
  }
  function periodBounds(year,season) {
    const p = {
      spring:[3,1,5,31,0],summer:[6,1,8,31,0],
      autumn:[9,1,11,30,0],winter:[12,1,2,0,1],
      year:[1,1,12,31,0]
    }[season];
    if (!p) return null;
    const start = new Date(Date.UTC(year,p[0]-1,p[1]));
    const end = season==="winter" ? new Date(Date.UTC(year+1,2,0)) :
      new Date(Date.UTC(year,p[2]-1,p[3]));
    return {start,end};
  }
  function humanDate(s) { return fmt.format(utc(s)); }
  function htmlEscape(s) {
    return String(s).replace(/[&<>"']/g,function(c){
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
    });
  }
  function install() {
    const parent=document.getElementById("stationClimateDaysSummary");
    if (!parent || document.getElementById("stationThresholdPanel")) return;
    const section=document.createElement("section");
    section.id="stationThresholdPanel";
    section.className="chart-container auto";
    section.style.cssText="padding:18px;margin:16px 0;border:1px solid #d9e2ea;border-radius:10px;background:#fff";
    section.innerHTML=
      '<h2 style="margin:0 0 5px">Schwellenwertanalyse · Temperaturfolgen</h2>'+
      '<p class="note" style="margin:0 0 14px">Wann trat an der gewählten DWD-Station ein bestimmter Schwellenwert erstmals an mehreren aufeinanderfolgenden Tagen auf?</p>'+
      '<div class="controls" style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end">'+
      '<label class="control-group">Parameter<select id="stationThresholdMetric"><option value="0">Tmax (TXK)</option><option value="1">Tmin (TNK)</option><option value="2">Tmittel (TMK)</option></select></label>'+
      '<label class="control-group">Bedingung<select id="stationThresholdOperator"><option value="lt">unter (&lt;)</option><option value="le">höchstens (≤)</option><option value="gt">über (&gt;)</option><option value="ge">mindestens (≥)</option></select></label>'+
      '<label class="control-group">Schwellenwert (°C)<input id="stationThresholdValue" type="number" min="-50" max="50" step="0.1" value="18" style="width:100px"></label>'+
      '<label class="control-group">Tage in Folge<input id="stationThresholdDays" type="number" min="1" max="60" step="1" value="3" style="width:80px"></label>'+
      '<label class="control-group">Zeitraum<select id="stationThresholdSeason"><option value="autumn">Herbst (Sep–Nov)</option><option value="spring">Frühling (Mär–Mai)</option><option value="summer">Sommer (Jun–Aug)</option><option value="winter">Winter (Dez–Feb)</option><option value="year">Kalenderjahr</option></select></label>'+
      '<button id="stationThresholdRun" class="action" type="button">Auswerten</button></div>'+
      '<div id="stationThresholdStatus" role="status" style="font-size:13px;color:#52606d;margin:12px 0">Station auswählen und auf „Auswerten“ klicken. Historische Tagesdaten werden bei Bedarf geladen.</div>'+
      '<div id="stationThresholdResults" hidden>'+
      '<div id="stationThresholdSummary" class="summary-box" style="margin:9px 0"></div>'+
      '<div style="position:relative;height:405px"><canvas id="stationThresholdChart"></canvas></div>'+
      '<div style="display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;margin:12px 0">'+
      '<button id="stationThresholdPNG" type="button" class="action">⬇ PNG</button>'+
      '<button id="stationThresholdPDF" type="button" class="action">⬇ PDF</button>'+
      '<button id="stationThresholdCSV" type="button" class="action">⬇ CSV</button></div>'+
      '<div class="table-wrap" style="max-height:320px;overflow:auto"><table id="stationThresholdTable"><thead><tr><th>Jahr</th><th>Erster Tag</th><th>Serienende</th><th>Bewertung</th></tr></thead><tbody></tbody></table></div>'+
      '<p class="note" style="margin-top:10px">Eine Serie zählt nur, wenn alle Tage den Grenzwert erfüllen. Fehlende Tageswerte unterbrechen die Folge. Ist vor einem gefundenen Ereignis ein Messwert unbekannt, wird das Jahr nicht als gesicherter erster Termin gewertet. Winter zählt zum Dezemberjahr. Laufende Zeiträume sind vorläufig. Stationen können Standortwechsel aufweisen.</p>'+
      '</div>';
    parent.insertAdjacentElement("afterend",section);
    document.getElementById("stationThresholdRun").addEventListener("click",run);
    document.getElementById("stationThresholdPNG").addEventListener("click",exportPng);
    document.getElementById("stationThresholdPDF").addEventListener("click",exportPdf);
    document.getElementById("stationThresholdCSV").addEventListener("click",exportCsv);
    document.getElementById("stationClimateDaysStationSelect").addEventListener("change",function(){
      sequence++;
      document.getElementById("stationThresholdResults").hidden=true;
      document.getElementById("stationThresholdStatus").textContent="Andere Station ausgewählt. Bitte neu auswerten.";
      lastAnalysis=null;
    });
  }
  async function decodeHistory(doc) {
    if(doc.format!=="dwd-tx-tn-tm-zlib16-v1" || !Array.isArray(doc.years) || !doc.data)
      throw new Error("Nicht unterstütztes Temperaturarchiv.");
    if(typeof DecompressionStream==="undefined") throw new Error("Dieser Browser unterstützt die komprimierten DWD-Daten nicht.");
    const binary=atob(doc.data);
    const packed=Uint8Array.from(binary,function(c){return c.charCodeAt(0);});
    const unpacked=await new Response(new Blob([packed]).stream().pipeThrough(new DecompressionStream("deflate"))).arrayBuffer();
    const expected=doc.years.length*366*3*2;
    if(unpacked.byteLength!==expected) throw new Error("Archivlänge ist inkonsistent.");
    const view=new DataView(unpacked);
    const years=new Map();
    doc.years.forEach(function(year,i){
      const arr=new Int16Array(366*3);
      const offset=i*366*3;
      for(let k=0;k<arr.length;k++)arr[k]=view.getInt16((offset+k)*2,true);
      years.set(Number(year),arr);
    });
    return years;
  }
  async function loadHistory(id) {
    if(cache.has(id)) return cache.get(id);
    const promise=(async function(){
      const response=await fetch(DIR+encodeURIComponent(id)+".json",{cache:"force-cache"});
      if(!response.ok) {
        if(response.status===404) throw new Error("Das historische Tagesarchiv wird noch aufgebaut. Nach dem DWD-Backfill erneut versuchen.");
        throw new Error("Tagesarchiv HTTP "+response.status);
      }
      const json=await response.json();
      if(String(json.station_id)!==String(id))throw new Error("Stations-ID im Archiv stimmt nicht überein.");
      return decodeHistory(json);
    })();
    cache.set(id,promise);
    try{return await promise;}catch(err){cache.delete(id);throw err;}
  }
  function tempAt(history,station,day,metric) {
    const year=day.getUTCFullYear();
    const archive=history.get(year);
    if(archive) {
      const value=archive[dayIndex(day)*3+metric];
      return value===MISSING?null:value;
    }
    if(year===Number(stationClimateDaysIndex.current_year)) {
      const pair=stationClimateDaysPair(station,iso(day));
      const value=pair && pair[2+metric];
      return Number.isFinite(value)?value:null;
    }
    return null;
  }
  function meets(value,operator,threshold) {
    if(operator==="lt")return value<threshold;
    if(operator==="le")return value<=threshold;
    if(operator==="gt")return value>threshold;
    return value>=threshold;
  }
  function evaluate(history,station,year,cfg) {
    const bounds=periodBounds(year,cfg.season);
    const latest=stationClimateDaysIndex.data_through;
    const isCurrent=Number(stationClimateDaysIndex.current_year);
    const limit=utc(latest);
    const end=bounds.end>limit?limit:bounds.end;
    if(end<bounds.start) return {year,status:"ausstehend"};
    let count=0,hadGap=false,days=0,valid=0;
    for(let day=bounds.start;day<=end;day=advance(day)) {
      days++;
      const v=tempAt(history,station,day,cfg.metric);
      if(v===null) {
        hadGap=true;
        count=0;
        continue;
      }
      valid++;
      count=meets(v,cfg.operator,cfg.threshold)?count+1:0;
      if(count>=cfg.days) {
        const first=new Date(day.getTime()-(cfg.days-1)*86400000);
        if(hadGap) return {year,status:"unvollständig",valid,days};
        return {year,status:"gefunden",first:iso(first),last:iso(day),
          doy:Math.round((first-bounds.start)/86400000),valid,days,
          provisional:bounds.end>limit};
      }
    }
    if(hadGap) return {year,status:"unvollständig",valid,days};
    if(bounds.end>limit) return {year,status:"laufend",valid,days};
    return {year,status:"keine Serie",valid,days};
  }
  function readConfig(){
    const threshold=Number(document.getElementById("stationThresholdValue").value);
    const days=Number(document.getElementById("stationThresholdDays").value);
    if(!Number.isFinite(threshold)||threshold<-50||threshold>50||!Number.isInteger(days)||days<1||days>60)
      throw new Error("Bitte Schwellenwert zwischen −50 und 50 °C und 1–60 ganze Tage wählen.");
    return {metric:Number(document.getElementById("stationThresholdMetric").value),
      operator:document.getElementById("stationThresholdOperator").value,
      threshold:Math.round(threshold*10),days:days,
      season:document.getElementById("stationThresholdSeason").value};
  }
  function average(a){return a.reduce(function(s,v){return s+v;},0)/a.length;}
  function median(a){if(!a.length)return null;const b=a.slice().sort(function(x,y){return x-y;});const mid=Math.floor(b.length/2);return b.length%2?b[mid]:(b[mid-1]+b[mid])/2;}
  function regression(points){
    if(points.length<8)return null;
    const mx=average(points.map(function(x){return x.year;}));
    const my=average(points.map(function(x){return x.doy;}));
    const denominator=points.reduce(function(s,p){return s+(p.year-mx)**2;},0);
    if(!denominator)return null;
    const slope=points.reduce(function(s,p){return s+(p.year-mx)*(p.doy-my);},0)/denominator;
    return {slope:slope,intercept:my-slope*mx};
  }
  function dayLabel(offset,season){
    const anchors={spring:"2001-03-01",summer:"2001-06-01",autumn:"2001-09-01",winter:"1999-12-01",year:"2001-01-01"};
    const d=new Date(utc(anchors[season]).getTime()+Math.round(offset)*86400000);
    return String(d.getUTCDate()).padStart(2,"0")+"."+String(d.getUTCMonth()+1).padStart(2,"0")+".";
  }
  function setStatus(s){document.getElementById("stationThresholdStatus").textContent=s;}
  async function run(){
    const token=++sequence;
    let cfg;
    try{cfg=readConfig();}catch(e){setStatus(e.message);return;}
    if(!stationClimateDaysIndex){setStatus("Bitte zuerst die Stations-Kenntage laden.");return;}
    const id=document.getElementById("stationClimateDaysStationSelect").value;
    const station=stationClimateDaysIndex.stations.find(function(s){return s.id===id;});
    if(!station){setStatus("Bitte eine DWD-Station wählen.");return;}
    const button=document.getElementById("stationThresholdRun");
    button.disabled=true;setStatus("Historische Temperaturwerte für "+station.name+" werden geladen …");
    try{
      const [history]=await Promise.all([loadHistory(id),loadStationClimateDaysCurrentMonths()]);
      if(token!==sequence)return;
      const first=Number(station.start_year)||1881;
      const last=Number(stationClimateDaysIndex.current_year);
      const rows=[];
      for(let y=first;y<=last;y++)rows.push(evaluate(history,id,y,cfg));
      const points=rows.filter(function(r){return r.status==="gefunden";});
      const finished=points.filter(function(r){return !r.provisional;});
      const reference=finished.filter(function(r){return r.year>=1991&&r.year<=2020;});
      const trend=regression(finished);
      lastAnalysis={station,cfg,rows,points,reference,trend};
      draw(lastAnalysis);
      const complete=rows.filter(function(r){return ["gefunden","keine Serie"].includes(r.status);}).length;
      setStatus(rows.length+" Jahre geprüft · "+complete+" mit eindeutig auswertbarer Ereignisfrage · "+
        points.length+" gefundene Serien · Daten bis "+humanDate(stationClimateDaysIndex.data_through)+".");
      document.getElementById("stationThresholdResults").hidden=false;
    }catch(e){
      if(token===sequence){setStatus("Auswertung nicht verfügbar: "+e.message);document.getElementById("stationThresholdResults").hidden=true;}
    }finally{if(token===sequence)button.disabled=false;}
  }
  function draw(result) {
    const {station,cfg,rows,points,reference,trend}=result;
    const stat=document.getElementById("stationThresholdSummary");
    const med=median(reference.map(function(r){return r.doy;}));
    const series=points.filter(function(x){return !x.provisional;});
    const earliest=series.slice().sort(function(a,b){return a.doy-b.doy;})[0];
    const latest=series.slice().sort(function(a,b){return b.doy-a.doy;})[0];
    const labels=["Tmax","Tmin","Tmittel"];
    const ops={lt:"<",le:"≤",gt:">",ge:"≥"};
    const seasonLabels={autumn:"Herbst",spring:"Frühling",summer:"Sommer",winter:"Winter",year:"Kalenderjahr"};
    const header=labels[cfg.metric]+" "+ops[cfg.operator]+" "+(cfg.threshold/10).toLocaleString("de-DE")+" °C · "+cfg.days+" Tage in Folge · "+seasonLabels[cfg.season];
    const trendText=trend ? (trend.slope*10).toLocaleString("de-DE",{maximumFractionDigits:1,minimumFractionDigits:1})+" Tage/Dekade" : "nicht ausreichend Daten";
    stat.innerHTML="<strong>"+htmlEscape(station.name)+"</strong> · "+htmlEscape(header)+
      "<div style='margin-top:8px'>Median 1991–2020: <strong>"+(med===null?"–":dayLabel(med,cfg.season))+
      "</strong> ("+reference.length+" Jahre) · Linearer Trend: <strong>"+trendText+"</strong></div>"+
      "<div style='margin-top:5px'>Frühester Beginn: <strong>"+(earliest?humanDate(earliest.first):"–")+
      "</strong> · Spätester Beginn: <strong>"+(latest?humanDate(latest.first):"–")+"</strong></div>";
    if(chart){chart.destroy();chart=null;}
    const data=[{type:"scatter",label:"Erster Schwellenwerttermin",data:points.map(function(r){return {x:r.year,y:r.doy,record:r};}),
      pointRadius:4.2,pointHoverRadius:7,backgroundColor:"#1769c2",borderColor:"#1769c2"}];
    if(trend&&series.length>=8){
      const x0=Math.min.apply(null,series.map(function(p){return p.year;}));
      const x1=Math.max.apply(null,series.map(function(p){return p.year;}));
      data.push({type:"line",label:"Linearer Trend",data:[{x:x0,y:trend.slope*x0+trend.intercept},{x:x1,y:trend.slope*x1+trend.intercept}],
        borderColor:"#c0392b",borderWidth:2,pointRadius:0,fill:false});
    }
    if(med!==null&&points.length){
      const x0=rows[0].year,x1=rows[rows.length-1].year;
      data.push({type:"line",label:"Median 1991–2020",data:[{x:x0,y:med},{x:x1,y:med}],
        borderColor:"#64748b",borderDash:[6,5],borderWidth:1.4,pointRadius:0});
    }
    const totalDays=Math.round((periodBounds(2001,cfg.season).end-periodBounds(2001,cfg.season).start)/86400000)+1;
    chart=new Chart(document.getElementById("stationThresholdChart"),{
      type:"scatter",data:{datasets:data},
      options:{responsive:true,maintainAspectRatio:false,animation:false,parsing:false,
        scales:{x:{type:"linear",title:{display:true,text:"Jahr"},ticks:{precision:0,maxTicksLimit:14}},
          y:{min:0,max:Math.max(totalDays-1,...points.map(function(r){return r.doy;})),
            reverse:true,title:{display:true,text:"Datum des ersten Auftretens"},
            ticks:{stepSize:10,callback:function(value){return dayLabel(value,cfg.season);}}}},
        plugins:{legend:{display:true,position:"bottom"},
          tooltip:{callbacks:{title:function(items){const p=items[0]&&items[0].raw;return p&&p.record?String(p.record.year):"";},
            label:function(ctx){return ctx.raw.record?"Beginn "+humanDate(ctx.raw.record.first)+(ctx.raw.record.provisional?" (vorläufig)":""):ctx.dataset.label;}}}}}
    });
    document.querySelector("#stationThresholdTable tbody").innerHTML=
      rows.map(function(r){return "<tr><td>"+r.year+"</td><td>"+(r.first?humanDate(r.first):"–")+
        "</td><td>"+(r.last?humanDate(r.last):"–")+"</td><td>"+r.status+(r.provisional?" (vorläufig)":"")+"</td></tr>";}).join("");
  }
  function filename(){const x=lastAnalysis;return "dwd_schwellenwert_"+x.station.id+"_"+x.cfg.season+"_"+x.cfg.metric+"_"+x.cfg.days+"tage";}
  function download(blob,ext){
    const a=document.createElement("a");const url=URL.createObjectURL(blob);
    a.href=url;a.download=filename()+"."+ext;document.body.appendChild(a);a.click();a.remove();setTimeout(function(){URL.revokeObjectURL(url);},3000);
  }
  function exportPng(){
    if(!lastAnalysis||!chart)return;
    const canvas=document.createElement("canvas");
    canvas.width=1500;canvas.height=850;
    const ctx=canvas.getContext("2d");
    ctx.fillStyle="#fff";ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.fillStyle="#0f172a";ctx.font="bold 34px Arial";
    ctx.fillText("DWD-Stations-Schwellenwertanalyse",46,60);
    ctx.font="22px Arial";ctx.fillText(lastAnalysis.station.name+" · "+lastAnalysis.cfg.days+" Tage in Folge",46,97);
    ctx.drawImage(chart.canvas,40,130,1420,640);
    ctx.font="17px Arial";ctx.fillStyle="#64748b";
    ctx.fillText("Quelle: DWD CDC Tageswerte · Fehlende Tage unterbrechen Serien · vorläufige Daten gekennzeichnet",46,818);
    canvas.toBlob(function(blob){if(blob)download(blob,"png");},"image/png");
  }
  function exportPdf(){
    if(!lastAnalysis||!chart)return;
    if(!window.jspdf||!window.jspdf.jsPDF){setStatus("PDF-Bibliothek nicht verfügbar.");return;}
    const pdf=new window.jspdf.jsPDF({unit:"mm",format:"a4"});
    pdf.setFont("helvetica","bold");pdf.setFontSize(16);
    pdf.text("DWD - Stations-Schwellenwertanalyse",12,17);
    pdf.setFont("helvetica","normal");pdf.setFontSize(10);
    pdf.text(lastAnalysis.station.name+" / "+lastAnalysis.cfg.days+" Tage in Folge",12,25);
    pdf.addImage(chart.canvas.toDataURL("image/png"),"PNG",12,33,186,104);
    pdf.setFontSize(8);pdf.text("Quelle: DWD CDC Tageswerte; fehlende Werte unterbrechen Serien.",12,146);
    pdf.text("Trend: "+(lastAnalysis.trend?(lastAnalysis.trend.slope*10).toFixed(2)+" Tage/Dekade":"nicht ermittelbar"),12,153);
    let row=0;
    pdf.setFontSize(9);
    for(const r of lastAnalysis.rows){
      if(row%48===0){
        pdf.addPage();pdf.setFont("helvetica","bold");pdf.text("Jahr / Beginn / Serienende / Bewertung",12,16);pdf.setFont("helvetica","normal");
      }
      pdf.text(r.year+"     "+(r.first||"-")+"     "+(r.last||"-")+"     "+r.status,12,24+(row%48)*5.4);
      row++;
    }
    pdf.save(filename()+".pdf");
  }
  function exportCsv(){
    if(!lastAnalysis)return;
    const cfg=lastAnalysis.cfg;
    const rows=[["Station","Parameter","Schwellenwert C","Operator","Folgetage","Zeitraum","Jahr","Erster Tag","Ende","Status","Vorläufig"]];
    lastAnalysis.rows.forEach(function(r){rows.push([lastAnalysis.station.name,["TXK","TNK","TMK"][cfg.metric],
      String(cfg.threshold/10).replace(".",","),cfg.operator,cfg.days,cfg.season,r.year,r.first||"",r.last||"",r.status,r.provisional?"ja":"nein"]);});
    const csv="\uFEFF"+rows.map(function(r){return r.map(function(v){return '"'+String(v).replace(/"/g,'""')+'"';}).join(";");}).join("\r\n");
    download(new Blob([csv],{type:"text/csv;charset=utf-8"}),"csv");
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install);
  else install();
})();
