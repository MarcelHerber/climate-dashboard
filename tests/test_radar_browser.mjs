import assert from "node:assert/strict";
import {chromium} from "playwright";
import {radarLabPage} from "../alpenwetter-worker/src/radar-lab.js";

const grid={west:1,east:19,south:45,north:56,width:900,height:550};
const frames=Array.from({length:36},(_,i)=>{
  const utc=new Date(Date.UTC(2026,10,10,12,0+i*5)).toISOString();
  return{utc,image:"frames/"+utc.slice(0,16).replace(/[-T:]/g,"")+".png",stats:{coverage:.68,wet_fraction:.1}};
});
const manifest={schema:1,product:"DWD RADOLAN RY / ODIM HDF5",source:"Deutscher Wetterdienst / Open Data",grid,units:"mm/h",palette:{no_echo:0,nodata:255,max_rate:120,log_base:.05},frames};
const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
try{
 for(const vp of [{width:1366,height:850,label:"desktop"},{width:390,height:844,label:"mobile"}]){
  const context=await browser.newContext({viewport:vp,acceptDownloads:true});
  const page=await context.newPage(),errors=[];
  page.on("pageerror",e=>errors.push(e.message));
  const data=await page.evaluate(()=>{
    const c=document.createElement("canvas");c.width=900;c.height=550;
    const x=c.getContext("2d"),img=x.createImageData(c.width,c.height);
    for(let j=0;j<c.height;j++)for(let i=0;i<c.width;i++){
      const n=(j*c.width+i)*4;
      const val=(i<80||j<40)?255:(i+j)%7===0?100:0;
      img.data[n]=img.data[n+1]=img.data[n+2]=val;img.data[n+3]=255;
    }
    x.putImageData(img,0,0);return c.toDataURL("image/png").split(",")[1];
  });
  const png=Buffer.from(data,"base64");
  await page.route("https://radar.example/radarlabor",r=>r.fulfill({status:200,contentType:"text/html",body:radarLabPage()}));
  await page.route("https://radar.example/radarlabor/api/current.json",r=>r.fulfill({status:200,contentType:"application/json",body:JSON.stringify(manifest)}));
  await page.route("https://radar.example/dynamik/api/boundaries",r=>r.fulfill({status:200,contentType:"application/json",body:'{"type":"FeatureCollection","features":[]}'}));
  await page.route(/https:\/\/radar\.example\/radarlabor\/api\/frames\/\d{12}\.png/,r=>r.fulfill({status:200,contentType:"image/png",body:png}));
  await page.goto("https://radar.example/radarlabor",{waitUntil:"domcontentloaded"});
  await page.waitForFunction(()=>document.querySelector("#status")?.textContent.includes("echtes 5-Minuten-Radarkomposit"),null,{timeout:25000});
  let m=await page.evaluate(()=>({
    scroll:document.documentElement.scrollWidth,width:document.documentElement.clientWidth,
    image:document.querySelector("#map").getBoundingClientRect().width,
    pixel:[...document.querySelector("#map").getContext("2d").getImageData(450,275,1,1).data]
  }));
  assert.ok(m.scroll<=m.width+2,"Horizontal overflow "+JSON.stringify(m));
  assert.ok(m.image>250);assert.equal(m.pixel[3],255);
  assert.equal(await page.locator("#legend .swatch").count(),11);
  await page.locator("#region").selectOption("north");
  await page.locator("#history").selectOption("12");
  await page.waitForFunction(()=>document.querySelector("#status")?.textContent.includes("12 Bilder"),null,{timeout:15000});
  await page.locator("#prev").click();
  await page.locator("#next").click();
  await page.locator("#overlay").selectOption("none");
  await page.locator("#overlay").selectOption("rain");
  await page.locator("#timeline").evaluate(el=>{el.value="0";el.dispatchEvent(new Event("input",{bubbles:true}));});
  const [download]=await Promise.all([page.waitForEvent("download",{timeout:15000}),page.locator("#png").click()]);
  assert.ok(download.suggestedFilename().endsWith(".png"));
  assert.deepEqual(errors,[],"Browser exception: "+errors.join("; "));
  await page.screenshot({path:"/tmp/radar-"+vp.label+".png",fullPage:true});
  console.log("DWD radar",vp.label,"map, 11 fixed legend stages, history, steps, overlay, export PASS",JSON.stringify(m));
  await context.close();
 }
}finally{await browser.close()}
