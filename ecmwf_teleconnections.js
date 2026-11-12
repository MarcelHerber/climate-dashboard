/* ECMWF ENS 50-member independent NAO/AO EOF projections.
   Only real validated ECMWF geopotential fields; never the official CPC mode. */
(() => {
  "use strict";
  if(document.body.dataset.climateModule!=="nao-ao")return;
  const $=id=>document.getElementById(id);
  const DATA="data/nao_ao_forecast/ecmwf_indices.json";
  const CPC="data/nao_ao_forecast/latest.json";
  const round=x=>Number.isFinite(x)?new Intl.NumberFormat("de-DE",{minimumFractionDigits:2,maximumFractionDigits:2}).format(x):"–";
  const fmt=d=>d?new Date(d+"T12:00:00Z").toLocaleDateString("de-DE",{day:"2-digit",month:"2-digit",timeZone:"UTC"}):"–";
  let doc=null,cpc=null,chart=null,table=[],title="",error="";
  const colors={nao:"#236cb2",ao:"#d18a2a"};
  function status(text,bad=false){
    const el=$("epsStatus");if(!el)return;el.textContent=text;el.classList.toggle("tele-error",bad);
  }
  function html(x){return String(x??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
  function item(name,value,description){
    return '<div class="kpi"><span>'+html(name)+'</span><b>'+html(value)+'</b><small>'+html(description)+'</small></div>';
  }
  function index(){return $("epsIndex").value;}
  function current(){return doc?.indices?.[index()];}
  function probability(){return $("epsMode").value==="probability";}
  function safeDay(v){return Math.min(15,Math.max(0,Number(v)));}
  function build(){
    const idx=index(), data=current(), ensemble=data, horizon=safeDay($("epsDays").value);
    const obs=cpc?.indices?.[idx]?.observations||[];
    const other=cpc?.indices?.[idx]?.latest||null;
    const mode=$("epsMode").value;
    const observed=mode==="ensemble"?obs.filter(r=>r[0]>=
      new Date(Date.parse(data.init_date+"T00:00:00Z")-25*86400000).toISOString().slice(0,10)
      && r[0]<=data.valid_dates[horizon]):[];
    const dates=new Set([...data.valid_dates.slice(0,horizon+1),...observed.map(r=>r[0])]);
    if(other&&$("epsCompare").checked){
      other.valid_dates.forEach(d=>{if(d>=data.init_date&&d<=data.valid_dates[horizon])dates.add(d);});
    }
    const keys=[...dates].sort();
    const lookup=(times,values)=>new Map(times.map((d,i)=>[d,values[i]]));
    const values=m=>keys.map(d=>m.has(d)?m.get(d):null);
    const sets=[];
    const push=(label,data,color,extra={})=>sets.push({label,data,borderColor:color,backgroundColor:color,...extra});
    if(mode==="ensemble"){
      if(observed.length)push("CPC-Beobachtung",values(lookup(observed.map(r=>r[0]),observed.map(r=>r[1]))),"#111e33",{borderWidth:2.7});
      push("ECMWF 10. Perzentil",values(lookup(data.valid_dates,data.p10)),"rgba(32,96,160,.37)",{borderWidth:1,borderDash:[4,3]});
      const low=sets.length-1;
      push("ECMWF 90. Perzentil",values(lookup(data.valid_dates,data.p90)),"rgba(32,96,160,.37)",{
        borderWidth:1,borderDash:[4,3],fill:{target:low,above:"rgba(38,112,186,.13)",below:"rgba(38,112,186,.13)"}
      });
      if($("epsMembers").checked){
        for(const [id,arr] of Object.entries(ensemble.members)){
          push("EPS-Mitglied "+id,values(lookup(data.valid_dates,arr)),"rgba(72,102,133,.22)",{borderWidth:1});
        }
      }
      push("ECMWF EPS-EOF Mittel",values(lookup(data.valid_dates,data.mean)),colors[idx],{borderWidth:3.1});
      if($("epsCompare").checked&&other){
        push("NOAA GEFS CPC-Mittel ("+other.init_date+")",
          values(lookup(other.valid_dates,other.mean)),"#b53d51",{borderDash:[7,4],borderWidth:2.8});
      }
    }else{
      const phase=[
        ["negative","Negativ < 0","#2674bd"],
        ["positive","Positiv ≥ 0","#c37834"],
        ["strong_negative","Stark negativ ≤ −1","#264b98"],
        ["strong_positive","Stark positiv ≥ +1","#bb3447"]
      ];
      for(const [key,label,color] of phase)
        push("EPS "+label,values(lookup(data.valid_dates,data.probability[key])),color,
          {borderWidth:key.startsWith("strong")?1.6:2.6,
           borderDash:key.startsWith("strong")?[5,4]:[]});
      if($("epsCompare").checked&&other?.probability){
        push("NOAA GEFS P(negativ) ("+other.init_date+")",
          values(lookup(other.valid_dates,other.probability.negative)),
          "#7446ad",{borderDash:[7,4],borderWidth:2});
      }
    }
    table=[["Gültig (UTC)",...sets.map(s=>s.label)],...keys.map((d,i)=>[d,...sets.map(s=>s.data[i])])];
    title=idx.toUpperCase()+" · ECMWF EPS 50 Member / EOF-NCEP-Referenz · "+data.init_date;
    return {keys,sets};
  }
  function chartRender(keys,sets){
    chart?.destroy();
    if(!window.Chart)throw Error("Chart.js nicht verfügbar.");
    const zero={id:"epsZeroLine",afterDraw(c){
      const area=c.chartArea,y=c.scales.y,ref=probability()?50:0;
      if(!area||!y||y.min>ref||y.max<ref)return;
      const ctx=c.ctx;ctx.save();ctx.setLineDash([5,4]);ctx.strokeStyle="#788ba2";ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(area.left,y.getPixelForValue(ref));
      ctx.lineTo(area.right,y.getPixelForValue(ref));ctx.stroke();ctx.restore();
    }};
    chart=new Chart($("epsChart"),{
      type:"line",plugins:[zero],data:{labels:keys,datasets:sets},
      options:{
        responsive:true,maintainAspectRatio:false,animation:false,
        interaction:{mode:"index",intersect:false},
        elements:{point:{radius:0,hitRadius:10,hoverRadius:3},line:{tension:0,borderWidth:2,spanGaps:false}},
        scales:{
          x:{grid:{display:false},ticks:{maxRotation:0,maxTicksLimit:11,
            callback:function(v){return fmt(this.getLabelForValue(v));}}},
          y:{min:probability()?0:undefined,max:probability()?100:undefined,
             title:{display:true,text:probability()?"Anteil der EPS-Mitglieder (%)":"CPC-kalibrierter EOF-Index (σ, Näherung)"},
             ticks:{callback:v=>probability()?v+" %":v}}
        },
        plugins:{
          datalabels:{display:false},
          legend:{display:true,position:"bottom",labels:{
            filter:item=>!item.text.startsWith("EPS-Mitglied "),usePointStyle:true,boxWidth:12}},
          tooltip:{filter:item=>!item.dataset.label.startsWith("EPS-Mitglied "),
            callbacks:{title:items=>items?.[0]?.label?fmt(items[0].label):"",
              label:c=>c.dataset.label+": "+round(c.parsed.y)+(probability()?" %":"")}}
        }
      }
    });
    for(const id of ["epsPNG","epsPDF","epsCSV"])$(id).disabled=false;
  }
  function render(){
    if(!doc)return;
    try{
      const entry=current(),days=safeDay($("epsDays").value);
      if(!entry||!entry.members||Object.keys(entry.members).length!==50)
        throw Error("Die ECMWF-Mitglieder sind unvollständig.");
      if(Date.now()-Date.parse(doc.run_utc)>5*86400000)
        throw Error("Der EPS-Modelllauf ist älter als fünf Tage.");
      const data=build();
      chartRender(data.keys,data.sets);
      $("epsMembersRow").hidden=probability();
      const d=Math.min(days,7);
      $("epsKpis").innerHTML=
        item("ECMWF 00-UTC-Lauf",entry.init_date,"50 gestörte ENS-Member · 15 Tage")+
        item("Tag +"+d+" · "+fmt(entry.valid_dates[d]),round(entry.mean[d]),"CPC-kalibrierter EOF-Index, nicht offizieller CPC")+
        item("P(negativ)",round(entry.probability.negative[d])+" %","Anteil von 50 realen ECMWF-Mitgliedern")+
        item("P(stark negativ)",round(entry.probability.strong_negative[d])+" %","Index ≤ −1");
      const met=entry.quality;
      $("epsMeta").textContent=
        "Quelle ECMWF Open Data · IFS ENS 00 UTC "+entry.init_date+
        " · 50 Mitglieder · 500/1000-hPa-Geopotenzialhöhe · NCEP/NCAR-R1-EOF, "+
        met.training_period+" kalibriert, 2001–2020 unabhängig gegen CPC-Monatsindizes geprüft: r="+
        round(met.holdout_correlation)+", RMSE="+round(met.holdout_rmse)+
        ". NAO ist eine vereinfachte Atlantik-EOF und nicht CPCs saisonale REOF; AO basiert auf einer hemisphärischen EOF. "+
        (cpc?.indices?.[index()]?.latest?"Violett/Rot im Vergleich: unabhängig veröffentlichter CPC-GEFS-Lauf "+cpc.indices[index()].latest.init_date+".":"CPC-GEFS-Vergleich aktuell nicht verfügbar.");
      status("ECMWF EPS "+index().toUpperCase()+" · "+doc.generated_at.slice(0,16).replace("T"," ")+" UTC · 50 echte Mitgliedsprognosen",false);
      error="";
    }catch(e){
      console.error("EPS NAO AO:",e);error=e.message;
      status("ECMWF-Indexdarstellung nicht verfügbar: "+e.message,true);
      chart?.destroy();chart=null;
      for(const id of ["epsPNG","epsPDF","epsCSV"])$(id).disabled=true;
    }
  }
  function filebase(){
    return "ecmwf_eps_eof_"+index()+"_"+$("epsMode").value+"_"+(current()?.init_date||"unknown");
  }
  function download(blob,ext){
    const url=URL.createObjectURL(blob),a=document.createElement("a");
    a.href=url;a.download=filebase()+"."+ext;document.body.appendChild(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1800);
  }
  function csv(){
    if(!table.length)return;
    const data="\ufeff"+table.map(row=>row.map(value=>'"'+String(value??"").replace(/"/g,'""')+'"').join(";")).join("\r\n");
    download(new Blob([data],{type:"text/csv;charset=utf-8"}),"csv");
  }
  function png(){
    if(!chart)return;
    const source=chart.canvas;
    const canvas=document.createElement("canvas");const w=1800,h=Math.round(w*source.height/source.width);
    canvas.width=w;canvas.height=h+230;
    const g=canvas.getContext("2d");
    g.fillStyle="#fff";g.fillRect(0,0,canvas.width,canvas.height);
    g.fillStyle="#16304a";g.font="bold 35px Arial";g.fillText(title.slice(0,96),58,65);
    g.font="22px Arial";g.fillStyle="#50637b";g.fillText("ECMWF Open Data · NCEP/NCAR EOF · keine offiziellen CPC-Indexprognosen",58,110);
    g.drawImage(source,45,140,w-90,h);
    g.font="18px Arial";g.fillText("Quelle: ECMWF, NOAA/PSL, NOAA/CPC · 50 ENS-Member · Modelllauf "+current().init_date,58,canvas.height-35);
    canvas.toBlob(b=>{if(b)download(b,"png");},"image/png");
  }
  function rgb(c){
    if(c.startsWith("#")){let x=c.slice(1);if(x.length===3)x=x.split("").map(c=>c+c).join("");
      return [parseInt(x.slice(0,2),16),parseInt(x.slice(2,4),16),parseInt(x.slice(4,6),16)];}
    const m=c.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    return m?[Number(m[1]),Number(m[2]),Number(m[3])]:[80,100,130];
  }
  function pdf(){
    if(!chart||!window.jspdf?.jsPDF){status("Vektor-PDF derzeit nicht verfügbar.",true);return;}
    const p=new window.jspdf.jsPDF({orientation:"landscape",unit:"mm",format:"a4"});
    const x0=23,y0=39,w=252,h=135,y=chart.scales.y;
    const xi=i=>x0+i*w/Math.max(1,chart.data.labels.length-1);
    const yi=v=>y0+h-(v-y.min)/Math.max(.001,y.max-y.min)*h;
    p.setFillColor(255,255,255);p.rect(0,0,297,210,"F");
    p.setTextColor(20,48,72);p.setFontSize(14);p.text(title.slice(0,93),x0,16);
    p.setFontSize(8.8);p.setTextColor(85,101,121);
    p.text("ECMWF Open Data · NCEP/NCAR-R1 EOF · CPC-kalibrierte Näherung · nicht offizieller CPC-Index",x0,24);
    p.setDrawColor(208,219,228);p.setLineWidth(.20);p.rect(x0,y0,w,h);
    for(let k=0;k<=5;k++){
      const v=y.min+(y.max-y.min)*k/5,yy=yi(v);
      p.setDrawColor(224,231,240);p.line(x0,yy,x0+w,yy);
      p.setFontSize(8);p.text(round(v),x0-3,yy+1,{align:"right"});
    }
    for(let k=0;k<6;k++){
      const ix=Math.round((chart.data.labels.length-1)*k/5),xx=xi(ix);
      p.text(fmt(chart.data.labels[ix]),xx,y0+h+7,{align:"center"});
    }
    const ref=probability()?50:0;
    if(ref>=y.min&&ref<=y.max){
      p.setDrawColor(85,97,112);p.setLineDashPattern([1.5,1.4],0);
      p.line(x0,yi(ref),x0+w,yi(ref));p.setLineDashPattern([],0);
    }
    chart.data.datasets.forEach((set,di)=>{
      if(!chart.isDatasetVisible(di))return;
      const c=rgb(set.borderColor||"#52677d");
      p.setDrawColor(...c);p.setLineWidth(set.label.startsWith("EPS-Mitglied ")?.12:(set.borderWidth||1)>=3?.7:.34);
      p.setLineDashPattern(set.borderDash?.length?[1.4,1.1]:[],0);
      const commands=[];let joined=false;
      set.data.forEach((v,i)=>{
        if(!Number.isFinite(v)){joined=false;return;}
        commands.push({op:joined?"l":"m",c:[xi(i),yi(v)]});
        joined=true;
      });
      if(commands.some(c=>c.op==="l"))p.path(commands,"S");
    });
    p.setLineDashPattern([],0);p.setFontSize(8);p.setTextColor(85,101,121);
    p.text("Alle 50 EPS-Linien werden als separat auswählbare Vektorpfade ausgegeben; Werte in CSV. Quelle: ECMWF / NOAA.",x0,198);
    p.save(filebase()+".pdf");
  }
  async function reload(){
    status("ECMWF-Indexarchiv wird geprüft …");
    try{
      const a=await fetch(DATA+"?t="+Date.now(),{cache:"no-store"});
      if(!a.ok)throw Error("ECMWF-Index noch nicht veröffentlicht (HTTP "+a.status+").");
      const latest=await a.json();
      if(latest.schema!==1||latest.ready!==true||latest.expected_members!==50||
         latest.is_official_cpc!==false||latest.nao_is_cpc_exact_method!==false||
         !latest.indices?.ao||!latest.indices?.nao)
        throw Error("Unvollständige oder unklar deklarierte ECMWF-Indexdaten.");
      doc=latest;
      try{
        const b=await fetch(CPC+"?t="+Date.now(),{cache:"no-store"});
        cpc=b.ok?await b.json():null;
      }catch{cpc=null;}
      render();
    }catch(e){
      doc=null;cpc=null;
      chart?.destroy();chart=null;
      status("Noch keine validierte ECMWF-EOF-Prognose: "+e.message,true);
      ["epsPNG","epsPDF","epsCSV"].forEach(id=>$(id).disabled=true);
    }
  }
  function init(){
    if(!$("epsChart"))return;
    for(const id of ["epsIndex","epsMode","epsDays","epsMembers","epsCompare"]){
      $(id).addEventListener("change",render);
    }
    $("epsReload").addEventListener("click",reload);
    $("epsCSV").addEventListener("click",csv);
    $("epsPNG").addEventListener("click",png);
    $("epsPDF").addEventListener("click",pdf);
    reload();
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();
