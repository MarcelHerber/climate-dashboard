import assert from "node:assert/strict";
import {chromium} from "playwright";
const root="https://climate-dashboard-alpenwetter.marcel-herber.workers.dev";
const password=process.env.ALPENWETTER_PASSWORD;
assert.ok(password,"Missing protected laboratory password");
const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
try {
 for(const viewport of [{width:1366,height:860,label:"desktop"},{width:390,height:844,label:"mobile"}]){
  const context=await browser.newContext({viewport,acceptDownloads:true});
  const page=await context.newPage(),errors=[],responses=[];
  page.on("pageerror",e=>errors.push(e.message));
  page.on("response",r=>{
   if(r.url().includes("/radarlabor/api/"))
     responses.push([r.url().split("/radarlabor/api/")[1],r.status()]);
  });
  let login;
  for(let attempt=0;attempt<18;attempt++){
    login=await page.goto(root+"/radarlabor/europa",{waitUntil:"domcontentloaded",timeout:30000});
    if(login.status()===200 && await page.locator('input[name="next"][value="/radarlabor/europa"]').count())break;
    await page.waitForTimeout(5000);
  }
  assert.equal(login.status(),200);
  assert.equal(await page.locator('input[name="next"][value="/radarlabor/europa"]').count(),1);
  const denied=await page.request.get(root+"/radarlabor/api/opera/current.json");
  assert.equal(denied.status(),401);
  await page.locator('input[type="password"]').fill(password);
  await Promise.all([
   page.waitForURL(/\/radarlabor\/europa\/?$/, {timeout:30000}),
   page.locator('button[type="submit"]').click()
  ]);
  try {
   await page.waitForFunction(()=>document.querySelector("#status")?.textContent.includes("Echtes OPERA-Europakomposit"),null,{timeout:90000});
  }catch(e){
   console.log("OPERA LIVE DEBUG",await page.locator("#status").textContent().catch(()=>null),responses.slice(0,20),errors);
   throw e;
  }
  await page.waitForFunction(()=>document.querySelector("#legend .item")?.textContent,null,{timeout:20000});
  const b=responses.find(x=>x[0]==="borders_europe.geojson");
  if(!b) await page.waitForTimeout(3000);
  assert.ok(responses.some(x=>x[0]==="borders_europe.geojson"&&x[1]===200),
   "High-res Natural Earth boundaries not fetched");
  assert.ok(responses.some(x=>x[0]==="opera/current.json"&&x[1]===200));
  assert.ok(responses.some(x=>x[0].startsWith("opera/frames/dbzh_")&&x[1]===200),"ECMWETNET dBZ images missing");
  const sample=await page.evaluate(()=>({
   width:document.documentElement.clientWidth,
   scrollWidth:document.documentElement.scrollWidth,
   canvas:[document.querySelector("canvas").width,document.querySelector("canvas").height]
  }));
  assert.ok(sample.scrollWidth<=sample.width+2,"Horizontal overflow "+JSON.stringify(sample));
  assert.deepEqual(sample.canvas,[1776,1056]);
  await page.locator("#rate").click();
  await page.waitForFunction(()=>document.getElementById("status")?.textContent.includes("Echtes OPERA-Europakomposit")&&document.getElementById("product")?.textContent.includes("NIMBUS"),null,{timeout:45000});
  await page.locator("#region").selectOption("central");
  await page.locator("#previous").click();
  await page.locator("#next").click();
  const [download]=await Promise.all([page.waitForEvent("download",{timeout:16000}),page.locator("#save").click()]);
  assert.ok(download.suggestedFilename().endsWith(".png"));
  assert.deepEqual(errors,[],"Live browser exceptions "+JSON.stringify(errors));
  console.log("LIVE OPERA EUROPE PASS",viewport.label,JSON.stringify(sample),JSON.stringify(responses.slice(0,10)));
  await page.screenshot({path:"/tmp/opera-europe-live-"+viewport.label+".png",fullPage:true});
  await context.close();
 }
}finally{await browser.close()}
