const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({args:['--no-sandbox']});
 try{
  for(const viewport of [{width:1440,height:1000},{width:390,height:844}]){
   const page=await browser.newPage({viewport,acceptDownloads:true});
   await page.goto('http://127.0.0.1:8765/stations_rekordlabor.html',{waitUntil:'domcontentloaded',timeout:90000});
   await page.locator('#rlTabRegional').click({timeout:15000});
   await page.locator('#rrMetric').selectOption('rs_high');
   await page.waitForFunction(()=>!document.getElementById('rrYearPng').disabled,{},{timeout:30000});
   const values=await page.evaluate(()=>Chart.getChart('rrYearCanvas').data.datasets.map(x=>x.data));
   assert.equal(values[0].length,366);
   assert.equal(values[0][318],83.2);
   assert.equal(values[1][59],null);
   assert.equal(values[1][365],null);
   const canvas=page.locator('#rrYearCanvas');
   await canvas.scrollIntoViewIfNeeded();
   const position=await page.evaluate(()=>{let c=Chart.getChart('rrYearCanvas');return {x:c.scales.x.getPixelForValue(318),y:c.scales.y.getPixelForValue(c.data.datasets[0].data[318])};});
   await canvas.click({position});
   // Chart.js handles native clicks on the next animation frame.
   await page.waitForFunction(()=>document.getElementById('rrYearDay').textContent.includes('Historischer Rekord'),{},{timeout:10000});
   const selected=await page.locator('#rrDay').inputValue();
   if(viewport.width>600){
    assert.equal(selected,'11-14');assert.match(await page.locator('#rrYearDay').innerText(),/Hückeswagen/);
    await page.locator('#rrTable tr').first().waitFor({timeout:60000});
    assert.match(await page.locator('#rrTable tr').first().innerText(),/Hückeswagen/);
   }
   else{assert.ok(['11-13','11-14','11-15'].includes(selected));assert.match(await page.locator('#rrYearDay').innerText(),/Historischer Rekord/);}
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   for(const [id,ext] of [['rrYearCsv','csv'],['rrYearPng','png'],['rrYearPdf','pdf']]){
    const p=page.waitForEvent('download',{timeout:30000});await page.locator('#'+id).click();
    const download=await p;assert.ok(download.suggestedFilename().endsWith('.'+ext));
    assert.ok(fs.statSync(await download.path()).size>1000);
    if(ext==='csv'){const csv=fs.readFileSync(await download.path(),'utf8');assert.equal(csv.split('\r\n').length,367);assert.match(csv,/Hückeswagen/);}
   }
   await page.locator('#rrArea').selectOption('Hessen');
   await page.locator('#rrMetric').selectOption('txk_low');
   await page.waitForFunction(()=>!document.getElementById('rrYearPng').disabled&&document.getElementById('rrYearStatus').textContent.includes('Hessen')&&document.getElementById('rrYearStatus').textContent.includes('Niedrigstes Tmax'),{},{timeout:30000});
   assert.equal(await page.evaluate(()=>Chart.getChart('rrYearCanvas').data.datasets[0].data.length),366);
   console.log('Passed',viewport.width,'px: real daily curves, click, filters, CSV/PNG/PDF');
   await page.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
