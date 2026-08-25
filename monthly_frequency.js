/* MONTHLY_FREQUENCY_DISTRIBUTION_V1 */
(function(){
  "use strict";

  const BIN_STEP=0.5;
  const BLUE="#2b6f8e";
  const RED="#c43b2f";

  function average(values){
    return values.length?values.reduce((sum,value)=>sum+value,0)/values.length:null;
  }
  function sampleStdDev(values){
    if(values.length<2)return null;
    const avg=average(values);
    return Math.sqrt(values.reduce((sum,value)=>sum+(value-avg)**2,0)/(values.length-1));
  }
  function buildDistribution(valuesA,valuesB,mode){
    const all=[...valuesA,...valuesB].filter(Number.isFinite);
    if(!all.length)return null;
    let start=Math.floor(Math.min(...all)/BIN_STEP)*BIN_STEP-BIN_STEP;
    let end=Math.ceil(Math.max(...all)/BIN_STEP)*BIN_STEP+BIN_STEP;
    if(end-start<BIN_STEP*4){start-=BIN_STEP;end+=BIN_STEP;}
    const count=Math.round((end-start)/BIN_STEP)+1;
    const centers=Array.from({length:count},(_,index)=>Number((start+index*BIN_STEP).toFixed(6)));
    const histogram=values=>{
      const bins=Array(centers.length).fill(0);
      values.forEach(value=>{
        const index=Math.max(0,Math.min(centers.length-1,Math.round((value-start)/BIN_STEP)));
        bins[index]+=1;
      });
      return mode==="percent"&&values.length?bins.map(value=>100*value/values.length):bins;
    };
    const normal=values=>{
      const avg=average(values);
      const sd=sampleStdDev(values);
      if(!Number.isFinite(avg)||!Number.isFinite(sd)||sd<=0)return centers.map(()=>null);
      const multiplier=mode==="percent"?100:values.length;
      return centers.map(x=>multiplier*BIN_STEP*Math.exp(-0.5*((x-avg)/sd)**2)/(sd*Math.sqrt(2*Math.PI)));
    };
    return {centers,histA:histogram(valuesA),histB:histogram(valuesB),normalA:normal(valuesA),normalB:normal(valuesB)};
  }
  function empiricalPercentile(values,value){
    if(!values.length||!Number.isFinite(value))return null;
    const below=values.filter(item=>item<value).length;
    const equal=values.filter(item=>item===value).length;
    return 100*(below+0.5*equal)/values.length;
  }

  globalThis.__monthlyFrequencyTestApi={buildDistribution,empiricalPercentile,average,sampleStdDev};
  if(typeof document==="undefined"||typeof Chart==="undefined")return;

  let chart=null;
  let mode="classic";
  let previousParam=null;
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
  .monthly-frequency-controls{display:grid;grid-template-columns:repeat(2,minmax(260px,1fr)) minmax(190px,.55fr);gap:14px;margin-bottom:16px}
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
  @media(max-width:980px){.monthly-frequency-controls{grid-template-columns:1fr 1fr}.monthly-frequency-scale{grid-column:1/-1}.monthly-frequency-stats{grid-template-columns:repeat(2,minmax(0,1fr))}}
  @media(max-width:640px){.monthly-frequency-switch{display:flex;width:100%}.monthly-frequency-switch button{flex:1;padding:9px 7px}.monthly-frequency-card{padding:14px}.monthly-frequency-controls{grid-template-columns:1fr}.monthly-frequency-scale{grid-column:auto}.monthly-frequency-stats{grid-template-columns:1fr}.monthly-frequency-chart-wrap{min-height:430px;padding:8px}.monthly-frequency-chart-wrap canvas{height:405px!important}}
  `;

  const presets=`
    <option value="1881-1910">1881–1910</option>
    <option value="1911-1940">1911–1940</option>
    <option value="1941-1970">1941–1970</option>
    <option value="1961-1990">1961–1990</option>
    <option value="1971-2000">1971–2000</option>
    <option value="1981-2010">1981–2010</option>
    <option value="1991-2020">1991–2020</option>
    <option value="custom">Freie Auswahl …</option>`;

  function injectStyle(){
    if(document.getElementById("monthlyFrequencyStyles"))return;
    const style=document.createElement("style");
    style.id="monthlyFrequencyStyles";
    style.textContent=css;
    document.head.appendChild(style);
  }
  function frequencyHtml(){
    return `
      <div class="monthly-frequency-head">
        <div><h2>Häufigkeitsverteilung der Temperatur</h2><p id="monthlyFrequencySubtitle">Zwei historische Zeiträume direkt miteinander vergleichen.</p></div>
        <span class="monthly-frequency-badge">Temperatur · DWD-Gebietsmittel</span>
      </div>
      <div class="monthly-frequency-controls">
        <div class="monthly-frequency-period monthly-frequency-period-a"><h3>Zeitraum A</h3><label for="monthlyFrequencyPresetA">Auswahl</label><select id="monthlyFrequencyPresetA">${presets}</select><div id="monthlyFrequencyCustomA" class="monthly-frequency-custom" hidden><div><label for="monthlyFrequencyStartA">Startjahr</label><input id="monthlyFrequencyStartA" type="number" min="1881" max="2100" step="1" value="1881"></div><div><label for="monthlyFrequencyEndA">Endjahr</label><input id="monthlyFrequencyEndA" type="number" min="1881" max="2100" step="1" value="1910"></div></div></div>
        <div class="monthly-frequency-period monthly-frequency-period-b"><h3>Zeitraum B</h3><label for="monthlyFrequencyPresetB">Auswahl</label><select id="monthlyFrequencyPresetB">${presets}</select><div id="monthlyFrequencyCustomB" class="monthly-frequency-custom" hidden><div><label for="monthlyFrequencyStartB">Startjahr</label><input id="monthlyFrequencyStartB" type="number" min="1881" max="2100" step="1" value="1991"></div><div><label for="monthlyFrequencyEndB">Endjahr</label><input id="monthlyFrequencyEndB" type="number" min="1881" max="2100" step="1" value="2020"></div></div></div>
        <div class="monthly-frequency-scale"><label for="monthlyFrequencyScale">Y-Achse</label><select id="monthlyFrequencyScale"><option value="auto" selected>Automatisch</option><option value="count">Anzahl der Jahre</option><option value="percent">Häufigkeit in %</option></select><div class="control-hint">Automatisch verwendet bei gleich vielen auswertbaren Jahren die Anzahl, sonst Prozent.</div></div>
      </div>
      <div id="monthlyFrequencySummary" class="summary-box">Häufigkeitsverteilung wird berechnet …</div>
      <div class="monthly-frequency-chart-wrap"><canvas id="monthlyFrequencyChart"></canvas></div>
      <div class="monthly-frequency-stats">
        <div class="monthly-frequency-stat period-a"><div id="monthlyFrequencyLabelA" class="label">Zeitraum A</div><div id="monthlyFrequencyMeanA" class="value">–</div><div id="monthlyFrequencyDetailA" class="detail">–</div></div>
        <div class="monthly-frequency-stat period-b"><div id="monthlyFrequencyLabelB" class="label">Zeitraum B</div><div id="monthlyFrequencyMeanB" class="value">–</div><div id="monthlyFrequencyDetailB" class="detail">–</div></div>
        <div class="monthly-frequency-stat"><div class="label">Verschiebung B − A</div><div id="monthlyFrequencyShift" class="value">–</div><div id="monthlyFrequencyShiftDetail" class="detail">Differenz der Mittelwerte</div></div>
        <div class="monthly-frequency-stat"><div class="label">Streuung σ</div><div id="monthlyFrequencySpread" class="value">–</div><div id="monthlyFrequencySpreadDetail" class="detail">Standardabweichung A / B</div></div>
        <div class="monthly-frequency-stat"><div id="monthlyFrequencyLatestLabel" class="label">Aktuellster vollständiger Wert</div><div id="monthlyFrequencyLatest" class="value">–</div><div id="monthlyFrequencyLatestDetail" class="detail">Perzentil gegenüber Zeitraum A</div></div>
      </div>
      <p class="monthly-frequency-note">Klassenbreite: 0,5 °C. Die glatten Linien zeigen an Mittelwert und Standardabweichung angepasste Normalverteilungen. Nur vollständig vorhandene Monate, Jahreszeiten oder Jahre werden berücksichtigt.</p>`;
  }
  function setText(id,value){const el=document.getElementById(id);if(el)el.textContent=value;}
  function formatTemp(value,decimals=2,sign=false){
    if(!Number.isFinite(value))return "–";
    return `${sign&&value>0?"+":""}${value.toLocaleString("de-DE",{minimumFractionDigits:decimals,maximumFractionDigits:decimals})} °C`;
  }
  function range(which){
    const preset=document.getElementById(`monthlyFrequencyPreset${which}`)?.value||"custom";
    if(preset!=="custom"&&/^\d{4}-\d{4}$/.test(preset)){
      const [start,end]=preset.split("-").map(Number);return {start,end,label:`${start}–${end}`};
    }
    const start=Math.round(Number(document.getElementById(`monthlyFrequencyStart${which}`)?.value));
    const end=Math.round(Number(document.getElementById(`monthlyFrequencyEnd${which}`)?.value));
    return {start,end,label:Number.isFinite(start)&&Number.isFinite(end)?`${start}–${end}`:"freie Auswahl"};
  }
  function syncPreset(which){
    const select=document.getElementById(`monthlyFrequencyPreset${which}`);const custom=document.getElementById(`monthlyFrequencyCustom${which}`);if(!select||!custom)return;
    const isCustom=select.value==="custom";custom.hidden=!isCustom;
    if(!isCustom){const [start,end]=select.value.split("-").map(Number);document.getElementById(`monthlyFrequencyStart${which}`).value=start;document.getElementById(`monthlyFrequencyEnd${which}`).value=end;}
  }
  function filterRange(series,r){return Number.isFinite(r.start)&&Number.isFinite(r.end)&&r.start<=r.end?series.filter(item=>item.year>=r.start&&item.year<=r.end):[];}
  function updateBounds(series){
    if(!series.length)return;const min=Math.min(...series.map(item=>item.year));const max=Math.max(...series.map(item=>item.year));
    for(const which of ["A","B"])for(const part of ["Start","End"]){const input=document.getElementById(`monthlyFrequency${part}${which}`);if(input){input.min=min;input.max=max;}}
  }
  function dataReady(){try{return Array.isArray(monthlyData)&&monthlyData.length>0&&typeof seriesFor==="function";}catch(_error){return false;}}

  const meanLinesPlugin={
    id:"monthlyFrequencyMeanLinesV1",
    afterDatasetsDraw(activeChart){
      if(activeChart.canvas.id!=="monthlyFrequencyChart"||!activeChart.$frequencyMeta)return;
      const {ctx,chartArea,scales:{x}}=activeChart;const meta=activeChart.$frequencyMeta;if(!chartArea||!x||!meta.centers.length)return;
      const first=meta.centers[0];ctx.save();
      meta.means.forEach((item,index)=>{
        if(!Number.isFinite(item.value))return;const position=(item.value-first)/BIN_STEP;const low=Math.max(0,Math.min(meta.centers.length-1,Math.floor(position)));const high=Math.max(0,Math.min(meta.centers.length-1,Math.ceil(position)));const fraction=high===low?0:position-Math.floor(position);const pixel=x.getPixelForValue(low)+(x.getPixelForValue(high)-x.getPixelForValue(low))*fraction;
        if(pixel<chartArea.left||pixel>chartArea.right)return;ctx.strokeStyle=item.color;ctx.lineWidth=1.5;ctx.setLineDash([5,4]);ctx.beginPath();ctx.moveTo(pixel,chartArea.top);ctx.lineTo(pixel,chartArea.bottom);ctx.stroke();ctx.setLineDash([]);ctx.font="700 11px Arial";ctx.textBaseline="top";ctx.textAlign=index===0?"right":"left";ctx.fillStyle=item.color;ctx.fillText(`Ø ${item.label}`,pixel+(index===0?-5:5),chartArea.top+5+index*14);
      });ctx.restore();
    }
  };

  function render(){
    if(mode!=="frequency")return;
    const monthly=document.getElementById("monthly");if(!monthly?.classList.contains("active"))return;
    if(!dataReady()){
      setText("monthlyFrequencySummary","Monatsdaten werden noch geladen …");
      clearTimeout(dataWaitTimer);dataWaitTimer=setTimeout(render,500);return;
    }
    const area=document.getElementById("monthlyAreaSelect")?.value||"Deutschland";const selection=document.getElementById("monthSelect")?.value||"07";
    const series=seriesFor(area,selection,"temp");updateBounds(series);syncPreset("A");syncPreset("B");const rangeA=range("A"),rangeB=range("B");
    if(!Number.isFinite(rangeA.start)||!Number.isFinite(rangeA.end)||rangeA.start>rangeA.end||!Number.isFinite(rangeB.start)||!Number.isFinite(rangeB.end)||rangeB.start>rangeB.end){setText("monthlyFrequencySummary","Bitte für beide Vergleichszeiträume ein gültiges Start- und Endjahr wählen.");if(chart){chart.destroy();chart=null;}return;}
    const rowsA=filterRange(series,rangeA),rowsB=filterRange(series,rangeB);const valuesA=rowsA.map(item=>item.value),valuesB=rowsB.map(item=>item.value);
    const requested=document.getElementById("monthlyFrequencyScale")?.value||"auto";const yMode=requested==="auto"?(valuesA.length===valuesB.length?"count":"percent"):requested;const distribution=buildDistribution(valuesA,valuesB,yMode);
    const meanA=average(valuesA),meanB=average(valuesB),sdA=sampleStdDev(valuesA),sdB=sampleStdDev(valuesB),shift=Number.isFinite(meanA)&&Number.isFinite(meanB)?meanB-meanA:null;const latest=series.at(-1)||null;const pctl=latest?empiricalPercentile(valuesA,latest.value):null;
    setText("monthlyFrequencySubtitle",`${area} · ${periodLabel(selection)} · Temperatur`);setText("monthlyFrequencyLabelA",`Zeitraum A · ${rangeA.label}`);setText("monthlyFrequencyLabelB",`Zeitraum B · ${rangeB.label}`);setText("monthlyFrequencyMeanA",formatTemp(meanA));setText("monthlyFrequencyMeanB",formatTemp(meanB));setText("monthlyFrequencyDetailA",`${valuesA.length} auswertbare Jahre · σ ${formatTemp(sdA)}`);setText("monthlyFrequencyDetailB",`${valuesB.length} auswertbare Jahre · σ ${formatTemp(sdB)}`);setText("monthlyFrequencyShift",formatTemp(shift,2,true));setText("monthlyFrequencyShiftDetail",Number.isFinite(shift)?`${rangeB.label} minus ${rangeA.label}`:"nicht berechenbar");setText("monthlyFrequencySpread",Number.isFinite(sdA)&&Number.isFinite(sdB)?`${sdA.toFixed(2).replace(".",",")} / ${sdB.toFixed(2).replace(".",",")} °C`:"–");setText("monthlyFrequencySpreadDetail",`${rangeA.label} / ${rangeB.label}`);setText("monthlyFrequencyLatestLabel",latest?`Aktuellster vollständiger Wert · ${latest.year}`:"Aktuellster vollständiger Wert");setText("monthlyFrequencyLatest",latest?formatTemp(latest.value):"–");setText("monthlyFrequencyLatestDetail",latest&&Number.isFinite(pctl)?`Perzentil ${pctl.toFixed(1).replace(".",",")} gegenüber ${rangeA.label}`:"Perzentil nicht berechenbar");
    const warning=[valuesA.length<10?`Zeitraum A enthält nur ${valuesA.length} Werte.`:"",valuesB.length<10?`Zeitraum B enthält nur ${valuesB.length} Werte.`:""].filter(Boolean).join(" ");const axis=yMode==="percent"?"relative Häufigkeit in %":"Anzahl der Jahre";setText("monthlyFrequencySummary",`${area} · ${periodLabel(selection)}: ${rangeA.label} (${valuesA.length} Werte) gegen ${rangeB.label} (${valuesB.length} Werte). Darstellung: ${axis}.${Number.isFinite(shift)?` Mittelwertverschiebung B − A: ${formatTemp(shift,2,true)}.`:""}${warning?` ${warning}`:""}`);
    if(!distribution||!valuesA.length||!valuesB.length){if(chart){chart.destroy();chart=null;}return;}
    const labels=distribution.centers.map(value=>value.toLocaleString("de-DE",{minimumFractionDigits:1,maximumFractionDigits:1}));if(chart)chart.destroy();
    chart=new Chart(document.getElementById("monthlyFrequencyChart"),{type:"bar",data:{labels,datasets:[{type:"bar",label:rangeA.label,data:distribution.histA,backgroundColor:"rgba(43,111,142,.45)",borderColor:BLUE,borderWidth:1,order:3},{type:"bar",label:rangeB.label,data:distribution.histB,backgroundColor:"rgba(196,59,47,.38)",borderColor:RED,borderWidth:1,order:3},{type:"line",label:`Normalverteilung ${rangeA.label}`,data:distribution.normalA,borderColor:BLUE,borderWidth:2.4,pointRadius:0,tension:.28,order:1},{type:"line",label:`Normalverteilung ${rangeB.label}`,data:distribution.normalB,borderColor:RED,borderWidth:2.4,pointRadius:0,tension:.28,order:1}]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{title:{display:true,text:`${area}: ${periodLabel(selection)} – Häufigkeitsverteilung`,font:{size:19}},subtitle:{display:true,text:`${rangeA.label} vs. ${rangeB.label} · Klassenbreite 0,5 °C`,font:{size:12}},legend:{position:"bottom",labels:{usePointStyle:true,boxWidth:10}},datalabels:{display:false},tooltip:{callbacks:{title:items=>`${items[0]?.label||""} °C`,label:context=>`${context.dataset.label}: ${Number(context.parsed.y).toLocaleString("de-DE",{minimumFractionDigits:yMode==="percent"?1:0,maximumFractionDigits:yMode==="percent"?1:2})}${yMode==="percent"?" %":""}`}}},scales:{x:{title:{display:true,text:"Mitteltemperatur in °C"},grid:{display:false},ticks:{maxRotation:0,autoSkip:true,maxTicksLimit:18}},y:{beginAtZero:true,title:{display:true,text:yMode==="percent"?"Häufigkeit (%)":"Anzahl"},ticks:{precision:yMode==="count"?0:1}}}}});
    chart.$frequencyMeta={centers:distribution.centers,means:[{value:meanA,color:BLUE,label:formatTemp(meanA).replace(" °C","")},{value:meanB,color:RED,label:formatTemp(meanB).replace(" °C","")} ]};chart.update();
  }

  function setMode(next,{persist=true}={}){
    mode=next==="frequency"?"frequency":"classic";const monthly=document.getElementById("monthly");monthly?.classList.toggle("monthly-frequency-active",mode==="frequency");document.getElementById("monthlyFrequencyView").hidden=mode!=="frequency";document.getElementById("monthlyFrequencyClassicButton").classList.toggle("active",mode==="classic");document.getElementById("monthlyFrequencyButton").classList.toggle("active",mode==="frequency");
    const param=document.getElementById("paramSelect");if(mode==="frequency"){if(param&&param.value!=="temp")previousParam=param.value;if(param)param.value="temp";render();}else{if(param&&previousParam&&[...param.options].some(option=>option.value===previousParam)){param.value=previousParam;param.dispatchEvent(new Event("change",{bubbles:true}));}previousParam=null;if(chart){setTimeout(()=>chart.resize(),0);}}
    if(persist&&typeof persistDashboardState==="function")persistDashboardState("monthlyViewMode",mode);
  }

  function init(){
    const monthly=document.getElementById("monthly");const controls=monthly?.querySelector(":scope > .controls");if(!monthly||!controls||document.getElementById("monthlyFrequencyView"))return;
    injectStyle();
    [...monthly.children].filter(node=>node!==monthly.firstElementChild&&node!==controls).forEach(node=>node.classList.add("monthly-frequency-classic-node"));
    ["paramSelect","monthlyReferenceSelect","monthlyReferenceCustomGroup","monthlyRollingSelect","monthlyRollingCustomGroup"].forEach(id=>document.getElementById(id)?.closest(".control-group")?.classList.add("monthly-frequency-classic-control"));controls.querySelector('button[onclick="resetMonthlyZoom()"]')?.classList.add("monthly-frequency-classic-control");
    const switcher=document.createElement("div");switcher.className="monthly-frequency-switch";switcher.innerHTML='<button id="monthlyFrequencyClassicButton" class="active" type="button">Zeitreihe &amp; Tabellen</button><button id="monthlyFrequencyButton" type="button">Häufigkeitsverteilung</button>';controls.insertAdjacentElement("afterend",switcher);
    const section=document.createElement("section");section.id="monthlyFrequencyView";section.className="monthly-frequency-card";section.hidden=true;section.innerHTML=frequencyHtml();switcher.insertAdjacentElement("afterend",section);
    document.getElementById("monthlyFrequencyPresetA").value="1881-1910";document.getElementById("monthlyFrequencyPresetB").value="1991-2020";syncPreset("A");syncPreset("B");
    document.getElementById("monthlyFrequencyClassicButton").addEventListener("click",()=>setMode("classic"));document.getElementById("monthlyFrequencyButton").addEventListener("click",()=>setMode("frequency"));
    for(const which of ["A","B"]){document.getElementById(`monthlyFrequencyPreset${which}`).addEventListener("change",()=>{syncPreset(which);render();});for(const part of ["Start","End"])document.getElementById(`monthlyFrequency${part}${which}`).addEventListener("change",render);}
    document.getElementById("monthlyFrequencyScale").addEventListener("change",render);document.getElementById("monthlyAreaSelect")?.addEventListener("change",()=>{if(mode==="frequency")render();});document.getElementById("monthSelect")?.addEventListener("change",()=>{if(mode==="frequency")render();});
    new MutationObserver(()=>{if(monthly.classList.contains("active")&&mode==="frequency")setTimeout(()=>{render();chart?.resize();},100);}).observe(monthly,{attributes:true,attributeFilter:["class"]});
    try{setMode(dashboardState?.monthlyViewMode==="frequency"?"frequency":"classic",{persist:false});}catch(_error){setMode("classic",{persist:false});}
  }

  try{Chart.register(meanLinesPlugin);}catch(_error){}
  init();
})();
