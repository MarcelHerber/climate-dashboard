(() => {
  "use strict";
  const $=id=>document.getElementById(id);
  const SRC="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/main/eurasia_snow/index.json";
  const MONTHS=[10,11,12,1,2,3], MONTH_NAMES={10:"Oktober",11:"November",12:"Dezember",1:"Januar",2:"Februar",3:"März"},
    ABBR={10:"Okt",11:"Nov",12:"Dez",1:"Jan",2:"Feb",3:"Mär"};
  const COLORS={obs:"#182a41",climo:"#78889a",band:"rgba(142,163,181,.22)",fit:"#ef6871"};
  let doc=null,chart=null;

  function show(message,kind="normal"){
    $("message").textContent=message;
    $("message").dataset.kind=kind;
  }
  function seasonName(y){return y+" / "+String(y+1);}
  function yearForMonth(season,month){return month>=10?season:season+1;}
  function monthLength(year,month){return new Date(Date.UTC(year,month,0)).getUTCDate();}
  function monthDaysForReference(month){return month===2?29:monthLength(2025,month);}
  function dateKey(year,month,day){
    return year+"-"+String(month).padStart(2,"0")+"-"+String(day).padStart(2,"0");
  }
  function monthSeries(season,month){
    const year=yearForMonth(season,month),days=monthLength(year,month);
    return Array.from({length:days},(_,i)=>{
      const day=i+1;
      return {month,day,year,date:dateKey(year,month,day),label:String(day)};
    });
  }
  function winterSeries(season){
    // Fixed reference-day axis with leap day reserved, so February/March
    // always line up across leap/nonleap seasons. A nonexistent Feb 29
    // is left missing rather than interpolated.
    return MONTHS.flatMap(month=>Array.from({length:monthDaysForReference(month)},(_,i)=>{
      const day=i+1,year=yearForMonth(season,month);
      const valid=day<=monthLength(year,month);
      return {month,day,year,date:valid?dateKey(year,month,day):null,
        label:day+" "+ABBR[month]};
    }));
  }
  function climatologyRow(month,day){
    const series=doc.climatology_by_month?.[String(month).padStart(2,"0")] ||
      (month===10?doc.climatology:[]);
    return Array.isArray(series)?series.find(p=>p.day===day):null;
  }
  function sourceRows(season,selection){
    return selection==="winter"?winterSeries(season):monthSeries(season,Number(selection));
  }
  function regression(values){
    const p=values.map((value,i)=>({x:i+1,y:value}))
      .filter(x=>Number.isFinite(x.y));
    if(p.length<8||p.at(-1).x<10)return null;
    const n=p.length,sx=p.reduce((s,v)=>s+v.x,0),
      sy=p.reduce((s,v)=>s+v.y,0),sxx=p.reduce((s,v)=>s+v.x*v.x,0),
      sxy=p.reduce((s,v)=>s+v.x*v.y,0),den=n*sxx-sx*sx;
    if(!den)return null;
    const slope=(n*sxy-sx*sy)/den,intercept=(sy-slope*sx)/n;
    return {slope,series:values.map((_,i)=>Math.max(0,intercept+slope*(i+1)))};
  }
  function dataset(label,arr,color,extra={}){
    return {label,data:arr,borderColor:color,backgroundColor:color,
      borderWidth:2.5,pointRadius:2.5,pointHoverRadius:5,
      spanGaps:false,tension:0,fill:false,...extra};
  }
  function initChart(){
    chart=new Chart($("plot"),{
      type:"line",data:{labels:[],datasets:[]},
      options:{
        responsive:true,maintainAspectRatio:false,
        interaction:{mode:"index",intersect:false},
        scales:{
          x:{title:{display:true,text:"Winterhalbjahr (UTC)"},ticks:{maxTicksLimit:18}},
          y:{min:0,title:{display:true,text:"Schneebedeckte Landfläche (Mio. km²)"}}
        },
        plugins:{
          legend:{position:"top",labels:{
            boxWidth:14,usePointStyle:true,
            filter:item=>!item.text.startsWith("Untergrenze ")}},
          tooltip:{callbacks:{
            label:item=>item.parsed.y===null?"":item.dataset.label+": "+item.parsed.y.toFixed(2)+" Mio. km²"
          }}
        }
      }
    });
  }
  function render(){
    if(!doc)return;
    const season=Number($("season").value),selection=$("month").value;
    if(!Number.isInteger(season))return;
    const rows=sourceRows(season,selection);
    const obs=rows.map(row=>row.date&&Number.isFinite(doc.daily[row.date])?doc.daily[row.date]:null);
    const clima=rows.map(row=>climatologyRow(row.month,row.day));
    const mean=clima.map(row=>row&&Number.isFinite(row.mean)?row.mean:null),
      low=clima.map(row=>row&&Number.isFinite(row.mean)&&Number.isFinite(row.stddev)?
        Math.max(0,row.mean-row.stddev):null),
      high=clima.map(row=>row&&Number.isFinite(row.mean)&&Number.isFinite(row.stddev)?
        row.mean+row.stddev:null);
    const isWinter=selection==="winter";
    const seasonTitle=seasonName(season), monthTitle=isWinter?"Oktober–März":MONTH_NAMES[Number(selection)];
    const available=mean.filter(Number.isFinite).length;
    const series=[];
    if(available){
      series.push(dataset("Untergrenze ±1σ",low,"rgba(0,0,0,0)",{
        pointRadius:0,borderWidth:0,backgroundColor:"rgba(0,0,0,0)"
      }));
      series.push(dataset("Klimatologie ±1σ",high,"rgba(0,0,0,0)",{
        pointRadius:0,borderWidth:0,backgroundColor:COLORS.band,
        fill:{target:"-1",above:COLORS.band,below:COLORS.band}
      }));
      series.push(dataset("Klimamittel (verfügbare Referenzjahre)",mean,COLORS.climo,{
        pointRadius:0,borderDash:[8,5],borderWidth:2.3
      }));
    }
    series.push(dataset("NOAA IMS · "+seasonTitle,obs,COLORS.obs,{
      borderWidth:3.2,pointRadius:isWinter?0:3.2
    }));
    $("showTrend").disabled=isWinter;
    const fit=(!isWinter&&$("showTrend").checked)?regression(obs):null;
    if(fit){
      series.push(dataset("Lineare Trendgerade (keine Prognose)",fit.series,COLORS.fit,{
        pointRadius:0,borderDash:[5,4],borderWidth:2
      }));
    }
    chart.options.scales.x.title.text=isWinter?"Winterhalbjahr "+seasonTitle:
      MONTH_NAMES[Number(selection)]+" "+yearForMonth(season,Number(selection));
    chart.data.labels=rows.map(r=>r.label);
    chart.data.datasets=series;
    chart.update();

    const valid=obs.map((value,i)=>({value,date:rows[i].date}))
      .filter(item=>item.value!==null);
    const last=valid.at(-1);
    $("latest").textContent=last?
      last.value.toFixed(2)+" Mio. km² · "+new Date(last.date+"T12:00:00Z")
        .toLocaleDateString("de-DE",{timeZone:"UTC",day:"2-digit",month:"2-digit",year:"numeric"}):
      "Für die Auswahl noch keine IMS-Tageswerte";
    $("slope").textContent=isWinter?"Nur für einzelne Monate":
      fit?(fit.slope>=0?"+":"")+fit.slope.toFixed(3)+" Mio. km²/Tag":
        "Noch keine belastbare Trendlinie";
    $("coverage").textContent=available+" / "+rows.length+" Kalendertage";
    const counts=clima.filter(row=>row&&Number.isFinite(row.mean))
      .map(row=>row.years);
    const loYears=counts.length?Math.min(...counts):0,hiYears=counts.length?Math.max(...counts):0;
    $("climNote").textContent="Referenz 1999–2025 ohne 2014 · "+available+
      " von "+rows.length+" Kalendertagen mit ausreichenden historischen Vergleichen"+
      (counts.length?" ("+loYears+"–"+hiYears+" Stichprobenjahre je dargestelltem Tag)":"")+
      ". Das historische Archiv wird weiter ergänzt. Für den 29. Februar gelten mindestens fünf statt zehn Vergleichsjahre.";
    $("modelNote").textContent="ECMWF IFS/EPS: bisher keine unabhängig berechneten, mit NOAA IMS räumlich vergleichbaren Modellflächen. Keine Prognosekurven aus dem Screenshot übernommen.";
    $("selectionNote").textContent=isWinter?
      "Gesamtes Winterhalbjahr: Oktober bis März in zeitlich richtiger Reihenfolge; der 29. Februar bleibt in Nichtschaltjahren leer. Kein interpolierter Wert.":
      "Monatsansicht: "+monthTitle+" "+yearForMonth(season,Number(selection))+
      " · beobachtete Tage und tagesgenaue Klimatologie.";
  }
  function archivedSeasons(){
    if(Array.isArray(doc.seasons)&&doc.seasons.length)
      return doc.seasons.map(Number).filter(Number.isInteger);
    return [...new Set(Object.keys(doc.daily).map(k=>{
      const year=Number(k.slice(0,4)),month=Number(k.slice(5,7));
      return month>=10?year:year-1;
    }))].sort((a,b)=>b-a);
  }
  function yearOptions(){
    const previous=$("season").value;
    $("season").replaceChildren();
    archivedSeasons().forEach(season=>{
      const option=new Option(seasonName(season),String(season));
      $("season").append(option);
    });
    if([...$("season").options].some(option=>option.value===previous))
      $("season").value=previous;
  }
  async function load(){
    try{
      show("NOAA-IMS-Winterdaten werden geladen …");
      const response=await fetch(SRC+"?t="+Date.now(),{cache:"no-store"});
      if(!response.ok)throw Error("HTTP "+response.status);
      const incoming=await response.json();
      if(incoming.schema!==1 || !incoming.daily ||
         incoming.source?.doi!=="10.7265/N52R3PMC")
        throw Error("Datenformat ungültig");
      doc=incoming;
      const first=!$("season").options.length;
      yearOptions();
      if(first){
        const today=new Date();
        const thisSeason=today.getUTCMonth()>=9?today.getUTCFullYear():today.getUTCFullYear()-1;
        if([...$("season").options].some(x=>x.value===String(thisSeason)))
          $("season").value=String(thisSeason);
        const m=today.getUTCMonth()+1;
        $("month").value=MONTHS.includes(m)?String(m):"winter";
      }
      $("updated").textContent="Datenstand: "+new Date(incoming.generated_utc).toLocaleString(
        "de-DE",{timeZone:"UTC",dateStyle:"medium",timeStyle:"short"})+" UTC";
      render();
      show("NOAA IMS: "+Object.keys(incoming.daily).length+
        " verifizierte Tageswerte · Auswahl Oktober–März · historische Klimatologie wird monatlich ergänzt.","success");
    }catch(error){
      show("NOAA-IMS-Beobachtungen konnten nicht geladen werden: "+
        error.message+". Keine geschätzten Schneewerte angezeigt.","warn");
    }
  }
  $("season").addEventListener("change",render);
  $("month").addEventListener("change",render);
  $("showTrend").addEventListener("change",render);
  $("refresh").addEventListener("click",load);
  $("png").addEventListener("click",()=>{
    if(!doc||!chart)return;
    const a=document.createElement("a");
    a.href=chart.toBase64Image("image/png",1);
    a.download="Eurasien_NOAA_IMS_"+$("season").value+"_"+$("month").value+".png";
    a.click();
  });
  $("csv").addEventListener("click",()=>{
    if(!doc)return;
    const rows=sourceRows(Number($("season").value),$("month").value),
      csv=["date,observation_million_km2,climatology_mean_million_km2,climatology_stddev_million_km2,reference_years"];
    for(const row of rows){
      const c=climatologyRow(row.month,row.day)||{};
      csv.push([row.date||"",row.date?doc.daily[row.date]??"": "",
        c.mean??"",c.stddev??"",c.years??0].join(","));
    }
    const blob=new Blob([csv.join("\n")+"\n"],{type:"text/csv;charset=utf-8"});
    const link=document.createElement("a");
    link.href=URL.createObjectURL(blob);
    link.download="Eurasien_NOAA_IMS_"+$("season").value+"_"+$("month").value+".csv";
    link.click();
    setTimeout(()=>URL.revokeObjectURL(link.href),2000);
  });
  initChart();
  load();
})();