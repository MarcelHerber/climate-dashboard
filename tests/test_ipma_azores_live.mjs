import assert from "node:assert/strict";
import {chromium} from "playwright";
const root="https://climate-dashboard-alpenwetter.marcel-herber.workers.dev";
const password=process.env.ALPENWETTER_PASSWORD;
assert.ok(password,"Missing protected Cloudflare lab password");
const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
try{
 for(const v of [{width:1370,height:900,name:"desktop"},{width:390,height:844,name:"mobile"}]){
  const context=await browser.newContext({viewport:v,acceptDownloads:true});
  const page=await context.newPage(),errors=[],network=[];
  page.on("pageerror",e=>errors.push(e.message));
  page.on("response",r=>{if(r.url().includes("/radarlabor/api/"))
      network.push({path:r.url().split("/radarlabor/api/")[1],status:r.status()});
  });
  let login;
  for(let attempt=0;attempt<18;attempt++){
    login=await page.goto(root+"/radarlabor/azoren",{waitUntil:"domcontentloaded",timeout:35000});
    if(login.status()===200&&await page.locator('input[name="next"][value="/radarlabor/azoren"]').count())break;
    await page.waitForTimeout(5000);
  }
  assert.equal(login.status(),200);
  assert.equal(await page.locator('input[name="next"][value="/radarlabor/azoren"]').count(),1);
  const denied=await page.request.get(root+"/radarlabor/api/azoren/current.json");
  assert.equal(denied.status(),401);
  await page.locator('input[type="password"]').fill(password);
  await Promise.all([
    page.waitForURL(/\/radarlabor\/azoren\/?$/, {timeout:30000}),
    page.locator('button[type="submit"]').click()
  ]);
  try{
    await page.waitForFunction(()=>document.getElementById("status")?.textContent.includes("Original-IPMA-Radardaten"),
      null,{timeout:70000});
  }catch(e){
    console.log("LIVE STATUS",await page.locator("#status").textContent().catch(()=>null));
    console.log("LIVE HTTP",JSON.stringify(network.slice(0,18)));
    console.log("LIVE JS",JSON.stringify(errors.slice(0,8)));
    throw e;
  }
  await page.waitForFunction(()=>document.getElementById("legend")?.naturalWidth>0,null,{timeout:30000});
  const stats=await page.evaluate(()=>({
    width:document.documentElement.clientWidth,
    scroll:document.documentElement.scrollWidth,
    canvasWidth:document.getElementById("radar").getBoundingClientRect().width,
    pixel:Array.from(document.getElementById("radar").getContext("2d").getImageData(700,300,1,1).data),
    status:document.getElementById("status").textContent,
    stamp:document.getElementById("stamp").textContent
  }));
  assert.ok(stats.scroll<=stats.width+2,"Horizontal overflow "+JSON.stringify(stats));
  assert.ok(stats.canvasWidth>=250);assert.equal(stats.pixel[3],255);
  for(const name of ["current.json","legend.png"]){
    assert.ok(network.some(x=>x.path==="azoren/"+name&&x.status===200),"Missing IPMA "+name);
  }
  assert.ok(network.some(x=>x.path.startsWith("azoren/frames/")&&x.status===200),"Missing official IPMA radar PNG");
  assert.ok(network.some(x=>x.path==="borders_europe.geojson"&&x.status===200),"Natural Earth borders absent");
  for(const r of ["west","center","east","all"])await page.locator("#region").selectOption(r);
  await page.locator("#prev").click();await page.locator("#next").click();
  const [download]=await Promise.all([page.waitForEvent("download",{timeout:18000}),page.locator("#png").click()]);
  assert.ok(download.suggestedFilename().endsWith(".png"));
  assert.deepEqual(errors,[],"Live browser errors: "+JSON.stringify(errors));
  await page.screenshot({path:"/tmp/ipma-azores-live-"+v.name+".png",fullPage:true});
  console.log("IPMA AZORES LIVE PASS",v.name,JSON.stringify(stats),JSON.stringify(network.slice(0,10)));
  await context.close();
 }
}finally{await browser.close()}
