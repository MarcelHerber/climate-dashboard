"use strict";
const test=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const raw=globalThis.ENSEMBLE_SOURCE||fs.readFileSync("t850_ensembles.js","utf8");
const src=raw.slice(raw.indexOf("const ENSEMBLE_API"),raw.indexOf("window.mountT850Ensembles=mount;"));
const harness=new Function("document",src+"\nreturn {PARAMS,ensembleFields:typeof ensembleFields==='function'?ensembleFields:null,parseMemberFields:typeof parseMemberFields==='function'?parseMemberFields:null,classicMemberColor:typeof classicMemberColor==='function'?classicMemberColor:null,classicDataset:typeof classicDataset==='function'?classicDataset:null,options,stats};")({getElementById:()=>null});
test("combined variable query uses the original temperature and precipitation fields",()=>{
 assert.ok(harness.PARAMS.t2mPrecip);
 assert.equal(harness.ensembleFields(harness.PARAMS.t2mPrecip),"temperature_2m,precipitation");
 assert.equal(harness.ensembleFields(harness.PARAMS.t850),"temperature_850hPa");
});
test("member IDs, missing values and true six-hour amounts are preserved",()=>{
 assert.ok(harness.parseMemberFields);
 const time=Array.from({length:13},(_,i)=>"2026-11-18T"+String(i).padStart(2,"0")+":00");
 const h={time,temperature_2m:Array(13).fill(-4),temperature_2m_member10:Array(13).fill(-3),temperature_2m_member2:Array(13).fill(-5),precipitation:Array(13).fill(0),precipitation_member02:Array(13).fill(1),precipitation_member10:Array(13).fill(2)};
 const a=harness.parseMemberFields(h,time,harness.PARAMS.t2mPrecip,120);
 assert.deepEqual(a.memberIds,[2,10]);
 assert.deepEqual(a.rain.memberIds,[2,10]);
 assert.deepEqual(a.rain.members[0],[null,6,6]);
 assert.deepEqual(a.rain.members[1],[null,12,12]);
 assert.deepEqual(a.members[0],[-5,-5,-5]);
 assert.equal(a.rain.control[1],0);
});
test("classic style keeps member identities and thin straight colored paths",()=>{
 assert.ok(harness.classicMemberColor);
 assert.notEqual(harness.classicMemberColor(1),harness.classicMemberColor(2));
 const a=harness.classicDataset(2,[-1,2],false);
 const b=harness.classicDataset(2,[0,5],true);
 assert.equal(a.borderColor,b.borderColor);
 assert.equal(a.tension,0);
 assert.equal(a.yAxisID,"y");
 assert.equal(b.yAxisID,"yRain");
 assert.equal(a._memberId,2);
 assert.equal(b._memberId,2);
});
test("combined chart renders independent Celsius and millimetre axes",()=>{
 assert.ok(harness.PARAMS.t2mPrecip);
 const options=harness.options({min:-15,max:4},harness.PARAMS.t2mPrecip,{min:0,max:20},true);
 assert.equal(options.scales.y.min,-15);
 assert.equal(options.scales.y.max,4);
 assert.equal(options.scales.yRain.min,0);
 assert.equal(options.scales.yRain.max,20);
 assert.equal(options.scales.yRain.position,"right");
 assert.match(options.scales.yRain.title.text,/mm/);
 assert.equal(options.scales.x.grid.display,true);
});
test("vector view maps values against the correct independent scale",()=>{
 const window={};vm.runInNewContext(globalThis.VECTOR_SOURCE||fs.readFileSync("t850_vector_export.js","utf8"),{window,console,Math,Number,Object,Array,String,Error});
 const exporter=window.T850VectorExport;
 const chart={data:{labels:["00","06","12"],datasets:[{label:"Temperatur",data:[-10,0,10],borderColor:"#ffffff",yAxisID:"y"},{label:"Regen",data:[0,50,100],borderColor:"#00dd44",yAxisID:"yRain"}]},scales:{x:{min:0,max:2},y:{min:-10,max:10},yRain:{min:0,max:100}}};
 const scene=exporter.buildScene(chart,{title:"Kombiniert",axis:"°C",rightAxis:"Niederschlag [mm]",classic:true});
 assert.equal(scene.series.length,2);
 assert.deepEqual(Array.from(scene.series[0].points[0],p=>p[1]),Array.from(scene.series[1].points[0],p=>p[1]));
 assert.equal(scene.rightTicks.at(-1).v,100);
 assert.equal(scene.classic,true);
 const svg=exporter.toSvg([scene]);
 assert.match(svg,/Niederschlag \[mm\]/);
 assert.match(svg,/fill="#000000"/);
});

test("switching classic preserves ensemble values and independent rain axes",()=>{
 const select={value:"classic"},paramSelect={value:"t2mPrecip"},canvas={getContext:()=>({})};
 const configs=[];
 class Chart {constructor(ctx,config){configs.push(config);}destroy(){}}
 const doc={getElementById:id=>({t850StyleSelect:select,t850ParamSelect:paramSelect,fakeCanvas:canvas,t850ComparisonChart:canvas})[id]||null};
 const h=new Function("document","Chart",src+"\nreturn {PARAMS,modelChart,comparisonChart};")(doc,Chart);
 const times=["2026-11-18T00:00","2026-11-18T06:00","2026-11-18T12:00"];
 const member=[-5,-4,-2],rain=[null,2,4];
 const r={model:{key:"test",label:"Test",canvas:"fakeCanvas",color:"#123456"},times,members:[member],memberIds:[2],allMembers:[member],control:member,stats:{mean:member,p10:member,p90:member,p25:member,p75:member},rain:{members:[rain],memberIds:[2],allMembers:[rain],control:rain,stats:{mean:rain}},mainAligned:member,mainRainAligned:rain,main:{run:times[0]}};
 h.modelChart(r,{min:-10,max:5},h.PARAMS.t2mPrecip);
 const classic=configs[0],p=classic.data.datasets.filter(d=>d._memberId===2);
 assert.equal(p.length,2);
 assert.equal(p[0].borderColor,p[1].borderColor);
 assert.deepEqual(p[0].data,member);assert.deepEqual(p[1].data,rain);
 assert.equal(classic.plugins[0].id,"ensembleClassicBackground");
 assert.equal(classic.data.datasets.find(d=>d.label==="Ensemble-Mittel").borderColor,"#ffffff");
 select.value="modern";h.modelChart(r,{min:-10,max:5},h.PARAMS.t2mPrecip);
 assert.ok(configs[1].data.datasets.some(d=>d.label==="10.–90. Perzentil"));
 assert.equal(configs[1].plugins.length,0);
 assert.equal(configs[1].options.scales.yRain.position,"right");
 h.comparisonChart([r],{min:-10,max:5},0,0,null,h.PARAMS.t2mPrecip);
 assert.deepEqual(configs[2].data.datasets.find(d=>d.yAxisID==="yRain").data,rain);
});
