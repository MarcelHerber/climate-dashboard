/* Real-data desktop/mobile smoke test for the standalone DWD annual station viewer. */
"use strict";
const assert=require("node:assert/strict");
const {chromium}=require("playwright");
const url=process.env.STATION_JAHR_URL||"http://127.0.0.1:8769/station_jahresanalyse.html";
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  for(const [device,viewport] of [["desktop",{width:1440,height:900}],["mobile",{width:390,height:844}]]){
   const context=await browser.newContext({viewport,acceptDownloads:true});
   const page=await context.newPage();
   const errors=[];
   page.on("pageerror",err=>errors.push(err.message));
   await page.goto(url,{waitUntil:"domcontentloaded",timeout:80000});
   await page.waitForFunction(()=>{
    const el=document.getElementById("sjaInventory");
    return el && /Stationen/.test(el.textContent);
   },null,{timeout:80000});
   const inventory=await page.locator("#sjaInventory").textContent();
   assert.match(inventory,/Temperatur/);
   await page.waitForFunction(()=>window.Chart?.getChart(document.querySelector("#sjaChart"))?.data?.labels?.length===365,
     null,{timeout:90000});
   const tempCount=await page.locator("#sjaYears input").count();
   assert.ok(tempCount>20,device+": historical temperature years missing");
   await page.locator("#sjaMetric").selectOption("0");
   assert.match(await page.locator("#sjaChartTitle").textContent(),/Tmax/);
   await page.locator("#sjaPrecip").click();
   try {
    await page.waitForFunction(()=>window.Chart?.getChart(document.querySelector("#sjaChart"))?.data?.labels?.length===12,
      null,{timeout:90000});
   } catch (error) {
    console.error(device,"precipitation state",await page.locator("#sjaStatus").textContent(),"errors",errors);
    throw error;
   }
   assert.match(await page.locator("#sjaChartTitle").textContent(),/Niederschlag/);
   await page.locator("#sjaMode").selectOption("daily");
   await page.waitForFunction(()=>window.Chart?.getChart(document.querySelector("#sjaChart"))?.data?.labels?.length===365,
     null,{timeout:60000});
   await page.locator("#sjaSnow").click();
   await page.waitForFunction(()=>window.Chart?.getChart(document.querySelector("#sjaChart"))?.data?.labels?.length===366,
     null,{timeout:90000});
   assert.match(await page.locator("#sjaStatus").textContent(),/hydrologischen Jahren/);
   assert.equal(errors.length,0,device+" JS errors: "+errors.join(" | "));
   if(device==="mobile"){
    const width=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,viewport:window.innerWidth}));
    if(width.scroll>width.viewport+8){
     const offenders=await page.evaluate(()=>[...document.querySelectorAll("body *")]
       .map(el=>({tag:el.tagName,cls:typeof el.className==="string"?el.className:"",
         right:Math.round(el.getBoundingClientRect().right),width:Math.round(el.getBoundingClientRect().width)}))
       .filter(el=>el.right>window.innerWidth+10).sort((a,b)=>b.right-a.right).slice(0,12));
     console.error("Mobile overflow culprits",offenders);
    }
    assert.ok(width.scroll<=width.viewport+8,"Mobile horizontal overflow: "+JSON.stringify(width));
   }
   const downloadPromise=page.waitForEvent("download");
   await page.locator("#sjaCsv").click();
   const downloaded=await downloadPromise;
   assert.ok(downloaded.suggestedFilename().endsWith(".csv"));
   console.log(device,inventory,"temperature years",tempCount,"snow chart and CSV OK");
   await context.close();
  }
 }finally{await browser.close();}
})().catch(err=>{console.error(err);process.exitCode=1;});
