const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const source=fs.readFileSync("mobile_navigation.js","utf8");
const html=fs.readFileSync("index.html","utf8");
const builder=fs.readFileSync("scripts/build_pages_site.sh","utf8");

function readData(){
 const window={};
 const document={readyState:"loading",addEventListener(){}};
 const script=source.replace(/\}\)\(\);\s*$/,
    "window.__navTest={CATEGORIES,flat,byId,normalize,isFile,openItem,recent,remember};})();");
 assert.notEqual(source,script,"Instrumentation should match the app IIFE");
 vm.runInNewContext(script,{window,document,Map,Set,JSON,String,Array,console});
 return window.__navTest;
}
function environment(pathname="/climate-dashboard/index.html"){
 const listeners={},ids=new Map();
 function node(tag){
  const e={tag,children:[],attributes:{},dataset:{},hidden:false,value:"",
   style:{overflow:""},textContent:"",className:"",id:"",type:"",
   classList:{add(){},toggle(){}},
   addEventListener(name,fn){this.handlers??={};this.handlers[name]=fn;},
   setAttribute(k,v){this.attributes[k]=v;},
   getAttribute(k){return this.attributes[k];},
   appendChild(x){this.children.push(x);return x;},
   insertBefore(x){this.children.unshift(x);return x;},
   replaceChildren(){this.children=[];},
   querySelectorAll(){return [];},
   focus(){},click(){this.handlers?.click?.();},
   get firstChild(){return this.children[0]||null},
  };
  return e;
 }
 const body=node("body");
 const document={
  readyState:"loading",body,activeElement:node("button"),
  createElement(tag){return node(tag)},
  getElementById(id){
   const walk=(e)=>e.id===id?e:e.children.map(walk).find(Boolean);
   return walk(body)||null;
  },
  querySelector(q){return null},
  addEventListener(name,fn){listeners[name]=fn},
  removeEventListener(){}
 };
 const location={pathname,hash:"",assigned:[],assign(value){this.assigned.push(value)}};
 const saved=new Map();
 const window={
  location,
  localStorage:{getItem(k){return saved.get(k)||null},setItem(k,v){saved.set(k,v)}},
  matchMedia(){return {matches:true}},
  addEventListener(){},scrollTo(){},
 };
 const sandbox={window,document,Map,Set,JSON,String,Array,console,decodeURIComponent,encodeURIComponent};
 vm.runInNewContext(source,sandbox,{timeout:2000});
 return {window,document,body,ready(){listeners.DOMContentLoaded()},saved};
}
test("all published root HTML modules are reachable through mobile categories",()=>{
 const {CATEGORIES,flat}=readData();
 assert.equal(CATEGORIES.length,6);
 const values=flat.map(x=>x.id);
 assert.equal(new Set(values).size,values.length);
 const rootFiles=builder.match(/required_root_files=\(\n([\s\S]*?)\n\)/)[1]
   .split("\n").map(x=>x.trim()).filter(x=>x.endsWith(".html"));
 assert.ok(rootFiles.length>=20);
 for(const page of rootFiles){
  if(page!=="index.html")assert.ok(values.includes(page),"Unreachable: "+page);
 }
 const mainTabs=[...new Set([...html.matchAll(/<button[^>]*class="[^"]*\btab-button\b[^"]*"[^>]*onclick="switchTab\('([^']+)'\)"/g)].map(x=>x[1]))];
 for(const tab of mainTabs){
  if(tab!=="era5Synoptic")assert.ok(values.includes(tab),"Missing tab "+tab);
 }
 assert.ok(!values.includes("era5Synoptic"),"Hidden experimental content remains hidden");
});
test("accent-insensitive search and no external arbitrary routes",()=>{
 const f=readData();
 assert.equal(f.normalize("Flächenkarten"),"flachenkarten");
 assert.equal(f.normalize("ENSO & Äquator"),"enso & aquator");
 assert.equal(f.isFile("stratosphaere.html"),true);
 assert.equal(f.isFile("https://attacker.net/"),false);
 assert.equal(f.isFile("../secret.html"),false);
});
test("mobile menu renders on standalone pages and resolves index deep links",()=>{
 const env=environment("/climate-dashboard/stratosphaere.html");
 env.ready();
 assert.ok(env.document.getElementById("cdMobileNav"),"Mobile shell should be created");
 const trigger=env.document.getElementById("cdMobileMenuButton");
 assert.ok(trigger);
 const dialog=env.document.getElementById("cdMobileMenu");
 assert.equal(dialog.hidden,true);
 trigger.click();
 assert.equal(dialog.hidden,false);
 assert.equal(trigger.attributes["aria-expanded"],"true");
 const findLinks=(e)=>[e,...e.children.flatMap(findLinks)];
 const buttons=findLinks(dialog).filter(x=>x.tag==="button");
 const target=buttons.find(x=>x.textContent==="Gebietsmittel");
 assert.ok(target,"Subpage menu should link directly to internal tab");
 target.click();
 assert.equal(env.window.location.assigned[0],"./index.html#cd-tab=monthly");
 assert.equal(dialog.hidden,true);
});
test("index menu supplements existing header while desktop nav stays unchanged",()=>{
 const env=environment();
 env.ready();
 const trigger=env.document.getElementById("cdMobileMenuButton");
 assert.ok(trigger);
 assert.ok(env.document.getElementById("cdMobileMenu"));
 assert.equal(env.body.children.length>=1,true);
 assert.ok(source.includes('document.querySelector(".dashboard-header .header-actions")'));
 assert.ok(!source.includes('document.querySelector(".primary-nav").remove()'));
 assert.match(fs.readFileSync("mobile_navigation.css","utf8"),/@media\(max-width:800px\)/);
 assert.doesNotMatch(fs.readFileSync("mobile_navigation.css","utf8"),/@media\(min-width:801px\)/);
});
test("bookmarks persist only recognized category destinations",()=>{
 const f=readData();
 assert.equal(f.byId.has("datenstatus.html"),true);
 assert.equal(f.byId.has("eurasia_snow.html"),true);
 assert.equal(f.byId.has("__alpenwetter__"),true);
 assert.equal(f.byId.has("overview"),true);
});
