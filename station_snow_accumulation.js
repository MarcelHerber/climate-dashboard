/* Climate Dashboard: accumulated measured snow depth (cm days), NOT snowfall.
   Source: DWD SHK_TAG, from the already published per-station daily archive. */
(function(root){
  "use strict";

  const PRESETS={
    "nov-mar":["11-01","03-31"],
    "winter":["12-01","02-29"],
    "nov-may":["11-01","05-31"],
    "hydro":["11-01","10-31"]
  };
  let initialized=false,chart=null,last=null;
  const byId=id=>document.getElementById(id);
  const finite=v=>v!==null && v!==undefined && Number.isFinite(Number(v)) && Number(v)>=0;
  const leap=year=>year%4===0&&(year%100!==0||year%400===0);
  const labelDay=md=>md.slice(3)+"."+md.slice(0,2)+".";
  const fmt=(value,digits=0)=>Number(value).toLocaleString("de-DE",{
    minimumFractionDigits:digits,maximumFractionDigits:digits});
  const median=values=>{
    if(!values.length)return null;
    const sorted=values.slice().sort((a,b)=>a-b),mid=sorted.length>>1;
    return sorted.length%2?sorted[mid]:(sorted[mid-1]+sorted[mid])/2;
  };

  function selectedDays(axis,start,end){
    const a=axis.indexOf(start),b=axis.indexOf(end);
    return a<0||b<0||b<a?null:axis.slice(a,b+1);
  }

  // Feb 29 is not a measurement date in non-leap hydrological years.
  // We carry the accumulated amount forward without counting an extra day.
  function accumulate(axis,days,values,year,{isCurrent=false}={}){
    if(!Array.isArray(axis)||!Array.isArray(values)||axis.length!==values.length){
      return null;
    }
    const indices=new Map(axis.map((d,i)=>[d,i]));
    let total=0,observed=0,expected=0,latest=null;
    const series=[];
    for(const day of days){
      if(!indices.has(day))return null;
      if(day==="02-29"&&!leap(year)){
        series.push(latest===null?null:total);
        continue;
      }
      expected++;
      const value=values[indices.get(day)];
      if(finite(value)){
        total+=Number(value);
        observed++;
        latest=total;
        series.push(Math.round(total*10)/10);
      }else{
        series.push(null); // missing values are never interpreted as zero
      }
    }
    const coverage=expected?observed/expected:0;
    return {year,series,total:observed?Math.round(total*10)/10:null,
      observed,expected,coverage,complete:expected>0&&observed===expected,
      isCurrent};
  }

  function rawValues(archive,current,currentYear,year){
    const axis=archive?.month_days;
    if(!Array.isArray(axis))return null;
    if(year===Number(currentYear)){
      const positions=Object.fromEntries((current?.columns||[]).map((k,i)=>[k,i]));
      const rows=new Map((current?.rows||[]).map(row=>[
        String(row[positions.date]||"").slice(5),row[positions.snow_cm]
      ]));
      return axis.map(day=>rows.has(day)?rows.get(day):null);
    }
    const entry=archive?.years?.find(item=>Number(item.year)===Number(year));
    return entry?.values||null;
  }

  function yearResult(archive,current,currentYear,year,days){
    const axis=archive?.month_days;
    const values=rawValues(archive,current,currentYear,year);
    return values?accumulate(axis,days,values,year,{
      isCurrent:year===Number(currentYear)}):null;
  }

  // The reference is the median of individual cumulative curves of complete
  // 1991-2020 measurement years, NOT the sum of daily median snow depths.
  // Exclude any incomplete season from the baseline for this exact interval.
  function reference(archive,days){
    const eligible=[];
    for(let year=1991;year<=2020;year++){
      const values=archive?.years?.find(item=>Number(item.year)===year)?.values;
      if(!Array.isArray(values))continue;
      const row=accumulate(archive.month_days,days,values,year);
      if(row?.complete)eligible.push(row);
    }
    if(eligible.length<5)return {count:eligible.length,series:null,total:null};
    const series=days.map((_,i)=>median(eligible.map(row=>row.series[i]).filter(finite)));
    return {count:eligible.length,series,total:series.at(-1)};
  }

  function report(archive,current,currentYear,years,start,end){
    if(!Array.isArray(archive?.month_days))return {error:"Jahresarchiv noch nicht verfügbar."};
    const days=selectedDays(archive.month_days,start,end);
    if(!days)return {error:"Das Enddatum muss am oder nach dem Startdatum liegen."};
    const rows=[...new Set([...years].map(Number))]
      .filter(Number.isInteger)
      .sort((a,b)=>b-a)
      .map(year=>yearResult(archive,current,currentYear,year,days))
      .filter(Boolean);
    return {days,rows,reference:reference(archive,days)};
  }

  function init(){
    if(initialized)return;
    const start=byId("stationSnowCumStart"),end=byId("stationSnowCumEnd");
    const preset=byId("stationSnowCumPreset");
    if(!start||!end||!preset)return;
    // Real axis arrives from the station archive; no synthetic calendar dates.
    const actual=last?.archive?.month_days||[];
    if(!actual.length)return;
    for(const select of [start,end]){
      select.replaceChildren();
      for(const md of actual){
        const option=document.createElement("option");
        option.value=md;option.textContent=labelDay(md);
        select.appendChild(option);
      }
    }
    start.value=PRESETS["nov-mar"][0];
    end.value=PRESETS["nov-mar"][1];
    preset.addEventListener("change",()=>{
      const dates=PRESETS[preset.value];
      if(dates){start.value=dates[0];end.value=dates[1];}
      draw();
    });
    for(const select of [start,end])select.addEventListener("change",()=>{
      preset.value="custom";
      draw();
    });
    const canvas=byId("stationSnowCumChart");
    for(const [buttonId,kind] of [
      ["stationSnowCumPng","png"],["stationSnowCumPdf","pdf"],["stationSnowCumCsv","csv"]
    ]){
      const button=byId(buttonId);
      button?.addEventListener("click",()=>{
        if(kind==="csv"){
          if(typeof root.runChartCsvExport==="function")root.runChartCsvExport(button,canvas);
        }else if(typeof root.runChartExport==="function"){
          root.runChartExport(button,canvas,kind);
        }
      });
    }
    initialized=true;
  }

  function render(ctx){
    last={...ctx,selectedYears:[...ctx.selectedYears]};
    init();
    draw();
  }

  function draw(){
    if(!last||!initialized)return;
    const status=byId("stationSnowCumStatus");
    const summary=byId("stationSnowCumSummary");
    const tbody=byId("stationSnowCumTableBody");
    const data=report(last.archive,last.current,last.currentYear,last.selectedYears,
      byId("stationSnowCumStart").value,byId("stationSnowCumEnd").value);
    if(chart){chart.destroy();chart=null;root.stationSnowAccumulationChart=null;}
    if(data.error){
      status.textContent=data.error;summary.textContent="–";
      byId("stationSnowCumEmpty").hidden=true;
      tbody.replaceChildren();return;
    }
    const {days,rows}=data,ref=data.reference;
    const hasRows=rows.some(row=>row.observed>0);
    status.textContent=
      fmt(days.length)+" Kalendertag-Positionen · "
      +rows.length+" ausgewählte Jahre · "
      +"Referenzmedian aus "+ref.count+" lückenlosen hydrologischen Jahren (1991–2020).";
    const fresh=rows.find(row=>row.isCurrent) || rows[0];
    const baseline=finite(ref.total)?" · Referenzmedian: "+fmt(ref.total)+" cm·Tage":"";
    summary.textContent=fresh&&fresh.total!==null
      ?"Schneehöhensumme "+fresh.year+": "+fmt(fresh.total)+" cm·Tage "
        +(fresh.complete?"(vollständig)":"(Teilstand, "+fmt(fresh.coverage*100,1)+" % beobachtet)")
        +baseline
      :"Kein ausgewähltes Jahr mit beobachteten Schneehöhen in diesem Zeitraum."+baseline;

    tbody.replaceChildren();
    for(const row of rows){
      const tr=document.createElement("tr");
      const columns=[
        String(row.year)+(row.isCurrent?" (aktuell)":""),
        row.total===null?"–":fmt(row.total,1),
        fmt(row.observed)+"/"+fmt(row.expected)+" ("+fmt(row.coverage*100,1)+" %)",
        row.observed?fmt(row.total/row.observed,1):"–",
        row.complete?"Vollständig":row.isCurrent?"Zwischenstand":"Unvollständig"
      ];
      for(const str of columns){
        const td=document.createElement("td");
        td.textContent=str;tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
    const datasets=[];
    if(ref.series){
      datasets.push({
        label:"Median der Schneehöhensummen 1991–2020 ("+ref.count+" Jahre)",
        data:ref.series,borderColor:"#4b5563",borderWidth:2.6,
        borderDash:[7,4],pointRadius:0,fill:false,spanGaps:false
      });
    }
    const color=window.StationSnowYears?.color;
    for(const row of rows){
      datasets.push({
        label:"Hydrologisches Jahr "+row.year+(row.complete?"":" (Teilreihe)"),
        data:row.series,
        borderColor:color?color(row.year,last.currentYear):"#b54e40",
        borderWidth:row.isCurrent?2.7:1.6,pointRadius:0,spanGaps:false,
        fill:false,tension:0
      });
    }
    if(!hasRows&&!ref.series){
      byId("stationSnowCumEmpty").hidden=false;
      return;
    }
    byId("stationSnowCumEmpty").hidden=true;
    chart=new Chart(byId("stationSnowCumChart"),{
      type:"line",
      data:{labels:days.map(labelDay),datasets},
      options:{
        responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},
        plugins:{
          title:{display:true,text:"Kumulierte Schneehöhe · "+last.station.name
            +" · "+labelDay(days[0])+"–"+labelDay(days.at(-1))+" · cm·Tage"},
          datalabels:{display:false},
          tooltip:{callbacks:{label:item=>item.parsed.y===null?null:
            item.dataset.label+": "+fmt(item.parsed.y,1)+" cm·Tage"}},
          zoom:{pan:{enabled:true,mode:"x"},zoom:{wheel:{enabled:true},
            pinch:{enabled:true},mode:"x"}}
        },
        scales:{x:{ticks:{maxTicksLimit:12,maxRotation:0}},
          y:{beginAtZero:true,title:{display:true,text:"Kumulierte Schneehöhe (cm·Tage)"}}}
      }
    });
    root.stationSnowAccumulationChart=chart;
  }

  root.StationSnowAccumulation=Object.freeze({
    PRESETS,selectedDays,accumulate,rawValues,yearResult,reference,report,render
  });
})(window);
