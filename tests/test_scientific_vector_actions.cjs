"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const js=fs.readFileSync("scientific_vector_actions.js","utf8");
function fixture(id="stratoEpsCanvas",withData=true){
  const elements=[],listeners={},actions=[],downloads=[];
  const wrapper={insertAdjacentElement(where,node){
    assert.equal(where,"afterend");actions.push(node);
  }};
  function node(tag){
    return {
      tagName:tag,children:[],events:{},style:{},textContent:"",className:"",
      setAttribute(name,value){this[name]=value},
      addEventListener(type,handler){this.events[type]=handler},
      appendChild(child){this.children.push(child)},
      querySelector(selector){
        if(selector===".cd-sciv-status")
          return this.children.find(c=>c.className==="cd-sciv-status")||null;
        return null;
      },
      remove(){this.removed=true}
    };
  }
  const canvas={id,closest(){return wrapper},parentElement:wrapper};
  const chart={
    canvas,config:{type:"line"},
    data:{labels:["2026-11-13","2026-11-14"],datasets:[{
      label:"_EPS p01",data:withData?[4,5]:[null,null],borderColor:"#abcdef"
    }]},
    scales:{x:{type:"category",min:0,max:1},y:{min:0,max:10,options:{title:{text:"Zonalwind (m/s)"}}}},
    isDatasetVisible(){return true}
  };
  const plugin=[];
  const fakePdf={save(name){downloads.push({pdf:name})}};
  const window={
    Chart:{register(p){plugin.push(p)},getChart(){return chart},instances:{}},
    jspdf:{jsPDF:class {save(name){fakePdf.save(name)}}},
    T850VectorExport:{
      buildScene(c,opts){downloads.push({scene:opts});return {title:opts.title}},
      saveSvg(scenes,name){downloads.push({svg:name,scenes})},
      drawPdf(pdf,scene){downloads.push({drawn:scene.title})}
    },
    addEventListener(){}
  };
  const document={
    readyState:"loading",
    head:{appendChild(item){elements.push(item)}},
    createElement:node,
    addEventListener(type,handler){listeners[type]=handler},
    getElementById(key){
      if(key==="stationSnowSelectedMeta")return {textContent:"Station 03668 · Nürnberg"};
      return null;
    }
  };
  vm.runInNewContext(js,{window,document,Date,Math,Number,Object,String,Promise,console}, {timeout:2500});
  listeners.DOMContentLoaded();
  return {plugin,chart,window,actions,downloads};
}
test("real stratosphere and DWD station canvases gain two vector download controls",()=>{
 for(const id of ["stratoEpsCanvas","stratoEnsembleCanvas","stationSnowChart"]){
   const h=fixture(id);
   assert.equal(h.plugin.length,1);
   h.plugin[0].afterUpdate(h.chart);
   assert.equal(h.actions.length,1,id);
   const buttons=h.actions[0].children.filter(x=>x.tagName==="button");
   assert.deepEqual(buttons.map(x=>x.textContent),["PDF (Vektor)","SVG (Ebenen)"]);
   h.plugin[0].afterUpdate(h.chart);
   assert.equal(h.actions.length,1,"No duplicated buttons on chart redraw");
 }
});
test("SVG uses current chart datasets, exact axis title and correct source",async()=>{
 const h=fixture("stratoEpsCanvas");
 h.plugin[0].afterUpdate(h.chart);
 const button=h.actions[0].children.find(n=>n.textContent==="SVG (Ebenen)");
 const before=JSON.stringify(h.chart.data);
 await button.events.click();
 assert.equal(JSON.stringify(h.chart.data),before);
 const scene=h.downloads.find(d=>d.scene).scene;
 assert.match(scene.source,/ECMWF IFS ENS Open Data/);
 assert.equal(scene.axis,"Zonalwind (m/s)");
 assert.match(h.downloads.find(d=>d.svg).svg,/^stratosphaere_ECMWF_EPS_60N_10hPa_\d{4}-\d\d-\d\d\.svg$/);
});
test("PDF is generated with scientific scene, not a screenshot",async()=>{
 const h=fixture("stationSnowChart");
 h.plugin[0].afterUpdate(h.chart);
 const pdf=h.actions[0].children.find(n=>n.textContent==="PDF (Vektor)");
 await pdf.events.click();
 const info=h.downloads.find(d=>d.scene).scene;
 assert.match(info.source,/DWD Climate Data Center/);
 assert.match(info.metadata[0],/Nürnberg/);
 assert.ok(h.downloads.some(d=>d.drawn===info.title));
 assert.ok(h.downloads.some(d=>d.pdf?.endsWith(".pdf")));
});
test("missing observations do not create misleading vector buttons",()=>{
 const h=fixture("stratoEpsCanvas",false);
 h.plugin[0].afterUpdate(h.chart);
 assert.equal(h.actions.length,0);
});
test("the published build injects the assets on both pages",()=>{
 const build=fs.readFileSync("scripts/build_pages_site.sh","utf8");
 for(const name of ["index.html","stratosphaere.html","scientific_vector_actions.js"])
   assert.ok(build.includes(name),name+" not staged for Pages");
 assert.match(build,/t850_vector_export\.js\?v=20261113-vector-source-v2/);
 assert.match(build,/node --test tests\/test_scientific_vector_actions\.cjs/);
});
