(() => {
  "use strict";
  const DIR = "station_threshold_daily/";
  const MISSING = -32768;
  const cache = new Map();
  let chart = null;
  let lastAnalysis = null;
  let sequence = 0;
  let yearView = "recent";
  let customStartYear = null;
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
    if (!document.getElementById("stationThresholdStyle")) {
      const style=document.createElement("style");
      style.id="stationThresholdStyle";
      style.textContent=[
        ".station-threshold-view-tools{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin:15px 0 9px}",
        ".station-threshold-range{display:flex;gap:0;border:1px solid #cbd5df;border-radius:8px;overflow:hidden}",
        ".station-threshold-range button{padding:8px 12px;background:#fff;border:0;border-right:1px solid #cbd5df;color:#334155;font-weight:700;cursor:pointer}",
        ".station-threshold-range button:last-child{border-right:0}",
        ".station-threshold-range button.active{background:#10213d;color:#fff}",
        ".station-threshold-options{display:flex;align-items:center;gap:14px;flex-wrap:wrap;color:#334155;font-size:13px}",
        ".station-threshold-options label{display:flex;align-items:center;gap:5px;cursor:pointer;white-space:nowrap}",
        ".station-threshold-options input{accent-color:#2563a9}",
        ".station-threshold-view-note{font-size:12px;color:#64748b;margin:3px 0 11px}",
        ".station-threshold-year-box{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:10px 12px;border:1px solid #d9e2ea;background:#f8fafc;border-radius:8px}",
        ".station-threshold-year-box label{display:flex;align-items:center;gap:7px;font-size:12px;color:#475569;font-weight:700}",
        ".station-threshold-year-box input{width:92px;border:1px solid #bdc9d4;border-radius:6px;padding:7px;font:inherit;color:#172033;background:#fff}",
        ".station-threshold-year-box input:focus{outline:2px solid #90b8df}",
        ".station-threshold-year-box input.active{border-color:#2b6fac;box-shadow:0 0 0 2px rgba(43,111,172,.15)}",
        ".station-threshold-range button:disabled{opacity:.5;cursor:not-allowed}",
        ".station-threshold-year-hint{font-size:11px;color:#64748b;flex-basis:100%}",
        "@media(max-width:700px){.station-threshold-range{width:100%}.station-threshold-range button{flex:1;padding:9px 6px;font-size:12px}}"
      ].join("");
      document.head.appendChild(style);
    }
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
      '<div class="station-threshold-view-tools">'+
      '<div class="station-threshold-range" role="group" aria-label="Angezeigte Jahre"><button id="stationThresholdRecent" class="active" type="button" aria-pressed="true">Letzte 40 Jahre</button><button id="stationThresholdAll" type="button" aria-pressed="false">Gesamte Messreihe</button></div>'+
      '<div class="station-threshold-options"><label><input id="stationThresholdTrend" type="checkbox" checked> Trendlinie</label><label><input id="stationThresholdMedian" type="checkbox" checked> Median 1991–2020</label><label><input id="stationThresholdExtremes" type="checkbox"> Extremjahre markieren</label></div></div>'+
      '<div class="station-threshold-year-box"><button id="stationThresholdComplete" class="action" type="button" aria-pressed="false" disabled>Ab lückenloser Messreihe</button><label for="stationThresholdStartYear">Oder Startjahr selbst wählen: <input id="stationThresholdStartYear" type="number" step="1" inputmode="numeric" placeholder="z. B. 1950" aria-label="Eigenes Startjahr"></label><span id="stationThresholdYearHint" class="station-threshold-year-hint">Vollständige Jahre werden für den gewählten Zeitraum und Temperaturparameter geprüft.</span></div>'+
      '<div id="stationThresholdViewNote" class="station-threshold-view-note"></div>'+
      '<div style="position:relative;height:340px"><canvas id="stationThresholdChart"></canvas></div>'+
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
    document.getElementById("stationThresholdRecent").addEventListener("click",function(){setYearView("recent");});
    document.getElementById("stationThresholdAll").addEventListener("click",function(){setYearView("all");});
    document.getElementById("stationThresholdComplete").addEventListener("click",function(){setYearView("complete");});
    document.getElementById("stationThresholdStartYear").addEventListener("change",function(event){
      const entered=Number(event.target.value);
      if(event.target.value.trim()===""){customStartYear=null;setYearView("recent");return;}
      if(!Number.isInteger(entered)){setStatus("Bitte ein gültiges Startjahr eingeben.");return;}
      customStartYear=entered;
      setYearView("custom");
    });
    ["stationThresholdTrend","stationThresholdMedian","stationThresholdExtremes"].forEach(function(id){
      document.getElementById(id).addEventListener("change",function(){if(lastAnalysis)draw(lastAnalysis);});
    });
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
    const anchors={spring:"2001-03-01",summer:"2001-06-01",autumn:"2001-09-01",winter:"2001-12-01",year:"2001-01-01"};
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
      const completeRange=completeObservationYears(history,id,cfg,rows);
      lastAnalysis={station,cfg,rows,points,reference,trend,completeRange};
      if(yearView==="complete"&&!completeRange)yearView="recent";
      syncYearControls(lastAnalysis);
      draw(lastAnalysis);
      const complete=rows.filter(function(r){return ["gefunden","keine Serie"].includes(r.status);}).length;
      setStatus(rows.length+" Jahre geprüft · "+complete+" mit eindeutig auswertbarer Ereignisfrage · "+
        points.length+" gefundene Serien · Daten bis "+humanDate(stationClimateDaysIndex.data_through)+".");
      document.getElementById("stationThresholdResults").hidden=false;
    }catch(e){
      if(token===sequence){setStatus("Auswertung nicht verfügbar: "+e.message);document.getElementById("stationThresholdResults").hidden=true;}
    }finally{if(token===sequence)button.disabled=false;}
  }
  function completeObservationYears(history,station,cfg,rows) {
    // 100 % der Tage im gewählten Zeitfenster müssen für TXK/TNK/TMK
    // vorliegen. Ein Ereignisfund allein genügt für diese Prüfung nicht.
    const through=utc(stationClimateDaysIndex.data_through);
    const complete=[];
    for(const row of rows) {
      const bounds=periodBounds(row.year,cfg.season);
      if(bounds.end>through)continue; // laufende Jahreszeit nicht als vollständig werten
      let valid=true;
      for(let day=bounds.start;day<=bounds.end;day=advance(day)) {
        if(!Number.isFinite(tempAt(history,station,day,cfg.metric))){
          valid=false;
          break;
        }
      }
      if(valid)complete.push(row.year);
    }
    if(!complete.length)return null;
    // Wähle die längste lückenlose Folge vollständig beobachteter Jahre.
    // Bei Gleichstand hat die jüngere Reihe Vorrang.
    let candidate=null,first=complete[0],last=first;
    function consider() {
      const run={first:first,last:last,years:last-first+1};
      if(!candidate||run.years>candidate.years||(run.years===candidate.years&&run.last>candidate.last))candidate=run;
    }
    for(let i=1;i<complete.length;i++) {
      const year=complete[i];
      if(year===last+1)last=year;
      else {consider();first=last=year;}
    }
    consider();
    return candidate;
  }

  function syncYearControls(result) {
    const complete=result&&result.completeRange;
    const button=document.getElementById("stationThresholdComplete");
    button.disabled=!complete;
    button.textContent=complete
      ?"Lückenlose Jahre: "+complete.first+"–"+complete.last
      :"Keine lückenlose Reihe verfügbar";
    const custom=document.getElementById("stationThresholdStartYear");
    const first=result.rows[0]?.year, last=result.rows[result.rows.length-1]?.year;
    custom.min=String(first);custom.max=String(last);
    if(customStartYear!==null) {
      customStartYear=Math.min(last,Math.max(first,customStartYear));
      custom.value=String(customStartYear);
    }
    custom.classList.toggle("active",yearView==="custom");
    for(const name of ["recent","all","complete"]){
      const id=name==="recent"?"stationThresholdRecent":name==="all"?"stationThresholdAll":"stationThresholdComplete";
      const el=document.getElementById(id);
      el.classList.toggle("active",name===yearView);
      el.setAttribute("aria-pressed",String(name===yearView));
    }
    const hint=document.getElementById("stationThresholdYearHint");
    hint.textContent=complete
      ?"Automatisch: längste zusammenhängende Folge mit 100 % gültigen Tageswerten je "+(result.cfg.season==="year"?"Jahr":"Jahreszeit")+" ("+["Tmax","Tmin","Tmittel"][result.cfg.metric]+"). Fehlende Tage schließen ein Jahr aus."
      :"Keine vollständig beobachteten Jahre im gewählten Zeitraum für diesen Temperaturparameter. Eigenes Startjahr bleibt möglich.";
  }

  function setYearView(view) {
    if(view==="complete"&&!lastAnalysis?.completeRange)return;
    yearView=["all","complete","custom"].includes(view)?view:"recent";
    if(yearView!=="custom") {
      customStartYear=null;
      document.getElementById("stationThresholdStartYear").value="";
    }
    if(lastAnalysis){syncYearControls(lastAnalysis);draw(lastAnalysis);}
  }

  function chartOptionsEnabled(id) {
    return !!document.getElementById(id)?.checked;
  }

  function selectedYearRange(rows) {
    const years=rows.map(function(row){return row.year;});
    if(!years.length)return {first:1900,last:2026};
    const last=years[years.length-1];
    if(yearView==="all")return {first:years[0],last:last};
    if(yearView==="complete"&&lastAnalysis?.completeRange)return {
      first:lastAnalysis.completeRange.first,
      last:lastAnalysis.completeRange.last
    };
    if(yearView==="custom"&&Number.isInteger(customStartYear))return {
      first:Math.min(last,Math.max(years[0],customStartYear)),last:last
    };
    return {first:Math.max(years[0],last-39),last:last};
  }

  function chartCalendarTicks(season,minDay,maxDay) {
    const bounds=periodBounds(2001,season);
    const span=maxDay-minDay;
    const ticks=[];
    const add=function(index){
      if(index>=minDay && index<=maxDay && !ticks.includes(index))ticks.push(index);
    };
    // Auch die Pufferzone vor und nach dem eigentlichen Zeitraum
    // berücksichtigen: dort liegen ggf. 15.02. / 01.06. usw.
    for(let i=Math.floor(minDay);i<=Math.ceil(maxDay);i++){
      const day=new Date(bounds.start.getTime()+i*86400000);
      if(day.getUTCDate()===1 ||
        (season!=="year" && day.getUTCDate()===15))add(i);
    }
    if(span<=28){
      for(let i=Math.ceil(minDay/7)*7;i<=maxDay;i+=7)add(i);
    }
    // In sehr engen Ausschnitten weiterhin ausreichend Datumsmarken.
    if(ticks.length<3){
      const step=Math.max(1,Math.round(span/3));
      for(let i=Math.ceil(minDay);i<=maxDay;i+=step)add(i);
    }
    return ticks.sort(function(a,b){return a-b;});
  }

  function stationThresholdYRange(datasets,season) {
    const bounds=periodBounds(2001,season);
    const seasonEnd=Math.round((bounds.end-bounds.start)/86400000);
    const values=datasets.flatMap(function(ds){
      return (ds.data||[]).map(function(point){return point&&point.y;})
        .filter(Number.isFinite);
    });
    if(!values.length)return {min:-7,max:seasonEnd+7};

    const first=Math.min.apply(null,values);
    const last=Math.max.apply(null,values);
    const nearEdgeDays=2;
    const edgePadding=8;
    // Je sechs bzw. sieben Tage Abstand zu den Punkten;
    // bei Ereignissen direkt am Periodenrand acht Tage außerhalb der Saison.
    let min=first<=nearEdgeDays ? -edgePadding : Math.floor(first-6);
    let max=last>=seasonEnd-nearEdgeDays ? seasonEnd+edgePadding : Math.ceil(last+7);

    // Auch bei sehr dicht beieinanderliegenden Punkten mindestens
    // 28 Tage zeigen, aber nicht auf die gesamte Saison aufblähen.
    const minimumSpan=28;
    if(max-min<minimumSpan){
      const missing=minimumSpan-(max-min);
      min-=Math.floor(missing/2);
      max+=Math.ceil(missing/2);
    }
    return {min:min,max:max};
  }

  function draw(result) {
    const {station,cfg,rows,points,reference}=result;
    const range=selectedYearRange(rows);
    const visible=points.filter(function(p){return p.year>=range.first && p.year<=range.last;});
    const finished=visible.filter(function(p){return !p.provisional;});
    const trend=regression(finished);
    result.visibleTrend=trend;
    result.visibleRange=range;
    const showTrend=chartOptionsEnabled("stationThresholdTrend");
    const showMedian=chartOptionsEnabled("stationThresholdMedian");
    const showExtremes=chartOptionsEnabled("stationThresholdExtremes");
    const stat=document.getElementById("stationThresholdSummary");
    const med=median(reference.map(function(r){return r.doy;}));
    const earliest=finished.slice().sort(function(a,b){return a.doy-b.doy || a.year-b.year;})[0]||null;
    const latest=finished.slice().sort(function(a,b){return b.doy-a.doy || a.year-b.year;})[0]||null;
    const labels=["Tmax","Tmin","Tmittel"];
    const ops={lt:"<",le:"≤",gt:">",ge:"≥"};
    const seasonLabels={autumn:"Herbst",spring:"Frühling",summer:"Sommer",winter:"Winter",year:"Kalenderjahr"};
    const header=labels[cfg.metric]+" "+ops[cfg.operator]+" "+(cfg.threshold/10).toLocaleString("de-DE")+" °C · "+cfg.days+" Tage in Folge · "+seasonLabels[cfg.season];
    const trendText=trend ? (trend.slope*10).toLocaleString("de-DE",{maximumFractionDigits:1,minimumFractionDigits:1})+" Tage/Dekade" : "nicht ausreichend Daten";
    stat.innerHTML="<strong>"+htmlEscape(station.name)+"</strong> · "+htmlEscape(header)+
      "<div style='margin-top:8px'>Median 1991–2020: <strong>"+(med===null?"–":dayLabel(med,cfg.season))+
      "</strong> ("+reference.length+" Jahre) · Linearer Trend "+range.first+"–"+range.last+": <strong>"+trendText+"</strong></div>"+
      "<div style='margin-top:5px'>Frühester Beginn in der Auswahl: <strong>"+(earliest?humanDate(earliest.first):"–")+
      "</strong> · Spätester Beginn: <strong>"+(latest?humanDate(latest.first):"–")+"</strong></div>";

    document.getElementById("stationThresholdViewNote").textContent=
      "Diagramm "+range.first+"–"+range.last+" · "+visible.length+" Ereignisse · "+
      (yearView==="complete"?"100 % vollständige "+(cfg.season==="year"?"Jahre":"Jahreszeiten")+" für "+["Tmax","Tmin","Tmittel"][cfg.metric]+" · ":"")+
      "Jahr und Datum beim Berühren eines Punkts · vollständige Jahrestabelle darunter.";

    if(chart){chart.destroy();chart=null;}
    const extremeLabel=function(rec){
      if(!showExtremes || !rec)return "";
      if(rec===earliest && rec===latest)return "Extremjahr "+rec.year;
      if(rec===earliest)return "Frühester: "+rec.year;
      if(rec===latest)return "Spätester: "+rec.year;
      return "";
    };
    const datasets=[{
      type:"scatter",label:"Erster Schwellenwerttermin",
      data:visible.map(function(rec){return {x:rec.year,y:rec.doy,record:rec};}),
      order:1,showLine:false,
      pointRadius:function(ctx){return extremeLabel(ctx.raw&&ctx.raw.record)?7:4.2;},
      pointHoverRadius:8,
      pointStyle:function(ctx){return extremeLabel(ctx.raw&&ctx.raw.record)?"rectRot":"circle";},
      backgroundColor:function(ctx){
        const rec=ctx.raw&&ctx.raw.record;
        return rec===earliest&&showExtremes?"#0b806b":rec===latest&&showExtremes?"#c16512":"#1769c2";
      },
      borderColor:"#ffffff",borderWidth:1.1
    }];
    if(showTrend&&trend&&finished.length>=8){
      const x0=Math.min.apply(null,finished.map(function(p){return p.year;}));
      const x1=Math.max.apply(null,finished.map(function(p){return p.year;}));
      datasets.push({type:"line",label:"Linearer Trend",order:2,
        data:[{x:x0,y:trend.slope*x0+trend.intercept},{x:x1,y:trend.slope*x1+trend.intercept}],
        borderColor:"#c0392b",borderWidth:2,pointRadius:0,fill:false});
    }
    if(showMedian&&med!==null&&visible.length){
      datasets.push({type:"line",label:"Median 1991–2020",order:3,
        data:[{x:range.first,y:med},{x:range.last,y:med}],
        borderColor:"#64748b",borderDash:[6,5],borderWidth:1.5,pointRadius:0,fill:false});
    }
    // Nur den tatsächlich belegten Datumsbereich abbilden.
    // Trend und Median werden berücksichtigt, damit keine Linie abgeschnitten wird.
    const yRange=stationThresholdYRange(datasets,cfg.season);
    const ticks=chartCalendarTicks(cfg.season,yRange.min,yRange.max);
    chart=new Chart(document.getElementById("stationThresholdChart"),{
      type:"scatter",
      data:{datasets:datasets},
      options:{
        responsive:true,maintainAspectRatio:false,animation:false,parsing:false,
        interaction:{mode:"nearest",intersect:true},
        scales:{
          x:{
            type:"linear",min:range.first-0.8,max:range.last+0.8,
            title:{display:true,text:"Jahr"},
            grid:{color:"rgba(148,163,184,.16)"},
            ticks:{
              maxTicksLimit:window.innerWidth<700?6:11,
              precision:0,
              callback:function(value){return Number.isInteger(value)?String(value):"";}
            }
          },
          y:{
            min:yRange.min,max:yRange.max,reverse:true,
            title:{display:true,text:"Datum des ersten Auftretens"},
            grid:{color:"rgba(148,163,184,.22)"},
            afterBuildTicks:function(scale){
              scale.ticks=ticks.map(function(value){return {value:value};});
            },
            ticks:{autoSkip:false,padding:8,
              callback:function(value){return dayLabel(value,cfg.season);}}
          }
        },
        plugins:{
          // ChartDataLabels is registered globally by the dashboard. Never
          // print point objects; permit only the two explicitly chosen extrema.
          datalabels:{
            display:function(ctx){
              return ctx.datasetIndex===0 &&
                !!extremeLabel(ctx.dataset.data[ctx.dataIndex]?.record);
            },
            formatter:function(value){return extremeLabel(value&&value.record);},
            align:"top",anchor:"end",offset:5,clamp:true,
            font:{size:10,weight:"bold"},color:"#334155",
            backgroundColor:"rgba(255,255,255,.93)",
            borderColor:"rgba(100,116,139,.28)",borderWidth:1,borderRadius:4,
            padding:3
          },
          legend:{display:true,position:"bottom",labels:{boxWidth:15,usePointStyle:true}},
          tooltip:{
            filter:function(item){return !!item.raw?.record;},
            callbacks:{
              title:function(items){
                const rec=items[0]&&items[0].raw&&items[0].raw.record;
                return rec?String(rec.year):"";
              },
              label:function(ctx){
                const rec=ctx.raw&&ctx.raw.record;
                return rec?"Erster Tag: "+humanDate(rec.first)+" · letzter Serientag: "+
                  humanDate(rec.last)+(rec.provisional?" (vorläufig)":""):"";
              }
            }
          }
        }
      }
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
  function exportAnalysisSubtitle(){
    const cfg=lastAnalysis.cfg, year=lastAnalysis.visibleRange;
    const metric=["Tmax","Tmin","Tmittel"][cfg.metric];
    const operator={lt:"<",le:"≤",gt:">",ge:"≥"}[cfg.operator];
    const season={autumn:"Herbst",spring:"Frühling",summer:"Sommer",winter:"Winter",year:"Gesamtjahr"}[cfg.season];
    return metric+" "+operator+" "+(cfg.threshold/10).toLocaleString("de-DE")+" °C · "+
      cfg.days+" Tage in Folge · "+season+" · "+year.first+"–"+year.last;
  }
  function exportPng(){
    if(!lastAnalysis||!chart)return;
    const source=chart.canvas;
    const width=1420;
    const height=Math.round(width*source.height/source.width);
    // Die Exportseite wird an die Grafik angepasst, statt mit fixer
    // 910-px-Höhe mehrere hundert Pixel leeren Weißraum zu erzeugen.
    const canvas=document.createElement("canvas");
    canvas.width=1500;canvas.height=167+height+52;
    const ctx=canvas.getContext("2d");
    ctx.fillStyle="#fff";ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.fillStyle="#0f172a";ctx.font="bold 34px Arial";
    ctx.fillText("DWD-Stations-Schwellenwertanalyse",46,60);
    ctx.font="bold 23px Arial";
    ctx.fillText(lastAnalysis.station.name,46,99);
    ctx.fillStyle="#475569";ctx.font="19px Arial";
    ctx.fillText(exportAnalysisSubtitle(),46,131);
    ctx.drawImage(source,(canvas.width-width)/2,167,width,height);
    ctx.font="17px Arial";ctx.fillStyle="#64748b";
    ctx.fillText("Quelle: DWD CDC Tageswerte · Fehlende Tage unterbrechen Serien · vorläufige Daten gekennzeichnet",46,canvas.height-18);
    canvas.toBlob(function(blob){if(blob)download(blob,"png");},"image/png");
  }
  function exportPdf(){
    if(!lastAnalysis||!chart)return;
    if(!window.jspdf||!window.jspdf.jsPDF){setStatus("PDF-Bibliothek nicht verfügbar.");return;}
    const pdf=new window.jspdf.jsPDF({unit:"mm",format:"a4"});
    pdf.setFont("helvetica","bold");pdf.setFontSize(16);
    pdf.text("DWD - Stations-Schwellenwertanalyse",12,17);
    pdf.setFont("helvetica","normal");pdf.setFontSize(10);
    pdf.text(lastAnalysis.station.name,12,25);
    pdf.setFontSize(9);
    pdf.text(exportAnalysisSubtitle().replace(/[≤≥]/g,function(ch){return ch==="≤"?"<=":">=";}),12,31);
    const width=186, height=Math.min(111,width*chart.canvas.height/chart.canvas.width);
    pdf.addImage(chart.canvas.toDataURL("image/png"),"PNG",12,40,width,height);
    const footerY=40+height+9;
    pdf.setFontSize(8);
    pdf.text("Quelle: DWD CDC Tageswerte; fehlende Werte unterbrechen Serien.",12,footerY);
    const visibleTrend=lastAnalysis.visibleTrend;
    pdf.text("Trend "+lastAnalysis.visibleRange.first+"-"+lastAnalysis.visibleRange.last+": "+
      (visibleTrend?(visibleTrend.slope*10).toFixed(2)+" Tage/Dekade":"nicht ermittelbar"),12,footerY+7);
    let row=0;
    pdf.setFontSize(9);
    for(const r of lastAnalysis.rows){
      if(row%48===0){
        pdf.addPage();pdf.setFont("helvetica","bold");
        pdf.text("Jahr / Beginn / Serienende / Bewertung",12,16);
        pdf.setFont("helvetica","normal");
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
