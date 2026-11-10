#!/usr/bin/env node
// Quick public GitHub Pages map regression test: validates Leaflet CSS SRI
// indirectly through computed layout, real DMI markers, map controls and tiles.
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const {chromium}=require("playwright");
const BASE="https://marcelherber.github.io/climate-dashboard/groenland_stationen.html";
const folder=path.join(process.cwd(),"artifacts");
fs.mkdirSync(folder,{recursive:true});
async function main(){
 const browser=await chromium.launch({headless:true});
 try{
  for(const device of [{name:"desktop",width:1440,height:900,mobile:false},
                       {name:"mobile",width:390,height:844,mobile:true}]){
   const context=await browser.newContext({
    viewport:{width:device.width,height:device.height},
    isMobile:device.mobile,hasTouch:device.mobile
   });
   const page=await context.newPage();
   const response=await page.goto(BASE,{waitUntil:"domcontentloaded",timeout:60000});
   assert.equal(response.status(),200,"Public Greenland page HTTP 200");
   await page.waitForFunction(()=>window.GreenlandDmiMath?.getState?.().stations>=10,
     null,{timeout:60000});
   await page.waitForFunction(()=>{
    const el=document.querySelector("#grMap .leaflet-tile");
    const marker=document.querySelector("#grMap path.leaflet-interactive");
    const zoom=document.querySelector("#grMap .leaflet-control-zoom-in");
    return el&&marker&&zoom&&getComputedStyle(el).position==="absolute"&&
     getComputedStyle(marker).visibility!=="hidden"&&
     getComputedStyle(zoom).display!=="none";
   },null,{timeout:45000});
   const mapState=await page.evaluate(()=>({
    stations:window.GreenlandDmiMath.getState().stations,
    markers:window.GreenlandDmiMath.getState().markerCount,
    zoom:window.GreenlandDmiMath.getState().mapZoom,
    tilePosition:getComputedStyle(document.querySelector("#grMap .leaflet-tile")).position,
    controls:document.querySelector("#grMap .leaflet-control-zoom")!==null
   }));
   assert.ok(mapState.stations>=10&&mapState.markers>=10);
   assert.equal(mapState.tilePosition,"absolute");
   assert.ok(mapState.controls);
   // Public Pages must contain both new layers, not just the old marker catalogue.
   await page.waitForFunction(()=>window.GreenlandClimateMath?.getState?.().recordModes.length>=3,
     null,{timeout:25000});
   await page.locator("#grMapMode").selectOption("high");
   assert.ok(await page.locator("#grMapRankingList li").count()>=5,
     "Public Pages must show the original DMI historical record leaderboard");
   assert.ok((await page.locator("#grMapLegend").innerText()).includes("°C"),
     "Record-map legend must identify the fixed scale unit");
   await page.locator("#grSearch").fill("Nuuk");
   await page.locator(".gr-station").filter({hasText:"04250"}).first().click();
   await page.waitForFunction(()=>window.GreenlandClimateMath?.getState?.().hasNormal,
     null,{timeout:80000});
   const climate=await page.evaluate(()=>window.GreenlandClimateMath.getState());
   assert.ok(climate.referenceYears>=24&&climate.points>=24,
     "Live Pages must calculate trustworthy Greenland climate anomalies");
   await page.locator("#grClimateView").selectOption("month");
   await page.waitForFunction(()=>window.GreenlandClimateMath?.getState?.().view==="month"&&
     window.GreenlandClimateMath.getState().hasNormal,null,{timeout:80000});
   console.log("PASS public Greenland climate "+device.name+":",JSON.stringify(climate));
   await page.locator("#grMap").screenshot({
    path:path.join(folder,"greenland-live-map-"+device.name+".png"),
    animations:"disabled"
   });
   console.log("PASS public Greenland "+device.name+":",JSON.stringify(mapState));
   await context.close();
  }
 }finally{await browser.close();}
}
main().catch(err=>{
 console.error("PUBLIC GREENLAND MAP FAILED:",err.stack||err);
 process.exitCode=1;
});
