#!/usr/bin/env node
"use strict";
/* Live NOAA IMS snow maps: real 24 km raster images, Europe/hemisphere
   switching, actual downloads and touch controls on GitHub Pages. */
const {chromium}=require("playwright");
const fs=require("node:fs");
const path=require("node:path");
const assert=require("node:assert/strict");

const ROOT=process.env.IMS_SNOW_LIVE_URL ||
  "https://marcelherber.github.io/climate-dashboard/eurasia_snow.html";
const OUTPUT=path.resolve("artifacts/ims-snow-live");
fs.mkdirSync(OUTPUT,{recursive:true});

async function readyImages(page, region, date) {
  await page.waitForFunction(({region,date})=>{
    const names=["snowCoverImage","snowAnomalyImage"];
    return names.every((id,i)=>{
      const el=document.getElementById(id);
      const part=(i===0?"cover":"anomaly");
      const suffix=region==="europe"?"_europe_"+part+".png":"_"+part+".png";
      return el&&!el.hidden&&el.complete&&el.naturalWidth>=2400&&
        el.naturalHeight>=900&&el.currentSrc.includes(date+suffix);
    }) && !document.getElementById("snowMapRegion").disabled;
  },{region,date},{timeout:60000});
}
async function press(page,selector,mobile) {
  if(mobile)await page.locator(selector).tap({timeout:25000});
  else await page.locator(selector).click({timeout:25000});
}
async function checkViewport(browser, device, archive) {
  const ctx=await browser.newContext({
    viewport:{width:device.width,height:850},
    isMobile:device.mobile,hasTouch:device.mobile,acceptDownloads:true,
    reducedMotion:"reduce"
  });
  const page=await ctx.newPage();
  const errors=[];
  page.on("pageerror",e=>errors.push(e.message));
  const result={device:device.name,viewport:device.width,dates:archive.maps.length};
  try {
    const response=await page.goto(ROOT,{waitUntil:"domcontentloaded",timeout:90000});
    assert.equal(response.status(),200);
    await page.waitForFunction(()=>document.getElementById("snowMapDate")?.options.length>=2
       && !document.getElementById("snowMapRegion")?.disabled,null,{timeout:90000});
    const dates=archive.maps.map(r=>r.date).sort().reverse();
    const newest=dates[0], previous=dates[1];
    assert.equal(await page.locator("#snowMapDate").inputValue(),newest);
    await readyImages(page,"hemisphere",newest);
    await page.locator("#snowMapRegion").selectOption("europe");
    await readyImages(page,"europe",newest);
    assert.match(await page.locator("#snowMapReference").innerText(),/Island bis Ural/);
    await press(page,"#snowMapPrevious",device.mobile);
    await readyImages(page,"europe",previous);
    assert.equal(await page.locator("#snowMapDate").inputValue(),previous);
    await press(page,"#snowMapNext",device.mobile);
    await readyImages(page,"europe",newest);
    for(const [id,part] of [["snowCoverDownload","Schneebedeckung"],["snowAnomalyDownload","Abweichung"]]){
      const promise=page.waitForEvent("download",{timeout:30000});
      await press(page,"#"+id,device.mobile);
      const downloaded=await promise;
      assert.match(downloaded.suggestedFilename(),/NOAA_IMS_Europa_Island-Ural_/);
      assert.ok(downloaded.suggestedFilename().includes(part));
      assert.ok(downloaded.suggestedFilename().includes(newest));
      const target=path.join(OUTPUT,device.name+"-"+id+".png");
      await downloaded.saveAs(target);
      const bytes=fs.readFileSync(target);
      assert.equal(bytes.subarray(0,8).toString("hex"),"89504e470d0a1a0a");
      assert.ok(bytes.length>100000,"Image unexpectedly small");
      result[id]={bytes:bytes.length,filename:downloaded.suggestedFilename()};
    }
    const layout=await page.evaluate(()=>{
      const card=document.querySelector("#snowCoverImage").closest(".snow-map-card");
      const image=document.getElementById("snowCoverImage");
      const container=card.getBoundingClientRect(), rect=image.getBoundingClientRect();
      return {cardWidth:container.width,imageWidth:rect.width,
        fits:rect.left>=container.left-3&&rect.right<=container.right+3,
        images:["snowCoverImage","snowAnomalyImage"].map(id=>{
          const img=document.getElementById(id);
          return {width:img.naturalWidth,height:img.naturalHeight,visible:!img.hidden};
        })};
    });
    assert.ok(layout.fits,"European map exceeds its card width");
    assert.ok(layout.images.every(x=>x.visible&&x.width>=2400&&x.height>=1400));
    result.europeLayout=layout;
    await page.locator("#snowMapRegion").selectOption("hemisphere");
    await readyImages(page,"hemisphere",newest);
    assert.equal(await page.locator("#snowMapDate").inputValue(),newest);
    assert.ok(errors.length===0,"Uncaught browser errors: "+errors.join(" | "));
    await page.screenshot({path:path.join(OUTPUT,device.name+".png"),fullPage:false});
    result.passed=true;
  }catch(error){
    result.passed=false;result.error=String(error).slice(0,1200);
    try{await page.screenshot({path:path.join(OUTPUT,device.name+"-error.png"),fullPage:false});}catch{}
  }finally{result.pageErrors=errors.slice(-5);await ctx.close()}
  return result;
}
async function main(){
  const response=await fetch(new URL("eurasia_snow/maps/index.json",ROOT));
  assert.equal(response.status,200,"Live image archive manifest");
  const archive=await response.json();
  assert.equal(archive.schema,1);
  assert.deepEqual(archive.reference_period,[2001,2020]);
  assert.ok(archive.maps.length>=3);
  assert.ok(archive.maps.every(row=>["cover","anomaly","europe_cover","europe_anomaly"]
    .every(kind=>row[kind]==="images/"+row.date+"_"+kind+".png")),
    "All declared real NOAA IMS map days need 4 verified image paths");
  const browser=await chromium.launch({headless:true});
  let report=[];
  try{
    for(const device of [{name:"desktop",width:1440,mobile:false},
                         {name:"mobile",width:390,mobile:true}]){
      report.push(await checkViewport(browser,device,archive));
    }
  }finally{await browser.close()}
  fs.writeFileSync(path.join(OUTPUT,"report.json"),JSON.stringify({
    testedAt:new Date().toISOString(),latest:archive.latest,
    maps:archive.maps.length,results:report
  },null,2));
  process.stdout.write(JSON.stringify(report,null,2)+"\n");
  if(report.some(x=>!x.passed))process.exitCode=1;
}
main().catch(e=>{console.error(e);process.exitCode=1});
