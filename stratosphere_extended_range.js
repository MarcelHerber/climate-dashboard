(function(){
'use strict';
const PROVIDER='ECMWF IFS Sub-seasonal S2S';
const KEYS=['c00',...Array.from({length:100},(_,i)=>'p'+String(i+1).padStart(3,'0'))];
const ROOT='https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/stratosphere-ecmwf-extended-data/data/stratosphere/extended/';
const API='https://charts.ecmwf.int/opencharts-api/v1/products/extended-zonal-mean-zonal-wind/?area=nh';
function validate(d){
  if(!d||d.schema_version!==1||d.provider!==PROVIDER||d.level_hpa!==10||d.latitude_deg!==60||d.units!=='m/s'||d.member_count!==101||!/^\d{4}-\d{2}-\d{2}T00:00:00Z$/.test(d.cycle_utc))return false;
  const cycle=Date.parse(d.cycle_utc);
  if(!Number.isFinite(cycle)||!Array.isArray(d.valid_dates)||d.valid_dates.length!==47||!Array.isArray(d.forecast_step_hours)||d.forecast_step_hours.length!==47)return false;
  return d.valid_dates.every((day,i)=>day===new Date(cycle+i*86400000).toISOString().slice(0,10)&&d.forecast_step_hours[i]===i*24)&&
    d.members&&Object.keys(d.members).length===101&&KEYS.every(k=>Array.isArray(d.members[k])&&d.members[k].length===47&&d.members[k].every(x=>typeof x==='number'&&Number.isFinite(x)&&x>-160&&x<170));
}
function statistics(data){
  if(!validate(data))throw new Error('Unvollständiger 101-Member-Lauf');
  const q=(a,p)=>{const x=(a.length-1)*p,i=Math.floor(x);return a[i]+(a[Math.ceil(x)]-a[i])*(x-i);};
  const rows=data.valid_dates.map((date,i)=>{
    const v=KEYS.map(k=>data.members[k][i]).sort((a,b)=>a-b);
    return {date,mean:v.reduce((sum,n)=>sum+n,0)/101,p10:q(v,.1),p25:q(v,.25),p75:q(v,.75),p90:q(v,.9),control:data.members.c00[i],probability:v.filter(x=>x<0).length/101*100};
  });
  const crossing=Object.fromEntries([14,28,42,46].map(h=>[h,KEYS.filter(k=>data.members[k].slice(1,h+1).some((x,i)=>data.members[k][i]>=0&&x<0)).length/101*100]));
  return {rows,crossing};
}
function chartLink(payload){
  const d=payload?.data,link=d?.link;
  if(d?.type!=='graphical_product'||d?.attributes?.name!=='extended-zonal-mean-zonal-wind'||link?.type!=='image/png')throw new Error('Unerwartetes ECMWF-Produkt');
  const url=new URL(link.href);
  if(url.origin!=='https://charts.ecmwf.int'||!url.pathname.startsWith('/content/')||!url.pathname.endsWith('.png'))throw new Error('Ungültige ECMWF-Grafikadresse');
  return url.href;
}
if(typeof module!=='undefined'&&module.exports){module.exports={validate,statistics,chartLink};return;}
const $=id=>document.getElementById(id),tab=$('stratoExtendedTab'),view=$('stratoExtendedView');
if(!tab||!view)return;
let selected=null,index=[],chart=null,prob=null,older=[],requestId=0,loaded=false;
const controls=['stratoExtendedMembers','stratoExtendedBands','stratoExtendedCompare','stratoExtendedPng','stratoExtendedCsv'];
const get=async url=>{const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);return r.json();};
const bust=()=>'?v='+Date.now();
const format=d=>d.slice(8,10)+'.'+d.slice(5,7)+'.'+d.slice(0,4);
const pct=n=>n.toLocaleString('de-DE',{maximumFractionDigits:1})+' %';
function destroy(){if(chart)chart.destroy();if(prob)prob.destroy();chart=prob=null;}
function setReady(ok){for(const id of controls)$(id).disabled=!ok;}
function render(){
  if(!selected||view.hidden||typeof Chart==='undefined')return;
  destroy();
  const {rows,crossing}=statistics(selected),labels=selected.valid_dates.map(format);
  const lines=[], line=(label,data,color,extra={})=>({label,data,borderColor:color,backgroundColor:color,borderWidth:2,pointRadius:0,tension:0,spanGaps:false,...extra});
  if($('stratoExtendedBands').checked){
    lines.push(line('_P10 Untergrenze',rows.map(r=>r.p10),'rgba(87,134,200,.2)',{borderWidth:0}),line('P10–P90',rows.map(r=>r.p90),'rgba(87,134,200,.2)',{borderWidth:0,fill:{target:'-1',above:'rgba(87,134,200,.2)'}}));
    lines.push(line('_P25 Untergrenze',rows.map(r=>r.p25),'rgba(87,134,200,.35)',{borderWidth:0}),line('P25–P75',rows.map(r=>r.p75),'rgba(87,134,200,.35)',{borderWidth:0,fill:{target:'-1',above:'rgba(87,134,200,.35)'}}));
  }
  if($('stratoExtendedMembers').checked)for(const k of KEYS.slice(1))lines.push(line('_Mitglied '+k,selected.members[k],'rgba(100,116,139,.32)',{borderWidth:.65}));
  if($('stratoExtendedCompare').checked)for(const [i,d] of older.entries()){
    const values=new Map(statistics(d).rows.map(r=>[r.date,r.mean]));
    lines.push(line('ENSEMBLE-Mittel '+format(d.cycle_utc),selected.valid_dates.map(day=>values.get(day)??null),['#0891b2','#7c3aed','#059669','#a16207','#94a3b8','#db2777'][i%6],{borderDash:[4,3],borderWidth:1.5}));
  }
  lines.push(line('0 m/s',rows.map(()=>0),'#64748b',{borderDash:[5,4],borderWidth:1}),line('Kontrolllauf',rows.map(r=>r.control),'#d97706',{borderDash:[4,3]}),line('Ensemble-Mittel (101)',rows.map(r=>r.mean),'#dc2626',{borderWidth:3}));
  const axis={responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'index',intersect:false},scales:{x:{ticks:{maxTicksLimit:12}},y:{title:{display:true,text:'Zonalwind (m/s)'}}},plugins:{legend:{labels:{filter:item=>!item.text.startsWith('_')}},tooltip:{filter:item=>!item.dataset.label.startsWith('_')}}};
  chart=new Chart($('stratoExtendedCanvas'),{type:'line',data:{labels,datasets:lines},options:axis});
  prob=new Chart($('stratoExtendedProbCanvas'),{type:'line',data:{labels,datasets:[line('Anteil U < 0 m/s',rows.map(r=>r.probability),'#2563eb',{fill:'origin',backgroundColor:'rgba(37,99,235,.16)'})]},options:{responsive:true,maintainAspectRatio:false,animation:false,scales:{x:{ticks:{maxTicksLimit:12}},y:{min:0,max:100,title:{display:true,text:'Anteil (%)'}}}}});
  for(const h of [14,28,42,46])$('stratoExtendedP'+h).textContent=pct(crossing[h]);
}
async function loadChart(){
  $('stratoExtendedOfficialStatus').textContent='Prüfe aktuelle offizielle ECMWF-Grafik …';
  try{
    const href=chartLink(await get(API+'&v='+Date.now()));
    $('stratoExtendedOfficialImage').src=href;
    $('stratoExtendedOfficialImage').hidden=false;
    $('stratoExtendedOfficialLink').href=href;
    $('stratoExtendedOfficialLink').hidden=false;
    $('stratoExtendedOfficialStatus').textContent='Neueste vom ECMWF bereitgestellte Originalgrafik · Initialisierungsdatum in der Grafik.';
  }catch(e){$('stratoExtendedOfficialImage').hidden=true;$('stratoExtendedOfficialLink').hidden=true;$('stratoExtendedOfficialStatus').textContent='Originalgrafik aktuell nicht abrufbar. Bitte den ECMWF-Quelllink verwenden.';}
}
async function loadData(reset=false){
  const id=++requestId;
  setReady(false);$('stratoExtendedDataStatus').textContent='Prüfe 101 Originalmitglieder aus dem S2S-Archiv …';
  try{
    if(reset||!index.length){
      const idx=await get(ROOT+'index.json'+bust());
      if(id!==requestId)return;
      if(idx.provider!==PROVIDER||!Array.isArray(idx.runs))throw new Error('Ungültiges Laufarchiv');
      index=idx.runs.filter(r=>/^runs\/\d{8}\.json$/.test(r.path)&&/^\d{4}-\d{2}-\d{2}T00:00:00Z$/.test(r.cycle_utc)).slice(0,8);
      if(!index.length)throw new Error('Keine geprüften Läufe verfügbar');
      const select=$('stratoExtendedCycle');select.replaceChildren();
      for(const r of index){const option=document.createElement('option');option.value=r.path;option.textContent=format(r.cycle_utc)+' · 00 UTC';select.append(option);}
    }
    const run=index.find(r=>r.path===$('stratoExtendedCycle').value)||index[0];
    const data=await get(ROOT+run.path+bust());
    if(!validate(data)||data.cycle_utc!==run.cycle_utc||Date.parse(data.cycle_utc)>Date.now())throw new Error('Lauf unvollständig oder falsch datiert');
    if(id!==requestId)return;
    selected=data;older=[];
    const hours=Math.floor((Date.now()-Date.parse(data.cycle_utc))/3600000);
    $('stratoExtendedDataStatus').textContent=`Lauf ${format(data.cycle_utc)}, 00 UTC · 101/101 Mitglieder · ${hours} h seit Initialisierung · bis ${format(data.valid_dates[46])}${hours>96?' · älterer Datenstand':''}`;
    setReady(true);render();
    if($('stratoExtendedCompare').checked)void loadOlder();
  }catch(e){if(id!==requestId)return;selected=null;destroy();for(const h of [14,28,42,46])$('stratoExtendedP'+h).textContent='–';$('stratoExtendedDataStatus').textContent='Noch kein vollständiger 101-Member-Lauf verfügbar. S2S-Daten werden frühestens nach 48 Stunden freigegeben; die offizielle Grafik bleibt unabhängig verfügbar.';}
}
async function loadOlder(){
  const run=selected?.cycle_utc;if(!run)return;
  const list=await Promise.all(index.filter(r=>r.cycle_utc<run).map(async r=>{try{const d=await get(ROOT+r.path);return validate(d)&&d.cycle_utc===r.cycle_utc?d:null;}catch{return null;}}));
  if(selected?.cycle_utc!==run)return;older=list.filter(Boolean);render();
}
function activate(active){
  view.hidden=!active;tab.setAttribute('aria-pressed',String(active));
  $('stratoGefsMainActions').hidden=active;
  if(active){
    for(const id of ['stratoGefs','stratoEps','stratoEcmwf']){$(id+'View').hidden=true;$(id+'Tab').setAttribute('aria-pressed','false');}
    if(!loaded){loaded=true;void loadChart();void loadData(true);}else render();
  }
}
tab.addEventListener('click',()=>activate(true));
for(const id of ['stratoGefsTab','stratoEpsTab','stratoEcmwfTab'])$(id).addEventListener('click',()=>activate(false));
$('stratoExtendedReload').addEventListener('click',()=>{void loadChart();void loadData(true);});
$('stratoExtendedCycle').addEventListener('change',()=>loadData());
for(const id of ['stratoExtendedMembers','stratoExtendedBands'])$(id).addEventListener('change',render);
$('stratoExtendedCompare').addEventListener('change',()=>{if($('stratoExtendedCompare').checked)void loadOlder();else render();});
$('stratoExtendedOfficialImage').addEventListener('error',()=>{$('stratoExtendedOfficialImage').hidden=true;$('stratoExtendedOfficialStatus').textContent='Die Originalgrafik konnte nicht geladen werden.';});
$('stratoExtendedCsv').addEventListener('click',()=>{
  if(!selected)return;const {rows}=statistics(selected);
  const fields=['Datum_UTC','Mittel_m_s','P10','P25','P75','P90','Kontrolle','U_unter_0_Prozent',...KEYS];
  const body=[fields.join(';'),...rows.map((r,i)=>[r.date,r.mean,r.p10,r.p25,r.p75,r.p90,r.control,r.probability,...KEYS.map(k=>selected.members[k][i])].join(';'))].join('\n');
  const uri=URL.createObjectURL(new Blob(['\ufeff'+body],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=uri;a.download='ECMWF_46Tage_U60_'+selected.cycle_utc.slice(0,10)+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(uri),3000);
});
$('stratoExtendedPng').addEventListener('click',()=>{
  if(!chart||!selected)return;const image=window.stratoChartExport?.fromChart(chart,{title:'ECMWF Sub-seasonal · 60° N / 10 hPa',subtitle:'Lauf '+selected.cycle_utc+' · 101 Mitglieder · 46 Tage',source:'ECMWF S2S / ECDS · CC BY 4.0'});const a=document.createElement('a');a.href=image?image.toDataURL('image/png'):chart.toBase64Image();a.download='ECMWF_46Tage_U60_'+selected.cycle_utc.slice(0,10)+'.png';a.click();
});
})();
