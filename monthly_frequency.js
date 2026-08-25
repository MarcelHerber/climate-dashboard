/* MONTHLY_FREQUENCY_DISTRIBUTION_V3 */
(function(){
  "use strict";

  const BIN_STEP=0.5;
  const INDIVIDUAL_CURVE_WIDTH=0.1;
  const BLUE="#2b6f8e";
  const RED="#c43b2f";

  function average(values){return values.length?values.reduce((sum,value)=>sum+value,0)/values.length:null;}
  function sampleStdDev(values){if(values.length<2)return null;const avg=average(values);return Math.sqrt(values.reduce((sum,value)=>sum+(value-avg)**2,0)/(values.length-1));}
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
  function buildDistribution(valuesA,valuesB,mode){
    const all=[...valuesA,...valuesB].filter(Number.isFinite);if(!all.length)return null;
    let start=Math.floor(Math.min(...all)/BIN_STEP)*BIN_STEP-BIN_STEP;let end=Math.ceil(Math.max(...all)/BIN_STEP)*BIN_STEP+BIN_STEP;
    if(end-start<BIN_STEP*4){start-=BIN_STEP;end+=BIN_STEP;}
    const count=Math.round((end-start)/BIN_STEP)+1,centers=Array.from({length:count},(_,index)=>Number((start+index*BIN_STEP).toFixed(6)));
    const histogram=values=>{const bins=Array(centers.length).fill(0);values.forEach(value=>{const index=Math.max(0,Math.min(centers.length-1,Math.round((value-start)/BIN_STEP)));bins[index]+=1;});return mode==="percent"&&values.length?bins.map(value=>100*value/values.length):bins;};
    const histA=histogram(valuesA),histB=histogram(valuesB);
    return {centers,histA,histB,pointsA:centers.map((x,i)=>({x,y:histA[i]})),pointsB:centers.map((x,i)=>({x,y:histB[i]})),normalA:normalPoints(valuesA,mode,BIN_STEP,start,end),normalB:normalPoints(valuesB,mode,BIN_STEP,start,end),start,end};
  }
  function buildIndividualBars(rowsA,rowsB,mode){
    const cleanA=rowsA.filter(row=>Number.isFinite(row?.value)),cleanB=rowsB.filter(row=>Number.isFinite(row?.value)),combined=[];
    cleanA.forEach(row=>combined.push({period:"A",row}));cleanB.forEach(row=>combined.push({period:"B",row}));
    if(!combined.length)return {pointsA:[],pointsB:[],normalA:[],normalB:[],start:null,end:null};
    const groups=new Map();combined.forEach(item=>{const key=Number(item.row.value).toFixed(6);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item);});
    const weightA=mode==="percent"&&cleanA.length?100/cleanA.length:1,weightB=mode==="percent"&&cleanB.length?100/cleanB.length:1,pointsA=[],pointsB=[];
    groups.forEach(group=>{
      group.sort((a,b)=>a.period.localeCompare(b.period)||Number(a.row.year)-Number(b.row.year));
      const value=Number(group[0].row.value),n=group.length,maxSpread=0.08;
      group.forEach((item,index)=>{
        const offset=n===1?0:-maxSpread/2+maxSpread*index/(n-1),point={x:Number((value+offset).toFixed(6)),y:item.period==="A"?weightA:weightB,value,year:item.row.year};
        (item.period==="A"?pointsA:pointsB).push(point);
      });
    });
    pointsA.sort((a,b)=>a.x-b.x||a.year-b.year);pointsB.sort((a,b)=>a.x-b.x||a.year-b.year);
    const valuesA=cleanA.map(row=>row.value),valuesB=cleanB.map(row=>row.value),all=[...valuesA,...valuesB];
    let start=Math.floor((Math.min(...all)-0.5)*10)/10,end=Math.ceil((Math.max(...all)+0.5)*10)/10;if(end-start<2){start-=0.5;end+=0.5;}
    return {pointsA,pointsB,normalA:normalPoints(valuesA,mode,INDIVIDUAL_CURVE_WIDTH,start,end),normalB:normalPoints(valuesB,mode,INDIVIDUAL_CURVE_WIDTH,start,end),start,end};
  }
  function empiricalPercentile(values,value){if(!values.length||!Number.isFinite(value))return null;const below=values.filter(item=>item<value).length,equal=values.filter(item=>item===value).length;return 100*(below+0.5*equal)/values.length;}
  function exportSlug(value){return String(value??"").toLowerCase().replace(/ß/g,"ss").normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"")||"export";}
  function exportFilename(area,period,rangeA,rangeB,extension){const ext=String(extension||"png").replace(/^\./,"").toLowerCase();return `haeufigkeitsverteilung_${exportSlug(area)}_${exportSlug(period)}_${rangeA.start}-${rangeA.end}_vs_${rangeB.start}-${rangeB.end}.${ext}`;}

  globalThis.__monthlyFrequencyTestApi={buildDistribution,buildIndividualBars,empiricalPercentile,average,sampleStdDev,exportFilename};
  if(typeof document==="undefined"||typeof Chart==="undefined")return;

  let chart=null,mode="classic",previousParam=null,dataWaitTimer=null;

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
  .monthly-frequency-controls{display:grid;grid-template-columns:repeat(2,minmax(240px,1fr)) repeat(2,minmax(170px,.55fr));gap:14px;margin-bottom:16px}
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
  .monthly-frequency-stat .label{font-size:11px;font-weight:700;color:#5f6b7a;line-height:1.35}.monthly-frequency-stat .value{margin:13px 0 4px;font-size:21px;font-weight:740;font-variant-numeric:tabular-nums}.monthly-frequency-stat .detail{font-size:11px;color:#748092;line-height:1.4}
  .monthly-frequency-stat.period-a .value{color:${BLUE}}.monthly-frequency-stat.period-b .value{color:${RED}}
  .monthly-frequency-note{margin:14px 0 0;color:var(--muted);font-size:12px;line-height:1.5}
  .monthly-frequency-export-bar{display:flex;justify-content:flex-end;gap:8px;margin:-2px 0 14px}
  .monthly-frequency-export-btn{appearance:none;border:1px solid #b9c0c7;border-radius:6px;padding:8px 12px;background:#fff;color:#223041;font:700 12px/1 Arial,sans-serif;cursor:pointer;box-shadow:0 1px 4px rgba(15,23,42,.08)}
  .monthly-frequency-export-btn:hover{background:#f0f3f5;border-color:#8e969e}.monthly-frequency-export-btn:focus-visible{outline:3px solid rgba(40,100,180,.28);outline-offset:2px}.monthly-frequency-export-btn[disabled]{opacity:.55;cursor:wait}
  .monthly-frequency-exporting .monthly-frequency-controls,.monthly-frequency-exporting .monthly-frequency-export-bar{display:none!important}
  .monthly-frequency-exporting{background:#fff!important;box-shadow:none!important}
  @media(max-width:1100px){.monthly-frequency-controls{grid-template-columns:1fr 1fr}.monthly-frequency-stats{grid-template-columns:repeat(2,minmax(0,1fr))}}
  @media(max-width:640px){.monthly-frequency-switch{display:flex;width:100%}.monthly-frequency-switch button{flex:1;padding:9px 7px}.monthly-frequency-card{padding:14px}.monthly-frequency-controls{grid-template-columns:1fr}.monthly-frequency-stats{grid-template-columns:1fr}.monthly-frequency-chart-wrap{min-height:430px;padding:8px}.monthly-frequency-chart-wrap canvas{height:405px!important}.monthly-frequency-export-bar{justify-content:stretch}.monthly-frequency-export-btn{flex:1}}
  `;

  const presets=`<option value="1881-1910">1881–1910</option><option value="1911-1940">1911–1940</option><option value="1941-1970">1941–1970</option><option value="1961-1990">1961–1990</option><option value="1971-2000">1971–2000</option><option value="1981-2010">1981–2010</option><option value="1991-2020">1991–2020</option><option value="custom">Freie Auswahl …</option>`;

  function injectStyle(){if(document.getElementById("monthlyFrequencyStyles"))return;const style=document.createElement("style");style.id="monthlyFrequencyStyles";style.textContent=css;document.head.appendChild(style);}
  function frequencyHtml(){return `
      <div class="monthly-frequency-head"><div><h2>Häufigkeitsverteilung der Temperatur</h2><p id="monthlyFrequencySubtitle">Zwei historische Zeiträume direkt miteinander vergleichen.</p></div><span class="monthly-frequency-badge">Temperatur · DWD-Gebietsmittel</span></div>
      <div class="monthly-frequency-controls">
        <div class="monthly-frequency-period monthly-frequency-period-a"><h3>Zeitraum A</h3><label for="monthlyFrequencyPresetA">Auswahl</label><select id="monthlyFrequencyPresetA">${presets}</select><div id="monthlyFrequencyCustomA" class="monthly-frequency-custom" hidden><div><label for="monthlyFrequencyStartA">Startjahr</label><input id="monthlyFrequencyStartA" type="number" min="1881" max="2100" step="1" value="1881"></div><div><label for="monthlyFrequencyEndA">Endjahr</label><input id="monthlyFrequencyEndA" type="number" min="1881" max="2100" step="1" value="1910"></div></div></div>
        <div class="monthly-frequency-period monthly-frequency-period-b"><h3>Zeitraum B</h3><label for="monthlyFrequencyPresetB">Auswahl</label><select id="monthlyFrequencyPresetB">${presets}</select><div id="monthlyFrequencyCustomB" class="monthly-frequency-custom" hidden><div><label for="monthlyFrequencyStartB">Startjahr</label><input id="monthlyFrequencyStartB" type="number" min="1881" max="2100" step="1" value="1991"></div><div><label for="monthlyFrequencyEndB">Endjahr</label><input id="monthlyFrequencyEndB" type="number" min="1881" max="2100" step="1" value="2020"></div></div></div>
        <div class="monthly-frequency-scale"><label for="monthlyFrequencyDisplay">Darstellung</label><select id="monthlyFrequencyDisplay"><option value="individual" selected>Einzelwerte</option><option value="bins">0,5-°C-Klassen</option></select><div class="control-hint">Einzelwerte zeigt jedes Jahr als eigenen schmalen Balken.</div></div>
        <div class="monthly-frequency-scale"><label for="monthlyFrequencyScale">Y-Achse</label><select id="monthlyFrequencyScale"><option value="auto" selected>Automatisch</option><option value="count">Anzahl der Jahre</option><option value="percent">Häufigkeit in %</option></select><div class="control-hint">Automatisch verwendet bei gleich vielen auswertbaren Jahren die Anzahl, sonst Prozent.</div></div>
      </div>
      <div class="monthly-frequency-export-bar" aria-label="Export der Häufigkeitsverteilung"><button id="monthlyFrequencyPngButton" class="monthly-frequency-export-btn" type="button">PNG</button><button id="monthlyFrequencyPdfButton" class="monthly-frequency-export-btn" type="button">PDF</button></div>
      <div id="monthlyFrequencySummary" class="summary-box">Häufigkeitsverteilung wird berechnet …</div>
      <div class="monthly-frequency-chart-wrap"><canvas id="monthlyFrequencyChart"></canvas></div>
      <div class="monthly-frequency-stats">
        <div class="monthly-frequency-stat period-a"><div id="monthlyFrequencyLabelA" class="label">Zeitraum A</div><div id="monthlyFrequencyMeanA" class="value">–</div><div id="monthlyFrequencyDetailA" class="detail">–</div></div>
        <div class="monthly-frequency-stat period-b"><div id="monthlyFrequencyLabelB" class="label">Zeitraum B</div><div id="monthlyFrequencyMeanB" class="value">–</div><div id="monthlyFrequencyDetailB" class="detail">–</div></div>
        <div class="monthly-frequency-stat"><div class="label">Verschiebung B − A</div><div id="monthlyFrequencyShift" class="value">–</div><div id="monthlyFrequencyShiftDetail" class="detail">Differenz der Mittelwerte</div></div>
        <div class="monthly-frequency-stat"><div class="label">Streuung σ</div><div id="monthlyFrequencySpread" class="value">–</div><div id="monthlyFrequencySpreadDetail" class="detail">Standardabweichung A / B</div></div>
        <div class="monthly-frequency-stat"><div id="monthlyFrequencyLatestLabel" class="label">Aktuellster vollständiger Wert</div><div id="monthlyFrequencyLatest" class="value">–</div><div id="monthlyFrequencyLatestDetail" class="detail">Perzentil gegenüber Zeitraum A</div></div>
      </div>
      <p id="monthlyFrequencyNote" class="monthly-frequency-note"></p>`;}

  function setText(id,value){const el=document.getElementById(id);if(el)el.textContent=value;}
  function formatTemp(value,decimals=2,sign=false){if(!Number.isFinite(value))return "–";return `${sign&&value>0?"+":""}${value.toLocaleString("de-DE",{minimumFractionDigits:decimals,maximumFractionDigits:decimals})} °C`;}
  function range(which){const preset=document.getElementById(`monthlyFrequencyPreset${which}`)?.value||"custom";if(preset!=="custom"&&/^\d{4}-\d{4}$/.test(preset)){const [start,end]=preset.split("-").map(Number);return {start,end,label:`${start}–${end}`};}const start=Math.round(Number(document.getElementById(`monthlyFrequencyStart${which}`)?.value)),end=Math.round(Number(document.getElementById(`monthlyFrequencyEnd${which}`)?.value));return {start,end,label:Number.isFinite(start)&&Number.isFinite(end)?`${start}–${end}`:"freie Auswahl"};}
  function syncPreset(which){const select=document.getElementById(`monthlyFrequencyPreset${which}`),custom=document.getElementById(`monthlyFrequencyCustom${which}`);if(!select||!custom)return;const isCustom=select.value==="custom";custom.hidden=!isCustom;if(!isCustom){const [start,end]=select.value.split("-").map(Number);document.getElementById(`monthlyFrequencyStart${which}`).value=start;document.getElementById(`monthlyFrequencyEnd${which}`).value=end;}}
  function filterRange(series,r){return Number.isFinite(r.start)&&Number.isFinite(r.end)&&r.start<=r.end?series.filter(item=>item.year>=r.start&&item.year<=r.end):[];}
  function updateBounds(series){if(!series.length)return;const min=Math.min(...series.map(item=>item.year)),max=Math.max(...series.map(item=>item.year));for(const which of ["A","B"])for(const part of ["Start","End"]){const input=document.getElementById(`monthlyFrequency${part}${which}`);if(input){input.min=min;input.max=max;}}}
  function dataReady(){try{return Array.isArray(monthlyData)&&monthlyData.length>0&&typeof seriesFor==="function";}catch(_error){return false;}}

  const meanLinesPlugin={id:"monthlyFrequencyMeanLinesV3",afterDatasetsDraw(activeChart){if(activeChart.canvas.id!=="monthlyFrequencyChart"||!activeChart.$frequencyMeta)return;const {ctx,chartArea,scales:{x}}=activeChart,meta=activeChart.$frequencyMeta;if(!chartArea||!x)return;ctx.save();meta.means.forEach((item,index)=>{if(!Number.isFinite(item.value))return;const pixel=x.getPixelForValue(item.value);if(pixel<chartArea.left||pixel>chartArea.right)return;ctx.strokeStyle=item.color;ctx.lineWidth=1.5;ctx.setLineDash([5,4]);ctx.beginPath();ctx.moveTo(pixel,chartArea.top);ctx.lineTo(pixel,chartArea.bottom);ctx.stroke();ctx.setLineDash([]);ctx.font="700 11px Arial";ctx.textBaseline="top";ctx.textAlign=index===0?"right":"left";ctx.fillStyle=item.color;ctx.fillText(`Ø ${item.label}`,pixel+(index===0?-5:5),chartArea.top+5+index*14);});ctx.restore();}};

  function exportContext(){const area=document.getElementById("monthlyAreaSelect")?.value||"Deutschland",selection=document.getElementById("monthSelect")?.value||"Jahr";return {area,period:typeof periodLabel==="function"?periodLabel(selection):selection,rangeA:range("A"),rangeB:range("B")};}
  async function monthlyFrequencyExportCanvas(){
    const node=document.getElementById("monthlyFrequencyView");if(!node)throw new Error("Exportbereich nicht gefunden.");if(typeof html2canvas!=="function")throw new Error("html2canvas ist nicht geladen.");
    node.classList.add("monthly-frequency-exporting");
    try{await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));return await html2canvas(node,{backgroundColor:"#ffffff",scale:2,useCORS:true,logging:false});}
    finally{node.classList.remove("monthly-frequency-exporting");}
  }
  function triggerDownload(href,filename){const link=document.createElement("a");link.href=href;link.download=filename;link.style.display="none";document.body.appendChild(link);link.click();link.remove();}
  async function downloadMonthlyFrequencyPng(){
    const canvas=await monthlyFrequencyExportCanvas(),context=exportContext(),filename=exportFilename(context.area,context.period,context.rangeA,context.rangeB,"png"),blob=await new Promise(resolve=>canvas.toBlob(resolve,"image/png",1));
    if(!blob)throw new Error("PNG konnte nicht erzeugt werden.");const url=URL.createObjectURL(blob);try{triggerDownload(url,filename);}finally{setTimeout(()=>URL.revokeObjectURL(url),1500);}
  }
  async function downloadMonthlyFrequencyPdf(){
    const canvas=await monthlyFrequencyExportCanvas(),jsPDFCtor=window.jspdf?.jsPDF;if(!jsPDFCtor)throw new Error("jsPDF ist nicht geladen.");
    const pdf=new jsPDFCtor({orientation:"landscape",unit:"mm",format:"a4"}),pageWidth=pdf.internal.pageSize.getWidth(),pageHeight=pdf.internal.pageSize.getHeight(),margin=8,maxWidth=pageWidth-margin*2,maxHeight=pageHeight-margin*2,ratio=Math.min(maxWidth/canvas.width,maxHeight/canvas.height),width=canvas.width*ratio,height=canvas.height*ratio,x=(pageWidth-width)/2,y=(pageHeight-height)/2;
    pdf.addImage(canvas.toDataURL("image/png"),"PNG",x,y,width,height,undefined,"FAST");const context=exportContext();pdf.save(exportFilename(context.area,context.period,context.rangeA,context.rangeB,"pdf"));
  }
  async function runExport(button,kind){if(!button)return;const old=button.textContent;button.disabled=true;button.textContent=`${kind} …`;try{if(kind==="PNG")await downloadMonthlyFrequencyPng();else await downloadMonthlyFrequencyPdf();}catch(error){console.error(`Häufigkeitsverteilung ${kind}-Export:`,error);window.alert(`${kind} konnte nicht erstellt werden: ${error.message}`);}finally{button.disabled=false;button.textContent=old;}}

  function render(){
    if(mode!=="frequency")return;const monthly=document.getElementById("monthly");if(!monthly?.classList.contains("active"))return;
    if(!dataReady()){setText("monthlyFrequencySummary","Monatsdaten werden noch geladen …");clearTimeout(dataWaitTimer);dataWaitTimer=setTimeout(render,500);return;}
    const area=document.getElementById("monthlyAreaSelect")?.value||"Deutschland",selection=document.getElementById("monthSelect")?.value||"07",series=seriesFor(area,selection,"temp");
    updateBounds(series);syncPreset("A");syncPreset("B");const rangeA=range("A"),rangeB=range("B");
    if(!Number.isFinite(rangeA.start)||!Number.isFinite(rangeA.end)||rangeA.start>rangeA.end||!Number.isFinite(rangeB.start)||!Number.isFinite(rangeB.end)||rangeB.start>rangeB.end){setText("monthlyFrequencySummary","Bitte für beide Vergleichszeiträume ein gültiges Start- und Endjahr wählen.");if(chart){chart.destroy();chart=null;}return;}
    const rowsA=filterRange(series,rangeA),rowsB=filterRange(series,rangeB),valuesA=rowsA.map(item=>item.value),valuesB=rowsB.map(item=>item.value),requested=document.getElementById("monthlyFrequencyScale")?.value||"auto",yMode=requested==="auto"?(valuesA.length===valuesB.length?"count":"percent"):requested,display=document.getElementById("monthlyFrequencyDisplay")?.value||"individual",prepared=display==="individual"?buildIndividualBars(rowsA,rowsB,yMode):buildDistribution(valuesA,valuesB,yMode);
    const meanA=average(valuesA),meanB=average(valuesB),sdA=sampleStdDev(valuesA),sdB=sampleStdDev(valuesB),shift=Number.isFinite(meanA)&&Number.isFinite(meanB)?meanB-meanA:null,latest=series.at(-1)||null,pctl=latest?empiricalPercentile(valuesA,latest.value):null;
    setText("monthlyFrequencySubtitle",`${area} · ${periodLabel(selection)} · Temperatur`);setText("monthlyFrequencyLabelA",`Zeitraum A · ${rangeA.label}`);setText("monthlyFrequencyLabelB",`Zeitraum B · ${rangeB.label}`);setText("monthlyFrequencyMeanA",formatTemp(meanA));setText("monthlyFrequencyMeanB",formatTemp(meanB));setText("monthlyFrequencyDetailA",`${valuesA.length} auswertbare Jahre · σ ${formatTemp(sdA)}`);setText("monthlyFrequencyDetailB",`${valuesB.length} auswertbare Jahre · σ ${formatTemp(sdB)}`);setText("monthlyFrequencyShift",formatTemp(shift,2,true));setText("monthlyFrequencyShiftDetail",Number.isFinite(shift)?`${rangeB.label} minus ${rangeA.label}`:"nicht berechenbar");setText("monthlyFrequencySpread",Number.isFinite(sdA)&&Number.isFinite(sdB)?`${sdA.toFixed(2).replace(".",",")} / ${sdB.toFixed(2).replace(".",",")} °C`:"–");setText("monthlyFrequencySpreadDetail",`${rangeA.label} / ${rangeB.label}`);setText("monthlyFrequencyLatestLabel",latest?`Aktuellster vollständiger Wert · ${latest.year}`:"Aktuellster vollständiger Wert");setText("monthlyFrequencyLatest",latest?formatTemp(latest.value):"–");setText("monthlyFrequencyLatestDetail",latest&&Number.isFinite(pctl)?`Perzentil ${pctl.toFixed(1).replace(".",",")} gegenüber ${rangeA.label}`:"Perzentil nicht berechenbar");
    const warning=[valuesA.length<10?`Zeitraum A enthält nur ${valuesA.length} Werte.`:"",valuesB.length<10?`Zeitraum B enthält nur ${valuesB.length} Werte.`:""].filter(Boolean).join(" "),axis=yMode==="percent"?"relative Häufigkeit in %":"Anzahl der Jahre",displayLabel=display==="individual"?"Einzelwerte":"0,5-°C-Klassen";
    setText("monthlyFrequencySummary",`${area} · ${periodLabel(selection)}: ${rangeA.label} (${valuesA.length} Werte) gegen ${rangeB.label} (${valuesB.length} Werte). Darstellung: ${displayLabel}, ${axis}.${Number.isFinite(shift)?` Mittelwertverschiebung B − A: ${formatTemp(shift,2,true)}.`:""}${warning?` ${warning}`:""}`);
    setText("monthlyFrequencyNote",display==="individual"?"Jedes Jahr wird als eigener schmaler Balken dargestellt. Gleiche Temperaturwerte werden innerhalb von ±0,04 °C minimal auseinandergezogen, damit einzelne Jahre sichtbar bleiben; im Tooltip steht der unveränderte Originalwert. Die glatten Linien zeigen angepasste Normalverteilungen. Nur vollständige Monate, Jahreszeiten oder Jahre werden berücksichtigt.":"Klassenbreite: 0,5 °C. Die glatten Linien zeigen an Mittelwert und Standardabweichung angepasste Normalverteilungen. Nur vollständige Monate, Jahreszeiten oder Jahre werden berücksichtigt.");
    if(!prepared||!valuesA.length||!valuesB.length){if(chart){chart.destroy();chart=null;}return;}if(chart)chart.destroy();
    const barA={type:"bar",label:rangeA.label,data:prepared.pointsA,parsing:false,backgroundColor:"rgba(43,111,142,.45)",borderColor:BLUE,borderWidth:1,barThickness:display==="individual"?5:20,order:3},barB={type:"bar",label:rangeB.label,data:prepared.pointsB,parsing:false,backgroundColor:"rgba(196,59,47,.38)",borderColor:RED,borderWidth:1,barThickness:display==="individual"?5:20,order:3},curveA={type:"line",label:`Normalverteilung ${rangeA.label}`,data:prepared.normalA,parsing:false,borderColor:BLUE,borderWidth:2.4,pointRadius:0,tension:.28,order:1},curveB={type:"line",label:`Normalverteilung ${rangeB.label}`,data:prepared.normalB,parsing:false,borderColor:RED,borderWidth:2.4,pointRadius:0,tension:.28,order:1};
    chart=new Chart(document.getElementById("monthlyFrequencyChart"),{type:"bar",data:{datasets:[barA,barB,curveA,curveB]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"nearest",intersect:true},plugins:{title:{display:true,text:`${area}: ${periodLabel(selection)} – Häufigkeitsverteilung`,font:{size:19}},subtitle:{display:true,text:`${rangeA.label} vs. ${rangeB.label} · ${displayLabel}`,font:{size:12}},legend:{position:"bottom",labels:{usePointStyle:true,boxWidth:10}},datalabels:{display:false},tooltip:{callbacks:{title:items=>{const raw=items[0]?.raw;if(display==="individual"&&raw?.year)return `${raw.value.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:2})} °C`;return `${Number(items[0]?.parsed?.x).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})} °C`;},label:context=>{const raw=context.raw;if(display==="individual"&&raw?.year)return `${context.dataset.label} · ${raw.year}: ${raw.value.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:2})} °C`;return `${context.dataset.label}: ${Number(context.parsed.y).toLocaleString("de-DE",{minimumFractionDigits:yMode==="percent"?1:0,maximumFractionDigits:yMode==="percent"?1:2})}${yMode==="percent"?" %":""}`;}}}},scales:{x:{type:"linear",min:prepared.start,max:prepared.end,title:{display:true,text:"Mitteltemperatur in °C"},grid:{display:false},ticks:{maxTicksLimit:18,callback:value=>Number(value).toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1})}},y:{beginAtZero:true,title:{display:true,text:yMode==="percent"?"Häufigkeit (%)":"Anzahl"},ticks:{precision:yMode==="count"?0:1}}}}});
    chart.$frequencyMeta={means:[{value:meanA,color:BLUE,label:formatTemp(meanA).replace(" °C","")},{value:meanB,color:RED,label:formatTemp(meanB).replace(" °C","")} ]};chart.update();
  }

  function setMode(next,{persist=true}={}){mode=next==="frequency"?"frequency":"classic";const monthly=document.getElementById("monthly");monthly?.classList.toggle("monthly-frequency-active",mode==="frequency");document.getElementById("monthlyFrequencyView").hidden=mode!=="frequency";document.getElementById("monthlyFrequencyClassicButton").classList.toggle("active",mode==="classic");document.getElementById("monthlyFrequencyButton").classList.toggle("active",mode==="frequency");const param=document.getElementById("paramSelect");if(mode==="frequency"){if(param&&param.value!=="temp")previousParam=param.value;if(param)param.value="temp";render();}else{if(param&&previousParam&&[...param.options].some(option=>option.value===previousParam)){param.value=previousParam;param.dispatchEvent(new Event("change",{bubbles:true}));}previousParam=null;if(chart)setTimeout(()=>chart.resize(),0);}if(persist&&typeof persistDashboardState==="function")persistDashboardState("monthlyViewMode",mode);}

  function init(){
    const monthly=document.getElementById("monthly"),controls=monthly?.querySelector(":scope > .controls");if(!monthly||!controls||document.getElementById("monthlyFrequencyView"))return;injectStyle();
    [...monthly.children].filter(node=>node!==monthly.firstElementChild&&node!==controls).forEach(node=>node.classList.add("monthly-frequency-classic-node"));
    ["paramSelect","monthlyReferenceSelect","monthlyReferenceCustomGroup","monthlyRollingSelect","monthlyRollingCustomGroup"].forEach(id=>document.getElementById(id)?.closest(".control-group")?.classList.add("monthly-frequency-classic-control"));controls.querySelector('button[onclick="resetMonthlyZoom()"]')?.classList.add("monthly-frequency-classic-control");
    const switcher=document.createElement("div");switcher.className="monthly-frequency-switch";switcher.innerHTML='<button id="monthlyFrequencyClassicButton" class="active" type="button">Zeitreihe &amp; Tabellen</button><button id="monthlyFrequencyButton" type="button">Häufigkeitsverteilung</button>';controls.insertAdjacentElement("afterend",switcher);
    const section=document.createElement("section");section.id="monthlyFrequencyView";section.className="monthly-frequency-card";section.hidden=true;section.innerHTML=frequencyHtml();switcher.insertAdjacentElement("afterend",section);
    document.getElementById("monthlyFrequencyPresetA").value="1881-1910";document.getElementById("monthlyFrequencyPresetB").value="1991-2020";syncPreset("A");syncPreset("B");
    document.getElementById("monthlyFrequencyClassicButton").addEventListener("click",()=>setMode("classic"));document.getElementById("monthlyFrequencyButton").addEventListener("click",()=>setMode("frequency"));
    for(const which of ["A","B"]){document.getElementById(`monthlyFrequencyPreset${which}`).addEventListener("change",()=>{syncPreset(which);render();});for(const part of ["Start","End"])document.getElementById(`monthlyFrequency${part}${which}`).addEventListener("change",render);}
    document.getElementById("monthlyFrequencyScale").addEventListener("change",render);document.getElementById("monthlyFrequencyDisplay").addEventListener("change",render);document.getElementById("monthlyFrequencyPngButton")?.addEventListener("click",event=>runExport(event.currentTarget,"PNG"));document.getElementById("monthlyFrequencyPdfButton")?.addEventListener("click",event=>runExport(event.currentTarget,"PDF"));document.getElementById("monthlyAreaSelect")?.addEventListener("change",()=>{if(mode==="frequency")render();});document.getElementById("monthSelect")?.addEventListener("change",()=>{if(mode==="frequency")render();});
    new MutationObserver(()=>{if(monthly.classList.contains("active")&&mode==="frequency")setTimeout(()=>{render();chart?.resize();},100);}).observe(monthly,{attributes:true,attributeFilter:["class"]});
    try{setMode(dashboardState?.monthlyViewMode==="frequency"?"frequency":"classic",{persist:false});}catch(_error){setMode("classic",{persist:false});}
  }

  try{Chart.register(meanLinesPlugin);}catch(_error){}
  init();
})();
