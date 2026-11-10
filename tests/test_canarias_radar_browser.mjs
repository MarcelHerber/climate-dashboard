import assert from "node:assert/strict";
import {chromium} from "playwright";
import {canariasRadarPage} from "../alpenwetter-worker/src/canarias-radar-lab.js";

const grid={west:-19.5,east:-12.2,south:27,north:30.6,width:1460,height:720};
const colors=["#0000fc","#0094fc","#00fcfc","#438323","#00c000","#00ff00","#ffff00","#ffbb00","#ff7f00","#ff0000","#c8005a"];
const labels=["12–18","18–24","24–30","30–36","36–42","42–48","48–54","54–60","60–66","66–72","≥72"];
const frames=[0,10,20].map(minute=>{
 const utc=new Date(Date.UTC(2026,10,10,21,minute)).toISOString();
 return {utc,image:"frames/"+utc.slice(0,16).replace(/[-T:]/g,"")+".png",stats:{echo_pixel_fraction:.025}};
});
const manifest={schema:1,source:"AEMET Canarias / regional LPA reflectivity GeoTIFF",
 grid,unit:"dBZ",radar_product:"PPI 0.5 degree",cadence_minutes:10,
 palette:{labels,colors,no_radar_echo_or_coverage_unknown:0},frames};
const geo={type:"FeatureCollection",features:[{
 type:"Feature",properties:{name:"Spanien"},geometry:{
 type:"MultiPolygon",coordinates:[[[[-17.1,28.2],[-16.4,28.2],[-16.4,28.6],[-17.1,28.6],[-17.1,28.2]]]]
 }
}]};
const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
try{
 for(const size of [{name:"desktop",width:1366,height:850},{name:"mobil",width:390,height:844}]){
  const context=await browser.newContext({viewport:size,acceptDownloads:true});
  const page=await context.newPage(),errors=[];
  page.on("pageerror",e=>errors.push(e.message));
  const encoded=await page.evaluate(()=>{
    const c=document.createElement("canvas");c.width=1460;c.height=720;
    const x=c.getContext("2d"),rgba=x.createImageData(c.width,c.height);
    for(let y=0;y<c.height;y++)for(let j=0;j<c.width;j++){
      const p=(y*c.width+j)*4;
      const v=(j>200&&j<850&&y>90&&y<460&&((j+y)%7===0))?(1+(j%11)):0;
      rgba.data[p]=rgba.data[p+1]=rgba.data[p+2]=v;rgba.data[p+3]=255;
    }
    x.putImageData(rgba,0,0);
    return c.toDataURL("image/png").split(",")[1];
  });
  const png=Buffer.from(encoded,"base64");
  await page.route("https://radar.example/radarlabor/kanaren",route=>route.fulfill({
    status:200,contentType:"text/html; charset=utf-8",body:canariasRadarPage()}));
  await page.route("https://radar.example/radarlabor/api/canarias/current.json",route=>route.fulfill({
    status:200,contentType:"application/json",body:JSON.stringify(manifest)}));
  await page.route("https://radar.example/radarlabor/api/borders_europe.geojson",route=>route.fulfill({
    status:200,contentType:"application/geo+json",body:JSON.stringify(geo)}));
  await page.route(/https:\/\/radar\.example\/radarlabor\/api\/canarias\/frames\/.*/,route=>route.fulfill({
    status:200,contentType:"image/png",body:png}));
  await page.goto("https://radar.example/radarlabor/kanaren",{waitUntil:"domcontentloaded"});
  await page.waitForFunction(()=>document.getElementById("status")?.textContent.includes("Echte AEMET-Messung"),null,{timeout:25000});
  const metrics=await page.evaluate(()=>({
    scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth,
    canvasWidth:document.querySelector("#radar").getBoundingClientRect().width,
    center:[...document.querySelector("#radar").getContext("2d").getImageData(700,350,1,1).data],
  }));
  assert.ok(metrics.canvasWidth>250);
  assert.ok(metrics.scroll<=metrics.client+2,"Horizontal overflow "+JSON.stringify(metrics));
  assert.equal(metrics.center[3],255);
  assert.equal(await page.locator("#legend .swatch").count(),11);
  for(const key of ["west","central","east","all"]){
    await page.locator("#region").selectOption(key);
    assert.equal(await page.locator("#region").inputValue(),key);
  }
  await page.locator("#layer").selectOption("off");
  await page.locator("#layer").selectOption("rain");
  await page.locator("#prev").click();
  await page.waitForFunction(()=>document.getElementById("time")?.textContent.includes("21:10"),null,{timeout:12000});
  await page.locator("#next").click();
  await page.locator("#timeline").evaluate(n=>{n.value="0";n.dispatchEvent(new Event("input",{bubbles:true}));});
  const [download]=await Promise.all([
    page.waitForEvent("download",{timeout:10000}),page.locator("#png").click()
  ]);
  assert.ok(download.suggestedFilename().endsWith(".png"));
  assert.deepEqual(errors,[],"Browser errors "+JSON.stringify(errors));
  await page.screenshot({path:"/tmp/canarias-radar-"+size.name+".png",fullPage:true});
  console.log("AEMET CANARIAS",size.name,"PASS",metrics);
  await context.close();
 }
}finally{await browser.close()}
