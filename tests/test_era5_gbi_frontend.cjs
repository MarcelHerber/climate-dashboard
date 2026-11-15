const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync(require('node:path').join(__dirname, '..', 'climate_advanced.js'), 'utf8');

async function fixture(era5) {
  const elements = Object.fromEntries(['advIndex','advCompare','advRange','advStatus','advInfo','advKpis','advChart','advPNG','advPDF','advCSV'].map(id=>[id,{value:'',textContent:'',disabled:true,addEventListener(type, cb){this.cb=cb;}}]));
  elements.advIndex.value='gbi'; elements.advCompare.value='none'; elements.advRange.value='all';
  let config, html;
  const document={body:{dataset:{climateModule:'nao-ao'}},readyState:'loading',getElementById:id=>elements[id],querySelector:()=>({insertAdjacentHTML(loc,value){html=value;}}),addEventListener(type,cb){this.start=cb;}};
  const source = {ready:true,europe:{gbi:{monthly:[['2025-01',2]],method:'NOAA legacy',latest_month:'2025-01'}}};
  const fetch = async url=>url.includes('gbi_era5') ? {ok:!!era5,json:async()=>era5} : {ok:true,json:async()=>source};
  vm.runInNewContext(script,{document,fetch,Chart:class{constructor(el,c){config=c;}destroy(){config=null;}},console,Date});
  await document.start();
  return {elements,config:()=>config,html};
}

test('only valid ERA5 is selected as modern GBI; separate NOAA retains original dates',async()=>{
  const monthly=[];
  for(let y=1940;y<=2025;y++)for(let m=1;m<=12;m++)monthly.push([`${y}-${String(m).padStart(2,'0')}`,1]);
  const f=await fixture({source:'ERA5',reference:'1991–2020',reference_months:360,reference_years:30,first_month:'1940-01',latest_month:'2025-12',method:'ERA5 method',monthly});
  assert.match(f.html,/GBI.*ERA5/);
  assert.match(f.config().data.datasets[0].label,/ERA5/);
  assert.equal(f.config().data.labels.at(-1),'2025-12');
  f.elements.advIndex.value='gbi_noaa';f.elements.advIndex.cb();
  assert.match(f.config().data.datasets[0].label,/NOAA/);
  assert.equal(f.config().data.labels.at(-1),'2025-01');
});

test('unavailable ERA5 does not silently display archived NOAA',async()=>{
  const f=await fixture(null);
  assert.equal(f.config(),undefined);
  assert.match(f.elements.advStatus.textContent,/ERA5/);
  assert.equal(f.elements.advPNG.disabled,true);
  f.elements.advIndex.value='gbi_noaa';f.elements.advIndex.cb();
  assert.equal(f.config().data.labels.at(-1),'2025-01');
});
