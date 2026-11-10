import assert from "node:assert/strict";
import {chromium} from "playwright";
const root="https://climate-dashboard-alpenwetter.marcel-herber.workers.dev";
const password=process.env.ALPENWETTER_PASSWORD;
assert.ok(password,"Protected studio password secret missing");
const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
try{
 for(const viewport of [{width:1366,height:850,name:"desktop"},{width:390,height:844,name:"mobil"}]){
  const context=await browser.newContext({viewport,acceptDownloads:true});
  const page=await context.newPage(),errors=[],network=[];
  page.on("pageerror",e=>errors.push(e.message));
  page.on("response",r=>{
   if(r.url().includes("/radarlabor/api/"))network.push([r.url().replace(root+"/radarlabor/api/",""),r.status()]);
  });
  let response;
  for(let i=0;i<18;i++){
   response=await page.goto(root+"/radarlabor/kanaren",{waitUntil:"domcontentloaded",timeout:30000});
   if(response.status()===200&&await page.locator('input[name="next"][value="/radarlabor/kanaren"]').count())break;
   await page.waitForTimeout(5000);
  }
  assert.equal(response.status(),200);
  assert.equal(await page.locator('input[name="next"][value="/radarlabor/kanaren"]').count(),1);
  const denied=await page.request.get(root+"/radarlabor/api/canarias/current.json");
  assert.equal(denied.status(),401);
  await page.locator('input[type="password"]').fill(password);
  await Promise.all([
   page.waitForURL(/\/radarlabor\/kanaren\/?$/,{timeout:30000}),
   page.locator('button[type="submit"]').click()
  ]);
  try{
   await page.waitForFunction(()=>document.getElementById("status")?.textContent.includes("Echte AEMET-Messung"),
       null,{timeout:85000});
  }catch(e){
   console.log("LIVE ERROR",await page.locator("#status").textContent().catch(()=>null));
   console.log("NETWORK",network.slice(0,15),"BROWSER ERRORS",errors.slice(0,15));throw e;
  }
  const data=await page.evaluate(()=>({
    width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,
    map:[document.getElementById("radar").width,document.getElementById("radar").height],
    stamp:document.getElementById("stamp").textContent
  }));
  assert.ok(data.scroll<=data.width+2,"Horizontal overflow: "+JSON.stringify(data));
  assert.deepEqual(data.map,[1460,720]);
  assert.ok(network.some(x=>x[0]==="canarias/current.json"&&x[1]===200));
  assert.ok(network.some(x=>x[0].startsWith("canarias/frames/")&&x[1]===200));
  assert.ok(network.some(x=>x[0]==="borders_europe.geojson"&&x[1]===200));
  for(const area of ["west","central","east","all"]){
   await page.locator("#region").selectOption(area);
  }
  const [download]=await Promise.all([page.waitForEvent("download",{timeout:12000}),page.locator("#png").click()]);
  assert.ok(download.suggestedFilename().endsWith(".png"));
  assert.deepEqual(errors,[],"Live JS exceptions: "+JSON.stringify(errors));
  console.log("LIVE CANARIAS AEMET PASS",viewport.name,JSON.stringify(data),JSON.stringify(network.slice(0,8)));
  await page.screenshot({path:"/tmp/canarias-live-"+viewport.name+".png",fullPage:true});
  await context.close();
 }
}finally{await browser.close()}
