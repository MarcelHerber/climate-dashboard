import assert from "node:assert/strict";
import { chromium } from "playwright";
const root="https://climate-dashboard-alpenwetter.marcel-herber.workers.dev";
const password=process.env.ALPENWETTER_PASSWORD;
assert.ok(password,"ALPENWETTER_PASSWORD is required for this authenticated test");
const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
try{
 for(const viewport of [{width:1370,height:900,label:"desktop"},{width:390,height:844,label:"mobile"}]){
  const context=await browser.newContext({viewport,acceptDownloads:true});
  const page=await context.newPage();const errors=[],http=[];
  page.on("pageerror",e=>errors.push(e.message));
  page.on("response",r=>{if(r.url().includes("/dynamik/api/shapiro/"))http.push([r.url().split("/dynamik/api/shapiro/")[1],r.status()])});
  const login=await page.goto(root+"/dynamik/shapiro",{waitUntil:"domcontentloaded",timeout:30000});
  assert.equal(login.status(),200);
  const unauthorized=await page.request.get(root+"/dynamik/api/shapiro/current.json");
  assert.equal(unauthorized.status(),401);
  await page.locator('input[type="password"]').fill(password);
  await Promise.all([page.waitForURL(/\/dynamik\/shapiro\/?$/, {timeout:30000}),
    page.locator('button[type="submit"]').click()]);
  await page.waitForFunction(()=>document.getElementById("status")?.textContent.includes("vollständig geladen"),null,{timeout:90000})
    .catch(async error=>{
      console.log("LIVE STATUS",await page.locator("#status").textContent().catch(()=>null));
      console.log("LIVE ERRORS",JSON.stringify(errors.slice(0,12)));
      console.log("LIVE HTTP",JSON.stringify(http.slice(0,25)));
      throw error;
    });
  const size=await page.evaluate(()=>({
    scroll:document.documentElement.scrollWidth,
    client:document.documentElement.clientWidth,
    center:Array.from(document.getElementById("synopticMap").getContext("2d").getImageData(750,500,1,1).data)
  }));
  assert.ok(size.scroll<=size.client+2,"Horizontal overflow "+JSON.stringify(size));
  assert.equal(size.center[3],255);
  await page.locator("#viewB").click();
  await page.waitForFunction(()=>document.getElementById("status")?.textContent.includes("vollständig geladen"),null,{timeout:45000});
  await page.locator("#viewC").click();
  await page.waitForFunction(()=>document.getElementById("status")?.textContent.includes("vollständig geladen"),null,{timeout:45000});
  await page.locator("#crossPick").click();
  const map=page.locator("#synopticMap"),rect=await map.boundingBox();
  await map.click({position:{x:rect.width*.36,y:rect.height*.38}});
  await map.click({position:{x:rect.width*.55,y:rect.height*.61}});
  await page.waitForFunction(()=>document.getElementById("crossHint")?.textContent.includes("Realer ECMWF-Modellquerschnitt"),null,{timeout:45000});
  const [download]=await Promise.all([page.waitForEvent("download",{timeout:12000}),page.locator("#save").click()]);
  assert.ok(download.suggestedFilename().endsWith(".png"));
  assert.deepEqual(errors,[],"Unexpected live JS errors");
  console.log(viewport.label,"LIVE Shapiro: map, switching, 7-level cross section, PNG PASS",
      JSON.stringify({size,requests:http.slice(0,20)}));
  await page.screenshot({path:"/tmp/shapiro-live-"+viewport.label+".png",fullPage:true});
  await context.close();
 }
}finally{await browser.close()}
