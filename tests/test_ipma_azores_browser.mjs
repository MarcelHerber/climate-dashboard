import assert from "node:assert/strict";
import {chromium} from "playwright";
import {azoresRadarPage} from "../alpenwetter-worker/src/azores-radar-lab.js";
const frames=Array.from({length:37},(_,i)=>{
 const stamp=new Date(Date.UTC(2026,10,11,11,20+i*5)).toISOString();
 return {utc:stamp,image:"frames/pcr_azo-"+stamp.slice(0,10)+"T"+stamp.slice(11,16).replace(":","")+".png"};
});
const manifest={schema:1,units:"mm/h",
 overlay_bounds:{west:-35.01827,east:-21.19264,south:32.83497,north:44.06629},frames};
const geo={type:"FeatureCollection",features:[{
 type:"Feature",properties:{name:"Portugal"},
 geometry:{type:"MultiPolygon",coordinates:[
 [[[-31.25,39.40],[-31.05,39.40],[-31.05,39.58],[-31.25,39.58],[-31.25,39.40]]],
 [[[-25.65,37.70],[-25.35,37.70],[-25.35,37.90],[-25.65,37.90],[-25.65,37.70]]]]}
}]};
const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
try{
 for(const vp of [{width:1370,height:930,name:"desktop"},{width:390,height:844,name:"mobile"}]){
  const context=await browser.newContext({viewport:vp,acceptDownloads:true});
  const page=await context.newPage(),errors=[];
  page.on("pageerror",e=>errors.push(e.message));
  const base64=await page.evaluate(()=>{
   const canvas=document.createElement("canvas");canvas.width=1500;canvas.height=1562;
   const ctx=canvas.getContext("2d");
   ctx.fillStyle="rgba(80,180,230,.85)";ctx.fillRect(400,500,550,410);
   ctx.fillStyle="rgba(245,175,70,.85)";ctx.fillRect(510,600,130,140);
   return canvas.toDataURL("image/png").split(",")[1];
  });
  const png=Buffer.from(base64,"base64");
  await page.route("https://radar.example/radarlabor/azoren",r=>r.fulfill({status:200,contentType:"text/html; charset=utf-8",body:azoresRadarPage()}));
  await page.route("https://radar.example/radarlabor/api/azoren/current.json",r=>r.fulfill({status:200,contentType:"application/json",body:JSON.stringify(manifest)}));
  await page.route("https://radar.example/radarlabor/api/azoren/legend.png",r=>r.fulfill({status:200,contentType:"image/png",body:png}));
  await page.route("https://radar.example/radarlabor/api/borders_europe.geojson",r=>r.fulfill({status:200,contentType:"application/geo+json",body:JSON.stringify(geo)}));
  await page.route(/https:\/\/radar\.example\/radarlabor\/api\/azoren\/frames\/.*/,r=>r.fulfill({status:200,contentType:"image/png",body:png}));
  await page.goto("https://radar.example/radarlabor/azoren",{waitUntil:"domcontentloaded"});
  await page.waitForFunction(()=>document.querySelector("#status")?.textContent.includes("Original-IPMA-Radardaten"),null,{timeout:20000});
  assert.equal(await page.locator("#legend").evaluate(img=>img.naturalWidth>0),true);
  const screen=await page.evaluate(()=>({
   scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth,
   mapWidth:document.getElementById("radar").getBoundingClientRect().width,
   center:Array.from(document.getElementById("radar").getContext("2d").getImageData(760,400,1,1).data)
  }));
  assert.ok(screen.scroll<=screen.client+2,vp.name+" horizontal overflow: "+JSON.stringify(screen));
  assert.ok(screen.mapWidth>250);assert.equal(screen.center[3],255);
  for(const region of ["west","center","east","all"]){
   await page.locator("#region").selectOption(region);
   assert.equal(await page.locator("#region").inputValue(),region);
  }
  await page.locator("#prev").click();await page.locator("#next").click();
  await page.locator("#timeline").evaluate(el=>{el.value="0";el.dispatchEvent(new Event("input",{bubbles:true}));});
  await page.locator("#showRadar").selectOption("off");await page.locator("#showRadar").selectOption("on");
  const [download]=await Promise.all([page.waitForEvent("download",{timeout:14000}),page.locator("#png").click()]);
  assert.ok(download.suggestedFilename().endsWith(".png"));
  assert.deepEqual(errors,[],"Browser JS exceptions: "+errors.join(";"));
  await page.screenshot({path:"/tmp/azores-radar-"+vp.name+".png",fullPage:true});
  console.log("IPMA AZORES MOCK PASS",vp.name,JSON.stringify(screen));
  await context.close();
 }
}finally{await browser.close()}
