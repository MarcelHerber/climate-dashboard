import assert from "node:assert/strict";
import { chromium } from "playwright";
import { shapiroLabPage } from "../alpenwetter-worker/src/shapiro-lab.js";

const keys=["thetae","msl","fgen","wind850","wind700","rh700","rh500","pv","jet300","gh500","omega700","u850","v850"];
const profiles=["wind","rh","omega","theta"];
const limits={
 thetae:[260,370],msl:[940,1050],fgen:[-32,32],wind850:[0,85],
 wind700:[0,95],rh700:[0,100],rh500:[0,100],pv:[-2,15],
 jet300:[0,110],gh500:[4300,6100],omega700:[-3,3],u850:[-85,85],v850:[-85,85]
};
const profileLimits={wind:[0,105],rh:[0,100],omega:[-5,5],theta:[240,410]};
const grid={width:461,height:253,west:-70,east:45,south:12,north:75,step:.25};
const levels=[300,400,500,600,700,850,925];
const frame=(hour)=>({
 hour,valid_utc:new Date(Date.UTC(2026,10,10,hour)).toISOString(),
 maps:Object.fromEntries(keys.map(k=>[k,"frames/2026111000/"+k+"_"+String(hour).padStart(3,"0")+".png"])),
 profiles:Object.fromEntries(profiles.map(k=>[k,"frames/2026111000/profile_"+k+"_"+String(hour).padStart(3,"0")+".png"])),
 candidates:[{
   track_id:1,hour,lat:50,lon:-20,msl_hpa:972.5,depth_hpa:22,
   wind850_ms:33,thetae_core_minus_ring_k:3.2,
   fgen_max_k_100km_3h:7.1,score:4,pressure_change_hpa_3h:null,
   criteria:{developed_low:true,organized_frontogenesis:true,strong_low_level_wind:true,warm_core_proxy:true},
   classification:"automatic_screening_only"
 }]
});
const manifest={
 schema:1,cycle:"2026111000",initialized_utc:"2026-11-10T00:00:00Z",
 grid,frames:[frame(0),frame(3)],
 encoding:{minmax:limits,profile_minmax:profileLimits,missing:255,scale_max:254},
 profile_levels_hpa:levels
};
const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
try{
 for(const viewport of [{width:1370,height:900,label:"desktop"},{width:390,height:844,label:"mobile"}]){
  const ctx=await browser.newContext({viewport,acceptDownloads:true});
  const page=await ctx.newPage(),errors=[];
  page.on("pageerror",e=>errors.push(e.message));
  const pngs=await page.evaluate(()=>{
    function create(w,h){
      const canvas=document.createElement("canvas");
      canvas.width=w;canvas.height=h;
      const ctx=canvas.getContext("2d"),id=ctx.createImageData(w,h);
      for(let y=0;y<h;y++)for(let x=0;x<w;x++){
        const n=(y*w+x)*4,val=Math.round(30+(x/w)*180);
        id.data[n]=id.data[n+1]=id.data[n+2]=val;id.data[n+3]=255;
      }
      ctx.putImageData(id,0,0);return canvas.toDataURL("image/png").split(",")[1];
    }
    return {map:create(461,253),atlas:create(461,1771)};
  });
  const image1=Buffer.from(pngs.map,"base64"),image2=Buffer.from(pngs.atlas,"base64");
  await page.route("https://studio.example/dynamik/shapiro",r=>r.fulfill({status:200,contentType:"text/html; charset=utf-8",body:shapiroLabPage()}));
  await page.route("https://studio.example/dynamik/api/shapiro/current.json",r=>r.fulfill({status:200,contentType:"application/json",body:JSON.stringify(manifest)}));
  await page.route("https://studio.example/dynamik/api/boundaries",r=>r.fulfill({status:200,contentType:"application/json",body:'{"type":"FeatureCollection","features":[]}'}));
  await page.route(/https:\/\/studio\.example\/dynamik\/api\/shapiro\/frames\/.*/,r=>r.fulfill({
    status:200,contentType:"image/png",body:r.request().url().includes("/profile_")?image2:image1
  }));
  await page.goto("https://studio.example/dynamik/shapiro",{waitUntil:"domcontentloaded"});
  await page.waitForFunction(()=>document.querySelector("#status")?.textContent.includes("vollständig geladen"),{timeout:22000});
  const info=await page.evaluate(()=>({
    viewport:document.documentElement.clientWidth,
    scrollWidth:document.documentElement.scrollWidth,
    mapWidth:document.getElementById("synopticMap").getBoundingClientRect().width,
    pixel:Array.from(document.getElementById("synopticMap").getContext("2d").getImageData(700,450,1,1).data)
  }));
  assert.ok(info.mapWidth>=240);
  assert.ok(info.scrollWidth<=info.viewport+2,viewport.label+" overflow "+JSON.stringify(info));
  assert.equal(info.pixel[3],255,"map not rendered");
  await page.locator("#viewB").click();
  await page.waitForFunction(()=>document.querySelector("#legendName")?.textContent.includes("850-hPa-Wind"));
  await page.locator("#viewC").click();
  await page.waitForFunction(()=>document.querySelector("#legendName")?.textContent.includes("PV 200"));
  await page.locator("#viewA").click();
  await page.locator(".candidate").first().click();
  assert.match(await page.locator("#candidateDetails").textContent(),/Nur automatische Vorprüfung/);
  await page.locator("#crossPick").click();
  const map=page.locator("#synopticMap"),rect=await map.boundingBox();
  await map.click({position:{x:rect.width*.35,y:rect.height*.35}});
  await map.click({position:{x:rect.width*.58,y:rect.height*.65}});
  await page.waitForFunction(()=>document.querySelector("#crossHint")?.textContent.includes("Realer ECMWF-Modellquerschnitt"),{timeout:13000});
  await page.locator("#profile").selectOption("rh");
  await page.waitForFunction(()=>document.querySelector("#crossHint")?.textContent.includes("· rh ·"),{timeout:13000});
  await page.locator("#slider").evaluate(n=>{n.value="1";n.dispatchEvent(new Event("input",{bubbles:true}))});
  await page.waitForFunction(()=>document.querySelector("#time")?.textContent.includes("+3 h"),{timeout:13000});
  const [download]=await Promise.all([
    page.waitForEvent("download",{timeout:12000}),page.locator("#save").click()
  ]);
  assert.ok(download.suggestedFilename().endsWith(".png"));
  assert.deepEqual(errors,[],"JS errors "+JSON.stringify(errors));
  await page.screenshot({path:"/tmp/shapiro-"+viewport.label+".png",fullPage:true});
  console.log(viewport.label,"Shapiro cards, candidates, cross section, PNG and viewport PASS",info);
  await ctx.close();
 }
}finally{await browser.close()}
