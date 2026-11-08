/* Five genuine NASA zonal-wind pressure levels, daily analyses and anomalies.
   Published GEFS/EPS originals are 10 hPa ONLY: no invented forecast at
   30,50,70,100 hPa. */
(()=>{
'use strict';
const $=id=>document.getElementById(id),nasa=window.stratoNASAData;
if(!nasa)return;
const LEVELS=nasa.LEVELS;
const COLORS={10:'#b42f32',30:'#bd7620',50:'#328467',70:'#246ba0',100:'#684ca6'};
const finite=x=>typeof x==='number'&&Number.isFinite(x);
const dates=(from,to)=>{const output=[];for(let d=from;d<=to;d=nasa.dateISO(d,1))output.push(d);return output;};
const anomaly=(observed,ref,mode)=>mode==='absolute'?observed:
  finite(observed)&&finite(ref)?observed-ref:null;
function scaleFor(mode){return mode==='absolute'?60:30;}
function color(value,mode){
  if(!finite(value))return '#e3e8ed';
  const fraction=Math.max(-1,Math.min(1,value/scaleFor(mode)));
  const mix=(a,b,x)=>Math.round(a+(b-a)*x);
  const center=[249,249,247];
  const target=fraction>=0?[191,59,46]:[32,99,166];
  const t=Math.abs(fraction);
  return 'rgb('+target.map((c,i)=>mix(center[i],c,t)).join(',')+')';
}
window.stratoVerticalMath={anomaly,scaleFor,color};
if(!$('stratoVerticalPanel'))return;
let history=null,forecast=null,lineChart=null,lastRows=[],token=0;
const status=s=>$('stratoVerticalStatus').textContent=s;
function tabularRows(analyses,mode) {
  const ordered=LEVELS.map(level=>{
    const data=analyses.get(level),available=[...data.observations].sort((a,b)=>a[0].localeCompare(b[0]));
    const latest=available.at(-1),ref=latest?nasa.climate(data,latest[0],'mean'):null;
    return {level,date:latest?.[0]||'',value:latest?.[1]??null,
      anomaly:finite(latest?.[1])&&finite(ref)?latest[1]-ref:null};
  });
  return ordered;
}
function paintHeatmap(history,from,to,mode) {
  const cv=$('stratoVerticalHeatmap'),ctx=cv.getContext('2d');
  const keys=dates(from,to),width=1220,height=360;
  cv.width=width;cv.height=height;
  ctx.fillStyle='#fff';ctx.fillRect(0,0,width,height);
  const left=110,right=1170,top=57,rowHeight=38;
  const span=(right-left)/Math.max(1,keys.length),norm=scaleFor(mode);
  ctx.fillStyle='#1e3450';ctx.textAlign='left';ctx.font='bold 20px Arial';
  ctx.fillText('Zonalwind 60° N · NASA-Tagesanalyse · '+(mode==='absolute'?'m/s':'Abweichung 1991–2020 (m/s)'),18,28);
  LEVELS.forEach((level,i)=>{
    ctx.fillStyle='#2d3c4c';ctx.font='bold 15px Arial';ctx.textAlign='right';
    ctx.fillText(level+' hPa',left-12,top+i*rowHeight+25);
    const data=history.get(level);
    keys.forEach((date,j)=>{
      const raw=data.observations.get(date);
      const clim=nasa.climate(data,date,'mean');
      const v=anomaly(raw,clim,mode);
      ctx.fillStyle=color(v,mode);ctx.fillRect(left+j*span,top+i*rowHeight,Math.ceil(span+.25),rowHeight-2);
      if(!finite(v)){
        ctx.strokeStyle='#b0b8c0';ctx.lineWidth=1;
        ctx.beginPath();ctx.moveTo(left+j*span,top+i*rowHeight+rowHeight-2);
        ctx.lineTo(left+(j+1)*span,top+i*rowHeight);ctx.stroke();
      }
    });
  });
  ctx.font='13px Arial';ctx.fillStyle='#49586b';ctx.textAlign='center';
  for(let i=0;i<keys.length;i+=Math.max(1,Math.floor(keys.length/9))){
    ctx.fillText(keys[i].slice(5),left+(i+.5)*span,top+LEVELS.length*rowHeight+23);
  }
  const legendY=top+LEVELS.length*rowHeight+56,legendX=left+80,legendW=900;
  for(let i=0;i<180;i++){
    const v=-norm+(i+.5)*(2*norm/180);
    ctx.fillStyle=color(v,mode);ctx.fillRect(legendX+i*legendW/180,legendY,Math.ceil(legendW/180),18);
  }
  ctx.fillStyle='#2e4055';ctx.font='13px Arial';
  ctx.fillText('-'+norm+' m/s',legendX,legendY+36);
  ctx.fillText('0 m/s',legendX+legendW/2,legendY+36);
  ctx.fillText('+'+norm+' m/s',legendX+legendW,legendY+36);
  ctx.fillStyle='#536677';ctx.font='12px Arial';ctx.textAlign='left';
  ctx.fillText('Fixe Farbskala · schraffierte Felder = fehlende Originaldaten',left,height-8);
  cv.onmousemove=event=>{
    const rect=cv.getBoundingClientRect();
    const x=(event.clientX-rect.left)*width/rect.width,y=(event.clientY-rect.top)*height/rect.height;
    const i=Math.floor((y-top)/rowHeight),j=Math.floor((x-left)/span);
    if(i<0||i>=LEVELS.length||j<0||j>=keys.length){cv.title='';return;}
    const level=LEVELS[i],d=keys[j],data=history.get(level);
    const v=anomaly(data.observations.get(d),nasa.climate(data,d,'mean'),mode);
    cv.title=d+' · '+level+' hPa · '+(finite(v)?v.toFixed(1)+' m/s':'kein Originalwert');
  };
}
function draw(){
  if(!history)return;
  const mode=$('stratoVerticalMode').value;
  const to=new Date().toISOString().slice(0,10),from=nasa.dateISO(to,-44);
  paintHeatmap(history,from,to,mode);
  const forecastG=window.stratoJointMath?.summarize(forecast?.gefs,forecast?.hour,'gefs');
  const forecastE=window.stratoJointMath?.summarize(forecast?.eps,forecast?.hour,'eps');
  const starts=[forecastG?.rows[0]?.date,forecastE?.rows[0]?.date].filter(Boolean).sort();
  const begin=starts[0]||nasa.dateISO(to,1);
  const until=[to,forecastG?.rows.at(-1)?.date,forecastE?.rows.at(-1)?.date].filter(Boolean).sort().at(-1);
  const all=dates(from,until),gmap=new Map((forecastG?.rows||[]).map(row=>[row.date,row])),
    emap=new Map((forecastE?.rows||[]).map(row=>[row.date,row]));
  const sets=LEVELS.map(level=>{
    const data=history.get(level);
    return {label:level+' hPa · NASA Analyse',data:all.map(date=>
      date<begin?anomaly(data.observations.get(date),nasa.climate(data,date,'mean'),mode):null),
      borderColor:COLORS[level],backgroundColor:COLORS[level],
      borderWidth:level===10?3:2.1,pointRadius:0,tension:0.1,spanGaps:false,fill:false};
  });
  const ten=history.get(10);
  for(const [label,memberMap,c] of [
    ['GEFS · 10 hPa Prognose',gmap,'#0965b3'],
    ['ECMWF ENS · 10 hPa Prognose',emap,'#d44e22']
  ]) {
    sets.push({label,data:all.map(date=>{
      const r=memberMap.get(date);
      return r?anomaly(r.mean,nasa.climate(ten,date,'mean'),mode):null;
    }),borderColor:c,backgroundColor:c,borderWidth:3,
      borderDash:[6,4],pointRadius:0,spanGaps:false,fill:false});
  }
  sets.push({label:'0 m/s · Schwelle / Normalniveau',
    data:all.map(()=>0),borderColor:'#728091',borderDash:[3,4],
    pointRadius:0,borderWidth:1,fill:false});
  if(lineChart){lineChart.destroy();lineChart=null;}
  lineChart=new Chart($('stratoVerticalLineChart'),{
    type:'line',data:{labels:all,datasets:sets},
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>
        c.dataset.label+': '+c.parsed.y.toFixed(1)+' m/s'}}},
      interaction:{mode:'index',intersect:false},
      scales:{x:{ticks:{maxTicksLimit:11,maxRotation:0},title:{display:true,text:'Datum · NASA täglich / Prognosen '+String(forecast?.hour||0).padStart(2,'0')+' UTC'}},
        y:{title:{display:true,text:mode==='absolute'?'Zonalwind (m/s)':'Abweichung vom Klimamittel (m/s)'}}}}
  });
  lastRows=tabularRows(history,mode);
  const body=$('stratoVerticalTable');body.replaceChildren();
  lastRows.forEach(item=>{
    const tr=document.createElement('tr');
    for(const value of [item.level+' hPa',item.date,
      finite(item.value)?item.value.toFixed(1)+' m/s':'–',
      finite(item.anomaly)?(item.anomaly>0?'+':'')+item.anomaly.toFixed(1)+' m/s':'–']){
      const cell=document.createElement('td');cell.textContent=value;tr.append(cell);
    }
    body.append(tr);
  });
  status('NASA Originalanalyse für fünf Niveaus · '+from+' bis '+to+
    '. GEFS/ECMWF ENS-Prognosen derzeit nachgewiesen nur bei 10 hPa'+
    (forecast?' ('+String(forecast.hour).padStart(2,'0')+' UTC)':'')+
    '. Anomalien beziehen sich auf 1991–2020. Fehlende Tage bleiben leer.');
  $('stratoVerticalPng').disabled=false;
  $('stratoVerticalHeatPng').disabled=false;
}
async function load(){
  const target=++token,to=new Date().toISOString().slice(0,10),from=nasa.dateISO(to,-44);
  status('Lade täglich gemessene/reanalysierte NASA-Zonalwinde auf 10, 30, 50, 70 und 100 hPa …');
  try{
    history=await nasa.load(LEVELS,from,to);
    if(target!==token)return;
    draw();
  }catch(error){
    if(target!==token)return;
    status('NASA-Vertikalprofil nicht verfügbar: '+error.message);
  }
}
$('stratoVerticalMode').addEventListener('change',draw);
window.addEventListener('stratosphere:joint-data-ready',event=>{forecast=event.detail;if(history)draw();});
$('stratoVerticalPng').addEventListener('click',()=>{
  if(!lineChart)return;
  const png=window.stratoChartExport.fromChart(lineChart,{
    title:'Polarwirbel · vertikaler Zonalwind 60° N · 10–100 hPa',
    subtitle:$('stratoVerticalMode').selectedOptions[0].textContent+
      ' · GEFS/EPS-Prognosen nur 10 hPa',
    source:'NASA Ozone Watch (MERRA-2/GEOS-FP) · NOAA GEFS / ECMWF IFS ENS nur 10 hPa'
  });
  const a=document.createElement('a');a.href=png.toDataURL('image/png');
  a.download='Stratosphaere_Zonalwind_5_Druckniveaus.png';a.click();
});
$('stratoVerticalHeatPng').addEventListener('click',()=>{
  const a=document.createElement('a');a.href=$('stratoVerticalHeatmap').toDataURL('image/png');
  a.download='Stratosphaere_60N_Zeit_Hoehe_NASA.png';a.click();
});
if(window.stratoJointForecastData)forecast=window.stratoJointForecastData;
void load();
})();
