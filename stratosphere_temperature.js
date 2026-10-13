/* Real-data stratospheric polar-cap temperature and paired 60N wind diagnostics. */
(() => {
  "use strict";
  const REPO="MarcelHerber/climate-dashboard";
  const ERA_URLS=["era5_stratosphere/index.json",
    "https://raw.githubusercontent.com/"+REPO+"/main/era5_stratosphere/index.json"];
  const WIND_ROOT="https://raw.githubusercontent.com/"+REPO+"/stratosphere-data/data/stratosphere/";
  const LEVELS=[10,30,50,100];
  const COLORS={10:"#2563eb",30:"#8b5cf6",50:"#0f766e",100:"#d97706"};
  const MON=["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"];
  let era=null,rows=new Map(),chart=null,wind=new Map(),windRef=new Map(),status="",ticket=0,plot=null;
  let cachedSeason=null,temperatureReady=false,backfillStatus=null;
  const $=id=>document.getElementById(id);
  function fmt(v,d=1){return Number.isFinite(v)?v.toLocaleString("de-DE",{maximumFractionDigits:d,minimumFractionDigits:d}):"–";}
  function dayOf(date){return Date.parse(date+"T00:00:00Z");}
  function dateISO(ms){return new Date(ms).toISOString().slice(0,10);}
  function seasonName(y){return y+"/"+String((y+1)%100).padStart(2,"0");}
  function dateList(year,view){
    const beginning=view==="ssw"?"11-01":view==="winter"?"09-01":"07-01";
    const end=view==="ssw"?"03-31":view==="winter"?"05-31":"06-30";
    const first=String(year)+"-"+beginning,last=String(year+1)+"-"+end;
    const list=[];for(let t=dayOf(first);t<=dayOf(last);t+=86400000)list.push(dateISO(t));
    return list;
  }
  function val(date,key){const n=rows.get(date)?.[key];return typeof n==="number"&&Number.isFinite(n)?n:null;}
  function ref(date,level){
    const n=era?.reference?.["tcap_"+level]?.[date.slice(5)]?.mean;
    return typeof n==="number"&&Number.isFinite(n)?n:null;
  }
  function changeAt(date,level,lag){
    const a=val(date,"tcap_"+level),b=val(dateISO(dayOf(date)-lag*86400000),"tcap_"+level);
    return a!==null&&b!==null?a-b:null;
  }
  function temp(date,level,mode,lag){
    const a=val(date,"tcap_"+level);if(a===null)return null;
    if(mode==="absolute")return a;
    if(mode==="change")return changeAt(date,level,lag);
    const b=ref(date,level);return b===null?null:a-b;
  }
  function parseNASA(text){
    const m=new Map();
    for(const line of text.split(/\r?\n/)){
      const columns=line.trim().split(/\s+/);
      if(!/^\d{4}-\d{2}-\d{2}$/.test(columns[0]||"")||columns.length<9)continue;
      const n=Number(columns[1]),lead=columns.length>=10?Number(columns[9]):0;
      if(!Number.isFinite(n)||n<=-9000||!Number.isFinite(lead)||lead<0)continue;
      m.set(columns[0],{value:n,lead});
    }
    return m;
  }
  function windAt(day,level,mode){
    const v=wind.get(level)?.get(day);if(!v)return null;
    const climate=windRef.get(level)?.[day.slice(5)]?.mean;
    const baseline=Number.isFinite(climate)?climate:null;
    const showAnom=mode==="anomaly";
    return {value:showAnom?(baseline!==null?v.value-baseline:null):v.value,
      actual:v.value,reference:baseline,forecast:v.lead>0,lead:v.lead};
  }
  async function fetchJsonWithFallback(urls){
    let last;for(const url of urls){
      try{const r=await fetch(url+(url.includes("?")?"&":"?")+"ts="+Math.floor(Date.now()/300000),{cache:"no-store"});
        if(!r.ok)throw Error("HTTP "+r.status);
        return await r.json();
      }catch(e){last=e;}
    }
    throw last||Error("ERA5-Archiv nicht erreichbar");
  }
  async function loadBackfillStatus(){
    const urls=["era5_stratosphere/backfill_status.json",
      "https://raw.githubusercontent.com/"+REPO+"/main/era5_stratosphere/backfill_status.json"];
    for(const url of urls){
      try{
        const r=await fetch(url+"?ts="+Math.floor(Date.now()/300000),{cache:"no-store"});
        if(!r.ok)continue;
        const data=await r.json();
        if(data.schema_version===1){backfillStatus=data;return;}
      }catch(e){/* Data workflow has not published a status yet. */}
    }
    backfillStatus=null;
  }
  function renderRunHealth(){
    const node=$("polarTempRunHealth");if(!node)return;
    if(!backfillStatus){
      node.textContent="CDS-Laufbericht noch nicht veröffentlicht. Die Balken zeigen ausschließlich echte ERA5-Werte im Index.";
      return;
    }
    const run=backfillStatus.last_run||{},time=backfillStatus.updated_utc||"–";
    const totalErrors=(run.priority_errors||0)+(run.climatology_errors||0)+(run.errors||[]).length;
    node.textContent="Letzter Datenlauf: "+time+
      " · SSW-Pakete: "+(run.priority_chunks_completed??"–")+
      " · Referenzpakete: "+(run.climatology_chunks_completed??"–")+
      (totalErrors?" · Fehler/abgebrochene Pakete: "+totalErrors:" · keine gemeldeten CDS-Fehler");
  }
  async function loadERA(){
    const value=await fetchJsonWithFallback(ERA_URLS);
    if(value.schema_version!==1||!Array.isArray(value.series))throw Error("ERA5-Index ungültig");
    era=value;rows=new Map(value.series.filter(x=>x&&typeof x.date==="string").map(x=>[x.date,x]));
    temperatureReady=true;
  }
  async function loadNASA(season,token){
    const response=await Promise.allSettled(LEVELS.flatMap(level=>[
      fetch(WIND_ROOT+"u60n_"+level+"_"+season+"_merra2.txt?v="+Math.floor(Date.now()/3600000),{cache:"no-store"})
        .then(r=>{if(!r.ok)throw Error("HTTP "+r.status);return r.text();}),
      fetch(WIND_ROOT+"climatology_"+level+"hpa.json?v="+Math.floor(Date.now()/3600000),{cache:"no-store"})
        .then(r=>{if(!r.ok)throw Error("HTTP "+r.status);return r.json();})
    ]));
    if(token!==ticket)return;
    wind=new Map();windRef=new Map();
    LEVELS.forEach((level,i)=>{
      const t=response[i*2],c=response[i*2+1];
      if(t.status==="fulfilled")wind.set(level,parseNASA(t.value));
      if(c.status==="fulfilled"&&c.value?.daily)windRef.set(level,c.value.daily);
    });
    cachedSeason=season;
  }
  function levelStats(dates,lag){
    const all=LEVELS.flatMap(level=>dates.map(date=>{
      const temperature=val(date,"tcap_"+level);
      return temperature===null?null:{date,level,temperature,change:changeAt(date,level,lag),
        anomaly:ref(date,level)===null?null:temperature-ref(date,level)};
    })).filter(Boolean);
    const strongest=all.filter(x=>Number.isFinite(x.change)).sort((a,b)=>b.change-a.change)[0];
    const peak=all.filter(x=>x.level===10).sort((a,b)=>b.temperature-a.temperature)[0];
    return {all,strongest,peak,temperatureDays:new Set(all.map(x=>x.date)).size};
  }
  function drawKpis(dates,lag){
    const info=$("polarTempKpis");info.replaceChildren();
    const x=levelStats(dates,lag);
    const latest=x.all.filter(x=>x.level===10).sort((a,b)=>b.date.localeCompare(a.date))[0];
    const list=[
      ["Letzte 10-hPa-Temperatur",latest?fmt(latest.temperature,1)+" °C":"–",latest?.date||"Keine ERA5-Daten"],
      ["Größte Temperaturänderung / "+lag+" Tage",x.strongest?((x.strongest.change>0?"+":"")+fmt(x.strongest.change,1)+" K"):"–",
        x.strongest?x.strongest.level+" hPa · "+x.strongest.date:"Benötigt zwei echte Tageswerte"],
      ["Temperaturmaximum 10 hPa",x.peak?fmt(x.peak.temperature,1)+" °C":"–",
        x.peak?.date||"Noch nicht verfügbar"],
      ["Abgedeckte Kalendertage",String(x.temperatureDays),
        "ERA5-Tagesmittel · nur verifizierte Werte"]
    ];
    for(const [name,value,detail] of list){
      const node=document.createElement("div");node.className="polar-temp-kpi";
      const heading=document.createElement("div");heading.textContent=name;
      const bold=document.createElement("strong");bold.textContent=value;
      const foot=document.createElement("span");foot.textContent=detail;
      node.append(heading,bold,foot);info.appendChild(node);
    }
  }
  function historicalSeries(selected,d,level){
    const yy=Number(selected);
    if(!Number.isFinite(yy))return null;
    const mm=Number(d.slice(5,7)),mapped=String(mm<=6?yy+1:yy)+d.slice(4);
    return val(mapped,"tcap_"+level);
  }
  function drawTrend(dates,mode,lag){
    const element=$("polarTempTrend");
    if(chart){chart.destroy();chart=null;}
    if(typeof Chart==="undefined")return;
    const datasets=LEVELS.map(level=>({
      label:level+" hPa",data:dates.map(d=>temp(d,level,mode,lag)),
      borderColor:COLORS[level],backgroundColor:COLORS[level],spanGaps:false,
      borderWidth:2.3,tension:.15,pointRadius:1.7,pointHoverRadius:4
    }));
    const compare=$("polarTempCompare").value;
    if(compare!==""){
      const other=dates.map(d=>{
        if(mode==="absolute")return historicalSeries(compare,d,10);
        if(mode==="anomaly"){
          const t=historicalSeries(compare,d,10),base=ref(d,10);
          return t!==null&&base!==null?t-base:null;
        }
        const t=historicalSeries(compare,d,10),previous=historicalSeries(compare,dateISO(dayOf(d)-lag*86400000),10);
        return t!==null&&previous!==null?t-previous:null;
      });
      if(other.some(Number.isFinite)){
        datasets.push({label:"Vergleich "+seasonName(Number(compare))+" · 10 hPa",
          data:other,borderColor:"#475569",borderDash:[6,4],borderWidth:2,
          pointRadius:2,spanGaps:false});
        $("polarTempCompareInfo").textContent="Historischer ERA5-Vergleich "+seasonName(Number(compare))+" verfügbar.";
      }else $("polarTempCompareInfo").textContent="Für "+seasonName(Number(compare))+" liegen noch keine passenden ERA5-Temperaturen vor; kein historischer Vergleich dargestellt.";
    }else $("polarTempCompareInfo").textContent="";
    const axis=mode==="absolute"?"Polkappen-Temperatur [°C]":mode==="change"?"Temperaturänderung über "+lag+" Tage [K]":"Abweichung 1991–2020 [K]";
    chart=new Chart(element.getContext("2d"),{type:"line",
      data:{labels:dates.map(d=>d.slice(5)),datasets},
      options:{responsive:true,maintainAspectRatio:false,animation:false,
        interaction:{intersect:false,mode:"index"},
        plugins:{legend:{position:"bottom"},tooltip:{callbacks:{
          title:ctx=>dates[ctx[0]?.dataIndex]||"",
          label:ctx=>ctx.dataset.label+": "+fmt(ctx.parsed.y,2)+" "+(mode==="absolute"?"°C":"K")
        }}},
        scales:{x:{ticks:{maxTicksLimit:14,maxRotation:0},grid:{display:false}},
          y:{title:{display:true,text:axis}}}
      }
    });
  }
  function diverge(number,scale){
    if(number===null||!Number.isFinite(number))return "#e7ebf0";
    const f=Math.max(-1,Math.min(1,number/scale)),a=f<0?[36,94,191]:[202,49,48],center=[250,250,250];
    return "rgb("+center.map((n,i)=>Math.round(n+(a[i]-n)*Math.abs(f))).join(",")+")";
  }
  function mapCells(dates,mode,lag){
    const t=[],w=[];
    for(const level of LEVELS){
      t.push({level,values:dates.map(d=>temp(d,level,mode,lag))});
      // Temperature-tendency panel keeps the absolute wind as the second panel.
      w.push({level,values:dates.map(d=>windAt(d,level,mode))});
    }
    const tv=t.flatMap(r=>r.values).filter(Number.isFinite);
    const wv=w.flatMap(r=>r.values.map(v=>v?.value)).filter(Number.isFinite);
    return {dates,t,w,hasTemperature:tv.length,hasWind:wv.length};
  }
  function drawPaired(dates,mode,lag){
    const canvas=$("polarTempPairCanvas"),container=$("polarTempPair");
    const rect=container.getBoundingClientRect(),width=Math.max(300,rect.width||800),height=580;
    const pixelRatio=Math.max(1,Math.min(3,window.devicePixelRatio||1));
    canvas.width=Math.round(width*pixelRatio);canvas.height=Math.round(height*pixelRatio);
    const ctx=canvas.getContext("2d");if(!ctx)return;
    ctx.setTransform(pixelRatio,0,0,pixelRatio,0,0);
    ctx.fillStyle="#fff";ctx.fillRect(0,0,width,height);
    const vals=mapCells(dates,mode,lag);
    const absPercentile=(arr,p)=>{
      const sorted=arr.filter(Number.isFinite).map(Math.abs).sort((a,b)=>a-b);
      return sorted.length?sorted[Math.min(sorted.length-1,Math.floor((sorted.length-1)*p))]:5;
    };
    const limitT=mode==="absolute"?30:Math.max(5,Math.ceil(absPercentile(vals.t.flatMap(r=>r.values),.98)/5)*5);
    const limitW=Math.max(5,Math.ceil(absPercentile(vals.w.flatMap(r=>r.values.map(v=>v?.value)),.98)/5)*5);
    const x0=width<480?62:79,x1=width-12,areaWidth=x1-x0,cellWidth=areaWidth/Math.max(1,dates.length);
    const bands=[{top:43,title:"Polkappentemperatur 60–90° N",
      unit:mode==="absolute"?"°C": "K",rows:vals.t,temperature:true,limit:limitT},
      {top:301,title:"Zonaler Wind 60° N (NASA)"+(mode==="anomaly"?" · Anomalien":""),unit:"m/s",
        rows:vals.w,temperature:false,limit:limitW}];
    const rowHeight=40,bandHeight=rowHeight*LEVELS.length;
    ctx.textBaseline="middle";
    for(const band of bands){
      ctx.textAlign="left";ctx.font="700 14px Arial";ctx.fillStyle="#20354d";
      ctx.fillText(band.title,x0,band.top-22,areaWidth);
      for(let i=0;i<band.rows.length;i++){
        const row=band.rows[i],y=band.top+i*rowHeight;
        ctx.fillStyle="#e7ebf0";ctx.fillRect(x0,y,areaWidth,rowHeight-3);
        for(let d=0;d<dates.length;d++){
          const item=row.values[d],value=band.temperature?item:item?.value;
          if(!Number.isFinite(value))continue;
          const xx=x0+d*cellWidth;
          const colorValue=band.temperature&&mode==="absolute"?value+65:value;
          const cap=band.temperature&&mode==="absolute"?30:band.limit;
          ctx.fillStyle=diverge(colorValue,cap);
          ctx.fillRect(xx,y,Math.max(1,cellWidth+.3),rowHeight-3);
          if(!band.temperature&&item.forecast){
            ctx.save();ctx.beginPath();ctx.rect(xx,y,Math.max(1,cellWidth),rowHeight-3);ctx.clip();
            ctx.strokeStyle="rgba(0,0,0,.55)";ctx.lineWidth=.8;
            for(let n=-40;n<cellWidth+40;n+=7){ctx.beginPath();ctx.moveTo(xx+n,y+rowHeight-3);ctx.lineTo(xx+n+rowHeight,y);ctx.stroke();}
            ctx.restore();
          }
        }
        ctx.textAlign="right";ctx.font="700 12px Arial";ctx.fillStyle="#38475a";
        ctx.fillText(row.level+" hPa",x0-7,y+rowHeight/2);
      }
      ctx.strokeStyle="#e0e5eb";ctx.strokeRect(x0,band.top,areaWidth,bandHeight);
      ctx.font="11px Arial";ctx.fillStyle="#41556b";ctx.textAlign="left";
      ctx.fillText(band.temperature&&mode==="absolute"?"Farbzentrum: −65 °C · blau = kälter, rot = wärmer":
        "Blau = negativ · Rot = positiv · grau = kein Datenwert",
        x0,band.top+bandHeight+18,areaWidth);
      for(let k=0;k<dates.length;k++){
        if(dates[k].slice(8)!=="01")continue;
        const pos=x0+k*cellWidth;
        ctx.strokeStyle="rgba(55,75,99,.24)";ctx.beginPath();
        ctx.moveTo(pos,band.top);ctx.lineTo(pos,band.top+bandHeight);ctx.stroke();
        ctx.textAlign="center";ctx.fillStyle="#475569";ctx.font="11px Arial";
        ctx.fillText(MON[Number(dates[k].slice(5,7))-1],Math.min(x1-14,Math.max(x0+14,pos+14)),band.top+bandHeight+38);
      }
    }
    const crossings=[...document.querySelectorAll("#sswEventList .ssw-event")].flatMap(element=>{
      if(!element.querySelector(".ssw-event-state.confirmed"))return [];
      const text=element.querySelector(".ssw-event-head strong")?.textContent||"";
      const match=text.match(/\d{4}-\d{2}-\d{2}/);return match?[match[0]]:[];
    });
    for(const day of crossings){
      const at=dates.indexOf(day);if(at<0)continue;
      const pos=x0+(at+.5)*cellWidth;
      ctx.strokeStyle="#0f172a";ctx.lineWidth=1.7;ctx.setLineDash([5,4]);
      for(const band of bands){ctx.beginPath();ctx.moveTo(pos,band.top);ctx.lineTo(pos,band.top+bandHeight);ctx.stroke();}
      ctx.setLineDash([]);ctx.fillStyle="#0f172a";ctx.font="11px Arial";ctx.textAlign="left";
      ctx.fillText("SSW "+day,pos+4,29,Math.max(50,x1-pos));
    }
    const explain=mode==="absolute"?"Temperatur: ERA5-Tagesmittel (°C) · Wind: NASA-Analyse/Prognose (m/s)":
      mode==="change"?"Temperatur: Änderung zum Tag vor "+lag+" Tagen (K) · Wind: NASA-Absolutwerte (m/s)":
      "Temperaturanomalien ERA5 1991–2020 (K) · Windabweichungen NASA 1991–2020 (m/s)";
    ctx.textAlign="left";ctx.font="12px Arial";ctx.fillStyle="#475569";
    ctx.fillText(explain,Math.min(x0,20),564,areaWidth+35);
    plot={dates,rows:vals,x0,x1,areaWidth,cellWidth,top:bands.map(b=>b.top),rowHeight,width,height,mode,lag};
    $("polarTempPairStatus").textContent="Gemeinsame Zeitachse · "+vals.hasTemperature+" ERA5-Temperaturfelder · "+
      vals.hasWind+" NASA-Windfelder · Lücken und Druckniveaus ohne Daten werden grau dargestellt.";
    $("polarTempPng").disabled=!(vals.hasTemperature||vals.hasWind);
    $("polarTempCsv").disabled=!(vals.hasTemperature||vals.hasWind);
  }
  function hover(ev){
    if(!plot)return;
    const rect=$("polarTempPairCanvas").getBoundingClientRect();
    const px=(ev.clientX-rect.left)*plot.width/Math.max(1,rect.width),
      py=(ev.clientY-rect.top)*plot.height/Math.max(1,rect.height);
    let layer=-1;
    for(let j=0;j<2;j++)if(py>=plot.top[j]&&py<plot.top[j]+plot.rowHeight*4)layer=j;
    const tooltip=$("polarTempTooltip");
    if(layer<0||px<plot.x0||px>=plot.x1){tooltip.hidden=true;return;}
    const index=Math.min(plot.dates.length-1,Math.floor((px-plot.x0)/plot.cellWidth));
    const row=Math.min(3,Math.floor((py-plot.top[layer])/plot.rowHeight));
    const day=plot.dates[index],level=LEVELS[row],metric=layer===0?
      temp(day,level,plot.mode,plot.lag):windAt(day,level,plot.mode);
    tooltip.textContent=day+" · "+level+" hPa\n"+
      (layer===0?"ERA5 Polkappenmittel\n":"NASA 60° N\n")+
      (layer===0?(metric===null?"Keine echten Temperaturdaten":
        (plot.mode==="absolute"?"Temperatur: "+fmt(metric,2)+" °C":
          plot.mode==="change"?plot.lag+"-Tage-Erwärmung: "+fmt(metric,2)+" K":"Anomalie: "+fmt(metric,2)+" K")):
        metric===null?"Kein gültiger Windwert":
          (metric.forecast?"Prognose":"Analyse")+" · "+fmt(metric.value,2)+" m/s"+
          (metric.reference!==null?"\nKlimamittel: "+fmt(metric.reference,2)+" m/s":""));
    tooltip.hidden=false;
    tooltip.style.left=Math.max(5,Math.min(rect.width-tooltip.offsetWidth-6,ev.clientX-rect.left+13))+"px";
    tooltip.style.top=Math.max(5,Math.min(rect.height-tooltip.offsetHeight-6,ev.clientY-rect.top+13))+"px";
  }
  function downloadBlob(blob,name){const link=document.createElement("a"),url=URL.createObjectURL(blob);
    link.href=url;link.download=name;document.body.appendChild(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),3000);
  }
  function filename(ext){return "Stratosphaere_Temperatur_Wind_"+seasonName(Number($("season").value)).replace("/","-")+
    "_"+$("polarTempMode").value+"_"+$("view").value+"."+ext;}
  function exportPng(){
    if(!plot)return;
    const input=$("polarTempPairCanvas");
    const out=document.createElement("canvas"),scale=input.width/plot.width,header=Math.round(98*scale);
    out.width=input.width;out.height=input.height+header;
    const ctx=out.getContext("2d");if(!ctx)return;
    ctx.fillStyle="#fff";ctx.fillRect(0,0,out.width,out.height);
    ctx.textBaseline="top";ctx.fillStyle="#173049";ctx.font="bold "+Math.round(20*scale)+"px Arial";
    ctx.fillText("Stratosphäre · Temperatur & Zonalwind · Saison "+seasonName(Number($("season").value)),16*scale,13*scale,out.width-32*scale);
    ctx.font=Math.round(13*scale)+"px Arial";ctx.fillStyle="#4b5563";
    ctx.fillText("Polkappe 60–90° N · 60° N Zonalwind · ERA5 / NASA Ozone Watch",16*scale,48*scale,out.width-32*scale);
    ctx.fillText("Echte Tagesdaten · keine Interpolation · SSW-Markierungen nur windbasiert bestätigt",16*scale,72*scale,out.width-32*scale);
    ctx.drawImage(input,0,header);
    out.toBlob(blob=>{if(blob)downloadBlob(blob,filename("png"));},"image/png");
  }
  function exportCSV(){
    if(!plot)return;
    const lines=["Datum;Druckniveau_hPa;ERA5_Polkappentemperatur_C;ERA5_Klimamittel_1991_2020_C;ERA5_Anomalie_K;ERA5_Erwaermung_"+plot.lag+"Tage_K;NASA_Wind_m_s;NASA_Klimamittel_m_s;NASA_Anomalie_m_s;NASA_Analyse_oder_Prognose"];
    const z=v=>Number.isFinite(v)?Number(v.toFixed(3)):"";
    for(const date of plot.dates)for(const level of LEVELS){
      const absolute=val(date,"tcap_"+level),climatology=ref(date,level),
        w=windAt(date,level,"absolute");
      lines.push([date,level,z(absolute),z(climatology),
        z(absolute!==null&&climatology!==null?absolute-climatology:null),
        z(changeAt(date,level,plot.lag)),z(w?.actual),z(w?.reference),
        z(w?.reference!==null&&w? w.actual-w.reference:null),
        w?(w.forecast?"Prognose":"Analyse"):"Fehlend"].join(";"));
    }
    downloadBlob(new Blob([String.fromCharCode(65279)+lines.join("\r\n")],{type:"text/csv;charset=utf-8"}),filename("csv"));
  }
  function renderPriorityCoverage(){
    const host=$("polarTempBackfill");if(!host||!era)return;
    host.replaceChildren();
    for(const year of [2009,2017,2018]){
      const days=dateList(year,"winter");
      const counts=LEVELS.map(level=>days.filter(day=>val(day,"tcap_"+level)!==null).length);
      const complete=days.filter(day=>LEVELS.every(level=>val(day,"tcap_"+level)!==null)).length;
      const percent=Math.round(100*complete/days.length);
      const card=document.createElement("div");card.className="polar-backfill-card";
      const name=document.createElement("strong");name.textContent="Winter "+seasonName(year)+" · "+percent+" %";
      const total=document.createElement("div");
      total.textContent=complete+"/"+days.length+" Tage mit allen 4 Druckniveaus";
      const bar=document.createElement("progress");bar.max=days.length;bar.value=complete;
      bar.setAttribute("aria-label","ERA5-Abdeckung Winter "+seasonName(year));
      const perLevel=document.createElement("small");
      perLevel.textContent=LEVELS.map((level,i)=>level+" hPa: "+counts[i]).join(" · ");
      card.append(name,total,bar,perLevel);host.appendChild(card);
    }
  }
  function refresh(){
    if(!temperatureReady)return;
    const year=Number($("season").value),mode=$("polarTempMode").value,
      lag=Number($("polarTempLag").value);
    const dates=dateList(year,$("view").value);
    const available=LEVELS.map(l=>l+" hPa: "+dates.filter(d=>val(d,"tcap_"+l)!==null).length+" Tage").join(" · ");
    const refCount=era.reference_years_completed??0;
    $("polarTempStatus").textContent="ERA5 "+(era.data_through||"–")+
      " · Referenzjahre vollständig: "+refCount+"/30 · "+available;
    const hasRef=LEVELS.some(l=>dates.some(d=>ref(d,l)!==null));
    $("polarTempWarning").textContent=mode==="anomaly"&&!hasRef?
      "Die 1991–2020-Klimatologie ist noch nicht vollständig. ERA5-Anomalien werden deshalb nicht berechnet; die NASA-Windabweichungen können unabhängig davon bereits gezeigt werden.":
      "Temperaturen aus ERA5 (Polkappenmittel 60–90° N), Wind aus NASA MERRA-2/GEOS-FP (60° N). Unterschiedliche Datengrundlagen sind separat gekennzeichnet; keine fehlenden Tage oder Druckniveaus werden interpoliert.";
    renderPriorityCoverage();renderRunHealth();drawKpis(dates,lag);drawTrend(dates,mode,lag);drawPaired(dates,mode,lag);
  }
  async function load(){
    const year=Number($("season").value),token=++ticket;
    $("polarTempStatus").textContent="ERA5-Tagesdaten und NASA-Winddaten werden geladen …";
    if(!temperatureReady){
      try{await loadERA();}catch(error){
        if(token!==ticket)return;
        $("polarTempStatus").textContent="ERA5-Stratosphärendaten nicht erreichbar: "+error.message;
        $("polarTempWarning").textContent="Keine Ersatzdaten berechnet.";
        return;
      }
    }
    if(token!==ticket)return;
    await loadBackfillStatus();
    if(token!==ticket)return;
    if(cachedSeason!==year){
      try{await loadNASA(year,token);}catch(e){if(token===ticket)status=String(e);}
    }
    if(token!==ticket)return;refresh();
  }
  function mount(){
    const anchor=$("sswEventsCard")||$("heatmapCard");if(!anchor||$("polarTemperatureCard"))return;
    const style=document.createElement("style");style.textContent=[
      ".polar-temp-controls{display:flex;flex-wrap:wrap;align-items:flex-end;gap:13px;margin:14px 0}",
      ".polar-temp-controls label{display:flex;flex-direction:column;gap:4px;font-size:13px;font-weight:700;color:#475569}",
      ".polar-temp-controls select{min-width:145px}",
      ".polar-backfill{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0 17px}",
      ".polar-backfill-card{display:flex;flex-direction:column;gap:5px;padding:10px;border:1px solid #dce3eb;border-radius:9px;background:#f9fbfd;font-size:12px;color:#475569}",
      ".polar-backfill-card strong{font-size:14px;color:#172033}",
      ".polar-backfill-card progress{width:100%;height:12px;accent-color:#2563eb}",
      ".polar-backfill-card small{font-size:11px}",
      ".polar-temp-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:14px 0}",
      ".polar-temp-kpi{padding:12px;border:1px solid #dce3eb;border-radius:8px;background:#f8fafc}",
      ".polar-temp-kpi div{font-size:12px;color:#64748b}",
      ".polar-temp-kpi strong{display:block;font-size:22px;color:#172033}",
      ".polar-temp-kpi span{font-size:11px;color:#64748b}",
      ".polar-temp-line{position:relative;height:380px}",
      ".polar-temp-pair{position:relative;height:580px;margin:12px 0}",
      ".polar-temp-pair canvas{display:block;width:100%;height:100%;cursor:crosshair}",
      ".polar-temp-tooltip{position:absolute;z-index:15;pointer-events:none;white-space:pre-line;background:#14243a;color:white;font:12px/1.5 Arial;padding:9px 12px;border-radius:8px;max-width:260px}",
      ".polar-temp-tooltip[hidden]{display:none}",
      ".polar-temp-note{color:#475569;font-size:12px}",
      "@media(max-width:850px){.polar-temp-kpis,.polar-backfill{grid-template-columns:repeat(1,minmax(0,1fr))}}"
    ].join("\n");document.head.appendChild(style);
    const section=document.createElement("section");section.id="polarTemperatureCard";section.className="card";
    section.innerHTML=[
      '<div class="levels-heading"><div><h2>Polkappentemperatur & Polarwirbel · ERA5 / NASA</h2>',
      '<p>Tagesmittel 60–90° N; kombiniert mit dem zonalen Wind bei 60° N. Gemeinsame Zeitachse, nur tatsächliche Daten.</p></div>',
      '<div class="levels-actions"><button class="btn" id="polarTempPng" disabled type="button">Heatmaps als PNG</button>',
      '<button class="btn" id="polarTempCsv" disabled type="button">Temperatur & Wind als CSV</button></div></div>',
      '<div class="polar-temp-controls">',
      '<label>Temperaturdarstellung<select id="polarTempMode">',
      '<option value="absolute">Temperatur (°C)</option><option value="anomaly">Abweichung 1991–2020 (K)</option>',
      '<option value="change">Erwärmung / Abkühlung (K)</option></select></label>',
      '<label>Änderung über<select id="polarTempLag">',
      '<option value="1">1 Tag</option><option value="3">3 Tage</option>',
      '<option value="7" selected>7 Tage</option><option value="10">10 Tage</option>',
      '<option value="14">14 Tage</option></select></label>',
      '<label>Historischer Vergleich (10 hPa)<select id="polarTempCompare">',
      '<option value="">Kein Vergleich</option><option value="1990">1990/91</option>',
      '<option value="2009">2009/10</option><option value="2017">2017/18</option>',
      '<option value="2018">2018/19</option><option value="2025">2025/26</option></select></label>',
      '</div><div id="polarTempStatus" class="info" aria-live="polite">ERA5-Tageswerte werden geladen …</div>',
      '<h3>ERA5-Backfillstand der SSW-Vergleichswinter</h3>',
      '<p id="polarTempRunHealth" class="polar-temp-note">Laufbericht wird geladen …</p>',
      '<div id="polarTempBackfill" class="polar-backfill" aria-label="ERA5-Historienfortschritt"></div>',
      '<div class="polar-temp-kpis" id="polarTempKpis"></div>',
      '<h3>Polkappentemperatur nach Druckniveau</h3>',
      '<div class="polar-temp-line"><canvas id="polarTempTrend"></canvas></div>',
      '<p id="polarTempCompareInfo" class="polar-temp-note"></p>',
      '<h3>Gemeinsame Zeit-Höhen-Auswertung</h3>',
      '<div class="polar-temp-pair" id="polarTempPair"><canvas id="polarTempPairCanvas" aria-label="Zeit-Höhen-Heatmap der Polkappentemperatur und des zonalen Windes" role="img"></canvas>',
      '<div class="polar-temp-tooltip" id="polarTempTooltip" role="status" hidden></div></div>',
      '<p id="polarTempPairStatus" class="polar-temp-note"></p>',
      '<p id="polarTempWarning" class="polar-temp-note"></p>',
      '<p class="source">Quelle: <a href="https://cds.climate.copernicus.eu/datasets/derived-era5-pressure-levels-daily-statistics" target="_blank" rel="noopener">Copernicus ERA5 Tagesstatistik</a> ',
      '(flächengewichtete Polkappe 60–90° N) und <a href="https://ozonewatch.gsfc.nasa.gov/meteorology/" target="_blank" rel="noopener">NASA Ozone Watch</a>',
      ' (60° N zonaler Wind). Tendenzen benötigen lückenlose Endpunkte im exakten Abstand; keine interpolierten Daten.',
      ' SSW-Linien markieren ausschließlich die bereits windbasiert bestätigten Ereignisse aus der Ereignisübersicht.</p>'
    ].join("");
    anchor.insertAdjacentElement("afterend",section);
    for(const id of ["polarTempMode","polarTempLag","polarTempCompare"])$(id).addEventListener("change",refresh);
    $("polarTempPng").addEventListener("click",exportPng);
    $("polarTempCsv").addEventListener("click",exportCSV);
    $("polarTempPairCanvas").addEventListener("pointermove",hover);
    $("polarTempPairCanvas").addEventListener("pointerdown",hover);
    $("polarTempPairCanvas").addEventListener("pointerleave",()=>{$("polarTempTooltip").hidden=true;});
    $("season").addEventListener("change",load);
    $("view").addEventListener("change",refresh);
    $("mode").addEventListener("change",()=>{
      $("polarTempMode").value=$("mode").value;
      refresh();
    });
    if(window.ResizeObserver){
      new ResizeObserver(()=>{if(temperatureReady)drawPaired(dateList(Number($("season").value),$("view").value),
        $("polarTempMode").value,Number($("polarTempLag").value));}).observe($("polarTempPair"));
    }
    const eventList=$("sswEventList");
    if(eventList&&window.MutationObserver){
      new MutationObserver(()=>{if(temperatureReady)drawPaired(dateList(Number($("season").value),$("view").value),
        $("polarTempMode").value,Number($("polarTempLag").value));})
        .observe(eventList,{childList:true,subtree:true});
    }
    load();
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",mount,{once:true});
  else mount();
})();