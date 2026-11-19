const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({args:['--no-sandbox']});
 try{
  for(const viewport of [{width:1440,height:1000},{width:390,height:844}]){
   const page=await browser.newPage({viewport,acceptDownloads:true});
   await page.route('https://raw.githubusercontent.com/**/regional_calendar/**',async route=>{
    const suffix=route.request().url().split('/regional_calendar/')[1];
    const file=path.join(process.env.RR_FIXTURES||path.join(__dirname,'fixtures'),suffix);
    if(fs.existsSync(file))await route.fulfill({path:file,headers:{'access-control-allow-origin':'*'}});
    else await route.abort();
   });
   await page.goto('http://127.0.0.1:8765/stations_rekordlabor.html',{waitUntil:'domcontentloaded',timeout:90000});
   await page.locator('#rlTabRegional').click({timeout:5000});
   await page.locator('#rrDay').selectOption('11-14');
   await page.locator('#rrLoad').click();
   await page.locator('#rrTable tr').first().waitFor({timeout:60000});
   assert.match(await page.locator('#rrTable tr').first().innerText(),/14,0/);
   assert.equal(await page.locator('#rrTable tr').count(),50);
   await page.locator('#rrArea').selectOption('Bayern');
   await page.locator('#rrMetric').selectOption('rs_high');
   await page.locator('#rrFirst').fill('2021');
   await page.locator('#rrLast').fill('2021');
   await page.locator('#rrLoad').click();
   await page.locator('#rrTable tr').first().waitFor({timeout:30000});
   assert.match(await page.locator('#rrTable tr').first().innerText(),/2,1/);
   assert.equal(await page.locator('#rrTable tr').count(),50);
   await page.locator('#rrMap svg [data-rank]').last().click();
   assert.match(await page.locator('#rrDetail').innerText(),/Rang/);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   const csvPromise=page.waitForEvent('download');await page.locator('#rrCsv').click();
   const csv=await csvPromise;assert.match(csv.suggestedFilename(),/\.csv$/);
   const pngPromise=page.waitForEvent('download');await page.locator('#rrPng').click();
   const png=await pngPromise;assert.match(png.suggestedFilename(),/\.png$/);
   const pdfPromise=page.waitForEvent('download');await page.locator('#rrPdf').click();
   const pdf=await pdfPromise;assert.match(pdf.suggestedFilename(),/\.pdf$/);
   assert.ok(fs.statSync(await png.path()).size>10000);
   assert.ok(fs.statSync(await pdf.path()).size>10000);
   console.log('Passed',viewport.width,'px, actual data, map, CSV, PNG, PDF');
   await page.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
