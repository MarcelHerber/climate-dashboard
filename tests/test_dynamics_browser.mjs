import assert from "node:assert/strict";
import {chromium} from "playwright";
import {dynamicsLabPage} from "../alpenwetter-worker/src/dynamics-lab.js";

const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
const keys=["tcwv","jet","ascent","pv","iru","irv"];
const grid={west:-70,east:45,south:12,north:75,width:461,height:253,step:.25};
const encoding={minmax:{tcwv:[0,70],jet:[0,110],ascent:[0,1.5],pv:[-2,15],iru:[-45,45],irv:[-45,45]}};
const frames=[0,3].map(hour=>({
  hour,valid_utc:new Date(Date.UTC(2026,10,10,hour)).toISOString(),
  images:Object.fromEntries(keys.map(k=>[k,"frames/2026111000/"+k+"_"+String(hour).padStart(3,"0")+".png"]))
}));
const manifest={schema:1,cycle:"2026111000",initialized_utc:"2026-11-10T00:00:00Z",grid,encoding,frames};
try {
  for (const device of [{name:"desktop",width:1366,height:850},{name:"mobil",width:390,height:844}]) {
    const context=await browser.newContext({viewport:{width:device.width,height:device.height},acceptDownloads:true});
    const page=await context.newPage();
    const errors=[];
    page.on("pageerror",e=>errors.push(e.message));
    const base64=await page.evaluate(()=>{
      const c=document.createElement("canvas");
      c.width=461;c.height=253;
      const x=c.getContext("2d"),d=x.createImageData(c.width,c.height);
      for(let y=0;y<c.height;y++)for(let j=0;j<c.width;j++){
        const p=(y*c.width+j)*4,v=Math.round(50+160*j/c.width);
        d.data[p]=v;d.data[p+1]=v;d.data[p+2]=v;d.data[p+3]=255;
      }
      x.putImageData(d,0,0);
      return c.toDataURL("image/png").split(",")[1];
    });
    const png=Buffer.from(base64,"base64");
    await page.route("https://studio.example/dynamik",route=>route.fulfill({
      status:200,contentType:"text/html; charset=utf-8",body:dynamicsLabPage()
    }));
    await page.route("https://studio.example/dynamik/api/data/current.json",route=>route.fulfill({
      status:200,contentType:"application/json",body:JSON.stringify(manifest)
    }));
    await page.route("https://studio.example/dynamik/api/boundaries",route=>route.fulfill({
      status:200,contentType:"application/json",body:'{"type":"FeatureCollection","features":[]}'
    }));
    await page.route(/https:\/\/studio\.example\/dynamik\/api\/data\/frames\/.*/,route=>route.fulfill({
      status:200,contentType:"image/png",body:png
    }));
    await page.goto("https://studio.example/dynamik",{waitUntil:"domcontentloaded"});
    await page.waitForFunction(()=>document.querySelector("#status")?.textContent.includes("vollständig geladen"),{timeout:20000});
    const metrics=await page.evaluate(()=>({
      windowWidth:window.innerWidth,scrollWidth:document.documentElement.scrollWidth,
      canvasWidth:document.querySelector("#map").getBoundingClientRect().width,
      allLayers:["tcwv","jet","ascent","pv","irrot"].every(id=>document.getElementById(id)?.checked)
    }));
    assert.ok(metrics.canvasWidth>=250,"Map too small");
    assert.ok(metrics.scrollWidth<=metrics.windowWidth+2,
      device.name+" horizontal overflow: "+JSON.stringify(metrics));
    assert.equal(metrics.allLayers,true);
    await page.locator("#region").selectOption("suedwest");
    await page.locator("#pv").uncheck();
    await page.locator("#irrot").uncheck();
    await page.locator("#timeline").evaluate(element=>{
      element.value="1";
      element.dispatchEvent(new Event("input",{bubbles:true}));
    });
    await page.waitForFunction(()=>document.querySelector("#valid")?.textContent.includes("+3 h"),{timeout:10000});
    await page.screenshot({path:"/tmp/dynamics-"+device.name+".png",fullPage:true});
    const [download]=await Promise.all([
      page.waitForEvent("download",{timeout:10000}),
      page.locator("#save").click()
    ]);
    assert.ok(download.suggestedFilename().endsWith(".png"));
    assert.deepEqual(errors,[],"Browser exceptions: "+errors.join("; "));
    console.log(device.name,"viewport OK; interactions and real canvas export OK",metrics);
    await context.close();
  }
} finally {await browser.close()}
