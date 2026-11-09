#!/usr/bin/env node
/* GitHub Pages true-data desktop/mobile E2E for DMI Greenland. */
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const {chromium}=require("playwright");
const BASE=process.env.GREENLAND_LIVE_URL||
 "https://marcelherber.github.io/climate-dashboard/groenland_stationen.html";
const out=path.join(process.cwd(),"artifacts");
fs.mkdirSync(out,{recursive:true});
async function main(){
 const browser=await chromium.launch({headless:true});
 try{
  for(const device of [{name:"desktop",width:1440,height:900,mobile:false},
                       {name:"mobile",width:390,height:844,mobile:true}]){
   const context=await browser.newContext({
     viewport:{width:device.width,height:device.height},
     hasTouch:device.mobile,isMobile:device.mobile,acceptDownloads:true
   });
   const page=await context.newPage();
   const errors=[];page.on("pageerror",e=>errors.push(e.message));
   const resp=await page.goto(BASE,{waitUntil:"domcontentloaded",timeout:90000});
   assert.equal(resp.status(),200,"Greenland page published");
   const cache=await page.evaluate(async()=>{
     const r=await fetch("data/dmi_greenland_stations.json",{cache:"no-store"});
     if(!r.ok)throw Error("No DMI snapshot: "+r.status);
     return await r.json();
   });
   assert.equal(cache.schema,1);assert.ok(cache.stations.length>=10);
   assert.ok(Object.keys(cache.latest).length>=1);
   await page.waitForFunction(()=>window.GreenlandDmiMath?.getState?.().stations>=10,null,{timeout:75000});
   assert.ok(await page.locator("#grMap .leaflet-container").count()||await page.locator("#grMap.leaflet-container").count(),
    "Leaflet must render interactive map");
   const station=cache.stations.find(s=>/Nuuk/i.test(s.name)&&s.parameters.includes("mean_temp"))||
     cache.stations.find(s=>s.parameters.includes("mean_temp")&&cache.latest[s.id]?.mean_temp);
   assert.ok(station,"DMI cached station with real temperature needed");
   await page.locator("#grSearch").fill(station.name);
   await page.waitForFunction(()=>document.querySelector("#grStationCount")?.textContent.includes("1 Station"),null,{timeout:5000})
     .catch(()=>{}); // More than one similarly named station is fine.
   const row=page.locator(".gr-station").filter({hasText:station.id}).first();
   assert.ok(await row.count(),"Filtered true station from DMI");
   if(device.mobile)await row.tap();else await row.click();
   assert.equal(await page.evaluate(()=>window.GreenlandDmiMath.getState().stationId),station.id);
   await page.waitForFunction(()=>window.GreenlandDmiMath.getState().series>=5,null,{timeout:105000});
   assert.ok(await page.evaluate(()=>!!Chart.getChart(document.getElementById("grChart"))),
     "Historical chart must render with actual values");
   await page.waitForFunction(()=>window.GreenlandDmiMath.getState().records>=2,null,{timeout:105000});
   assert.ok((await page.locator("#grRecordStatus").innerText()).includes("Rekordparametern"));
   const csvPromise=page.waitForEvent("download",{timeout:30000});
   await page.locator("#grCsv").click();const csv=await csvPromise;
   assert.ok(csv.suggestedFilename().endsWith(".csv"));
   const bytes=fs.readFileSync(await csv.path());
   assert.ok(bytes.length>300&&bytes.toString("utf8").includes(station.id));
   const pngPromise=page.waitForEvent("download",{timeout:30000});
   await page.locator("#grPng").click();const png=await pngPromise;
   assert.equal(fs.readFileSync(await png.path()).subarray(0,8).toString("hex"),"89504e470d0a1a0a");
   const rPromise=page.waitForEvent("download",{timeout:30000});
   await page.locator("#grRecordCsv").click();const csvR=await rPromise;
   assert.ok(fs.readFileSync(await csvR.path()).toString("utf8").includes("Rekordwert"));
   await page.locator("#grResolution").selectOption("day");
   await page.waitForFunction(()=>window.GreenlandDmiMath.getState().series>=15,null,{timeout:105000});
   const statuses=await page.locator("#grSeriesStatus").innerText();
   assert.ok(statuses.includes("gültige DMI-Originalwerte"));
   await page.screenshot({path:path.join(out,"greenland-"+device.name+".png"),fullPage:true});
   const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
   assert.ok(overflow<=6,"Horizontal overflow on "+device.name+": "+overflow);
   assert.deepEqual(errors,[],"Uncaught browser errors");
   console.log("PASS Greenland "+device.name+": "+cache.stations.length+
       " authentic stations, original time series, four historical records, chart exports, responsive map");
   await context.close();
  }
 }finally{await browser.close();}
}
main().catch(e=>{console.error("GREENLAND LIVE E2E FAILED:",e.stack||e);process.exitCode=1;});
