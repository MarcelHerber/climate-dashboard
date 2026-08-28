/* MONTHLY_FREQUENCY_DISTRIBUTION_V4 */
(function(){
  "use strict";

  const BIN_STEP=0.5;
  const INDIVIDUAL_CURVE_WIDTH=0.1;
  const BLUE="#2b6f8e";
  const RED="#c43b2f";

  function average(values){return values.length?values.reduce((sum,value)=>sum+value,0)/values.length:null;}
  function median(values){
    const sorted=values.filter(Number.isFinite).slice().sort((a,b)=>a-b);
    if(!sorted.length)return null;
    const mid=Math.floor(sorted.length/2);
    return sorted.length%2?sorted[mid]:(sorted[mid-1]+sorted[mid])/2;
  }
  function sampleStdDev(values){
    if(values.length<2)return null;
    const avg=average(values);
    return Math.sqrt(values.reduce((sum,value)=>sum+(value-avg)**2,0)/(values.length-1));
  }
  function parameterConfig(param){
    const configs={
      temp:{param:"temp",label:"Temperatur",unit:"°C",decimals:2,showNormal:true,curveWidth:INDIVIDUAL_CURVE_WIDTH},
      rain:{param:"rain",label:"Niederschlag",unit:"mm",decimals:1,showNormal:false},
      sun:{param:"sun",label:"Sonnenscheindauer",unit:"h",decimals:1,showNormal:false}
    };
    return configs[param]||configs.temp;
  }
  function classStep(param,values=[]){
    if(param==="temp")return BIN_STEP;
    const clean=values.filter(Number.isFinite);
    const span=clean.length?Math.max(...clean)-Math.min(...clean):0;
    if(param==="rain"){
      if(span<=80)return 5;
      if(span<=180)return 10;
      if(span<=400)return 20;
      if(span<=700)return 25;
      return 50;
    }
    if(span<=160)return 10;
    if(span<=350)return 20;
    if(span<=800)return 50;
    return 100;
  }
  function normalPoints(values,mode,width,start,end,count=121){
    const avg=average(values),sd=sampleStdDev(values);
    if(!Number.isFinite(avg)||!Number.isFinite(sd)||sd<=0||!Number.isFinite(start)||!Number.isFinite(end)||end<=start)return [];
    const multiplier=mode==="percent"?100:values.length;
    return Array.from({length:count},(_,index)=>{
      const x=start+(end-start)*index/(count-1);
      const y=multiplier*width*Math.exp(-0.5*((x-avg)/sd)**2)/(sd*Math.sqrt(2*Math.PI));
      return {x,y};
    });
  }
  function buildDistribution(valuesA,valuesB,mode,options={}){
    const all=[...valuesA,...valuesB].filter(Number.isFinite);
    if(!all.length)return null;
    const step=Number(options.step)||BIN_STEP;
    const showNormal=options.showNormal!==false;
    let start=Math.floor(Math.min(...all)/step)*step-step;
    let end=Math.ceil(Math.max(...all)/step)*step+step;
    if(end-start<step*4){start-=step;end+=step;}
    const count=Math.round((end-start)/step)+1;
    const centers=Array.from({length:count},(_,index)=>Number((start+index*step).toFixed(6)));
    const histogram=values=>{
      const bins=Array(centers.length).fill(0);
      values.forEach(value=>{
        const index=Math.max(0,Math.min(centers.length-1,Math.round((value-start)/step)));
        bins[index]+=1;
      });
      return mode==="percent"&&values.length?bins.map(value=>100*value/values.length):bins;
    };
    const histA=histogram(valuesA),histB=histogram(valuesB);
    return {
      centers,histA,histB,
      pointsA:centers.map((x,i)=>({x,y:histA[i]})),
      pointsB:centers.map((x,i)=>({x,y:histB[i]})),
      normalA:showNormal?normalPoints(valuesA,mode,step,start,end):[],
      normalB:showNormal?normalPoints(valuesB,mode,step,start,end):[],
      start,end,step
    };
  }
  function buildIndividualBars(rowsA,rowsB,mode,options={}){
    const cleanA=rowsA.filter(row=>Number.isFinite(row?.value));
    const cleanB=rowsB.filter(row=>Number.isFinite(row?.value));
    const combined=[];
    cleanA.forEach(row=>combined.push({period:"A",row}));
    cleanB.forEach(row=>combined.push({period:"B",row}));
    if(!combined.length)return {pointsA:[],pointsB:[],normalA:[],normalB:[],start:null,end:null};

    const step=Number(options.step)||BIN_STEP;
    const showNormal=options.showNormal!==false;
    const spread=Number(options.spread)||Math.min(step*0.16,step/3);
    const padding=Number(options.padding)||step;
    const groups=new Map();
    combined.forEach(item=>{
      const key=Number(item.row.value).toFixed(6);
      if(!groups.has(key))groups.set(key,[]);
      groups.get(key).push(item);
    });
    const weightA=mode==="percent"&&cleanA.length?100/cleanA.length:1;
    const weightB=mode==="percent"&&cleanB.length?100/cleanB.length:1;
    const pointsA=[],pointsB=[];
    groups.forEach(group=>{
      group.sort((a,b)=>a.period.localeCompare(b.period)||Number(a.row.year)-Number(b.row.year));
      const value=Number(group[0].row.value),n=group.length;
      group.forEach((item,index)=>{
        const offset=n===1?0:-spread/2+spread*index/(n-1);
        const point={
          x:Number((value+offset).toFixed(6)),
          y:item.period==="A"?weightA:weightB,
          value,
          year:item.row.year
        };
        (item.period==="A"?pointsA:pointsB).push(point);
      });
    });
    pointsA.sort((a,b)=>a.x-b.x||a.year-b.year);
    pointsB.sort((a,b)=>a.x-b.x||a.year-b.year);
    const valuesA=cleanA.map(row=>row.value),valuesB=cleanB.map(row=>row.value),all=[...valuesA,...valuesB];
    let start=Math.floor((Math.min(...all)-padding)/step)*step;
    let end=Math.ceil((Math.max(...all)+padding)/step)*step;
    if(end-start<step*4){start-=step;end+=step;}
    const curveWidth=Number(options.curveWidth)||INDIVIDUAL_CURVE_WIDTH;
    return {
      pointsA,pointsB,
      normalA:showNormal?normalPoints(valuesA,mode,curveWidth,start,end):[],
      normalB:showNormal?normalPoints(valuesB,mode,curveWidth,start,end):[],
      start,end,step
    };
  }
  function empiricalPercentile(values,value){
    if(!values.length||!Number.isFinite(value))return null;
    const below=values.filter(item=>item<value).length;
    const equal=values.filter(item=>item===value).length;
    return 100*(below+0.5*equal)/values.length;
  }
  function exportSlug(value){
    return String(value??"").toLowerCase().replace(/ß/g,"ss").normalize("NFD")
      .replace(/[\u0300-\u036f]/g,"").replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"")||"export";
  }
  function exportFilename(area,period,rangeA,rangeB,extension,param="temp"){
    const ext=String(extension||"png").replace(/^\./,"").toLowerCase();
    const config=parameterConfig(param);
    return `haeufigkeitsverteilung_${exportSlug(config.label)}_${exportSlug(area)}_${exportSlug(period)}_${rangeA.start}-${rangeA.end}_vs_${rangeB.start}-${rangeB.end}.${ext}`;
  }

  globalThis.__monthlyFrequencyTestApi={
    buildDistribution,buildIndividualBars,empiricalPercentile,average,median,sampleStdDev,
    parameterConfig,classStep,exportFilename
  };
  if(typeof document==="undefined"||typeof Chart==="undefined")return;

  let chart=null;
  let mode="classic";
  let dataWaitTimer=null;

  const css=`
  .monthly-frequency-switch{display:inline-flex;gap:4px;margin:0 0 18px;padding:4px;border:1px solid #d6dde3;border-radius:9px;background:#eef2f5}
  .monthly-frequency-switch button{appearance:none;border:0;border-radius:6px;padding:9px 14px;background:transparent;color:#465568;font:700 13px/1.2 Arial,sans-serif;cursor:pointer}
  .monthly-frequency-switch button.active{background:#fff;color:#17253a;box-shadow:0 1px 4px rgba(15,23,42,.12)}
  #monthly.monthly-frequency-active>.monthly-frequency-classic-node{display:none!important}
  #monthly.monthly-frequency-active .monthly-frequency-classic-control{display:none!important}
  .monthly-frequency-card{margin:0 0 22px;padding:20px;border:1px solid var(--border);border-radius:8px;background:var(--card);box-shadow:var(--shadow)}
  .monthly-frequency-card[hidden]{display:none!important}
  .monthly-frequency-head{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px;margin-bottom:16px}
  .monthly-frequency-head h2{margin:0 0 5px;font-size:22px}.monthly-frequency-head p{margin:0;color:var(--muted);line-height:1.5}
  .monthly-frequency-badge{align-self:flex-start;padding:5px 9px;border-radius:999px;background:#eef3f7;color:#455568;font-size:11px;font-weight:700;white-space:nowrap}
  .monthly-frequency-controls{display:grid;grid-template-columns:repeat(2,minmax(220px,1fr)) repeat(3,minmax(155px,.55fr));gap:14px;margin-bottom:16px}
  .monthly-frequency-period,.monthly-frequency-scale{padding:14px;border:1px solid #dfe4e8;border-radius:8px;background:#f9fafb}
  .monthly-frequency-period-a{border-top:3px solid ${BLUE}}.monthly-frequency-period-b{border-top:3px solid ${RED}}
  .monthly-frequency-period h3{margin:0 0 10px;font-size:15px}
  .monthly-frequency-period label,.monthly-frequency-scale label{display:block;margin:0 0 5px;color:#46515f;font-size:12px;font-weight:700}
  .monthly-frequency-period select,.monthly-frequency-period input,.monthly-frequency-scale select{width:100%;padding:8px 9px;border:1px solid #b9c0c7;border-radius:6px;background:#fff;font:inherit}
  .monthly-frequency-custom{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}.monthly-frequency-custom[hidden]{display:none!important}
  .monthly-frequency-scale .control-hint{margin-top:8px;line-height:1.4}
  .monthly-frequency-chart-wrap{min-height:500px;margin:16px 0;padding:16px;border:1px solid #e1e5e8;border-radius:8px;background:#fff}
  .monthly-frequency-chart-wrap canvas{width:100%!important;height:465px!important}
  .monthly-frequency-stats{display:grid;grid-template-columns:repeat(5,minmax(145px,1fr));gap:10px;margin-top:14px}
  .monthly-frequency-stat{min-height:108px;padding:13px;border:1px solid #e0e5e9;border-radius:7px;background:#fafbfc}
  .monthly-frequency-stat .label{font-size:11px;font-weight:700;color:#5f6b7a;line-height:1.35}
  .monthly-frequency-stat .value{margin:13px 0 4px;font-size:21px;font-weight:740;font-variant-numeric:tabular-nums}
  .monthly-frequency-stat .detail{font-size:11px;color:#748092;line-height:1.4}
  .monthly-frequency-stat.period-a .value{color:${BLUE}}.monthly-frequency-stat.period-b .value{color:${RED}}
  .monthly-frequency-note{margin:14px 0 0;color:var(--muted);font-size:12px;line-height:1.5}
  .monthly-frequency-export-bar{display:flex;justify-content:flex-end;gap:8px;margin:-2px 0 14px}
  .monthly-frequency-export-btn{appearance:none;border:1px solid #b9c0c7;border-radius:6px;padding:8px 12px;background:#fff;color:#223041;font:700 12px/1 Arial,sans-serif;cursor:pointer;box-shadow:0 1px 4px rgba(15,23,42,.08)}
  .monthly-frequency-export-btn:hover{background:#f0f3f5;border-color:#8e969e}
  .monthly-frequency-export-btn:focus-visible{outline:3px solid rgba(40,100,180,.28);outline-offset:2px}
  .monthly-frequency-export-btn[disabled]{opacity:.55;cursor:wait}
  .monthly-frequency-exporting .monthly-frequency-controls,.monthly-frequency-exporting .monthly-frequency-export-bar{display:none!important}
  .monthly-frequency-exporting{background:#fff!important;box-shadow:none!important}
  @media(max-width:1250px){.monthly-frequency-controls{grid-template-columns:1fr 1fr 1fr}.monthly-frequency-stats{grid-template-columns:repeat(2,minmax(0,1fr))}}
  @media(max-width:760px){.monthly-frequency-controls{grid-template-columns:1fr}.monthly-frequency-switch{display:flex;width:100%}.monthly-frequency-switch button{flex:1;padding:9px 7px}.monthly-frequency-card{padding:14px}.monthly-frequency-stats{grid-template-columns:1fr}.monthly-frequency-chart-wrap{min-height:430px;padding:8px}.monthly-frequency-chart-wrap canvas{height:405px!important}.monthly-frequency-export-bar{justify-content:stretch}.monthly-frequency-export-btn{flex:1}}
  `;

  const presets=`<option value="1881-1910">1881–1910</option><option value="1911-1940">1911–1940</option><option value="1941-1970">1941–1970</option><option value="1961-1990">1961–1990</option><option value="1971-2000">1971–2000</option><option value="1981-2010">1981–2010</option><option value="1991-2020">1991–2020</option><option value="custom">Freie Auswahl …</option>`;

  function injectStyle(){
    if(document.getElementById("monthlyFrequencyStyles"))return;
    const style=document.createElement("style");
    style.id="monthlyFrequencyStyles";
    style.textContent=css;
    document.head.appendChild(style);
  }
  function frequencyHtml(){return `
      <div class="monthly-frequency-head">
        <div><h2 id="monthlyFrequencyTitle">Häufigkeitsverteilung der Temperatur</h2><p id="monthlyFrequencySubtitle">Zwei historische Zeiträume direkt miteinander vergleichen.</p></div>
        <span id="monthlyFrequencyBadge" class="monthly-frequency-badge">Temperatur · DWD-Gebietsmittel</span>
      </div>
      <div class="monthly-frequency-controls">
        <div class="monthly-frequency-period monthly-frequency-period-a"><h3>Zeitraum A</h3><label for="monthlyFrequencyPresetA">Auswahl</label><select id="monthlyFrequencyPresetA">${presets}</select><div id="monthlyFrequencyCustomA" class="monthly-frequency-custom" hidden><div><label for="monthlyFrequencyStartA">Startjahr</label><input id="monthlyFrequencyStartA" type="number" min="1881" max="2100" step="1" value="1881"></div><div><label for="monthlyFrequencyEndA">Endjahr</label><input id="monthlyFrequencyEndA" type="number" min="1881" max="2100" step="1" value="1910"></div></div></div>
        <div class="monthly-frequency-period monthly-frequency-period-b"><h3>Zeitraum B</h3><label for="monthlyFrequencyPresetB">Auswahl</label><select id="monthlyFrequencyPresetB">${presets}</select><div id="monthlyFrequencyCustomB" class="monthly-frequency-custom" hidden><div><label for="monthlyFrequencyStartB">Startjahr</label><input id="monthlyFrequencyStartB" type="number" min="1881" max="2100" step="1" value="1991"></div><div><label for="monthlyFrequencyEndB">Endjahr</label><input id="monthlyFrequencyEndB" type="number" min="1881" max="2100" step="1" value="2020"></div></div></div>
        <div class="monthly-frequency-scale"><label for="monthlyFrequencyParam">Parameter</label><select id="monthlyFrequencyParam"><option value="temp" selected>Temperatur</option><option value="rain">Niederschlag</option><option value="sun">Sonnenscheindauer</option></select><div class="control-hint">Niederschlag in mm, Sonnenschein in Stunden.</div></div>
        <div class="monthly-frequency-scale"><label for="monthlyFrequencyDisplay">Darstellung</label><select id="monthlyFrequencyDisplay"><option value="individual" selected>Einzelwerte</option><option id="monthlyFrequencyBinsOption" value="bins">0,5-°C-Klassen</option></select><div class="control-hint">Einzelwerte zeigt jedes Jahr als eigenen schmalen Balken.</div></div>
        <div class="monthly-frequency-scale"><label for="monthlyFrequencyScale">Y-Achse</label><select id="monthlyFrequencyScale"><option value="auto" selected>Automatisch</option><option value="count">Anzahl der Jahre</option><option value="percent">Häufigkeit in %</option></select><div class="control-hint">Automatisch verwendet bei gleich vielen auswertbaren Jahren die Anzahl, sonst Prozent.</div></div>
      </div>
      <div class="monthly-frequency-export-bar" aria-label="Export der Häufigkeitsverteilung"><button id="monthlyFrequencyPngButton" class="monthly-frequency-export-btn" type="button">PNG</button><button id="monthlyFrequencyPdfButton" class="monthly-frequency-export-btn" type="button">PDF</button></div>
      <div id="monthlyFrequencySummary" class="summary-box">Häufigkeitsverteilung wird berechnet …</div>
      <div class="monthly-frequency-chart-wrap"><canvas id="monthlyFrequencyChart"></canvas></div>
      <div class="monthly-frequency-stats">
        <div class="monthly-frequency-stat period-a"><div id="monthlyFrequencyLabelA" class="label">Zeitraum A</div><div id="monthlyFrequencyMeanA" class="value">–</div><div id="monthlyFrequencyDetailA" class="detail">–</div></div>
        <div class="monthly-frequency-stat period-b"><div id="monthlyFrequencyLabelB" class="label">Zeitraum B</div><div id="monthlyFrequencyMeanB" class="value">–</div><div id="monthlyFrequencyDetailB" class="detail">–</div></div>
        <div class="monthly-frequency-stat"><div class="label">Verschiebung B − A</div><div id="monthlyFrequencyShift" class="value">–</div><div id="monthlyFrequencyShiftDetail" class="detail">Differenz der Mittelwerte</div></div>
        <div class="monthly-frequency-stat"><div id="monthlyFrequencySpreadLabel" class="label">Streuung σ</div><div id="monthlyFrequencySpread" class="value">–</div><div id="monthlyFrequencySpreadDetail" class="detail">Standardabweichung A / B</div></div>
        <div class="monthly-frequency-stat"><div id="monthlyFrequencyLatestLabel" class="label">Aktuellster vollständiger Wert</div><div id="monthlyFrequencyLatest" class="value">–</div><div id="monthlyFrequencyLatestDetail" class="detail">Perzentil gegenüber Zeitraum A</div></div>
      </div>
      <p id="monthlyFrequencyNote" class="monthly-frequency-note"></p>`;}

  function setText(id,value){const el=document.getElementById(id);if(el)el.textContent=value;}
  function formatValue(value,param="temp",decimals=null,sign=false){
    if(!Number.isFinite(value))return "–";
    const config=parameterConfig(param),places=decimals===null?config.decimals:decimals;
    return `${sign&&value>0?"+":""}${value.toLocaleString("de-DE",{minimumFractionDigits:places,maximumFractionDigits:places})} ${config.unit}`;
  }
  function range(which){
    const preset=document.getElementById(`monthlyFrequencyPreset${which}`)?.value||"custom";
    if(preset!=="custom"&&/^\d{4}-\d{4}$/.test(preset)){
      const [start,end]=preset.split("-").map(Number);
      return {start,end,label:`${start}–${end}`};
    }
    const start=Math.round(Number(document.getElementById(`monthlyFrequencyStart${which}`)?.value));
    const end=Math.round(Number(document.getElementById(`monthlyFrequencyEnd${which}`)?.value));
    return {start,end,label:Number.isFinite(start)&&Number.isFinite(end)?`${start}–${end}`:"freie Auswahl"};
  }
  function syncPreset(which){
    const select=document.getElementById(`monthlyFrequencyPreset${which}`);
    const custom=document.getElementById(`monthlyFrequencyCustom${which}`);
    if(!select||!custom)return;
    const isCustom=select.value==="custom";
    custom.hidden=!isCustom;
    if(!isCustom){
      const [start,end]=select.value.split("-").map(Number);
      document.getElementById(`monthlyFrequencyStart${which}`).value=start;
      document.getElementById(`monthlyFrequencyEnd${which}`).value=end;
    }
  }
  function ensureParameterRange(param){
    if(param!=="sun")return;
    const current=range("A");
    if(current.end>=1951)return;
    const preset=document.getElementById("monthlyFrequencyPresetA");
    if(preset){preset.value="1961-1990";syncPreset("A");}
  }
  function filterRange(series,r){return Number.isFinite(r.start)&&Number.isFinite(r.end)&&r.start<=r.end?series.filter(item=>item.year>=r.start&&item.year<=r.end):[];}
  function updateBounds(series){
    if(!series.length)return;
    const min=Math.min(...series.map(item=>item.year)),max=Math.max(...series.map(item=>item.year));
    for(const which of ["A","B"])for(const part of ["Start","End"]){
      const input=document.getElementById(`monthlyFrequency${part}${which}`);
      if(input){input.min=min;input.max=max;}
    }
  }
  function dataReady(){try{return Array.isArray(monthlyData)&&monthlyData.length>0&&typeof seriesFor==="function";}catch(_error){return false;}}

  const referenceLinesPlugin={
    id:"monthlyFrequencyReferenceLinesV4",
    afterDatasetsDraw(activeChart){
      if(activeChart.canvas.id!=="monthlyFrequencyChart"||!activeChart.$frequencyMeta)return;
      const {ctx,chartArea,scales:{x}}=activeChart,meta=activeChart.$frequencyMeta;
      if(!chartArea||!x)return;
      ctx.save();
      (meta.lines||[]).forEach((item,index)=>{
        if(!Number.isFinite(item.value))return;
        const pixel=x.getPixelForValue(item.value);
        if(pixel<chartArea.left||pixel>chartArea.right)return;
        ctx.strokeStyle=item.color;
        ctx.lineWidth=item.width||1.5;
        ctx.setLineDash(item.dash||[5,4]);
        ctx.beginPath();ctx.moveTo(pixel,chartArea.top);ctx.lineTo(pixel,chartArea.bottom);ctx.stroke();
        ctx.setLineDash([]);
        ctx.font="700 11px Arial";ctx.textBaseline="top";ctx.textAlign=index%2===0?"right":"left";ctx.fillStyle=item.color;
        ctx.fillText(`${item.prefix||"Ø"} ${item.label}`,pixel+(index%2===0?-5:5),chartArea.top+5+index*14);
      });
      ctx.restore();
    }
  };

  function exportContext(){
    const area=document.getElementById("monthlyAreaSelect")?.value||"Deutschland";
    const selection=document.getElementById("monthSelect")?.value||"Jahr";
    const param=document.getElementById("monthlyFrequencyParam")?.value||"temp";
    return {area,period:typeof periodLabel==="function"?periodLabel(selection):selection,param,rangeA:range("A"),rangeB:range("B")};
  }
  async function monthlyFrequencyExportCanvas(){
    const node=document.getElementById("monthlyFrequencyView");
    if(!node)throw new Error("Exportbereich nicht gefunden.");
    if(typeof html2canvas!=="function")throw new Error("html2canvas ist nicht geladen.");
    node.classList.add("monthly-frequency-exporting");
    try{
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
      return await html2canvas(node,{backgroundColor:"#ffffff",scale:2,useCORS:true,logging:false});
    }finally{node.classList.remove("monthly-frequency-exporting");}
  }
  function triggerDownload(href,filename){
    const link=document.createElement("a");link.href=href;link.download=filename;link.style.display="none";
    document.body.appendChild(link);link.click();link.remove();
  }
  async function downloadMonthlyFrequencyPng(){
    const canvas=await monthlyFrequencyExportCanvas(),context=exportContext();
    const filename=exportFilename(context.area,context.period,context.rangeA,context.rangeB,"png",context.param);
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,"image/png",1));
    if(!blob)throw new Error("PNG konnte nicht erzeugt werden.");
    const url=URL.createObjectURL(blob);
    try{triggerDownload(url,filename);}finally{setTimeout(()=>URL.revokeObjectURL(url),1500);}
  }
  async function downloadMonthlyFrequencyPdf(){
    const canvas=await monthlyFrequencyExportCanvas(),jsPDFCtor=window.jspdf?.jsPDF;
    if(!jsPDFCtor)throw new Error("jsPDF ist nicht geladen.");
    const pdf=new jsPDFCtor({orientation:"landscape",unit:"mm",format:"a4"});
    const pageWidth=pdf.internal.pageSize.getWidth(),pageHeight=pdf.internal.pageSize.getHeight(),margin=8;
    const maxWidth=pageWidth-margin*2,maxHeight=pageHeight-margin*2;
    const ratio=Math.min(maxWidth/canvas.width,maxHeight/canvas.height),width=canvas.width*ratio,height=canvas.height*ratio;
    const x=(pageWidth-width)/2,y=(pageHeight-height)/2;
    pdf.addImage(canvas.toDataURL("image/png"),"PNG",x,y,width,height,undefined,"FAST");
    const context=exportContext();
    pdf.save(exportFilename(context.area,context.period,context.rangeA,context.rangeB,"pdf",context.param));
  }
  async function runExport(button,kind){
    if(!button)return;
    const old=button.textContent;button.disabled=true;button.textContent=`${kind} …`;
    try{if(kind==="PNG")await downloadMonthlyFrequencyPng();else await downloadMonthlyFrequencyPdf();}
    catch(error){console.error(`Häufigkeitsverteilung ${kind}-Export:`,error);window.alert(`${kind} konnte nicht erstellt werden: ${error.message}`);}
    finally{button.disabled=false;button.textContent=old;}
  }

  function render(){
    if(mode!=="frequency")return;
    const monthly=document.getElementById("monthly");
    if(!monthly?.classList.contains("active"))return;
    if(!dataReady()){
      setText("monthlyFrequencySummary","Monatsdaten werden noch geladen …");
      clearTimeout(dataWaitTimer);dataWaitTimer=setTimeout(render,500);return;
    }

    const area=document.getElementById("monthlyAreaSelect")?.value||"Deutschland";
    const selection=document.getElementById("monthSelect")?.value||"07";
    const param=document.getElementById("monthlyFrequencyParam")?.value||"temp";
    const config=parameterConfig(param);
    ensureParameterRange(param);
    const series=seriesFor(area,selection,param);
    updateBounds(series);syncPreset("A");syncPreset("B");
    const rangeA=range("A"),rangeB=range("B");

    if(!Number.isFinite(rangeA.start)||!Number.isFinite(rangeA.end)||rangeA.start>rangeA.end||!Number.isFinite(rangeB.start)||!Number.isFinite(rangeB.end)||rangeB.start>rangeB.end){
      setText("monthlyFrequencySummary","Bitte für beide Vergleichszeiträume ein gültiges Start- und Endjahr wählen.");
      if(chart){chart.destroy();chart=null;}return;
    }

    const rowsA=filterRange(series,rangeA),rowsB=filterRange(series,rangeB);
    const valuesA=rowsA.map(item=>item.value),valuesB=rowsB.map(item=>item.value),allValues=[...valuesA,...valuesB];
    const step=classStep(param,allValues);
    const requested=document.getElementById("monthlyFrequencyScale")?.value||"auto";
    const yMode=requested==="auto"?(valuesA.length===valuesB.length?"count":"percent"):requested;
    const display=document.getElementById("monthlyFrequencyDisplay")?.value||"individual";
    const options={step,showNormal:config.showNormal,curveWidth:config.curveWidth,spread:param==="temp"?0.08:Math.min(step*.16,step/3),padding:step};
    const prepared=display==="individual"?buildIndividualBars(rowsA,rowsB,yMode,options):buildDistribution(valuesA,valuesB,yMode,options);

    const meanA=average(valuesA),meanB=average(valuesB),medianA=median(valuesA),medianB=median(valuesB);
    const sdA=sampleStdDev(valuesA),sdB=sampleStdDev(valuesB);
    const shift=Number.isFinite(meanA)&&Number.isFinite(meanB)?meanB-meanA:null;
    const latest=series.at(-1)||null,pctl=latest?empiricalPercentile(valuesA,latest.value):null;
    const minA=valuesA.length?Math.min(...valuesA):null,maxA=valuesA.length?Math.max(...valuesA):null;
    const minB=valuesB.length?Math.min(...valuesB):null,maxB=valuesB.length?Math.max(...valuesB):null;

    setText("monthlyFrequencyTitle",`Häufigkeitsverteilung ${config.label}`);
    setText("monthlyFrequencyBadge",`${config.label} · DWD-Gebietsmittel`);
    setText("monthlyFrequencySubtitle",`${area} · ${periodLabel(selection)} · ${config.label}`);
    setText("monthlyFrequencyLabelA",`Zeitraum A · ${rangeA.label}`);
    setText("monthlyFrequencyLabelB",`Zeitraum B · ${rangeB.label}`);
    setText("monthlyFrequencyMeanA",formatValue(meanA,param));
    setText("monthlyFrequencyMeanB",formatValue(meanB,param));

    if(config.showNormal){
      setText("monthlyFrequencyDetailA",`${valuesA.length} auswertbare Jahre · σ ${formatValue(sdA,param)}`);
      setText("monthlyFrequencyDetailB",`${valuesB.length} auswertbare Jahre · σ ${formatValue(sdB,param)}`);
      setText("monthlyFrequencySpreadLabel","Streuung σ");
      setText("monthlyFrequencySpread",Number.isFinite(sdA)&&Number.isFinite(sdB)?`${formatValue(sdA,param)} / ${formatValue(sdB,param)}`:"–");
    }else{
      setText("monthlyFrequencyDetailA",`${valuesA.length} Jahre · Median ${formatValue(medianA,param)} · Min/Max ${formatValue(minA,param)} / ${formatValue(maxA,param)}`);
      setText("monthlyFrequencyDetailB",`${valuesB.length} Jahre · Median ${formatValue(medianB,param)} · Min/Max ${formatValue(minB,param)} / ${formatValue(maxB,param)}`);
      setText("monthlyFrequencySpreadLabel","Median A / B");
      setText("monthlyFrequencySpread",Number.isFinite(medianA)&&Number.isFinite(medianB)?`${formatValue(medianA,param)} / ${formatValue(medianB,param)}`:"–");
    }
    setText("monthlyFrequencySpreadDetail",`${rangeA.label} / ${rangeB.label}`);
    setText("monthlyFrequencyShift",formatValue(shift,param,config.decimals,true));
    setText("monthlyFrequencyShiftDetail",Number.isFinite(shift)?`${rangeB.label} minus ${rangeA.label}`:"nicht berechenbar");
    setText("monthlyFrequencyLatestLabel",latest?`Aktuellster vollständiger Wert · ${latest.year}`:"Aktuellster vollständiger Wert");
    setText("monthlyFrequencyLatest",latest?formatValue(latest.value,param):"–");
    setText("monthlyFrequencyLatestDetail",latest&&Number.isFinite(pctl)?`Perzentil ${pctl.toFixed(1).replace(".",",")} gegenüber ${rangeA.label}`:"Perzentil nicht berechenbar");

    const classText=param==="temp"?"0,5-°C-Klassen":`${step.toLocaleString("de-DE")} ${config.unit}-Klassen`;
    const binsOption=document.getElementById("monthlyFrequencyBinsOption");if(binsOption)binsOption.textContent=classText;
    const axis=yMode==="percent"?"relative Häufigkeit in %":"Anzahl der Jahre";
    const displayLabel=display==="individual"?"Einzelwerte":classText;
    const warning=[valuesA.length<10?`Zeitraum A enthält nur ${valuesA.length} Werte.`:"",valuesB.length<10?`Zeitraum B enthält nur ${valuesB.length} Werte.`:""].filter(Boolean).join(" ");
    setText("monthlyFrequencySummary",`${area} · ${periodLabel(selection)} · ${config.label}: ${rangeA.label} (${valuesA.length} Werte) gegen ${rangeB.label} (${valuesB.length} Werte). Darstellung: ${displayLabel}, ${axis}.${Number.isFinite(shift)?` Mittelwertverschiebung B − A: ${formatValue(shift,param,config.decimals,true)}.`:""}${warning?` ${warning}`:""}`);

    if(config.showNormal){
      setText("monthlyFrequencyNote",display==="individual"
        ?"Jedes Jahr wird als eigener schmaler Balken dargestellt. Gleiche Temperaturwerte werden minimal auseinandergezogen, damit einzelne Jahre sichtbar bleiben; im Tooltip steht der unveränderte Originalwert. Die glatten Linien zeigen angepasste Normalverteilungen. Nur vollständige Monate, Jahreszeiten oder Jahre werden berücksichtigt."
        :"Klassenbreite: 0,5 °C. Die glatten Linien zeigen an Mittelwert und Standardabweichung angepasste Normalverteilungen. Nur vollständige Monate, Jahreszeiten oder Jahre werden berücksichtigt.");
    }else{
      setText("monthlyFrequencyNote",display==="individual"
        ?`Jedes Jahr wird als eigener schmaler Balken dargestellt. Identische Werte werden nur minimal auseinandergezogen; im Tooltip steht der unveränderte Originalwert. Für ${config.label} wird keine Normalverteilung eingezeichnet; Mittelwert und Median werden separat markiert. Nur vollständige Monate, Jahreszeiten oder Jahre werden berücksichtigt.`
        :`Klassenbreite: ${step.toLocaleString("de-DE")} ${config.unit}. Für ${config.label} wird keine Normalverteilung eingezeichnet; Mittelwert und Median werden separat markiert. Nur vollständige Monate, Jahreszeiten oder Jahre werden berücksichtigt.`);
    }

    if(!prepared||!valuesA.length||!valuesB.length){
      if(chart){chart.destroy();chart=null;}
      return;
    }
    if(chart)chart.destroy();

    const datasets=[
      {type:"bar",label:rangeA.label,data:prepared.pointsA,parsing:false,backgroundColor:"rgba(43,111,142,.45)",borderColor:BLUE,borderWidth:1,barThickness:display==="individual"?5:20,order:3},
      {type:"bar",label:rangeB.label,data:prepared.pointsB,parsing:false,backgroundColor:"rgba(196,59,47,.38)",borderColor:RED,borderWidth:1,barThickness:display==="individual"?5:20,order:3}
    ];
    if(config.showNormal){
      datasets.push(
        {type:"line",label:`Normalverteilung ${rangeA.label}`,data:prepared.normalA,parsing:false,borderColor:BLUE,borderWidth:2.4,pointRadius:0,tension:.28,order:1},
        {type:"line",label:`Normalverteilung ${rangeB.label}`,data:prepared.normalB,parsing:false,borderColor:RED,borderWidth:2.4,pointRadius:0,tension:.28,order:1}
      );
    }
    const valueText=value=>`${Number(value).toLocaleString("de-DE",{minimumFractionDigits:config.decimals,maximumFractionDigits:config.decimals})} ${config.unit}`;
    chart=new Chart(document.getElementById("monthlyFrequencyChart"),{
      type:"bar",
      data:{datasets},
      options:{
        responsive:true,maintainAspectRatio:false,interaction:{mode:"nearest",intersect:true},
        plugins:{
          title:{display:true,text:`${area}: ${periodLabel(selection)} – ${config.label}`,font:{size:19}},
          subtitle:{display:true,text:`${rangeA.label} vs. ${rangeB.label} · ${displayLabel}`,font:{size:12}},
          legend:{position:"bottom",labels:{usePointStyle:true,boxWidth:10}},
          datalabels:{display:false},
          tooltip:{callbacks:{
            title:items=>{
              const raw=items[0]?.raw;
              if(display==="individual"&&raw?.year)return valueText(raw.value);
              return valueText(items[0]?.parsed?.x);
            },
            label:context=>{
              const raw=context.raw;
              if(display==="individual"&&raw?.year)return `${context.dataset.label} · ${raw.year}: ${valueText(raw.value)}`;
              return `${context.dataset.label}: ${Number(context.parsed.y).toLocaleString("de-DE",{minimumFractionDigits:yMode==="percent"?1:0,maximumFractionDigits:yMode==="percent"?1:2})}${yMode==="percent"?" %":""}`;
            }
          }}
        },
        scales:{
          x:{type:"linear",min:prepared.start,max:prepared.end,title:{display:true,text:`${config.label} in ${config.unit}`},grid:{display:false},ticks:{maxTicksLimit:18,callback:value=>Number(value).toLocaleString("de-DE",{maximumFractionDigits:config.decimals})}},
          y:{beginAtZero:true,title:{display:true,text:yMode==="percent"?"Häufigkeit (%)":"Anzahl"},ticks:{precision:yMode==="count"?0:1}}
        }
      }
    });
    const lines=[
      {value:meanA,color:BLUE,label:formatValue(meanA,param).replace(` ${config.unit}`,""),prefix:"Ø"},
      {value:meanB,color:RED,label:formatValue(meanB,param).replace(` ${config.unit}`,""),prefix:"Ø"}
    ];
    if(!config.showNormal){
      lines.push(
        {value:medianA,color:BLUE,label:formatValue(medianA,param).replace(` ${config.unit}`,""),prefix:"Med",dash:[2,3],width:1.2},
        {value:medianB,color:RED,label:formatValue(medianB,param).replace(` ${config.unit}`,""),prefix:"Med",dash:[2,3],width:1.2}
      );
    }
    chart.$frequencyMeta={lines};
    chart.update();
  }

  function setMode(next,{persist=true}={}){
    mode=next==="frequency"?"frequency":"classic";
    const monthly=document.getElementById("monthly");
    monthly?.classList.toggle("monthly-frequency-active",mode==="frequency");
    document.getElementById("monthlyFrequencyView").hidden=mode!=="frequency";
    document.getElementById("monthlyFrequencyClassicButton").classList.toggle("active",mode==="classic");
    document.getElementById("monthlyFrequencyButton").classList.toggle("active",mode==="frequency");
    if(mode==="frequency"){
      const classic=document.getElementById("paramSelect")?.value;
      const param=document.getElementById("monthlyFrequencyParam");
      if(param&&["temp","rain","sun"].includes(classic))param.value=classic;
      ensureParameterRange(param?.value||"temp");
      render();
    }else if(chart)setTimeout(()=>chart.resize(),0);
    if(persist&&typeof persistDashboardState==="function")persistDashboardState("monthlyViewMode",mode);
  }

  function init(){
    const monthly=document.getElementById("monthly"),controls=monthly?.querySelector(":scope > .controls");
    if(!monthly||!controls||document.getElementById("monthlyFrequencyView"))return;
    injectStyle();
    [...monthly.children].filter(node=>node!==monthly.firstElementChild&&node!==controls).forEach(node=>node.classList.add("monthly-frequency-classic-node"));
    ["paramSelect","monthlyReferenceSelect","monthlyReferenceCustomGroup","monthlyRollingSelect","monthlyRollingCustomGroup"].forEach(id=>document.getElementById(id)?.closest(".control-group")?.classList.add("monthly-frequency-classic-control"));
    controls.querySelector('button[onclick="resetMonthlyZoom()"]')?.classList.add("monthly-frequency-classic-control");

    const switcher=document.createElement("div");
    switcher.className="monthly-frequency-switch";
    switcher.innerHTML='<button id="monthlyFrequencyClassicButton" class="active" type="button">Zeitreihe &amp; Tabellen</button><button id="monthlyFrequencyButton" type="button">Häufigkeitsverteilung</button>';
    controls.insertAdjacentElement("afterend",switcher);
    const section=document.createElement("section");
    section.id="monthlyFrequencyView";section.className="monthly-frequency-card";section.hidden=true;section.innerHTML=frequencyHtml();
    switcher.insertAdjacentElement("afterend",section);

    document.getElementById("monthlyFrequencyPresetA").value="1881-1910";
    document.getElementById("monthlyFrequencyPresetB").value="1991-2020";
    syncPreset("A");syncPreset("B");
    document.getElementById("monthlyFrequencyClassicButton").addEventListener("click",()=>setMode("classic"));
    document.getElementById("monthlyFrequencyButton").addEventListener("click",()=>setMode("frequency"));
    for(const which of ["A","B"]){
      document.getElementById(`monthlyFrequencyPreset${which}`).addEventListener("change",()=>{syncPreset(which);render();});
      for(const part of ["Start","End"])document.getElementById(`monthlyFrequency${part}${which}`).addEventListener("change",render);
    }
    document.getElementById("monthlyFrequencyScale").addEventListener("change",render);
    document.getElementById("monthlyFrequencyDisplay").addEventListener("change",render);
    document.getElementById("monthlyFrequencyParam").addEventListener("change",event=>{ensureParameterRange(event.target.value);render();});
    document.getElementById("monthlyFrequencyPngButton")?.addEventListener("click",event=>runExport(event.currentTarget,"PNG"));
    document.getElementById("monthlyFrequencyPdfButton")?.addEventListener("click",event=>runExport(event.currentTarget,"PDF"));
    document.getElementById("monthlyAreaSelect")?.addEventListener("change",()=>{if(mode==="frequency")render();});
    document.getElementById("monthSelect")?.addEventListener("change",()=>{if(mode==="frequency")render();});
    new MutationObserver(()=>{if(monthly.classList.contains("active")&&mode==="frequency")setTimeout(()=>{render();chart?.resize();},100);}).observe(monthly,{attributes:true,attributeFilter:["class"]});
    try{setMode(dashboardState?.monthlyViewMode==="frequency"?"frequency":"classic",{persist:false});}
    catch(_error){setMode("classic",{persist:false});}
  }

  try{Chart.register(referenceLinesPlugin);}catch(_error){}
  init();
})();

/* DWD_DAILY_MAP_LOADER_V1 */
(()=>{if(typeof document==="undefined")return;if(document.querySelector('script[data-dwd-daily-map]'))return;const s=document.createElement("script");s.src="dwd_station_daily_map.js?v=3";s.dataset.dwdDailyMap="1";document.body.appendChild(s)})();
