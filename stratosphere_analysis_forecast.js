/* Historical NASA daily zonal winds + same-hour GEFS/EPS forecasts.
   NASA daily values and 12-UTC model validities are deliberately NOT claimed
   to be temporally collocated. Missing data stay null. */
(()=>{
'use strict';
const $=id=>document.getElementById(id);
const dates=window.stratoNASAData;
const root=$('stratoHistoryForecastPanel');
if(!root||!dates)return;
let last=null,chart=null,rows=[],available=null;
let request=0;
const fmt=n=>Number.isFinite(n)?n.toFixed(1):'–';
const finite=n=>typeof n==='number'&&Number.isFinite(n);
const iso=d=>d?.slice(0,10);
const line=(label,data,color,width=2,props={})=>({
  label,data,borderColor:color,backgroundColor:color,borderWidth:width,
  pointRadius:0,pointHoverRadius:4,spanGaps:false,tension:0,fill:false,...props
});
function compose(history,comparison,mode){
  const g=window.stratoJointMath?.summarize(comparison?.gefs,comparison?.hour,'gefs');
  const e=window.stratoJointMath?.summarize(comparison?.eps,comparison?.hour,'eps');
  const now=new Date().toISOString().slice(0,10);
  const starts=[g?.rows[0]?.date,e?.rows[0]?.date].filter(Boolean);
  const startsOn=starts.length?starts.sort()[0]:now;
  const from=dates.dateISO(startsOn,-30);
  const ends=[g?.rows.at(-1)?.date,e?.rows.at(-1)?.date,startsOn].filter(Boolean);
  const end=ends.sort().at(-1);
  const gmap=new Map((g?.rows||[]).map(row=>[row.date,row]));
  const emap=new Map((e?.rows||[]).map(row=>[row.date,row]));
  const ref=history?.get(10);
  const result=[];
  for(let date=from;date<=end;date=dates.dateISO(date,1)){
    const average=dates.climate(ref,date,'mean');
    const adjust=n=>mode==='anomaly'&&finite(n)&&finite(average)?n-average:n;
    const validReference=mode!=='anomaly'||finite(average);
    const observed=ref?.observations?.get(date);
    const gRow=gmap.get(date),eRow=emap.get(date);
    result.push({date,average:mode==='anomaly'?0:average,
      p10:adjust(dates.climate(ref,date,'p10')),
      p90:adjust(dates.climate(ref,date,'p90')),
      analysis:date<=startsOn&&validReference&&finite(observed)?adjust(observed):null,
      gefs:validReference&&gRow?adjust(gRow.mean):null,
      eps:validReference&&eRow?adjust(eRow.mean):null,
      transition:date===startsOn});
  }
  return {rows:result,from,end,transition:startsOn,g,e,mode};
}
window.stratoHistoryMath={compose};
const markerPlugin={
  id:'stratoAnalysisBoundary',
  afterDatasetsDraw(graph){
    const label=graph.data.labels||[];
    const index=label.indexOf(graph.$transition);
    const x=graph.scales?.x?.getPixelForValue(index);
    if(index<0||!Number.isFinite(x))return;
    const {ctx,chartArea}=graph;ctx.save();
    ctx.strokeStyle='#425569';ctx.lineWidth=1.6;ctx.setLineDash([6,4]);
    ctx.beginPath();ctx.moveTo(x,chartArea.top);ctx.lineTo(x,chartArea.bottom);ctx.stroke();
    ctx.setLineDash([]);ctx.fillStyle='#314a62';ctx.font='600 11px Arial';
    ctx.fillText('Prognosestart',Math.min(chartArea.right-95,Math.max(chartArea.left+2,x+5)),chartArea.top+13);
    ctx.restore();
  }
};
function draw(result){
  if(chart){chart.destroy();chart=null;}
  rows=result.rows;
  const c=rows.map(row=>row.date),metric=result.mode==='anomaly'?'Abweichung (m/s)':'Zonalwind (m/s)';
  const lower=line('_Klimaperzentile 10–90 % Untergrenze',rows.map(r=>r.p10),'transparent',0);
  const upper=line('Klimaperzentile 10–90 %',rows.map(r=>r.p90),'transparent',0,
    {fill:{target:'-1',above:'rgba(109,128,146,.22)',below:'rgba(109,128,146,.22)'}});
  const datasets=[
    lower,upper,
    line('NASA Klimamittel 1991–2020',rows.map(r=>r.average),'#8c7a33',2,{borderDash:[6,3]}),
    line('NASA Tagesanalyse',rows.map(r=>r.analysis),'#222d3d',3.2),
    line('GEFS Ensemble-Mittel (10 hPa)',rows.map(r=>r.gefs),'#1167ac',3),
    line('ECMWF ENS-Mittel (10 hPa)',rows.map(r=>r.eps),'#c34825',3),
    line('0 m/s · Windumkehrschwelle',c.map(()=>0),'#566576',1.1,{borderDash:[3,4]})
  ];
  chart=new Chart($('stratoHistoryForecastCanvas'),{
    type:'line',data:{labels:c,datasets},
    plugins:[markerPlugin],
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      interaction:{mode:'index',intersect:false},
      plugins:{legend:{display:false},tooltip:{filter:x=>x.dataset.label[0]!=='_',
        callbacks:{label:item=>item.dataset.label+': '+fmt(item.parsed.y)+' m/s'}}},
      scales:{x:{ticks:{maxTicksLimit:13,maxRotation:0},title:{display:true,text:'Datum (NASA täglich / Modelle '+String(last?.hour||0).padStart(2,'0')+' UTC)'}},
        y:{title:{display:true,text:metric}}}
    }
  });
  chart.$transition=result.transition;
  $('stratoHistoryForecastPng').disabled=false;
  $('stratoHistoryForecastCsv').disabled=false;
  const seen=rows.filter(r=>finite(r.analysis)).map(r=>r.date);
  $('stratoHistoryForecastStatus').textContent=
    'NASA-Analyse bis '+(seen.at(-1)||'nicht verfügbar')+
    ' · '+rows.filter(r=>finite(r.gefs)).length+' GEFS- und '+
    rows.filter(r=>finite(r.eps)).length+' ECMWF-ENS-Prognosetage.'+
    (Number(last?.hour)===12?' NASA-Tagesanalysen sind nicht automatisch 12-UTC-Messwerte.':'')+
    ' Nicht vorhandene Termine bleiben leer; kein künstlicher Anschluss.';
}
async function refresh(){
  const token=++request,source=last,mode=$('stratoHistoryForecastMode').value;
  $('stratoHistoryForecastStatus').textContent='Lade NASA-Tagesanalysen und historische 1991–2020-Perzentile …';
  $('stratoHistoryForecastPng').disabled=true;$('stratoHistoryForecastCsv').disabled=true;
  const starts=[source?.gefs?.valid_dates?.[0],source?.eps?.valid_dates?.[0]].filter(Boolean).sort();
  const from=dates.dateISO(starts[0]||new Date().toISOString().slice(0,10),-30);
  try {
    const history=await dates.load([10],from,starts[0]||new Date().toISOString().slice(0,10));
    if(token!==request)return;
    available=compose(history,source,mode);
    draw(available);
  }catch(err){
    if(token!==request)return;
    $('stratoHistoryForecastStatus').textContent='NASA-Reihen derzeit nicht erreichbar: '+err.message;
    if(chart){chart.destroy();chart=null;}
  }
}
$('stratoHistoryForecastMode').addEventListener('change',refresh);
window.addEventListener('stratosphere:joint-data-ready',event=>{last=event.detail;void refresh();});
$('stratoHistoryForecastPng').addEventListener('click',()=>{
  if(!chart)return;
  const png=window.stratoChartExport.fromChart(chart,{
    title:'Polarwirbel: NASA-Analyse und GEFS/ECMWF-ENS-Prognose · 60° N / 10 hPa',
    subtitle:'Klimareferenz 1991–2020 · '+$('stratoHistoryForecastMode').selectedOptions[0].textContent+
      ' · Modelle '+String(last?.hour||0).padStart(2,'0')+' UTC',
    source:'NASA Ozone Watch (MERRA-2 / GEOS-FP), NOAA GEFS, ECMWF IFS ENS · Referenz 1991–2020'
  });
  const a=document.createElement('a');a.href=png.toDataURL('image/png');
  a.download='Stratosphaere_NASA_GEFS_ECMWF_Analyse_Prognose.png';a.click();
});
$('stratoHistoryForecastCsv').addEventListener('click',()=>{
  if(!rows.length)return;
  const cols=['Datum','NASA_Tagesanalyse_m_s','NASA_Klimamittel_oder_Null',
    'P10','P90','GEFS_Mittel','ECMWF_ENS_Mittel'];
  const text=[cols.join(';'),...rows.map(r=>[
    r.date,r.analysis??'',r.average??'',r.p10??'',r.p90??'',r.gefs??'',r.eps??''
  ].join(';'))].join('\r\n');
  const url=URL.createObjectURL(new Blob(['\ufeff'+text],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='Stratosphaere_Analyse_Prognose.csv';a.click();
  setTimeout(()=>URL.revokeObjectURL(url),3000);
});
if(window.stratoJointForecastData){last=window.stratoJointForecastData;void refresh();}
else void refresh();
})();
