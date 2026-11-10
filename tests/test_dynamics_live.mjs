import assert from "node:assert/strict";
import {chromium} from "playwright";

const base="https://climate-dashboard-alpenwetter.marcel-herber.workers.dev";
const password=process.env.ALPENWETTER_PASSWORD;
assert.ok(password,"ALPENWETTER_PASSWORD GitHub Action secret missing");

const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
try {
  const page=await browser.newPage({viewport:{width:1366,height:850}});
  const consoleErrors=[],requests=[],fails=[];
  page.on("console",msg=>{if(msg.type()==="error")consoleErrors.push(msg.text().slice(0,500));});
  page.on("pageerror",error=>consoleErrors.push("JS: "+error.message.slice(0,700)));
  page.on("requestfailed",request=>fails.push(request.url().replace(base,"") + " " + request.failure()?.errorText));
  page.on("response",response=>{
    if(response.url().includes("/dynamik/api/"))
      requests.push({path:response.url().replace(base,""),status:response.status(),type:response.headers()["content-type"]});
  });
  const login=await page.goto(base+"/dynamik",{waitUntil:"domcontentloaded",timeout:30000});
  assert.equal(login.status(),200);
  console.log("Pre-auth URL",page.url(),"CSP",login.headers()["content-security-policy"]);
  const apiPre=await page.request.get(base+"/dynamik/api/data/current.json");
  console.log("Unauthenticated API",apiPre.status());
  assert.equal(apiPre.status(),401);
  await page.locator('input[name="password"]').fill(password);
  await Promise.all([
    page.waitForURL(/\/dynamik\/?$/, {timeout:30000}),
    page.locator('button[type="submit"]').click()
  ]).catch(async err=>{console.log("Login redirect",page.url(),err.message.slice(0,250));});
  // The login returns to the same URL. Give the browser a chance to initialize its UI.
  await page.waitForTimeout(3000);
  const initial=await page.evaluate(()=>({
    title:document.title,
    path:location.pathname,
    status:document.getElementById("status")?.innerText,
    run:document.getElementById("run")?.innerText,
    htmlScriptCount:document.querySelectorAll("script").length,
    scriptLength:document.querySelector("script")?.textContent.length,
    playDisabled:document.querySelector("#play")?.disabled,
    mapWidth:document.querySelector("#map")?.width,
    canvasCenter:(()=>{
      const c=document.querySelector("#map");
      if(!c)return null;
      try{return Array.from(c.getContext("2d").getImageData(Math.floor(c.width/2),Math.floor(c.height/2),1,1).data)}
      catch(e){return e.message}
    })()
  }));
  console.log("Page state",JSON.stringify(initial));
  console.log("HTTP model responses",JSON.stringify(requests.slice(0,12)));
  console.log("Browser console errors",JSON.stringify(consoleErrors.slice(0,12)));
  console.log("Failed network calls",JSON.stringify(fails.slice(0,8)));
  await page.screenshot({path:"/tmp/dynamics-live-before.png",fullPage:true});
  // A valid page starts the loading process even if upstream forecast data are absent.
  assert.ok(initial.status && !initial.status.includes("Suche nach vollständigen ECMWF"),
    "Inline initialization did not run; errors: "+JSON.stringify(consoleErrors));
  assert.ok(initial.run && initial.run.includes("ECMWF"),"Model header missing");
  await page.waitForFunction(()=>
    /vollständig geladen|Darstellung nicht möglich|Kein bestätigter|Noch kein vollständiger/.test(
      document.querySelector("#status")?.textContent||""),
      {timeout:30000}
  ).catch(()=>{});
  const finalStatus=await page.locator("#status").innerText();
  console.log("Post-load status",finalStatus);
  console.log("All error messages",JSON.stringify(consoleErrors.slice(0,20)));
  console.log("All data HTTP",JSON.stringify(requests.slice(0,20)));
  await page.screenshot({path:"/tmp/dynamics-live-after.png",fullPage:true});
  assert.match(finalStatus,/vollständig geladen/,"Forecast data not available to authenticated browser");
}finally{await browser.close()}
