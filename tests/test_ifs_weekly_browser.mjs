// Browser regression: by default requires original IFS and ERA5 data.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir,readFile} from 'node:fs/promises';
const {chromium}=createRequire(import.meta.url)('playwright');
const fixture=process.argv.includes('--fixture');
const url='http://127.0.0.1:8765/ifs_weekly_europe.html';
const out='ifs-test-output';
await mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.IFS_TEST_CHROMIUM?{executablePath:process.env.IFS_TEST_CHROMIUM}:{})});
const cells=1801*601;
function packed(value){const b=Buffer.alloc(cells*2);for(let i=0;i<cells;i++)b.writeInt16LE(value,i*2);return b.toString('base64');}
const lead_hours=Array.from({length:29},(_,i)=>i*6);
const run=Date.parse('2026-11-14T00:00:00Z');
const dataFixture={schema:1,type:'ifs_0p1_seven_day_forecast',grid_degrees:.1,width:1801,height:601,
  lat_north:85,lat_south:25,lon_west:-80,lon_east:100,period_days:7,sample_count:29,lead_hours,
  run_utc:new Date(run).toISOString(),valid_from_utc:new Date(run).toISOString(),valid_to_utc:new Date(run+168*3600000).toISOString(),
  sources:lead_hours.map(h=>({forecast_hour:h,valid_utc:new Date(run+h*3600000).toISOString(),sha256:'a'.repeat(64),bytes:200000})),
  forecast_mean_q10_b64:packed(80),anomaly_mean_q10_b64:packed(20),reference_ready:true,
  reference_version:'era5-t2m-calendar-hour-1991-2020-v1',reference_metadata:{period:'1991–2020',years:30,native_grid_degrees:.25,interpolation:'bilinear'}};
const geoFixture={width:1801,height:601,grid_degrees:.1,countries:[{id:0,name:'Testland',cells}],
  country_mask_b64:packed(0),rings:Array.from({length:101},()=>[[5,46],[5,47],[6,47],[5,46]])};
try{
  for(const [name,viewport] of [['desktop',{width:1440,height:950}],['mobile',{width:390,height:844}]]){
    const page=await browser.newPage({viewport,acceptDownloads:true});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    if(fixture){
      await page.route('**/ifs_weekly_europe/current.json',r=>r.fulfill({json:dataFixture}));
      await page.route('**/ifs_weekly_europe/geography.json',r=>r.fulfill({json:geoFixture}));
    }
    await page.goto(url,{waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>!document.querySelector('#weekPng').disabled,{},{timeout:120000});
    assert.match(await page.locator('#weekReference').innerText(),/ERA5 1991–2020/);
    assert.match(await page.locator('#weekMapLabel').innerText(),/0,1°/);
    assert.equal(await page.locator('#weekMap').getAttribute('width'),'2100');
    assert.equal(await page.locator('#weekMetric').inputValue(),'anomaly');
    await page.locator('#weekRegion').selectOption('germany');
    await page.locator('#weekProjection').selectOption('latlon');
    assert.match(await page.locator('#weekMapLabel').innerText(),/Deutschland/);
    assert.equal(await page.locator('#weekWarning').isVisible(),false);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),true);
    await page.screenshot({path:`${out}/${name}.png`,fullPage:true});
    const pending=page.waitForEvent('download');await page.locator('#weekPng').click();
    const dl=await pending;await dl.saveAs(`${out}/${name}-download.png`);
    const png=await readFile(`${out}/${name}-download.png`);
    assert.equal(png.readUInt32BE(16),2100);assert.equal(png.readUInt32BE(20),1425);
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
