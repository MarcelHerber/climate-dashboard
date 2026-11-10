import assert from "node:assert/strict";
import { chromium } from "playwright";
const BASE="https://climate-dashboard-alpenwetter.marcel-herber.workers.dev";
const password=process.env.ALPENWETTER_PASSWORD;
assert.ok(password,"Missing Cloudflare password secret in GitHub Actions");

const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
try {
 for(const vp of [{width:1366,height:850,label:"desktop"},{width:390,height:844,label:"mobile"}]){
  const context=await browser.newContext({viewport:vp,acceptDownloads:true});
  const page=await context.newPage(),errors=[],network=[];
  page.on("pageerror",err=>errors.push(err.message));
  page.on("response",r=>{if(r.url().includes("/radarlabor/api/"))network.push({path:r.url().split("/radarlabor/api/")[1],status:r.status()})});
  // Worker deployment can finish after the data action that triggers this QA.
  let login;
  for(let retry=0;retry<18;retry++){
    login=await page.goto(BASE+"/radarlabor",{waitUntil:"domcontentloaded",timeout:35000});
    if(login.status()===200 && await page.locator('input[name="next"][value="/radarlabor"]').count())break;
    await page.waitForTimeout(5000);
  }
  assert.equal(login.status(),200);
  assert.equal(await page.locator('input[name="next"][value="/radarlabor"]').count(),1,"New Worker radar route not deployed");
  const denied=await page.request.get(BASE+"/radarlabor/api/current.json");
  assert.equal(denied.status(),401);
  await page.locator('input[type="password"]').fill(password);
  await Promise.all([
    page.waitForURL(/\/radarlabor\/?$/, {timeout:30000}),
    page.locator('button[type="submit"]').click()
  ]);
  try{
   await page.waitForFunction(()=>document.getElementById("status")?.textContent.includes("echtes 5-Minuten-Radarkomposit"),
     null,{timeout:65000});
  }catch(err){
   console.log("LIVE RADAR STATUS",await page.locator("#status").textContent().catch(()=>null));
   console.log("BROWSER ERRORS",JSON.stringify(errors));
   console.log("RADAR API",JSON.stringify(network.slice(0,16)));
   throw err;
  }
  const m=await page.evaluate(()=>({
   width:document.documentElement.clientWidth,
   scrollWidth:document.documentElement.scrollWidth,
   center:[...document.querySelector("#map").getContext("2d").getImageData(420,230,1,1).data],
   frameName:document.getElementById("mapStamp").textContent,
   legend:document.querySelectorAll(".swatch").length
  }));
  assert.ok(m.scrollWidth<=m.width+2,"Horizontal overflow: "+JSON.stringify(m));
  assert.equal(m.center[3],255);
  assert.equal(m.legend,11);
  assert.match(m.frameName,/DWD RY · 5-Min-Intervall/);
  await page.locator("#region").selectOption("south");
  await page.locator("#history").selectOption("12");
  await page.waitForFunction(()=>document.getElementById("status")?.textContent.includes("12 Bilder"),null,{timeout:35000});
  await page.locator("#prev").click();
  await page.locator("#next").click();
  const [download]=await Promise.all([page.waitForEvent("download",{timeout:18000}),page.locator("#png").click()]);
  assert.ok(download.suggestedFilename().endsWith(".png"));
  assert.deepEqual(errors,[],"Unexpected browser JS errors");
  await page.screenshot({path:"/tmp/radarlabor-live-"+vp.label+".png",fullPage:true});
  console.log("LIVE DWD RY",vp.label,"PASS",JSON.stringify(m),"HTTP",JSON.stringify(network.slice(0,6)));
  await context.close();
 }
}finally{await browser.close()}
