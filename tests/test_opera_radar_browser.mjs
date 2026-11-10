import assert from "node:assert/strict";
import {chromium} from "playwright";
import {operaRadarPage} from "../alpenwetter-worker/src/opera-radar-lab.js";

const grid={west:-27,east:47,south:29,north:73,width:1480,height:880};
const frames=(kind,cadence,count)=>Array.from({length:count},(_,i)=>{
 const utc=new Date(Date.UTC(2026,10,10,17,i*cadence)).toISOString();
 return {utc,image:"frames/"+kind+"_"+utc.slice(0,16).replace(/[-T:]/g,"")+".png",
   stats:{coverage:.51,echo_fraction:.03}};
});
const manifest={schema:1,source:"EUMETNET OPERA",grid,encoding:{
 nodata:255,undetect:0,echo_min:1,echo_max:254,dbzh_range:[-20,75],rate_max:120,rate_log_base:.05
},products:{
 dbzh:{name:"CIRRUS",unit:"dBZ",cadence_minutes:5,native_km:1,frames:frames("dbzh",5,12)},
 rate:{name:"NIMBUS",unit:"mm/h",cadence_minutes:15,native_km:2,frames:frames("rate",15,8)}
}};
const borders={type:"FeatureCollection",features:[{
 type:"Feature",properties:{name:"Sample"},
 geometry:{type:"Polygon",coordinates:[[[5,47],[15,47],[15,55],[5,55],[5,47]]]}
}]};
const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
try{
 for(const v of [{width:1366,height:850,name:"desktop"},{width:390,height:844,name:"mobil"}]){
  const context=await browser.newContext({viewport:v,acceptDownloads:true});
  const page=await context.newPage(),errors=[];
  page.on("pageerror",e=>errors.push(e.message));
  const png=await page.evaluate(()=>{
   const canvas=document.createElement("canvas");canvas.width=1480;canvas.height=880;
   const ctx=canvas.getContext("2d"),id=ctx.createImageData(canvas.width,canvas.height);
   for(let j=0;j<canvas.height;j++)for(let i=0;i<canvas.width;i++){
     const o=(j*canvas.width+i)*4;
     const value=(j<70||i<50)?255:(i+j)%13<4?155:0;
     id.data[o]=id.data[o+1]=id.data[o+2]=value;id.data[o+3]=255;
   }
   ctx.putImageData(id,0,0);return canvas.toDataURL("image/png").split(",")[1];
  });
  const image=Buffer.from(png,"base64");
  await page.route("https://radar.example/radarlabor/europa",r=>r.fulfill({status:200,contentType:"text/html; charset=utf-8",body:operaRadarPage()}));
  await page.route("https://radar.example/radarlabor/api/opera/current.json",r=>r.fulfill({status:200,contentType:"application/json",body:JSON.stringify(manifest)}));
  await page.route("https://radar.example/radarlabor/api/borders_europe.geojson",r=>r.fulfill({status:200,contentType:"application/geo+json",body:JSON.stringify(borders)}));
  await page.route(/https:\/\/radar\.example\/radarlabor\/api\/opera\/frames\/.*/,r=>r.fulfill({status:200,contentType:"image/png",body:image}));
  await page.goto("https://radar.example/radarlabor/europa",{waitUntil:"domcontentloaded"});
  await page.waitForFunction(()=>document.getElementById("status")?.textContent.includes("Echtes OPERA-Europakomposit"),null,{timeout:35000});
  const metrics=await page.evaluate(()=>({
    scrollWidth:document.documentElement.scrollWidth,width:document.documentElement.clientWidth,
    canvasWidth:document.querySelector("canvas").getBoundingClientRect().width,
    pixel:Array.from(document.querySelector("canvas").getContext("2d").getImageData(700,500,1,1).data),
  }));
  assert.ok(metrics.scrollWidth<=metrics.width+2,v.name+" horizontal overflow "+JSON.stringify(metrics));
  assert.ok(metrics.canvasWidth>250);
  assert.equal(metrics.pixel[3],255);
  assert.equal(await page.locator("#legend .item").count(),10);
  await page.locator("#rate").click();
  await page.waitForFunction(()=>document.getElementById("product")?.textContent.includes("NIMBUS")&&document.getElementById("status")?.textContent.includes("Echtes OPERA-Europakomposit"),null,{timeout:35000});
  assert.equal(await page.locator("#legend .item").count(),11);
  await page.locator("#region").selectOption("balearics");
  assert.equal(await page.locator("#region").inputValue(),"balearics");
  await page.waitForFunction(()=>document.querySelector("#status")?.textContent.includes("Echtes OPERA-Europakomposit"),null,{timeout:10000});
  await page.locator("#region").selectOption("central");
  await page.locator("#previous").click();
  await page.locator("#next").click();
  await page.locator("#timeline").evaluate(e=>{e.value="0";e.dispatchEvent(new Event("input",{bubbles:true}));});
  await page.locator("#overlay").selectOption("off");
  await page.locator("#overlay").selectOption("on");
  const [download]=await Promise.all([page.waitForEvent("download",{timeout:15000}),page.locator("#save").click()]);
  assert.ok(download.suggestedFilename().endsWith(".png"));
  assert.deepEqual(errors,[],"Browser errors "+v.name+": "+errors.join("; "));
  await page.screenshot({path:"/tmp/opera-radar-"+v.name+".png",fullPage:true});
  console.log("OPERA EUROPE BROWSER PASS",v.name,metrics);
  await context.close();
 }
}finally{await browser.close()}
