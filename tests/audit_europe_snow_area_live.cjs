"use strict";
const {chromium}=require("playwright");
const fs=require("node:fs"),path=require("node:path"),assert=require("node:assert/strict");
const OUT=path.resolve("artifacts/ims-europe-area-live");
fs.mkdirSync(OUT,{recursive:true});
const PAGE="https://marcelherber.github.io/climate-dashboard/eurasia_snow.html";
const RAW="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/main/eurasia_snow/europe_index.json";

async function waitForRegion(page,expected){
  await page.waitForFunction(expected=>{
    const source=document.getElementById("seriesRegion");
    const plot=document.getElementById("plot");
    const chart=window.Chart?.getChart?.(plot);
    return source?.value===expected && chart?.data?.datasets?.some(x=>x.label.startsWith("NOAA IMS")) &&
      document.getElementById("message")?.dataset.kind==="success";
  },expected,{timeout:90000});
}
async function testViewport(browser,device,archive){
  const context=await browser.newContext({
    viewport:{width:device.width,height:850},isMobile:device.mobile,
    hasTouch:device.mobile,acceptDownloads:true,deviceScaleFactor:1,
    reducedMotion:"reduce"
  });
  const page=await context.newPage(),errors=[],result={device:device.name};
  page.on("pageerror",e=>errors.push(e.message));
  try{
    const response=await page.goto(PAGE,{waitUntil:"domcontentloaded",timeout:90000});
    assert.equal(response.status(),200,"Published Climate Dashboard page");
    await page.locator("#seriesRegion").waitFor({timeout:90000});
    await waitForRegion(page,"eurasia");
    await page.locator("#seriesRegion").selectOption("europe");
    await waitForRegion(page,"europe");
    const date=archive.observed_latest;
    const [year,month,day]=date.split("-").map(Number);
    await page.locator("#month").selectOption(String(month));
    await page.locator("#calendarYear").selectOption(String(year));
    const expected=archive.daily[date];
    const data=await page.evaluate(day=>{
      const chart=Chart.getChart(document.getElementById("plot"));
      const obs=chart.data.datasets.find(x=>x.label.startsWith("NOAA IMS"));
      return {value:obs?.data[day-1],title:document.getElementById("plotTitle").textContent};
    },day);
    assert.ok(Math.abs(data.value-expected)<.00001,JSON.stringify({data,expected}));
    assert.match(data.title,/Europas/);
    const baseline=archive.climatology_by_month[String(month).padStart(2,"0")][day-1];
    result.area_mkm2=expected;result.reference_mkm2=baseline.mean;
    await page.locator("#showAreaAnomaly").check();
    const anomalous=await page.evaluate(day=>{
      const chart=Chart.getChart(document.getElementById("plot"));
      const obs=chart.data.datasets.find(x=>x.label.startsWith("NOAA IMS"));
      return {value:obs.data[day-1],yMin:chart.options.scales.y.min,
        title:document.getElementById("plotTitle").textContent};
    },day);
    if(baseline.mean!==null){
      assert.ok(Math.abs(anomalous.value-(expected-baseline.mean))<.00002);
      assert.match(anomalous.title,/Anomalie/);
    }else assert.equal(anomalous.value,null);
    const png=page.waitForEvent("download",{timeout:30000});
    if(device.mobile)await page.locator("#png").tap();
    else await page.locator("#png").click();
    const image=await png;
    assert.match(image.suggestedFilename(),/Europa_Island-Ural.*Anomalie\.png$/);
    const file=path.join(OUT,device.name+"-diagram.png");
    await image.saveAs(file);
    assert.equal(fs.readFileSync(file).subarray(0,8).toString("hex"),"89504e470d0a1a0a");
    const csvPromise=page.waitForEvent("download",{timeout:30000});
    if(device.mobile)await page.locator("#csv").tap();
    else await page.locator("#csv").click();
    const csv=await csvPromise;
    assert.match(csv.suggestedFilename(),/Europa_Island-Ural.*\.csv$/);
    const csvPath=path.join(OUT,device.name+"-values.csv");
    await csv.saveAs(csvPath);
    const text=fs.readFileSync(csvPath,"utf8");
    assert.match(text,/anomaly_million_km2/);
    assert.ok(text.includes(date));
    const widths=await page.evaluate(()=>({
      body:document.documentElement.scrollWidth, viewport:window.innerWidth,
      canvas:document.getElementById("plot").getBoundingClientRect().width
    }));
    assert.ok(widths.canvas>0);
    assert.ok(widths.body<=widths.viewport+5,"Horizontal viewport overflow: "+JSON.stringify(widths));
    await page.locator("#seriesRegion").selectOption("eurasia");
    await waitForRegion(page,"eurasia");
    const eurasia=await page.evaluate(day=>{
      const chart=Chart.getChart(document.getElementById("plot"));
      return chart.data.datasets.find(x=>x.label.startsWith("NOAA IMS"))?.data[day-1];
    },day);
    assert.notEqual(eurasia,anomalous.value,"Region switch leaked Europe data");
    await page.screenshot({path:path.join(OUT,device.name+".png"),fullPage:false});
    result.passed=true;result.widths=widths;result.pngBytes=fs.statSync(file).size;
  }catch(e){
    result.passed=false;result.error=String(e).slice(0,1200);
    try{await page.screenshot({path:path.join(OUT,device.name+"-failed.png")})}catch{}
  }
  result.pageErrors=errors.slice(-5);
  await context.close();
  return result;
}
(async()=>{
  const response=await fetch(RAW+"?t="+Date.now());
  assert.equal(response.status,200,"Real European IMS area archive must be published");
  const archive=await response.json();
  assert.equal(archive.source.doi,"10.7265/N52R3PMC");
  assert.deepEqual(archive.analysis.region,
    {lat_south:35,lat_north:75,lon_west:-25,lon_east:70});
  assert.ok(Object.keys(archive.daily).length>300);
  const browser=await chromium.launch({headless:true});
  let results=[];
  try{
    for(const device of [{name:"desktop",width:1440,mobile:false},{name:"mobile",width:390,mobile:true}]){
      results.push(await testViewport(browser,device,archive));
    }
  }finally{await browser.close()}
  fs.writeFileSync(path.join(OUT,"report.json"),JSON.stringify({tested:new Date().toISOString(),
    latest:archive.observed_latest,dayCount:Object.keys(archive.daily).length,results},null,2));
  process.stdout.write(JSON.stringify(results,null,2)+"\n");
  if(results.some(x=>!x.passed))process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1});
