import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {chromium} from "playwright";

const src=readFileSync(new URL("../mosmix.js",import.meta.url),"utf8");
const a=src.indexOf("  function addCss() {");
const b=src.indexOf("  function addNavigation() {",a);
assert.ok(a>0 && b>a);
const helpers=src.slice(a,b);
const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
try{
 for(const vp of [{name:"desktop",width:1440,height:900},{name:"handy",width:390,height:844}]){
  const context=await browser.newContext({viewport:vp});
  const page=await context.newPage(),errors=[];
  page.on("pageerror",e=>errors.push(e.message));
  await page.setContent('<!doctype html><html lang="de"><head><meta charset="utf-8">'+
   '<meta name="viewport" content="width=device-width,initial-scale=1"><style>'+
   '*{box-sizing:border-box}body{margin:0;background:#eef3f7;color:#172033;font:15px system-ui}'+
   'main{max-width:1500px;margin:auto;padding:14px}.tab-content{display:block}'+
   '</style></head><body><main id="main"></main></body></html>');
  await page.evaluate(code=>{
    const call=new Function(code+"\nreturn {addCss,sectionHtml};")();
    call.addCss();
    document.getElementById("main").innerHTML=call.sectionHtml();
  },helpers);
  const info=await page.evaluate(()=>{
   const cards=[...document.querySelectorAll(".mosmix-chart-card")];
   const actions=[...document.querySelectorAll("[data-mosmix-export-chart]")];
   return {
    client:document.documentElement.clientWidth,
    scroll:document.documentElement.scrollWidth,
    cards:cards.length,actions:actions.length,
    actionWidths:actions.map(a=>Math.round(a.getBoundingClientRect().width)),
    outside:actions.filter(el=>{
      const r=el.getBoundingClientRect();return r.left<0||r.right>innerWidth+1;
    }).length
   };
  });
  assert.equal(info.cards,6);
  assert.equal(info.actions,12);
  assert.ok(info.actionWidths.every(n=>n>=40));
  assert.equal(info.outside,0,"Single download buttons clipped");
  assert.ok(info.scroll<=info.client+2,vp.name+" scroll overflow "+JSON.stringify(info));
  assert.deepEqual(errors,[]);
  await page.screenshot({path:"/tmp/mosmix-single-export-"+vp.name+".png",fullPage:true});
  console.log("MOSMIX single export layout",vp.name,"PASS",JSON.stringify(info));
  await context.close();
 }
}finally{await browser.close()}
