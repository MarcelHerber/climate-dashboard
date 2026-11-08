/* Extended GEFS/EPS comparison: first reversal within +7/+15d, absolute
   mean-model divergence, and same-hour previous model run changes. */
(()=>{
'use strict';
const $=id=>document.getElementById(id);
const math=window.stratoJointMath;
function probability(stats,days) {
  if(!stats||!Number.isInteger(days)||days<1||stats.rows.length<=days)return null;
  const first=stats.rows.slice(1,days+1).reduce((total,row)=>total+row.first,0);
  return {first,total:stats.count,percent:100*first/stats.count,days};
}
function difference(rows) {
  return rows.map(row=>({date:row.date,value:row.g.mean-row.e.mean,
    gefs:row.g.mean,eps:row.e.mean}));
}
window.stratoMetricsMath={probability,difference};
if(!$('stratoJointMetricsPanel')||!math)return;
let comparison=null,stats=null,aligned=[],diffChart=null,past=null;
let sequence=0;
const provider={
  gefs:{index:'https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/stratosphere-ensemble-data/data/stratosphere/ensemble/gefs_index.json',
    base:'https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/stratosphere-ensemble-data/data/stratosphere/ensemble/',
    name:'NOAA GEFS'},
  eps:{index:'https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/stratosphere-ecmwf-ens-data/data/stratosphere/ecmwf/ens_index.json',
    base:'https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/stratosphere-ecmwf-ens-data/data/stratosphere/ecmwf/',
    name:'ECMWF IFS ENS'}
};
const percent=(p)=>p===null?'–':Math.round(p.percent)+' % ('+p.first+'/'+p.total+')';
function label(id,value){$(id).textContent=value;}
async function lastRun(model,activeCycle,hour){
  const p=provider[model];
  const indexRequest=await fetch(p.index+'?t='+Date.now(),{cache:'no-store'});
  if(!indexRequest.ok)throw Error('Index '+indexRequest.status);
  const index=await indexRequest.json();
  if(index.provider!==p.name||!Array.isArray(index.runs))throw Error('Unbekannte Modelllaufquelle');
  const older=index.runs.filter(run=>
    run.cycle_utc<activeCycle &&
    Number(run.cycle_utc?.slice(11,13))===hour &&
    /^runs\/\d{8}_\d{6}\.json$/.test(run.path||'')
  ).sort((a,b)=>b.cycle_utc.localeCompare(a.cycle_utc))[0];
  if(!older)return null;
  const response=await fetch(p.base+older.path+'?t='+Date.now(),{cache:'no-store'});
  if(!response.ok)throw Error('Archiv '+response.status);
  const raw=await response.json();
  if(raw.cycle_utc!==older.cycle_utc || raw.provider!==p.name)return null;
  const summary=math.summarize(raw,hour,model);
  return summary;
}
async function loadPrevious(token,hour){
  if(!stats?.g || !stats?.e)return;
  const result=await Promise.allSettled([
    lastRun('gefs',stats.g.cycle,hour),lastRun('eps',stats.e.cycle,hour)
  ]);
  if(sequence!==token)return;
  const g=result[0].status==='fulfilled'?result[0].value:null;
  const e=result[1].status==='fulfilled'?result[1].value:null;
  past={g,e};
  for(const [k,target] of [['g','stratoMetricTrendG'],['e','stratoMetricTrendE']]){
    const latest=stats[k],previous=past[k];
    if(!previous){label(target,'Kein vorheriger geprüfter Lauf für dieselbe UTC-Stunde.');continue;}
    const trend=[7,15].map(days=>{
      const a=probability(latest,days),b=probability(previous,days);
      return !a||!b?'+'+days+' d: –':
        '+'+days+' d: '+((a.percent-b.percent)>=0?'+':'')+
        (a.percent-b.percent).toFixed(1)+' Prozentpunkte';
    }).join(' · ');
    label(target,'Vorlauf '+previous.cycle+' → '+latest.cycle+' · '+trend);
  }
}
function draw(){
  if(diffChart){diffChart.destroy();diffChart=null;}
  const h=Number(comparison?.hour??0);
  stats={g:math.summarize(comparison?.gefs,h,'gefs'),
    e:math.summarize(comparison?.eps,h,'eps')};
  aligned=math.align(stats.g,stats.e);
  const limit=Number($('stratoMetricThreshold').value)||10;
  const diff=difference(aligned);
  const flagged=diff.filter(item=>Math.abs(item.value)>=limit);
  for(const [model,prefix] of [['g','G'],['e','E']]){
    label('stratoMetric'+prefix+'7',percent(probability(stats[model],7)));
    label('stratoMetric'+prefix+'15',percent(probability(stats[model],15)));
  }
  const biggest=diff.reduce((a,b)=>Math.abs(b.value)>Math.abs(a.value)?b:a,
    {value:0,date:''});
  label('stratoMetricLargest',diff.length?biggest.value.toFixed(1)+' m/s am '+biggest.date:'–');
  label('stratoMetricDivergence',flagged.length+'/'+diff.length+
    ' gemeinsame Tage mit |GEFS – ECMWF| ≥ '+limit+' m/s.');
  $('stratoMetricPng').disabled=!diff.length;
  $('stratoMetricCsv').disabled=!diff.length;
  if(!diff.length){label('stratoMetricTrendG','–');label('stratoMetricTrendE','–');return;}
  diffChart=new Chart($('stratoMetricDiffChart'),{
    type:'line',data:{labels:diff.map(x=>x.date),datasets:[
      {label:'GEFS minus ECMWF ENS · Mittelwertdifferenz (m/s)',
        data:diff.map(x=>x.value),borderColor:'#275c88',
        backgroundColor:'#275c88',borderWidth:3,spanGaps:false,fill:false,
        pointRadius:diff.map(x=>Math.abs(x.value)>=limit?5:2),
        pointBackgroundColor:diff.map(x=>Math.abs(x.value)>=limit?'#c23827':'#275c88')},
      {label:'0 m/s · gleiche Mittelwerte',data:diff.map(()=>0),borderColor:'#536578',
        borderDash:[4,4],borderWidth:1,pointRadius:0}
    ]},
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:item=>
        item.dataset.label+': '+item.parsed.y.toFixed(1)+' m/s'}}},
      scales:{x:{ticks:{maxTicksLimit:11,maxRotation:0},title:{display:true,text:'Gemeinsamer '+String(h).padStart(2,'0')+'-UTC-Gültigkeitstermin'}},
        y:{title:{display:true,text:'GEFS minus ECMWF ENS (m/s)'}}}
    }
  });
  const token=++sequence;
  past=null;
  label('stratoMetricTrendG','Prüfe vorherige GEFS-Modellläufe derselben UTC-Stunde …');
  label('stratoMetricTrendE','Prüfe vorherige ECMWF-Modellläufe derselben UTC-Stunde …');
  void loadPrevious(token,h);
}
window.addEventListener('stratosphere:joint-data-ready',event=>{
  comparison=event.detail;draw();
});
$('stratoMetricThreshold').addEventListener('change',()=>{
  // The threshold changes the alert styling, not the probabilities.
  if(comparison)draw();
});
$('stratoMetricPng').addEventListener('click',()=>{
  if(!diffChart||!stats?.g||!stats?.e)return;
  const png=window.stratoChartExport.fromChart(diffChart,{
    title:'Polarwirbel · Ensemble-Mittelwertdifferenz GEFS – ECMWF ENS',
    subtitle:'60° N · 10 hPa · '+String(comparison.hour).padStart(2,'0')+' UTC',
    source:'NOAA GEFS, ECMWF IFS ENS · gleiche Gültigkeitstermine · keine Interpolation'
  });
  const a=document.createElement('a');a.download='Stratosphaere_GEFS_ECMWF_Mitteldifferenz.png';
  a.href=png.toDataURL('image/png');a.click();
});
$('stratoMetricCsv').addEventListener('click',()=>{
  if(!aligned.length)return;
  const out=['date_utc;gefs_mean_ms;eps_mean_ms;gefs_minus_eps_ms',
    ...difference(aligned).map(r=>[r.date,r.gefs,r.eps,r.value].join(';'))].join('\r\n');
  const url=URL.createObjectURL(new Blob(['\ufeff'+out],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='Stratosphaere_GEFS_ECMWF_Mitteldifferenz.csv';
  a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);
});
if(window.stratoJointForecastData){comparison=window.stratoJointForecastData;draw();}
})();
