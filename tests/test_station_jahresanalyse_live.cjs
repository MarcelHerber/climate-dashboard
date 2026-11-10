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
   // One temperature year must fill to the 1991–2020 line, with red above / blue below.
   await page.waitForFunction(()=>document.querySelector("#sjaFillYear")?.options.length>=2,null,{timeout:10000});
   const fillState=()=>page.evaluate(()=>{
    const chart=window.Chart.getChart(document.getElementById("sjaChart"));
    const filled=chart.data.datasets.filter(d=>d.fill&&typeof d.fill==="object");
    return {fills:filled.map(d=>({name:d.label,target:d.fill.target,above:d.fill.above,below:d.fill.below})),
      selected:document.getElementById("sjaFillYear").value,
      datasetCount:chart.data.datasets.length};
   });
   let state=await fillState();
   assert.equal(state.fills.length,1,device+": exactly one shaded year");
   assert.equal(state.fills[0].target,0,"Fill must reference 1991–2020 dataset");
   assert.match(state.fills[0].above,/219,63,56/);
   assert.match(state.fills[0].below,/39,107,201/);
   assert.ok(state.fills[0].name.startsWith(state.selected),"Highlighted year mismatch");
   const choices=await page.locator("#sjaFillYear option").evaluateAll(opts=>opts.map(o=>o.value));
   await page.locator("#sjaFillYear").selectOption(choices.find(y=>y!==state.selected));
   state=await fillState();
   assert.ok(state.fills[0].name.startsWith(state.selected),"Changed shading year was not applied");
   await page.locator('#sjaYears input[value="'+state.selected+'"]').uncheck();
   state=await fillState();
   assert.ok(state.fills[0].name.startsWith(state.selected),"Fill not reassigned after deselecting shaded year");
   const pngDownload=page.waitForEvent("download");
   await page.locator("#sjaPng").click();
   assert.ok((await pngDownload).suggestedFilename().endsWith(".png"));
   await page.locator("#sjaMetric").selectOption("0");
   assert.match(await page.locator("#sjaChartTitle").textContent(),/Tmax/);
   await page.locator("#sjaPrecip").click();
   assert.equal(await page.locator("#sjaFillControls").isVisible(),false,"Fill picker must be temperature-only");
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
   console.log(device,inventory,"temperature years",tempCount,"red/blue fill, PNG, snow chart and CSV OK");
   await context.close();
  }
 }finally{await browser.close();}
})().catch(err=>{console.error(err);process.exitCode=1;});
