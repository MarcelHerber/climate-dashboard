const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { REGIONS } = require('../stratosphere_height.js');
const levels = {ecmwf:[10,50,100,150,200,250,300,400,500,600,700,850,925,1000],gefs:[10,50,100,200,250,300,500,700,850,925,1000]};
const cycle = new Date().toISOString().slice(0,10);
const add = n => new Date(Date.parse(cycle)+86400000*n).toISOString().slice(0,10);
const row = (p, anomaly=0) => Object.fromEntries(Object.keys(REGIONS).map((r,i)=>[r,Object.fromEntries(p.map(h=>[h,12+1500*Math.log10(1000/h)+anomaly*(i+1)/4]))]));
const ref={},history={},forecasts={};
for(let i=-60;i<=15;i++){
  ref[add(i).slice(5)] = row(levels.ecmwf);
  if(i<0 && i!==-30)history[add(i)]=row(levels.ecmwf,60*Math.sin(i/8));
}
for(const [model,p] of Object.entries(levels)){
  forecasts[model]={schema:1,model,cycle:cycle+'T00:00:00Z',units:'dam',member_count:model==='gefs'?31:51,levels:p,days:Object.fromEntries(Array.from({length:16},(_,i)=>[add(i),row(p,80*Math.cos(i/8))]))};
}
(async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:900},acceptDownloads:true});
    await page.route('https://raw.githubusercontent.com/**',async route=>{
      const url=route.request().url();
      const value=url.includes('reference.json')?{period:[1991,2020],days:ref}:url.includes('analysis.json')?{days:history}:url.includes('bridge.json')?{days:{}}:url.includes('ecmwf-data')?forecasts.ecmwf:forecasts.gefs;
      await route.fulfill({status:200,headers:{'access-control-allow-origin':'*'},contentType:'application/json',body:JSON.stringify(value)});
    });
    await page.setContent('<html><body><section id="polarVortexCard">existing card</section></body></html>');
    for(const [pkg,file] of [['d3','../dist/d3.min.js'],['jspdf','jspdf.umd.min.js'],['svg2pdf.js','svg2pdf.umd.min.js']]){
      await page.addScriptTag({path:path.resolve(path.dirname(require.resolve(pkg)),file)});
    }
    await page.addStyleTag({path:path.join(__dirname,'../stratosphere_height.css')});
    await page.addScriptTag({path:path.join(__dirname,'../stratosphere_height.js')});
    await page.waitForSelector('#heightPlot svg');
    assert.equal(await page.locator('#heightPlot svg pattern').count(),2);
    assert.ok((await page.locator('#heightPlot svg path').count())>20);
    assert.match(await page.locator('#heightStatus').innerText(),/51 Member/);
    await page.selectOption('#heightModel','gefs');
    assert.match(await page.locator('#heightStatus').innerText(),/31 Member/);
    await page.selectOption('#heightRegion2','');
    assert.equal(await page.locator('#heightPlot svg pattern').count(),1);
    await page.selectOption('#heightRegion2','atlantic');
    await page.setViewportSize({width:390,height:844});
    await page.waitForFunction(()=>document.querySelector('#heightPlot svg').getAttribute('height')==='1110');
    await page.setViewportSize({width:1440,height:900});
    await page.waitForFunction(()=>document.querySelector('#heightPlot svg').getAttribute('height')==='635');
    for(const extension of ['PNG','PDF']){
      const pending=page.waitForEvent('download',{timeout:60000});
      await page.click('#height'+extension);
      const download=await pending;
      const bytes=fs.readFileSync(await download.path());
      assert.ok(bytes.length>10000);
      assert.ok(download.suggestedFilename().endsWith('.'+extension.toLowerCase()));
      if(extension==='PDF'){
        assert.equal(bytes.subarray(0,4).toString(),'%PDF');
        assert.ok(!/\/Subtype\s*\/Image/.test(bytes.toString('latin1')),'PDF must retain vector geometry');
      }
    }
    console.log('Responsive charts, model and region switches, PNG and vector PDF verified.');
  }finally{await browser.close();}
})().catch(err=>{console.error(err);process.exitCode=1;});
