// Browser regression: by default requires original IFS and ERA5 data.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir,readFile} from 'node:fs/promises';
const {chromium}=createRequire(import.meta.url)('playwright');
const fixture=process.argv.includes('--fixture');
const arctic=process.argv.includes('--arctic');
const domain=arctic?'ifs_weekly_arctic':'ifs_weekly_europe';
const url='http://127.0.0.1:8765/'+domain+'.html';
const out=arctic?'ifs-arctic-test-output':'ifs-test-output';
await mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.IFS_TEST_CHROMIUM?{executablePath:process.env.IFS_TEST_CHROMIUM}:{})});
const width=arctic?3600:1801,height=arctic?301:601,cells=width*height;
function packed(value){const b=Buffer.alloc(cells*2);for(let i=0;i<cells;i++)b.writeInt16LE(value,i*2);return b.toString('base64');}
const lead_hours=Array.from({length:29},(_,i)=>i*6);
const run=Date.parse('2026-11-14T00:00:00Z');
const dataFixture={schema:1,type:'ifs_0p1_seven_day_forecast',grid_degrees:.1,width,height,
  lat_north:arctic?90:85,lat_south:arctic?60:25,lon_west:arctic?-180:-80,lon_east:arctic?179.9:100,period_days:7,sample_count:29,lead_hours,
  run_utc:new Date(run).toISOString(),valid_from_utc:new Date(run).toISOString(),valid_to_utc:new Date(run+168*3600000).toISOString(),
  sources:lead_hours.map(h=>({forecast_hour:h,valid_utc:new Date(run+h*3600000).toISOString(),sha256:'a'.repeat(64),bytes:200000})),
  forecast_mean_q10_b64:packed(80),anomaly_mean_q10_b64:packed(20),reference_ready:true,
  reference_version:'era5-t2m-calendar-hour-1991-2020-'+(arctic?'arctic-v1':'v1'),reference_metadata:{period:'1991–2020',years:30,native_grid_degrees:.25,interpolation:'bilinear'}};
const geoFixture={width,height,grid_degrees:.1,countries:[{id:0,name:'Testland',cells}],
  country_mask_b64:packed(0),rings:Array.from({length:101},()=>arctic?[[5,75],[5,76],[6,76],[5,75]]:[[5,46],[5,47],[6,47],[5,46]])};
const periods=[1,3,5,7,10,15];
function periodFixture(days){
  const leads=Array.from({length:days*4+1},(_,i)=>i*6);
  return {...dataFixture,type:days===7?dataFixture.type:'ifs_0p1_period_forecast',period_days:days,sample_count:leads.length,lead_hours:leads,
    valid_to_utc:new Date(run+days*86400000).toISOString(),sources:leads.map(h=>({forecast_hour:h,valid_utc:new Date(run+h*3600000).toISOString(),sha256:'a'.repeat(64),bytes:200000}))};
}
try{
  for(const [name,viewport] of [['desktop',{width:1440,height:950}],['mobile',{width:390,height:844}]]){
    const page=await browser.newPage({viewport,acceptDownloads:true});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    if(fixture){
      await page.route('**/'+domain+'/current.json',r=>r.fulfill({json:dataFixture}));
      await page.route('**/'+domain+'/geography.json',r=>r.fulfill({json:geoFixture}));
      await page.route('**/'+domain+'/periods.json',r=>r.fulfill({json:{schema:1,run_utc:dataFixture.run_utc,periods}}));
      await page.route('**/'+domain+'/current_*.json',r=>r.fulfill({json:periodFixture(Number(r.request().url().match(/current_(\d+)\.json/)[1]))}));
    }
    await page.goto(url,{waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>!document.querySelector('#weekPng').disabled,{},{timeout:120000});
    assert.match(await page.locator('#weekReference').innerText(),/ERA5 1991–2020/);
    assert.match(await page.locator('#weekMapLabel').innerText(),/0,1°/);
    assert.equal(await page.locator('#weekMap').getAttribute('width'),'2100');
    assert.equal(await page.locator('#weekMetric').inputValue(),'anomaly');
    for(const days of periods){
      await page.locator('#weekPeriod').selectOption(String(days));
      await page.waitForFunction(d=>!document.querySelector('#weekPeriod').disabled&&document.querySelector('#weekSubtitle').textContent.includes(`${d*4+1} Originalfelder`),days,{timeout:120000});
      assert.match(await page.locator('#weekMapLabel').innerText(),new RegExp(`${days} Tage`));
    }
    assert.equal(await page.locator('#weekPeriod').inputValue(),'15');
    if(arctic){
      for(const cap of [60,70,80]){
        await page.locator('#weekRegion').selectOption('polar'+cap);
        assert.match(await page.locator('#weekMapLabel').innerText(),new RegExp(cap+'–90°N'));
        const pixels=await page.locator('#weekMap').evaluate(c=>{
          const ctx=c.getContext('2d');return [Array.from(ctx.getImageData(0,0,1,1).data),Array.from(ctx.getImageData(c.width/2,c.height/2,1,1).data)];
        });
        assert.deepEqual(pixels[0],[237,243,247,255]);
        assert.notDeepEqual(pixels[0],pixels[1]);
      }
      await page.screenshot({path:`${out}/${name}-polar.png`,fullPage:true});
    }else await page.locator('#weekRegion').selectOption('germany');
    await page.locator('#weekProjection').selectOption('latlon');
    assert.match(await page.locator('#weekMapLabel').innerText(),arctic?/80–90°N/:/Deutschland/);
    assert.equal(await page.locator('#weekWarning').isVisible(),false);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),true);
    await page.screenshot({path:`${out}/${name}.png`,fullPage:true});
    const pending=page.waitForEvent('download');await page.locator('#weekPng').click();
    const dl=await pending;await dl.saveAs(`${out}/${name}-download.png`);
    assert.match(dl.suggestedFilename(),/15tage/);
    const png=await readFile(`${out}/${name}-download.png`);
    assert.equal(png.readUInt32BE(16),2100);assert.equal(png.readUInt32BE(20),arctic?2565:1425);
    await page.locator('#weekMetric').selectOption('absolute');
    assert.match(await page.locator('#weekCountryHeader').innerText(),/Temperatur/);
    await page.evaluate(()=>{window.print=()=>{};});
    await page.locator('#weekPdf').click();
    await page.waitForFunction(()=>document.body.classList.contains('weekly-export-print'));
    const pdf=await page.pdf({path:`${out}/${name}-download.pdf`,printBackground:true,preferCSSPageSize:true});
    assert.ok(pdf.length>10000);
    assert.equal(errors.length,0,errors.join('\n'));
    await page.close();
    console.log(`PASS ${name}: original-size map, real rendering, region/projection, PNG and PDF (${fixture?'synthetic test fixture':'real data'})`);
  }
}finally{await browser.close();}
