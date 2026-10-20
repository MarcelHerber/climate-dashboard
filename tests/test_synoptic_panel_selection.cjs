"use strict";
const assert=require("node:assert/strict");
const {test}=require("node:test");
const {chooseAt,best,classify,visible}=require("../synoptic_panel_logic.js");
const t1="2026-10-19T12:00+00:00",t2="2026-10-20T12:00+00:00";
const rec=(id,publisher,time,kind="Analyse")=>({source_id:id,publisher_id:publisher,valid_utc:time,kind});
test("one exact UTC time and four independent agencies",()=>{
 const charts=[rec("noaa_full","noaa",t1),rec("dwd","dwd",t1),rec("knmi","knmi",t1),rec("chmi","chmi",t1),rec("aemet","aemet",t1),rec("noaa_opc","noaa",t2)];
 const picked=chooseAt(charts,t1,"all");
 assert.deepEqual(picked.ids,["dwd","aemet","knmi","chmi"]);
 assert.equal(picked.publishers,4);
 assert.equal(picked.count,4);
});
test("NOAA subproducts are not four independent services",()=>{
 const charts=["noaa_opc","noaa_full","noaa_west","noaa_48"].map(id=>rec(id,"noaa",t1));
 const picked=chooseAt(charts,t1,"all");
 assert.equal(picked.count,4);
 assert.equal(picked.publishers,1);
});
test("forecast/analysis filters never leak across modes",()=>{
 const charts=[rec("dwd","dwd",t1),rec("aemet","aemet",t1,"Prognose"),rec("knmi","knmi",t1,"Prognose"),rec("chmi","chmi",t1)];
 assert.deepEqual(chooseAt(charts,t1,"analysis").ids,["dwd","chmi"]);
 assert.deepEqual(chooseAt(charts,t1,"forecast").ids,["aemet","knmi"]);
});
test("maximize available original images, do not borrow from another UTC slot",()=>{
 const charts=[rec("dwd","dwd",t1),rec("aemet","aemet",t1),
 rec("dwd","dwd",t2),rec("aemet","aemet",t2),rec("knmi","knmi",t2),rec("chmi","chmi",t2)];
 const result=best(charts,[t1,t2],"all",Date.parse(t1));
 assert.equal(result.time,t2);
 assert.equal(result.count,4);
 assert.equal(new Set(result.ids).size,4);
});
test("closer UTC wins when coverage is equal",()=>{
 const charts=[rec("dwd","dwd",t1),rec("aemet","aemet",t1),rec("dwd","dwd",t2),rec("aemet","aemet",t2)];
 assert.equal(best(charts,[t1,t2],"all",Date.parse(t1)).time,t1);
});
test("empty inputs and external/non-chart providers remain empty",()=>{
 assert.deepEqual(chooseAt([],t1,"all").ids,[]);
 assert.equal(best([],[],"all",Date.now()),null);
});

test("front analysis / front forecast / isobar-only categories are exclusive",()=>{
 const analysis=rec("dwd","dwd",t1);
 const forecast=rec("aemet","aemet",t1,"Prognose");
 const model={...rec("imo","imo",t1,"Prognose"),map_type:"isobars_model_forecast_no_fronts"};
 assert.equal(classify(analysis),"analysis_fronts");
 assert.equal(classify(forecast),"forecast_fronts");
 assert.equal(classify(model),"isobars_only");
 assert.equal(classify({...rec("unverified","x",t1,"Prognose")}),"other");
 for(const kind of ["analysis_fronts","forecast_fronts","isobars_only"]){
  assert.equal([analysis,forecast,model].filter(r=>visible(r,kind)).length,1);
 }
});
test("only independent providers never pads slots with NOAA duplicates",()=>{
 const charts=[rec("dwd","dwd",t1),rec("noaa_full","noaa",t1),
   rec("noaa_opc","noaa",t1),rec("noaa_west","noaa",t1)];
 const picked=chooseAt(charts,t1,"all",{uniquePublishers:true});
 assert.deepEqual(picked.ids,["dwd","noaa_opc"]);
 assert.equal(picked.count,2);
 assert.equal(picked.publishers,2);
 assert.equal(chooseAt(charts,t1,"all",{uniquePublishers:false}).count,4);
});
test("forecast fronts and pure pressure forecast cannot be silently mixed",()=>{
 const charts=[rec("aemet","aemet",t1,"Prognose"),
  {...rec("imo","imo",t1,"Prognose"),map_type:"isobars_model_forecast_no_fronts"},
  rec("dwd","dwd",t1)];
 assert.deepEqual(chooseAt(charts,t1,"forecast_fronts").ids,["aemet"]);
 assert.deepEqual(chooseAt(charts,t1,"isobars_only").ids,["imo"]);
 assert.deepEqual(chooseAt(charts,t1,"analysis_fronts").ids,["dwd"]);
});
test("closest fully populated strict four-map time beats NOAA duplicates",()=>{
 const data=[rec("noaa_opc","noaa",t1),rec("noaa_full","noaa",t1),
  rec("noaa_west","noaa",t1),rec("noaa_48","noaa",t1),
  rec("dwd","dwd",t2),rec("knmi","knmi",t2),rec("aemet","aemet",t2)];
 const picked=best(data,[t1,t2],"all",Date.parse(t1),{uniquePublishers:true});
 assert.equal(picked.time,t2);
 assert.equal(picked.publishers,3);
 assert.deepEqual(picked.ids,["dwd","aemet","knmi"]);
});

test("new Pacific original NOAA products share one publisher and preserve map type",()=>{
 const pac=["noaa_pace","noaa_pacw","noaa_pacfull","noaa_pac24","noaa_pac48","noaa_pac96"];
 const input=pac.map((id,i)=>rec(id,"noaa",t1,i>=3?"Prognose":"Analyse"));
 assert.deepEqual([...new Set(input.map(x=>classify(x)))].sort(),["analysis_fronts","forecast_fronts"]);
 const strict=chooseAt(input,t1,"all",{uniquePublishers:true});
 assert.equal(strict.count,1);
 assert.equal(strict.publishers,1);
 assert.equal(chooseAt(input,t1,"analysis_fronts").count,3);
 assert.equal(chooseAt(input,t1,"forecast_fronts").count,3);
 assert.equal(chooseAt(input,t1,"all",{uniquePublishers:false}).count,4);
});
