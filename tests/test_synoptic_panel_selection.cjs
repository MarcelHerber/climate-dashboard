"use strict";
const assert=require("node:assert/strict");
const {test}=require("node:test");
const {chooseAt,best}=require("../synoptic_panel_logic.js");
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
