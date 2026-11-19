(function () {
  'use strict';
  const REGIONS={polar:['Nordpol','60–90° N · alle Längengrade'],pacific:['Nordpazifik','60–90° N · 120° E–120° W'],atlantic:['Nordatlantik','60–90° N · 90° W–30° E'],eurasia:['Eurasien','60–90° N · 30–120° E']};
  const MODELS={ecmwf:'ECMWF-ENS',gefs:'GEFS'};
  const LEVELS=[-45,-35,-27,-20,-14,-8,-4,-2,2,4,8,14,20,27,35,45];
  const COLORS=['#9917c4','#6423b9','#4326b0','#143dd8','#3275ce','#63a9e8','#98c9ec','#b7c9db','#f8fafc','#fff0a6','#ffce4c','#ff9a16','#ff6a0c','#f43120','#ca1535','#ec168c','#f19ae5'];
  const DAY=86400000;
  const finite=v=>typeof v==='number' && Number.isFinite(v);
  const iso=(date)=>new Date(date).toISOString().slice(0,10);
  const add=(date,n)=>iso(Date.parse(date+'T00:00:00Z')+n*DAY);
  function makeSeries(region,forecast,ref,history,bridge) {
    const cycle=forecast.cycle.slice(0,10), pressure=forecast.levels.slice().sort((a,b)=>a-b);
    const dates=Array.from({length:76},(_,i)=>add(cycle,i-60));
    const native=[];
    const values=dates.map((date,i)=>{
      const actual=(i>=60?forecast.days[date]:history[date]||bridge[date])?.[region], normal=ref[date.slice(5)]?.[region];
      const levels=i>=60||!actual?pressure:Object.keys(actual).map(Number).sort((a,b)=>a-b);
      native.push(levels);
      return levels.map(p=>finite(actual?.[p])&&finite(normal?.[p])?actual[p]-normal[p]:null);
    });
    const sources=dates.map((d,i)=>i>=60?MODELS[forecast.model]:history[d]?'ERA5':bridge[d]?'GFS-Analyse':null);
    return {dates,pressure,native,values,sources,cycle};
  }
  function sampleAt(s,x,p) {
    if(x<0||x>s.dates.length-1||p<s.pressure[0]||p>s.pressure.at(-1))return null;
    const lo=Math.floor(x),hi=Math.ceil(x);
    const at=i=>{
      const levels=s.native[i],j=levels.findIndex(a=>a>=p);
      if(j<0||p<levels[0])return null;
      const k=levels[j]===p||j===0?j:j-1;
      const w=j===k?0:(Math.log(p)-Math.log(levels[k]))/(Math.log(levels[j])-Math.log(levels[k]));
      const a=s.values[i][k],b=s.values[i][j];return finite(a)&&finite(b)?a+(b-a)*w:null;
    };
    const a=at(lo),b=at(hi);return finite(a)&&finite(b)?a+(b-a)*(x-lo):null;
  }
  function validForecast(f,model,now=Date.now()) {
    if(!f||f.schema!==1||f.model!==model||f.units!=='dam'||!/^\d{4}-\d\d-\d\dT00:00:00Z$/.test(f.cycle)||!Array.isArray(f.levels)||f.levels[0]!==10||f.levels.at(-1)!==1000||f.member_count!==(model==='ecmwf'?51:31))return false;
    const age=now-Date.parse(f.cycle); if(!finite(age)||age<0||age>3*DAY)return false;
    return Array.from({length:16},(_,i)=>add(f.cycle.slice(0,10),i)).every(d=>Object.keys(REGIONS).every(r=>f.levels.every(p=>finite(f.days?.[d]?.[r]?.[p]))));
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={makeSeries,sampleAt,validForecast,REGIONS};return;}
  let data={},svg=null,request=0;
  const by=id=>document.getElementById(id);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
  const text=(x,y,s,opts='')=>`<text x="${x}" y="${y}" ${opts}>${esc(s)}</text>`;
  const dateLabel=s=>s.slice(8,10)+'.'+s.slice(5,7)+'.';
  const options=Object.entries(REGIONS).map(([id,[name]])=>`<option value="${id}">${esc(name)}</option>`).join('');
  async function fetchJson(branch,file) {
    const urls=[`https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/${branch}/${file}`,`https://cdn.jsdelivr.net/gh/MarcelHerber/climate-dashboard@${branch}/${file}`];
    let problem;for(const url of urls){try{const r=await fetch(url+'?v='+Math.floor(Date.now()/3600000),{cache:'no-store',signal:AbortSignal.timeout(15000)});if(!r.ok)throw Error(r.status);return await r.json();}catch(e){problem=e;}}throw problem;
  }
  const dark=()=>document.documentElement.dataset.theme==='dark'||document.body.dataset.theme==='dark'||document.body.classList.contains('dark-mode')||document.body.classList.contains('dark')||document.documentElement.classList.contains('dark')||getComputedStyle(document.body).colorScheme==='dark';
  function renderSvg(series,model,mobile,isDark) {
    const compare=series.length===2, stacked=compare&&mobile, width=compare&&!stacked?1440:760,height=stacked?1110:635;
    const ink=isDark?'#dce7f5':'#20334a', bg=isDark?'#142033':'#ffffff',muted=isDark?'#b1c1d5':'#5c7084', frame=isDark?'#7f91a6':'#879bad';
    let out=`<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Zeit-Höhen-Analyse der Geopotentialanomalien" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" font-family="Arial, sans-serif" fill="${ink}"><rect width="${width}" height="${height}" fill="${bg}"/>`;
    out+=text(44,32,'Geopotentialanomalien der Polarregion','font-size="22" font-weight="700"');
    out+=text(44,55,`${MODELS[model]} · 00 UTC ${series[0].s.cycle} · ERA5 1991–2020 · Geopotentialhöhe (dam)`,'font-size="13" fill="'+muted+'"');
    for(let index=0;index<series.length;index++){
      const {region,s}=series[index], x0=(compare&&!stacked?index*710:0)+62, y0=(stacked?index*455:0)+112, w=compare&&!stacked?612:662,h=380;
      const xx=i=>x0+w*i/75, yy=p=>y0+h*Math.log10(p/10)/2;
      out+=text(x0,y0-27,REGIONS[region][0],'font-size="19" font-weight="700"');out+=text(x0,y0-10,REGIONS[region][1],'font-size="12" fill="'+muted+'"');
      const nX=302,nY=161, vals=[], mask=[];
      for(let j=0;j<nY;j++){const p=10*Math.pow(100,j/(nY-1));for(let i=0;i<nX;i++){const v=sampleAt(s,i/(nX-1)*75,p);vals.push(v===null?NaN:v);mask.push(v===null?0:1);}}
      const contours=window.d3.contours().size([nX,nY]);
      const projection=window.d3.geoTransform({point(x,y){this.stream.point(x0+(x-.5)*w/(nX-1),y0+(y-.5)*h/(nY-1));}});
      const path=window.d3.geoPath(projection), coverage=path(contours.thresholds([.5])(mask)[0])||'';
      const clip='heightValid'+index, pattern='heightMissing'+index, bounds='heightBounds'+index;
      out+=`<defs><clipPath id="${bounds}"><rect x="${x0}" y="${y0}" width="${w}" height="${h}"/></clipPath><clipPath id="${clip}"><path d="${coverage}"/></clipPath><pattern id="${pattern}" width="8" height="8" patternUnits="userSpaceOnUse"><rect width="8" height="8" fill="${isDark?'#2c394c':'#e6ebf1'}"/><path d="M0 8L8 0" stroke="${isDark?'#45536b':'#ccd5df'}" stroke-width="1"/></pattern></defs>`;
      out+=`<rect x="${x0}" y="${y0}" width="${w}" height="${h}" fill="url(#${pattern})"/><g clip-path="url(#${bounds})"><g clip-path="url(#${clip})"><rect x="${x0-2}" y="${y0-2}" width="${w+4}" height="${h+4}" fill="${COLORS[0]}"/>`;
      contours.thresholds(LEVELS)(vals).forEach((c,i)=>{if(c.coordinates.length)out+=`<path d="${path(c)}" fill="${COLORS[i+1]}"/>`;});
      for(const c of contours.thresholds([55,65,75,85])(vals)){
        if(!c.coordinates.length)continue;out+=`<path d="${path(c)}" fill="none" stroke="#68205e" stroke-width="1"/>`;
        const ring=c.coordinates[0]?.[0];if(ring?.length>30){const point=ring.find(([x,y])=>x>8&&x<nX-8&&y>12&&y<nY-10);if(point)out+=text(x0+(point[0]-.5)*w/(nX-1),y0+(point[1]-.5)*h/(nY-1),c.value,'font-size="10" fill="#68205e" stroke="#f19ae5" stroke-width="3" paint-order="stroke"');}
      }out+='</g></g>';
      for(const p of [10,30,50,100,200,500,1000]){const y=yy(p);out+=`<line x1="${x0}" y1="${y}" x2="${x0+w}" y2="${y}" stroke="${ink}" opacity=".25" stroke-dasharray="2 4"/>`;out+=text(x0-9,y+4,p,'text-anchor="end" font-size="12"');}
      for(const i of [0,10,20,30,40,50,60,67,75]){const x=xx(i);out+=`<line x1="${x}" y1="${y0}" x2="${x}" y2="${y0+h}" stroke="${ink}" opacity=".23" stroke-dasharray="2 4"/>`;out+=text(x,y0+h+20,dateLabel(s.dates[i]),'text-anchor="middle" font-size="12"');}
      const division=xx(60);out+=`<line x1="${division}" y1="${y0}" x2="${division}" y2="${y0+h}" stroke="#142135" stroke-width="2.2"/><rect x="${x0}" y="${y0}" width="${w}" height="${h}" stroke="${frame}" fill="none"/>`;
      for(const [i,label] of [[30,'ANALYSE'],[67.5,'PROGNOSE']]){let x=xx(i);out+=`<rect x="${x-43}" y="${y0+7}" width="86" height="19" rx="2" fill="#ffffff" opacity=".88"/>`;out+=text(x,y0+21,label,'text-anchor="middle" font-size="11" font-weight="bold" fill="#172b45"');}
      out+=text(x0-44,y0+h/2,'Luftdruck (hPa)',`font-size="12" text-anchor="middle" transform="rotate(-90 ${x0-44} ${y0+h/2})"`);
    }
    const ly=height-100,lx=width*.09,lw=width*.82,step=lw/COLORS.length;
    COLORS.forEach((c,i)=>{out+=`<rect x="${lx+step*i}" y="${ly}" width="${step+.2}" height="16" fill="${c}"/>`;});
    LEVELS.forEach((v,i)=>{out+=text(lx+step*(i+1),ly+32,v,'text-anchor="middle" font-size="11"');});
    out+=text(width/2,ly+51,'Abweichung der Geopotentialhöhe vom Klimamittel (dam)','text-anchor="middle" font-size="13"');
    out+=text(width/2,height-31,'Analyse: ERA5 / bei Latenz GFS · Zwischenstufen logarithmisch interpoliert','text-anchor="middle" font-size="11" fill="'+muted+'"');
    out+=text(width/2,height-15,'Schraffur: fehlende Analyse, Vorhersage oder Klimareferenz','text-anchor="middle" font-size="11" fill="'+muted+'"');
    return out+'</svg>';
  }
  function render(){
    const target=by('heightPlot'),status=by('heightStatus'),model=by('heightModel').value,f=data[model];svg=null;by('heightPNG').disabled=by('heightPDF').disabled=true;
    const ref=data.reference?.period?.join('-')==='1991-2020'?data.reference.days||{}:{}, n=Object.keys(ref).length;
    const message=`ERA5-Klimareferenz: ${n}/366 Kalendertage (1991–2020).`;
    if(!validForecast(f,model)){target.textContent='Für dieses Modell ist noch kein vollständiger, aktueller 15-Tage-Lauf verfügbar.';status.textContent=message;return;}
    const first=by('heightRegion1').value,second=by('heightRegion2').value,regions=[first,...(second&&second!==first?[second]:[])];
    const series=regions.map(region=>({region,s:makeSeries(region,f,ref,data.analysis?.days||{},data.bridge?.days||{})}));
    const available=series.some(a=>a.s.values.some(v=>v.some(finite)));
    if(!available){target.textContent='Die tagesgenaue ERA5-Klimareferenz für diesen Zeitraum wird noch aufgebaut. Es werden keine Ersatzwerte angezeigt.';status.textContent=message+` · Modelllauf: ${f.cycle.slice(0,10)} 00 UTC.`;return;}
    if(!window.d3){target.textContent='Darstellungsbibliothek konnte nicht geladen werden.';return;}
    const mobile=target.clientWidth<780;target.innerHTML=renderSvg(series,model,mobile,dark());svg=target.querySelector('svg');by('heightPNG').disabled=false;by('heightPDF').disabled=!(window.jspdf?.jsPDF);
    const source=series[0].s.sources;const firstGfs=source.indexOf('GFS-Analyse'),lastGfs=source.lastIndexOf('GFS-Analyse');
    status.textContent=message+` · Lauf: ${f.cycle.slice(0,10)} 00 UTC · ${f.member_count} Member.`+(firstGfs>=0?` · GFS-Analyse als ERA5-Latenzüberbrückung: ${series[0].s.dates[firstGfs]}–${series[0].s.dates[lastGfs]}.`:'');
  }
  async function reload(){
    const id=++request;by('heightStatus').textContent='Aktuelle Ensemble- und ERA5-Daten werden geladen …';by('heightPlot').textContent='Daten werden geprüft …';svg=null;by('heightPNG').disabled=by('heightPDF').disabled=true;
    const names=[['ecmwf','strato-height-ecmwf-data','forecast.json'],['gefs','strato-height-gefs-data','forecast.json'],['bridge','strato-height-gefs-data','bridge.json'],['reference','strato-height-reference-data','reference.json'],['analysis','strato-height-reference-data','analysis.json']];
    const loaded=await Promise.allSettled(names.map(([,b,f])=>fetchJson(b,f)));if(id!==request)return;
    data=Object.fromEntries(names.map(([name],i)=>[name,loaded[i].status==='fulfilled'?loaded[i].value:null]));
    if(!validForecast(data[by('heightModel').value],by('heightModel').value)&&validForecast(data.gefs,'gefs'))by('heightModel').value='gefs';render();
  }
  function download(href,name){const a=document.createElement('a');a.href=href;a.download=name;document.body.append(a);a.click();a.remove();}
  const filename=()=>`Stratosphaere_${by('heightModel').value}_${by('heightRegion1').value}_${by('heightRegion2').value||'einzeln'}_${data[by('heightModel').value]?.cycle.slice(0,10)}`;
  function png(){if(!svg)return;const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)],{type:'image/svg+xml;charset=utf-8'}));const image=new Image();image.onload=()=>{const c=document.createElement('canvas');c.width=svg.viewBox.baseVal.width*2;c.height=svg.viewBox.baseVal.height*2;c.getContext('2d').drawImage(image,0,0,c.width,c.height);download(c.toDataURL('image/png'),filename()+'.png');URL.revokeObjectURL(url);};image.onerror=()=>{URL.revokeObjectURL(url);by('heightStatus').textContent='PNG-Export fehlgeschlagen.';};image.src=url;}
  async function pdf(){if(!svg||!window.jspdf?.jsPDF)return;try{const w=svg.viewBox.baseVal.width,h=svg.viewBox.baseVal.height;const doc=new window.jspdf.jsPDF({orientation:w>=h?'landscape':'portrait',unit:'pt',format:[w,h]});if(typeof doc.svg!=='function')throw Error('SVG-PDF-Modul nicht geladen');await doc.svg(svg,{x:0,y:0,width:w,height:h});doc.save(filename()+'.pdf');}catch(e){by('heightStatus').textContent='Vektor-PDF konnte nicht erstellt werden: '+e.message;}}
  function mount(){
    const anchor=by('polarVortexCard')||by('stratoHistoryCard');if(!anchor||by('stratoHeightCard'))return;
    const card=document.createElement('section');card.className='card strato-height-card';card.id='stratoHeightCard';card.innerHTML=`<h2>Geopotentialanomalien · Zeit-Höhen-Analyse</h2><p class="legendnotes">Polare Sektoren (60–90° N), 10–1000 hPa · 60 Tage Rückblick und 15 Tage Prognose · ERA5 1991–2020 (00 UTC).</p><div class="strato-height-controls"><label>Modell<select id="heightModel"><option value="ecmwf">ECMWF-ENS</option><option value="gefs">GEFS</option></select></label><label>Region 1<select id="heightRegion1">${options}</select></label><label>Region 2<select id="heightRegion2"><option value="">Einzelansicht</option>${options}</select></label><button class="btn" id="heightReload" type="button">Neu laden</button><button class="btn" id="heightPNG" disabled>PNG</button><button class="btn" id="heightPDF" disabled>Vektor-PDF</button></div><p id="heightStatus" class="info" role="status" aria-live="polite"></p><div id="heightPlot" class="strato-height-plot" aria-live="polite"></div><p class="legendnotes">Quellen: Copernicus ERA5, ECMWF Open Data (50 gestörte Mitglieder + Kontrolllauf), NOAA GEFS (operatives Ensemblemittel) / GFS-Analyse. Flächengewichtete Gebietsmittel. Die schwarzen Trennlinien markieren den Prognosebeginn; 30 hPa und andere nicht native Stufen werden nur für die Darstellung in log(p) interpoliert. Positive Höhenanomalien sind allein kein Nachweis einer Major SSW.</p>`;
    anchor.before(card);by('heightRegion1').value='pacific';by('heightRegion2').value='atlantic';
    ['heightModel','heightRegion1','heightRegion2'].forEach(id=>by(id).addEventListener('change',render));by('heightReload').addEventListener('click',reload);by('heightPNG').addEventListener('click',png);by('heightPDF').addEventListener('click',pdf);
    let lastWidth=0;new ResizeObserver(entries=>{const width=entries[0].contentRect.width;if(Math.abs(width-lastWidth)>15){lastWidth=width;if(svg)render();}}).observe(by('heightPlot'));
    new MutationObserver(()=>{if(svg)render();}).observe(document.documentElement,{attributes:true,attributeFilter:['class','data-theme','style']});
    new MutationObserver(()=>{if(svg)render();}).observe(document.body,{attributes:true,attributeFilter:['class','data-theme']});reload();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount);else mount();
})();
