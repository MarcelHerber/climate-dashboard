/* ERA5 stratospheric diagnostics – independent of existing ERA5 map controls. */
(() => {
  "use strict";
  const METRICS = [
    ["u60_10","Zonaler Wind 60° N · 10 hPa","m/s",1],
    ["u60_30","Zonaler Wind 60° N · 30 hPa","m/s",1],
    ["u60_50","Zonaler Wind 60° N · 50 hPa","m/s",1],
    ["u60_100","Zonaler Wind 60° N · 100 hPa","m/s",1],
    ["tcap_10","Polkappentemperatur 60–90° N · 10 hPa","°C",2],
    ["tcap_50","Polkappentemperatur 60–90° N · 50 hPa","°C",2],
    ["tcap_100","Polkappentemperatur 60–90° N · 100 hPa","°C",2],
    ["zcap_10","Polkappen-Geopotentialhöhe · 10 hPa","gpm",2],
    ["wave1_10","Zonale Welle 1 · 60° N / 10 hPa","gpm",3],
    ["wave2_10","Zonale Welle 2 · 60° N / 10 hPa","gpm",3],
    ["heatflux_100","Eddy-Wärmefluss 60° N · 100 hPa","K m/s",3],
    ["o3cap_50","Ozon-Massenmischungsverhältnis 60–90° N · 50 hPa","mg/kg",3],
    ["pv60_10","Potenzielle Vorticity 60° N · 10 hPa","PVU",3],
    ["ssw_wind_reversal","Windumkehr 60° N · 10 hPa (Indikator)","0 / 1",4],
    ["ssw_major_events","Major-SSW-Ereignisse (WMO-Kriterien)","Anzahl",4],
    ["nam_10","NAM-Index · 10 hPa (EOF-basiert)","σ",4],
    ["vortex_area_10","Polarwirbelfläche · 10 hPa","km²",4]
  ];
  const META = Object.fromEntries(METRICS.map(x => [x[0],x]));
  let data=null,chart=null,loaded=false;
  function mount() {
    if(document.getElementById("era5Stratosphere"))return;
    const layout=document.querySelector("#era5Atmosphere .era5-atmos-layout");
    if(!layout)return;
    const section=document.createElement("section");
    section.id="era5Stratosphere";
    section.className="era5-atmos-card";
    section.style.marginTop="20px";
    section.innerHTML=
      '<h3>Stratosphäre & Polarwirbel · ERA5 Tagesdaten</h3>'+
      '<p>Eigenständige Zeitreihen auf Copernicus-ERA5-Tagesmitteln. Bestehende Monatskarten bleiben unabhängig.</p>'+
      '<div class="controls" style="margin:14px 0 12px;box-shadow:none;border:1px solid #dce3e8">'+
      '<div class="control-group"><label for="era5StratoMetric">Parameter</label><select id="era5StratoMetric"></select></div>'+
      '<div class="control-group"><label for="era5StratoYear">Jahr</label><select id="era5StratoYear"></select></div></div>'+
      '<div id="era5StratoStatus" class="era5-atmos-status" role="status">Lade Stratosphärendaten …</div>'+
      '<div id="era5StratoChartFrame" style="position:relative;height:390px"><canvas id="era5StratoChart" aria-label="Stratosphärenzeitreihe" role="img"></canvas></div>'+
      '<p id="era5StratoInfo" style="margin-top:10px"></p>'+
      '<p class="era5-atmos-source">Quelle: Copernicus C3S ERA5, Tagesmittel UTC aus 6-stündlichen Werten (00/06/12/18 UTC), 1°-Diagnostikraster. Die Polkappenwerte sind flächengewichtet. Referenz 1991–2020 nach vollständigem Backfill. Eine Windumkehr ist noch kein bestätigtes Major SSW. Keine interpolierten oder erfundenen Daten.</p>';
    layout.insertAdjacentElement("afterend",section);
    const param=document.getElementById("era5StratoMetric");
    [1,2,3,4].forEach(stage=>{
      const group=document.createElement("optgroup");
      group.label=({1:"Etappe 1 · Zonalwind",2:"Etappe 2 · Temperatur und Höhe",3:"Etappe 3 · Dynamik und Chemie",4:"Etappe 4 · Ereignisse und Indizes"})[stage];
      METRICS.filter(x=>x[3]===stage).forEach(x=>{
        const option=document.createElement("option");option.value=x[0];option.textContent=x[1];group.appendChild(option);
      });
      param.appendChild(group);
    });
    param.value="u60_10";
    param.addEventListener("change",render);
    document.getElementById("era5StratoYear").addEventListener("change",render);
    if(window.ResizeObserver)new ResizeObserver(()=>chart?.resize()).observe(section);
    document.addEventListener("click",()=>window.setTimeout(()=>{if(section.offsetParent)chart?.resize();},200));
    load();
  }
  async function load(){
    if(loaded)return;loaded=true;
    try{
      const response=await fetch("era5_stratosphere/index.json?ts="+Date.now(),{cache:"no-store"});
      if(!response.ok)throw new Error("HTTP "+response.status);
      const obj=await response.json();
      if(obj.schema_version!==1||!Array.isArray(obj.series))throw new Error("Index ungültig");
      data=obj;
    }catch(error){console.info("ERA5-Stratosphäre: noch keine verifizierten Daten",error);data=null;}
    const years=data?[...new Set(data.series.map(r=>r.date.slice(0,4)))].sort().reverse():[];
    const select=document.getElementById("era5StratoYear");
    (years.length?years:[String(new Date().getUTCFullYear())]).forEach(y=>select.add(new Option(y,y)));
    render();
  }
  function render(){
    const key=document.getElementById("era5StratoMetric")?.value||"u60_10";
    const year=document.getElementById("era5StratoYear")?.value||"";
    const status=document.getElementById("era5StratoStatus"),info=document.getElementById("era5StratoInfo");
    const frame=document.getElementById("era5StratoChartFrame"),meta=META[key];
    const rows=(data?.series||[]).filter(r=>r.date.startsWith(year+"-"));
    const valid=rows.filter(r=>Number.isFinite(r[key]));
    if(chart){chart.destroy();chart=null;}
    if(!valid.length||typeof Chart==="undefined"){
      frame.style.display="none";
      status.textContent=!data?"Noch kein veröffentlichter ERA5-Stratosphärenindex. Der Datenworkflow muss erst erfolgreich laufen.":
        "Noch keine verifizierten Werte für "+meta[1]+" in "+year+" (Etappe "+meta[3]+").";
      info.textContent="Keine simulierten Daten. Die ERA5-Monatskarten oberhalb bleiben nutzbar.";
      return;
    }
    frame.style.display="block";
    const ref=data.reference?.[key]||{},keys=Object.keys(ref),hasRef=keys.length>0;
    const refValues=(field)=>rows.map(r=>{const x=ref[r.date.slice(5)];return Number.isFinite(x?.[field])?x[field]:null;});
    const sets=[];
    if(hasRef){
      sets.push({label:"P10 (1991–2020)",data:refValues("p10"),borderWidth:0,pointRadius:0,spanGaps:false});
      sets.push({label:"P10–P90",data:refValues("p90"),borderWidth:0,pointRadius:0,fill:"-1",backgroundColor:"rgba(70,110,150,.17)",spanGaps:false});
      sets.push({label:"Mittel 1991–2020",data:refValues("mean"),borderColor:"#b84042",borderWidth:2.5,pointRadius:0,spanGaps:false});
    }
    sets.push({label:year+" · "+meta[1],data:rows.map(r=>Number.isFinite(r[key])?r[key]:null),borderColor:"#226d9d",borderWidth:2.5,pointRadius:0,spanGaps:false});
    chart=new Chart(document.getElementById("era5StratoChart"),{
      type:"line",data:{labels:rows.map(r=>r.date),datasets:sets},
      options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:"index",intersect:false},
        plugins:{legend:{position:"bottom"},tooltip:{callbacks:{label:ctx=>ctx.dataset.label+": "+(ctx.parsed.y===null?"–":ctx.parsed.y.toLocaleString("de-DE",{maximumFractionDigits:2})+" "+meta[2])}}},
        scales:{x:{ticks:{maxTicksLimit:13,callback:function(v){return this.getLabelForValue(v)?.slice(5,7)+"/"+year;}}},y:{title:{display:true,text:meta[2]}}}}
    });
    const last=valid[valid.length-1];
    status.textContent="ERA5-Tagesdaten bis "+last.date+" · "+valid.length+" Werte für "+year+
      (hasRef?" · Klimamittel und P10–P90 (1991–2020)":" · historischer Referenzlauf noch unvollständig");
    info.textContent="Letzter Wert: "+last[key].toLocaleString("de-DE",{maximumFractionDigits:2})+" "+meta[2]+
      " · Datenstand: "+(data.generated_at||"–");
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",mount,{once:true});else mount();
})();
