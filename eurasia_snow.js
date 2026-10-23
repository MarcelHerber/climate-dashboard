(() => {
  "use strict";
  const $=id=>document.getElementById(id);
  const SRC="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/main/eurasia_snow/index.json";
  const days=Array.from({length:31},(_,i)=>i+1);
  const palette={obs:"#182a41",model:"#087eb3",eps:"#2542c1",climo:"#78889a",band:"rgba(142,163,181,.19)",fit:"#ef6871"};
  let doc=null,chart=null;

  function show(message,kind="normal"){
    $("message").textContent=message;
    $("message").dataset.kind=kind;
  }
  function parseDay(date){
    const match=/^\d{4}-10-(\d{2})$/.exec(date);
    return match?Number(match[1]):null;
  }
  function pointsFor(year){
    const values=Array(31).fill(null);
    for(const [date,value] of Object.entries(doc.daily||{})){
      if(!date.startsWith(year+"-"))continue;
      const day=parseDay(date);
      if(day&&day<=31&&Number.isFinite(value))values[day-1]=value;
    }
    return values;
  }
  function trend(observed){
    const xs=[],ys=[];
    observed.forEach((value,i)=>{
      if(value!==null&&i<31){xs.push(i+1);ys.push(value);}
    });
    if(xs.length<8 || xs.at(-1)<17)return null;
    const n=xs.length, sx=xs.reduce((s,v)=>s+v,0),
      sy=ys.reduce((s,v)=>s+v,0);
    const sxx=xs.reduce((s,v)=>s+v*v,0),
      sxy=xs.reduce((s,v,i)=>s+v*ys[i],0);
    const denominator=n*sxx-sx*sx;
    if(!denominator)return null;
    const slope=(n*sxy-sx*sy)/denominator;
    const offset=(sy-slope*sx)/n;
    // Regression is an optional statistical extension, NOT an ECMWF forecast.
    return {slope,values:days.map(d=>Math.max(0,offset+slope*d))};
  }
  function dataset(label,data,color,extra={}){
    return {label,data,borderColor:color,backgroundColor:color,
      borderWidth:2.8,pointRadius:2.8,pointHoverRadius:5,spanGaps:false,
      fill:false,tension:0, ...extra};
  }
  function mkChart(){
    chart=new Chart($("plot"),{
      type:"line",
      data:{labels:days.map(d=>String(d)),datasets:[]},
      options:{
        responsive:true,maintainAspectRatio:false,
        interaction:{mode:"index",intersect:false},
        scales:{
          x:{title:{display:true,text:"Oktobertag (UTC)"},ticks:{maxTicksLimit:16}},
          y:{min:0,title:{display:true,text:"Schneebedeckte Landfläche (Mio. km²)"}}
        },
        plugins:{
          legend:{position:"top",labels:{boxWidth:14,usePointStyle:true}},
          tooltip:{callbacks:{label:c=>c.parsed.y===null?"":c.dataset.label+": "+c.parsed.y.toFixed(2)+" Mio. km²"}}
        }
      }
    });
  }
  function render(){
    if(!doc)return;
    const year=Number($("year").value)||2026;
    const obs=pointsFor(year);
    const c=doc.climatology||[];
    const mean=days.map(day=>{
      const item=c.find(v=>v.day===day);
      return item&&item.mean!==null?item.mean:null;
    });
    const lo=days.map(day=>{
      const item=c.find(v=>v.day===day);
      return item&&item.mean!==null?Math.max(0,item.mean-item.stddev):null;
    });
    const hi=days.map(day=>{
      const item=c.find(v=>v.day===day);
      return item&&item.mean!==null?item.mean+item.stddev:null;
    });
    const series=[];
    if(mean.some(v=>v!==null)){
      series.push(dataset("Klimatologie −1σ",lo,"rgba(0,0,0,0)",{
        backgroundColor:"rgba(0,0,0,0)",pointRadius:0,borderWidth:0
      }));
      series.push(dataset("Klimatologie ±1σ",hi,"rgba(0,0,0,0)",{
        pointRadius:0,borderWidth:0,backgroundColor:palette.band,
        fill:{target:"-1",above:palette.band,below:palette.band}
      }));
      series.push(dataset("Klimamittel 1999–2025 (ohne 2014)",mean,palette.climo,{
        pointRadius:0,borderDash:[8,5],borderWidth:2.3
      }));
    }
    series.push(dataset("NOAA IMS beobachtet · "+year,obs,palette.obs,{borderWidth:3.5,pointRadius:3.5}));
    if($("showTrend").checked){
      const t=trend(obs);
      if(t)series.push(dataset("Lineare Trendfortschreibung (keine Prognose)",t.values,palette.fit,{
        pointRadius:0,borderDash:[5,4],borderWidth:2
      }));
    }
    // Never create model lines from unverified screenshot values. An actual
    // independent model ingest may add explicit model series in the future.
    if(doc.forecast && doc.forecast.verified===true &&
       Number.isInteger(doc.forecast.run_year) &&
       doc.forecast.run_year===year){
      for(const [key,label,color] of [["hres","ECMWF IFS",palette.model],
                                       ["eps_mean","ECMWF EPS-Mittel",palette.eps]]){
        const line=doc.forecast[key];
        if(Array.isArray(line)&&line.length===31)
          series.push(dataset(label,line.map(v=>Number.isFinite(v)?v:null),color,{pointRadius:3}));
      }
    }
    chart.data.datasets=series;
    chart.update();
    const valid=obs.map((v,i)=>({v,day:i+1})).filter(x=>x.v!==null);
    const last=valid.at(-1);
    $("latest").textContent=last?(last.v.toFixed(2)+" Mio. km² am "+last.day+". Oktober "+year):"Keine Beobachtungen verfügbar";
    const slope=trend(obs);
    $("slope").textContent=slope?(slope.slope>=0?"+":"")+slope.slope.toFixed(3)+" Mio. km²/Tag":"Noch keine belastbare Trendlinie";
    const count=c.filter(x=>x.mean!==null).length;
    $("coverage").textContent=count===31?"31 / 31 Oktobertage":count+" / 31 Oktobertage";
    $("climNote").textContent=count===31?
      "Klimatologie vollständig: mindestens 10 historische Vergleichsjahre pro Oktobertag.":
      "Klimatologie im Aufbau: derzeit "+count+" von 31 Tagen mit mindestens 10 historischen Vergleichsjahren.";
    $("modelNote").textContent=doc.forecast?.verified===true?
      "Verifizierte, räumlich vereinheitlichte Modellflächen verfügbar.":
      "ECMWF IFS/EPS: noch nicht aus Original-Modellfeldern berechnet. Deshalb erscheinen bewusst keine Prognosekurven.";
  }
  function yearsInArchive(){
    const years=[...new Set(Object.keys(doc.daily||{}).map(k=>Number(k.slice(0,4))))].filter(Number.isFinite);
    return years.sort((a,b)=>b-a);
  }
  async function load(){
    try{
      show("Verifizierte NOAA-IMS-Daten werden geladen …");
      const resp=await fetch(SRC+"?t="+Date.now(),{cache:"no-store"});
      if(!resp.ok)throw new Error("HTTP "+resp.status);
      const value=await resp.json();
      if(value.schema!==1 || !value.daily || value.source?.doi!=="10.7265/N52R3PMC")
        throw new Error("Ungültiges Datenformat");
      doc=value;
      const available=yearsInArchive();
      $("year").replaceChildren();
      available.forEach(year=>{
        const option=new Option(String(year),String(year));
        $("year").append(option);
      });
      $("year").value=available.includes(2026)?"2026":String(available[0]);
      $("updated").textContent=value.generated_utc?
        "Datenstand: "+new Intl.DateTimeFormat("de-DE",{dateStyle:"medium",timeStyle:"short",timeZone:"UTC"}).format(new Date(value.generated_utc))+" UTC":"";
      render();
      show("NOAA IMS: "+Object.keys(value.daily).length+" geprüfte Tageswerte · Beobachtungen und Klimatologie werden schrittweise ergänzt.","success");
    }catch(err){
      show("Noch keine verifizierten NOAA-IMS-Zeitreihen veröffentlicht ("+err.message+"). Das Diagramm bleibt bewusst leer.","warn");
      $("latest").textContent="Ausstehend";
      $("slope").textContent="Ausstehend";
      $("coverage").textContent="Ausstehend";
      $("modelNote").textContent="Keine Modellwerte aus der Vorlage übernommen; ECMWF muss unabhängig ausgewertet werden.";
    }
  }
  $("year").addEventListener("change",render);
  $("showTrend").addEventListener("change",render);
  $("refresh").addEventListener("click",load);
  $("png").addEventListener("click",()=>{
    if(!chart||!doc)return;
    const a=document.createElement("a");
    a.href=chart.toBase64Image("image/png",1);
    a.download="Eurasien_Schneebedeckung_NOAA_IMS_"+$("year").value+".png";
    a.click();
  });
  $("csv").addEventListener("click",()=>{
    if(!doc)return;
    const year=$("year").value,obs=pointsFor(Number(year));
    const rows=["day,observation_million_km2,climatology_mean_million_km2,climatology_stddev_million_km2,climatology_years"];
    days.forEach((d,i)=>{
      const c=doc.climatology.find(x=>x.day===d)||{};
      rows.push([d,obs[i]??"",c.mean??"",c.stddev??"",c.years??0].join(","));
    });
    const blob=new Blob([rows.join("\n")+"\n"],{type:"text/csv;charset=utf-8"});
    const a=document.createElement("a");a.href=URL.createObjectURL(blob);
    a.download="Eurasien_NOAA_IMS_Oktober_"+year+".csv";
    a.click();setTimeout(()=>URL.revokeObjectURL(a.href),2000);
  });
  mkChart();
  load();
})();
