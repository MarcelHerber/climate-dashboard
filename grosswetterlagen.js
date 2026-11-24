/* Gross weather type dashboard. Catalogues are never combined. */
'use strict';
const DAY=86400000;
function parseCatalogue(text){
 const map=new Map();
 for(const [i,line] of text.replace(/^\uFEFF/,'').split(/\r?\n/).entries()){
  const parts=line.split(';').map(s=>s.trim().replace(/^"|"$/g,''));
  if(!parts[0]||parts[0].startsWith('#'))continue;
  if(!/^\d{4}-\d{2}-\d{2}$/.test(parts[0])){if(i===0||/^(datum|date)$/i.test(parts[0]))continue;throw Error('Ungültiges Datum in Zeile '+(i+1));}
  const date=parts[0], code=parts[parts.length>=3?2:1]?.toUpperCase(), time=Date.parse(date+'T00:00:00Z');
  if(!Number.isFinite(time)||new Date(time).toISOString().slice(0,10)!==date||!code||!/^[A-Z0-9_-]{1,12}$/.test(code))throw Error('Ungültiger Datensatz in Zeile '+(i+1));
  if(map.has(date))throw Error('Doppeltes Datum: '+date);
  map.set(date,{date,code,time,year:+date.slice(0,4),month:+date.slice(5,7)});
 }
 if(!map.size)throw Error('Keine gültigen Tagesdaten.');
 return [...map.values()].sort((a,b)=>a.time-b.time);
}
function episodes(rows){
 const runs=[];for(const row of rows){const last=runs.at(-1);if(last&&last.code===row.code&&last.end.time+DAY===row.time){last.end=row;last.n++;}else runs.push({code:row.code,start:row,end:row,n:1});}
 return runs.filter((r,i)=>i>0&&i<runs.length-1&&runs[i-1].end.time+DAY===r.start.time&&r.end.time+DAY===runs[i+1].start.time);
}
function transitions(rows,accept){
 const counts=new Map();
 for(let i=1;i<rows.length;i++){const a=rows[i-1],b=rows[i];if(b.time-a.time!==DAY||a.code===b.code||!accept(a)||!accept(b))continue;const k=a.code+'|'+b.code;counts.set(k,(counts.get(k)||0)+1);}
 return counts;
}
if(typeof module!=='undefined')module.exports={parseCatalogue,episodes,transitions};
if(typeof document!=='undefined')(()=>{
const $=id=>document.getElementById(id), all='Alle', names=['Deutschland','Baden-Württemberg','Bayern','Berlin','Brandenburg','Bremen','Hamburg','Hessen','Mecklenburg-Vorpommern','Niedersachsen','Nordrhein-Westfalen','Rheinland-Pfalz','Saarland','Sachsen','Sachsen-Anhalt','Schleswig-Holstein','Thüringen'];
const remote='https://opendata.dwd.de/climate_environment/CDC/event_catalogues/europe/weather_types/GWL-REA/v1.6/historical/GWL-REA_v1.6_ERA5_GLP_catalogue.csv';
const raw='https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/bundeslaender-data-';
let rows=[],codes=[],chart,epoch=0,loadedSource='';
const fmt=(x,d=1)=>Number.isFinite(x)?x.toLocaleString('de-DE',{minimumFractionDigits:d,maximumFractionDigits:d}):'–';
const opts=(el,values)=>el.replaceChildren(...values.map(([v,t])=>new Option(t,v)));
function table(el,headers,data){const head=document.createElement('thead'),tr=head.insertRow();for(const h of headers){const th=document.createElement('th');th.textContent=h;tr.append(th);}const body=document.createElement('tbody');for(const row of data){const tr=body.insertRow();for(const v of row)tr.insertCell().textContent=v;}el.replaceChildren(head,body);}
function status(s,error=false){$('status').textContent=s;$('status').classList.toggle('error',error);}
function colour(code){const i=codes.indexOf(code);return 'hsl('+((i*137.508)%360)+' 55% 38%)';}
function base(r){const s=$('season').value;return r.date>=$('from').value&&r.date<=$('to').value&&(s==='all'||s.split(',').map(Number).includes(r.month));}
function selected(r){return base(r)&&($('type').value===all||r.code===$('type').value);}
function download(name,blob){const a=document.createElement('a'),url=URL.createObjectURL(blob);a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);}
function init(text,source,label){rows=parseCatalogue(text);loadedSource=source;codes=[...new Set(rows.map(r=>r.code))].sort();$('from').value=rows[0].date;$('to').value=rows.at(-1).date;for(const id of ['from','to']){$(id).min=rows[0].date;$(id).max=rows.at(-1).date;}opts($('type'),[[all,all],...codes.map(c=>[c,c])]);$('type').value=codes.includes('WZ')?'WZ':all;opts($('year'),[...new Set(rows.map(r=>r.year))].reverse().map(y=>[y,y]));$('results').hidden=false;const gaps=Math.round((rows.at(-1).time-rows[0].time)/DAY)+1-rows.length;status(label+' · '+rows[0].date+' bis '+rows.at(-1).date+' · '+rows.length.toLocaleString('de-DE')+' Tage · '+gaps+' fehlende Tage.');render();}
async function fetchText(url){const res=await fetch(url,{signal:AbortSignal.timeout(20000)});if(!res.ok)throw Error('HTTP '+res.status);return res.text();}
async function load(){const token=++epoch;rows=[];$('results').hidden=true;const s=$('source').value;if(s==='hb'){status('Bitte die Tagesdaten des historischen Katalogs als CSV importieren.');return;}status('Katalog wird geladen …');try{let text;try{text=await fetchText('data/grosswetterlagen/rea.csv');parseCatalogue(text);}catch(e){text=await fetchText(remote);}if(token!==epoch)return;init(text,s,'DWD GWL-REA v1.6');}catch(e){if(token===epoch)status('Abruf fehlgeschlagen: '+e.message+' — Original-CSV beim DWD herunterladen und hier importieren.',true);}}
function render(){
 const token=++epoch;const filtered=rows.filter(base), picked=filtered.filter(selected), counts=new Map(codes.map(c=>[c,0]));for(const r of filtered)counts.set(r.code,counts.get(r.code)+1);
 const chosen=$('type').value;
 let expected=0;const a=Date.parse($('from').value),b=Date.parse($('to').value);if(Number.isFinite(a)&&Number.isFinite(b))for(let t=a;t<=b;t+=DAY){const d=new Date(t);if($('season').value==='all'||$('season').value.split(',').map(Number).includes(d.getUTCMonth()+1))expected++;}
 $('coverage').textContent='Klassifizierte Tage: '+filtered.length+' von '+expected+' möglichen Tagen im Zeitraum.';
 const most=[...counts].sort((a,b)=>b[1]-a[1])[0];
 $('kpis').replaceChildren(...[['Ausgewählte Tage',picked.length],['Häufigster Typ',most?.[1]?most[0]:'–'],['Anteil Auswahl',filtered.length?fmt(100*picked.length/filtered.length)+' %':'–']].map(([l,v])=>{const d=document.createElement('div'),s=document.createElement('strong');s.textContent=v;d.append(s,l);return d;}));
 function ref(start,end){const season=$('season').value,rr=rows.filter(r=>r.year>=start&&r.year<=end&&(season==='all'||season.split(',').map(Number).includes(r.month))),m=new Map();for(const r of rr)m.set(r.code,(m.get(r.code)||0)+1);let expected=0;for(let t=Date.UTC(start,0,1);t<Date.UTC(end+1,0,1);t+=DAY)if(season==='all'||season.split(',').map(Number).includes(new Date(t).getUTCMonth()+1))expected++;return {m,n:rr.length,expected};}const refs=[ref(1961,1990),ref(1991,2020)];table($('freq'),['GWL','Tage','Anteil (%)',...refs.map((r,i)=>['1961–1990','1991–2020'][i]+' (%) · n='+r.n+'/'+r.expected)],[...counts].sort((a,b)=>b[1]-a[1]).map(([c,n])=>[c,n,fmt(filtered.length?100*n/filtered.length:NaN),...refs.map(r=>r.n===r.expected?fmt(100*(r.m.get(c)||0)/r.n):'–')]));
 const byYear=new Map();for(const r of filtered){const v=byYear.get(r.year)||[0,0];v[0]++;if(selected(r))v[1]++;byYear.set(r.year,v);}
 chart?.destroy();if(typeof Chart!=='undefined'){const y=[...byYear.keys()];chart=new Chart($('trend'),{type:'bar',data:{labels:y.map(v=>v+' (n='+byYear.get(v)[0]+')'),datasets:(chosen===all?codes:[chosen]).map(c=>{const countsByYear=new Map();for(const row of filtered)if(row.code===c)countsByYear.set(row.year,(countsByYear.get(row.year)||0)+1);return {label:c,data:y.map(v=>100*(countsByYear.get(v)||0)/byYear.get(v)[0]),backgroundColor:colour(c)};})},options:{responsive:true,maintainAspectRatio:false,animation:false,scales:{x:{stacked:chosen===all},y:{stacked:chosen===all,beginAtZero:true,max:chosen===all?100:undefined,title:{display:true,text:'Anteil (%)'}}},plugins:{legend:{display:true}}}});}
 const runs=episodes(rows).filter(r=>(chosen===all||r.code===chosen)&&r.start.date >= $('from').value&&r.end.date <= $('to').value&&episodeMatchesSeason(r)).sort((a,b)=>b.n-a.n||a.start.time-b.start.time);table($('records'),['GWL','Beginn','Ende','Tage'],runs.slice(0,100).map(r=>[r.code,r.start.date,r.end.date,r.n]));
 const trans=transitions(rows,base);const totals=new Map(codes.map(c=>[c,codes.reduce((n,d)=>n+(trans.get(c+'|'+d)||0),0)]));table($('matrix'),['Von → Nach',...codes],codes.map(c=>[c,...codes.map(d=>{const n=trans.get(c+'|'+d)||0;return c===d?'–':totals.get(c)?fmt(100*n/totals.get(c),0)+'% ('+n+')':'–';})]));
 for(const tr of $('matrix').tBodies[0].rows)for(let i=1;i<tr.cells.length;i++){const n=parseFloat(tr.cells[i].textContent);if(Number.isFinite(n)&&n>0)tr.cells[i].style.backgroundColor='rgba(55,126,185,'+(n/130)+')';}
 calendar();$('climtable').replaceChildren();$('climstatus').textContent='Filter geändert. Regionale Auswertung erneut starten.';
}
function episodeMatchesSeason(run){const s=$('season').value;if(s==='all')return true;const months=s.split(',').map(Number);for(let t=run.start.time;t<=run.end.time;t+=DAY)if(!months.includes(new Date(t).getUTCMonth()+1))return false;return true;}
function calendar(){const year=+$('year').value,m=new Map(rows.filter(r=>r.year===year&&selected(r)).map(r=>[r.date,r]));const cells=[];function cell(t,r){const e=document.createElement('span');e.textContent=t;if(r){e.className='day';e.style.backgroundColor=colour(r.code);e.title=r.date+' · '+r.code;}return e;}cells.push(cell(''));for(let d=1;d<=31;d++)cells.push(cell(d));for(let mo=1;mo<=12;mo++){cells.push(cell(String(mo).padStart(2,'0')));for(let d=1;d<=31;d++){const key=year+'-'+String(mo).padStart(2,'0')+'-'+String(d).padStart(2,'0'),r=m.get(key);cells.push(cell(r?.code||'',r));}}$('calendar').replaceChildren(...cells);}
async function json(url){return JSON.parse(await fetchText(url));}
async function climate(){
 const token=++epoch,parameter=$('param').value,region=$('region').value,dates=new Map(rows.filter(base).map(r=>[r.date,r.code])),years=new Set([...dates.keys()].map(s=>+s.slice(0,4))),root=raw+parameter+'/';
 $('climtable').replaceChildren();$('climstatus').textContent='Archiv wird gelesen …';try{
 const index=await json(root+'index.json'),target=index.years.filter(y=>years.has(y)),stats=new Map(codes.map(c=>[c,{n:0,sum:0,min:Infinity,max:-Infinity}]));let failed=0,used=0;
 for(let i=0;i<target.length;i+=6){const batch=await Promise.allSettled(target.slice(i,i+6).map(y=>json(root+y+'.json')));if(token!==epoch)return;for(const result of batch){if(result.status!=='fulfilled'){failed++;continue;}const data=result.value,v=data.regions?.[region];if(!Array.isArray(v)||v.length!==data.dates?.length){failed++;continue;}used++;data.dates.forEach((d,i)=>{const c=dates.get(d),x=v[i];if(!c||!Number.isFinite(x))return;const s=stats.get(c);s.n++;s.sum+=x;s.min=Math.min(s.min,x);s.max=Math.max(s.max,x);});}$('climstatus').textContent='Jahre gelesen: '+Math.min(i+6,target.length)+' / '+target.length;}
 if(token!==epoch)return;const unit=parameter==='precipitation'?'mm':parameter==='sunshine'?'h':'°C';table($('climtable'),['GWL','Messtage','Mittel ('+unit+')','Minimum','Maximum'],[...stats].filter(([c])=>$('type').value===all||c===$('type').value).map(([c,s])=>[c,s.n,fmt(s.n?s.sum/s.n:NaN),fmt(s.min),fmt(s.max)]));$('climstatus').textContent=region+' · '+used+' von '+years.size+' ausgewählten Jahren lesbar; '+failed+' Abruffehler. Keine Interpolation. Min/Max sind Extremwerte der täglichen Gebietsmittel.';
 }catch(e){if(token===epoch)$('climstatus').textContent='Archiv konnte nicht geladen werden: '+e.message;}
}
$('theme').onclick=()=>{const t=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=t;try{localStorage.setItem('climateDashboardThemeV1',t)}catch(e){}};
$('load').onclick=load;$('source').onchange=load;$('file').onchange=async()=>{const f=$('file').files[0];if(!f)return;const token=++epoch,s=$('source').value;try{const text=await f.text();if(token===epoch)init(text,s,'Lokaler Import: '+f.name);}catch(e){if(token===epoch){$('results').hidden=true;status(e.message,true);}}};
for(let i=1;i<=12;i++)$('season').add(new Option(new Date(Date.UTC(2020,i-1,1)).toLocaleString('de-DE',{month:'long',timeZone:'UTC'}),String(i)));
for(const id of ['from','to','season','type'])$(id).onchange=render;$('year').onchange=calendar;opts($('region'),names.map(n=>[n,n]));$('climate').onclick=climate;for(const id of ['param','region'])$(id).onchange=()=>{++epoch;$('climtable').replaceChildren();$('climstatus').textContent='Auswertung erneut starten.';};
$('csv').onclick=()=>download('grosswetterlagen-'+loadedSource+'.csv',new Blob(['Datum;GWL\n'+rows.filter(selected).map(r=>r.date+';'+r.code).join('\n')+'\n'],{type:'text/csv;charset=utf-8'}));
$('png').onclick=()=>{if(!chart)return;$('trend').toBlob(b=>{if(b)download('grosswetterlagen.png',b);});};load();
})();
