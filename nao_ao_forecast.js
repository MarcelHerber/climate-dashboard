/* NAO/AO forecast monitor: official NOAA CPC CSV-derived GEFS/GFS values only. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  if (document.body.dataset.climateModule !== "nao-ao") return;

  const URL = "data/nao_ao_forecast/latest.json";
  const STYLE = {nao:"#1868ae", ao:"#d18b27"};
  const num = v => Number.isFinite(v) ? new Intl.NumberFormat("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1}).format(v) : "–";
  const stamp = d => d ? new Date(d+"T12:00:00Z").toLocaleDateString("de-DE",{day:"2-digit",month:"2-digit",timeZone:"UTC"}) : "–";
  const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  let archive = null, chart = null, exportRows = [], exportTitle = "", lastError = "";

  function status(text, bad) {
    const el = $("teleStatus");
    if (!el) return;
    el.textContent = text;
    el.classList.toggle("tele-error", !!bad);
  }
  function checkbox(id) {return $(id).checked;}
  function selection(id) {return $(id).value;}
  function validIndex() {return archive?.indices?.[selection("teleIndex")] || null;}
  function lastGoodDate(row) {return row?.[0] || "–";}
  function statsCard(label,value,sub) {
    return '<div class="kpi"><span>'+escapeHTML(label)+'</span><b>'+escapeHTML(value)+'</b><small>'+escapeHTML(sub)+'</small></div>';
  }
  function switchChart(dates,sets,yLabel,probability) {
    if (!window.Chart) throw Error("Chart.js wurde nicht geladen.");
    chart?.destroy();
    const zero = {id:"teleReference",afterDraw(c) {
      const y=c.scales.y,a=c.chartArea,value=probability?50:0;
      if(!a||!y||y.min>value||y.max<value)return;
      const ctx=c.ctx;ctx.save();ctx.strokeStyle="rgba(71,85,105,.60)";ctx.lineWidth=1.1;
      ctx.setLineDash([5,5]);ctx.beginPath();ctx.moveTo(a.left,y.getPixelForValue(value));
      ctx.lineTo(a.right,y.getPixelForValue(value));ctx.stroke();ctx.restore();
    }};
    chart = new Chart($("teleChart"),{
      type:"line",data:{labels:dates,datasets:sets},plugins:[zero],
      options:{
        responsive:true,maintainAspectRatio:false,animation:false,
        interaction:{mode:"index",intersect:false},
        elements:{point:{radius:0,hitRadius:10,hoverRadius:3},line:{tension:0,borderWidth:2,spanGaps:false}},
        scales:{
          x:{ticks:{maxRotation:0,maxTicksLimit:11,callback:function(v){return stamp(this.getLabelForValue(v));}},
             grid:{display:false}},
          y:{min:probability?0:undefined,max:probability?100:undefined,
             title:{display:true,text:yLabel},ticks:{callback:v=>probability?v+" %":v}}
        },
        plugins:{
          datalabels:{display:false},
          legend:{position:"bottom",labels:{
            filter:item=>!item.text.startsWith("GEFS-Mitglied "),
            usePointStyle:true,boxWidth:12
          }},
          tooltip:{callbacks:{
            title:a=>a?.[0]?.label?stamp(a[0].label):"",
            label:c=>c.dataset.label+": "+num(c.parsed.y)+(probability?" %":"")
          }}
        }
      }
    });
    ["telePNG","telePDF","teleCSV"].forEach(id=>$(id).disabled=false);
  }

  function composeData(index,view,horizon) {
    const data=validIndex(), current=data.latest, observations=data.observations;
    const lastValid = current.valid_dates[horizon];
    const observed = (view==="ensemble"||view==="models"?observations:[]).filter(r=>r[0]>=
      new Date(Date.parse(current.init_date+"T00:00:00Z")-35*86400000).toISOString().slice(0,10)
      && r[0]<=lastValid);
    const dateSet = new Set([...observed.map(r=>r[0]),...current.valid_dates.slice(0,horizon+1)]);
    if(view==="models" && current.gfs)
      current.gfs.valid_dates.forEach(d=>{if(d<=lastValid && d>=observed[0]?.[0])dateSet.add(d);});
    const dates=[...dateSet].sort();
    const lookup=(dataDates,values)=>new Map(dataDates.map((date,i)=>[date,values[i]]));
    const values=(map)=>dates.map(d=>map.get(d)??null);
    const color=STYLE[index];
    const base={
      observed:lookup(observed.map(x=>x[0]),observed.map(x=>x[1])),
      mean:lookup(current.valid_dates,current.mean),
      p10:lookup(current.valid_dates,current.p10),
      p90:lookup(current.valid_dates,current.p90),
    };
    const sets = [];
    const push=(label,values,color,other={})=>sets.push({label,data:values,borderColor:color,backgroundColor:color,...other});
    const axisLabel = view==="probability" ? "Ensembleanteil (%)" : "Standardisierter CPC-Index (σ)";
    if(view!=="probability"){
      push("CPC-Beobachtung",values(base.observed),"#151e35",{borderWidth:2.6});
    }
    if(view==="ensemble"){
      push("10. Perzentil",values(base.p10),"rgba(24,104,174,.35)",{borderWidth:1,borderDash:[3,3]});
      push("90. Perzentil",values(base.p90),"rgba(24,104,174,.35)",{
        borderWidth:1,borderDash:[3,3],fill:{target:sets.length-1,above:"rgba(24,104,174,.14)",below:"rgba(24,104,174,.14)"}
      });
      if(checkbox("teleMembers")){
        for(const [member,arr] of Object.entries(current.members)){
          push("GEFS-Mitglied "+member,values(lookup(current.valid_dates,arr)),"rgba(85,106,130,.23)",{borderWidth:.9});
        }
      }
      push("GEFS-Mittel",values(base.mean),color,{borderWidth:3});
      if(checkbox("teleGfs") && current.gfs)
        push("GFS-Hauptlauf",values(lookup(current.gfs.valid_dates,current.gfs.values)),"#b23b42",{borderWidth:2,borderDash:[7,4]});
    }else if(view==="models"){
      push("GEFS-Ensemblemittel",values(base.mean),color,{borderWidth:3});
      if(current.gfs)
        push("GFS-Hauptlauf",values(lookup(current.gfs.valid_dates,current.gfs.values)),"#b23b42",{borderWidth:2.7});
    }else if(view==="runs"){
      const previous=data.previous_runs.slice(0,Number(selection("teleCompareRuns"))-1);
      previous.forEach((run,i)=>{
        const shade=0.28+0.09*i;
        push("GEFS "+run.init_date,values(lookup(run.valid_dates,run.mean)),
          "rgba(95,111,132,"+shade+")",{borderWidth:1.6,borderDash:[5,3]});
      });
      push("Aktueller Lauf "+current.init_date,values(base.mean),color,{borderWidth:3});
    }else if(view==="probability"){
      const names=[
        ["negative","NAO/AO negativ (<0)","#266fb3"],
        ["positive","NAO/AO positiv (≥0)","#b35e2f"],
        ["strong_negative","Deutlich negativ (≤−1)","#274aa7"],
        ["strong_positive","Deutlich positiv (≥+1)","#b33236"]
      ];
      for(const [key,label,c] of names)
        push(label.replace("NAO/AO",index.toUpperCase()),values(lookup(current.valid_dates,current.probability[key])),c,
          {borderWidth:key.startsWith("strong")?1.6:2.6,borderDash:key.startsWith("strong")?[5,3]:[]});
    }
    // CSV exports the displayed dates and all visible lines, including every GEFS member.
    exportRows=[["Datum",...sets.map(s=>s.label)],...dates.map((d,i)=>[d,...sets.map(s=>s.data[i])])];
    exportTitle=index.toUpperCase()+" · "+selection("teleView")+" · NOAA/CPC · GEFS "+current.init_date;
    return {dates,sets,axisLabel};
  }

  function render() {
    if(!archive)return;
    try{
      const index=selection("teleIndex"),view=selection("teleView"),horizon=Number(selection("teleDays"));
      const entry=validIndex();
      if(!entry?.latest?.members || !entry.observations?.length)throw Error("Der Datensatz ist unvollständig.");
      const lastDate=entry.latest.init_date;
      if(Date.parse(lastDate+"T00:00:00Z")<Date.now()-6*86400000)
        throw Error("Die NOAA-Prognose ist nicht mehr aktuell: "+lastDate);
      const data=composeData(index,view,horizon);
      switchChart(data.dates,data.sets,data.axisLabel,view==="probability");
      for(const option of $("teleDay").options)option.disabled=Number(option.value)>horizon;
      if(Number(selection("teleDay"))>horizon)$("teleDay").value=String(horizon);
      const day=Number(selection("teleDay"));
      const p=entry.latest.probability;
      $("teleKpis").innerHTML=
        statsCard("GEFS-Modelllauf",entry.latest.init_date,"NOAA/CPC · Datum, UTC-Stunde nicht ausgewiesen")+
        statsCard("Tag +"+day+" · "+stamp(entry.latest.valid_dates[day]),num(entry.latest.mean[day]),"Ensemblemittel · Index")+
        statsCard("Negative Phase",num(p.negative[day])+" %","Anteil mit Index < 0 · "+entry.latest.member_count[day]+" Member")+
        statsCard("Deutlich negativ",num(p.strong_negative[day])+" %","Anteil mit Index ≤ −1");
      $("teleMeta").textContent="NOAA/CPC GEFS "+entry.latest.init_date+
        " · "+entry.latest.member_count[0]+" von 31 Mitgliedern an Tag 0 · Beobachtungen bis "+
        entry.observation_latest_date+
        " · 10.–90. Perzentil aus den verfügbaren Membern. Prognosewerte nicht als Beobachtung interpretieren."+
        (entry.latest.gfs?" GFS-Lauf: "+entry.latest.gfs.init_date+".":" GFS derzeit nicht verfügbar.")+
        " Ein ECMWF-Vergleich wird erst nach gleicher Indexdefinition und geprüfter Datenverfügbarkeit eingeblendet.";
      $("teleRunCompare").hidden=view!=="runs";
      $("teleMembersWrap").hidden=view!=="ensemble";
      $("teleGfsWrap").hidden=view!=="ensemble";
      $("teleDayWrap").hidden=false;
      status(index.toUpperCase()+" · echte CPC-Indexprognosen · aktualisiert "+archive.generated_at.slice(0,16).replace("T"," ")+" UTC",false);
      lastError="";
    }catch(error){
      console.error(error);lastError=error.message;
      status("Prognose nicht verfügbar: "+error.message,true);
      ["telePNG","telePDF","teleCSV"].forEach(id=>$(id).disabled=true);
      chart?.destroy();chart=null;
    }
  }

  function fileBase(){
    return "nao_ao_"+selection("teleIndex")+"_"+selection("teleView")+"_"+
      (archive?.indices?.[selection("teleIndex")]?.latest?.init_date||"unknown");
  }
  function download(blob,ext){
    const url=globalThis.URL.createObjectURL(blob),a=document.createElement("a");
    a.download=fileBase()+"."+ext;a.href=url;document.body.appendChild(a);a.click();a.remove();
    setTimeout(()=>globalThis.URL.revokeObjectURL(url),1800);
  }
  function csv(){
    if(!exportRows.length)return;
    const content="\ufeff"+exportRows.map(r=>r.map(x=>'"'+String(x??"").replace(/"/g,'""')+'"').join(";")).join("\r\n");
    download(new Blob([content],{type:"text/csv;charset=utf-8"}),"csv");
  }
  function png(){
    if(!chart)return;
    const source=chart.canvas,w=1700,plotHeight=Math.round(w*source.height/source.width);
    const c=document.createElement("canvas");c.width=w;c.height=plotHeight+220;
    const g=c.getContext("2d");g.fillStyle="#fff";g.fillRect(0,0,c.width,c.height);
    g.fillStyle="#142b43";g.font="bold 34px Arial";g.fillText(exportTitle,60,60);
    g.fillStyle="#516274";g.font="22px Arial";
    g.fillText("Quelle: NOAA Climate Prediction Center · "+archive.generated_at.slice(0,10),60,103);
    g.drawImage(source,50,135,1600,plotHeight);
    g.font="17px Arial";g.fillText("Originale CPC-Indexwerte · GEFS 31 Member · keine Glättung durch das Dashboard",60,c.height-30);
    c.toBlob(blob=>{if(blob)download(blob,"png");},"image/png");
  }
  function rgb(value){
    if(value.startsWith("#")){
      let v=value.slice(1);if(v.length===3)v=v.split("").map(x=>x+x).join("");
      return [parseInt(v.slice(0,2),16),parseInt(v.slice(2,4),16),parseInt(v.slice(4,6),16)];
    }
    const m=value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    return m?[+m[1],+m[2],+m[3]]:[75,94,116];
  }
  function pdf(){
    if(!chart || !window.jspdf?.jsPDF){status("Vektor-PDF-Export nicht verfügbar.",true);return;}
    // Rebuild paths as true PDF strokes: Illustrator/After Effects can edit
    // the individual member lines; no embedded screenshot of the plot.
    const p=new window.jspdf.jsPDF({orientation:"landscape",unit:"mm",format:"a4"});
    const left=22,top=40,w=257,h=133;
    const yAxis=chart.scales.y, min=yAxis.min,max=yAxis.max;
    const sx=i=>left+(i/Math.max(1,chart.data.labels.length-1))*w;
    const sy=v=>top+h-(v-min)/Math.max(.001,max-min)*h;
    p.setFillColor(255,255,255);p.rect(0,0,297,210,"F");
    p.setFontSize(15);p.setTextColor(20,43,67);p.text(exportTitle.slice(0,96),left,16);
    p.setFontSize(9);p.setTextColor(78,93,111);
    p.text("Quelle NOAA/CPC · Datenstand "+archive.generated_at.slice(0,16).replace("T"," ")+" UTC · echte Vektorkurven",left,24);
    p.setDrawColor(205,215,226);p.setLineWidth(.2);p.rect(left,top,w,h);
    for(let k=0;k<=5;k++){
      const v=min+(max-min)*k/5,y=sy(v);
      p.setDrawColor(230,234,242);p.line(left,y,left+w,y);
      p.setFontSize(8);p.setTextColor(70,85,105);p.text(num(v),left-3,y+1,{align:"right"});
    }
    for(let k=0;k<6;k++){
      const i=Math.round((chart.data.labels.length-1)*k/5),x=sx(i);
      p.setTextColor(70,85,105);p.setFontSize(8);
      p.text(stamp(chart.data.labels[i]),x,top+h+7,{align:"center"});
    }
    const ref=selection("teleView")==="probability"?50:0;
    if(ref>=min && ref<=max){
      p.setDrawColor(110,119,134);p.setLineWidth(.24);p.setLineDashPattern([1.3,1.4],0);
      p.line(left,sy(ref),left+w,sy(ref));p.setLineDashPattern([],0);
    }
    chart.data.datasets.forEach((set,i)=>{
      if(!chart.isDatasetVisible(i))return;
      const c=rgb(set.borderColor||"#60738a");p.setDrawColor(...c);
      p.setLineWidth(set.label.startsWith("GEFS-Mitglied")?.12:set.borderWidth>=3?.7:.38);
      if(set.borderDash?.length)p.setLineDashPattern([1.4,1.0],0);else p.setLineDashPattern([],0);
      // One continuous stroke per uninterrupted member curve. This preserves
      // a selectable/editable vector path rather than hundreds of line segments.
      const commands=[];let contiguous=false;
      set.data.forEach((v,j)=>{
        if(!Number.isFinite(v)){contiguous=false;return;}
        const xy=[sx(j),sy(v)];
        commands.push({op:contiguous?"l":"m",c:xy});
        contiguous=true;
      });
      if(commands.some(x=>x.op==="l"))p.path(commands,"S");
    });
    p.setLineDashPattern([],0);
    p.setFontSize(8);p.setTextColor(80,90,108);
    p.text("Einzelne Kurven sind separate PDF-Vektorpfade. Farben und Beschriftungen entsprechen der Ansicht.",left,196);
    p.save(fileBase()+".pdf");
  }
  async function init(){
    const root=$("naoAoForecast");if(!root)return;
    for(const id of ["teleIndex","teleView","teleDays","teleDay","teleCompareRuns","teleMembers","teleGfs"]){
      $(id).addEventListener("change",render);
    }
    $("telePNG").addEventListener("click",png);
    $("telePDF").addEventListener("click",pdf);
    $("teleCSV").addEventListener("click",csv);
    $("teleReload").addEventListener("click",()=>load());
    await load();
  }
  async function load(){
    status("Prüfe das veröffentlichte NOAA/CPC-Ensemblearchiv …",false);
    try{
      const resp=await fetch(URL+"?t="+Date.now(),{cache:"no-store"});
      if(!resp.ok)throw Error("HTTP "+resp.status+" – Datenimport noch nicht veröffentlicht");
      const doc=await resp.json();
      if(doc.schema!==1||!doc.ready||!doc.indices?.nao?.latest||!doc.indices?.ao?.latest)
        throw Error("Der veröffentlichte Prognosedatensatz ist unvollständig.");
      archive=doc;render();
    }catch(error){
      archive=null;lastError=error.message;
      status("Echte NOAA-Prognosedaten fehlen noch: "+error.message,true);
      ["telePNG","telePDF","teleCSV"].forEach(id=>$(id).disabled=true);
    }
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();
