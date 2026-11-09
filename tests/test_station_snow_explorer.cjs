"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");

const src=fs.readFileSync("station_snow_explorer.js","utf8");
const html=fs.readFileSync("index.html","utf8");
const base=JSON.parse(fs.readFileSync("station_snow_height_index.json","utf8"));
const additionalPath="station_snow_height_additional_index.json";
const extra=fs.existsSync(additionalPath)
  ?JSON.parse(fs.readFileSync(additionalPath,"utf8")):{stations:[]};
const stations=[...base.stations,...(extra.stations||[])];

const context={
  module:{exports:{}},
  window:{},
  globalThis:{}
};
vm.runInNewContext(src,context,{filename:"station_snow_explorer.js"});
const explorer=context.module.exports;

test("fast search ranks exact name, accents and station IDs",()=>{
  const entries=[
    {name:"Nürnberg",id:"03668",accepted_history_years:28},
    {name:"Nürnberg Flughafen",id:"09991",accepted_history_years:39},
    {name:"Zugspitze",id:"05792",accepted_history_years:50},
    {name:"Saarbrücken-Ensheim",id:"04336",accepted_history_years:40}
  ];
  assert.equal(explorer.normalize("NÜRNBERG"),"nurnberg");
  assert.deepEqual(Array.from(explorer.suggestions(entries,"nurnberg")).map(x=>x.id),["03668","09991"]);
  assert.equal(explorer.suggestions(entries,"05792")[0].name,"Zugspitze");
  assert.equal(explorer.suggestions(entries,"ensheim")[0].id,"04336");
  assert.equal(explorer.suggestions(entries,"not_a_station").length,0);
});
test("suggestions are bounded even with 5,000 matching stations",()=>{
  const many=Array.from({length:6000},(_,i)=>({
    name:"Schnee Station "+i,id:String(i).padStart(5,"0"),accepted_history_years:20
  }));
  assert.equal(explorer.suggestions(many,"schnee",15).length,15);
  assert.equal(explorer.suggestions(many,"",15).length,0);
});
test("quality classification needs 30 fully observed hydrological years",()=>{
  assert.equal(explorer.isLong({accepted_history_years:29}),false);
  assert.equal(explorer.isLong({accepted_history_years:30}),true);
  assert.equal(explorer.isLong({accepted_history_years:50}),true);
  assert.equal(explorer.isLong({accepted_history_years:undefined}),false);
});
test("pixel-grid clustering merges same-position stations and omits invalid coords",()=>{
  const entries=[
    {id:"1",lat:50.0,lon:8.0},
    {id:"2",lat:50.01,lon:8.01},
    {id:"3",lat:54,lon:12},
    {id:"bad",lat:null,lon:null},
    {id:"outside",lat:65,lon:25}
  ];
  const result=explorer.clusters(entries,(lat,lon)=>({x:lon*12,y:lat*12}),48);
  assert.equal(result.length,2);
  assert.equal(result.reduce((n,x)=>n+x.count,0),3);
  assert.ok(result.some(group=>group.count===2));
  assert.ok(result.some(group=>group.count===1));
});
test("adjacent grid clusters cannot overlap on touch screens",()=>{
  const points=[
    {id:"a",lat:50,lon:7},
    {id:"b",lat:50,lon:7.1},
    {id:"c",lat:50,lon:7.4},
    {id:"d",lat:50,lon:9}
  ];
  const project=(lat,lon)=>({x:lon*100,y:lat*100});
  const clusters=explorer.clusters(points,project,10);
  for(let i=0;i<clusters.length;i++)for(let j=i+1;j<clusters.length;j++){
    const a=project(clusters[i].lat,clusters[i].lon);
    const b=project(clusters[j].lat,clusters[j].lon);
    assert.ok(Math.hypot(a.x-b.x,a.y-b.y)>=48,"cluster icons overlap");
  }
  assert.equal(clusters.reduce((sum,item)=>sum+item.count,0),points.length);
});
test("source and measurement-quality labels preserve different RR/KL semantics",()=>{
  const d=explorer.detailsFor({id:"00019",name:"Abtsgmünd",
    state:"Baden-Württemberg",height:400,observed_history_years:48,
    accepted_history_years:45,reference_years_available:29,
    source:"DWD-RR · SH_TAG",current_available:true});
  assert.match(d.detail,/48 Jahre mit Tageswerten/);
  assert.match(d.detail,/45 vollständig/);
  assert.match(d.detail,/29\/30 Referenzjahre/);
  assert.match(d.source,/RR · SH_TAG/);
});
test("site contains accessible search, filter, deferred map and selected summary",()=>{
  for(const id of ["stationSnowSuggestions","stationSnowMapDetails","stationSnowMap",
    "stationSnowMapStatus","stationSnowSelectedMeta","stationSnowAvailabilitySelect",
    "stationSnowElevationSelect","stationSnowLongSeriesOnly"]){
    assert.match(html,new RegExp("id=\""+id+"\""),id);
  }
  assert.match(html,/station_snow_explorer\.js/);
  assert.match(html,/station_snow_explorer\.css/);
  assert.match(html,/onSearchInput\(\)/);
  assert.match(html,/stationSnowFileCache\.size>8/);
  assert.match(html,/stationSnowCurrentById/);
  assert.ok(src.includes("map.getZoom()"),"Map should create zoom-dependent clusters");
  assert.ok(src.includes("details.open"),"Map should be collapsible");
  assert.ok(src.includes("onSelect"),"Map and search must select station");
  assert.ok(!src.includes("MarkerClusterGroup"),"No extra cluster CDN dependency");
});
test("typing in station search does not refetch or reset the active chart",()=>{
  const from=html.indexOf('document.getElementById("stationSnowSearch").addEventListener("input"');
  assert.ok(from>0);
  const to=html.indexOf("});",from);
  const event=html.slice(from,to+3);
  assert.ok(!event.includes("updateStationSnow()"),event);
  assert.ok(event.includes("onSearchInput"),event);
});
test("catalogue has unique DWD IDs and consistent coordinate behavior",()=>{
  assert.ok(stations.length>=299);
  assert.equal(new Set(stations.map(s=>s.id)).size,stations.length);
  assert.ok(stations.some(x=>explorer.validCoordinate(x)),"No geolocatable stations");
  const allLong=stations.filter(explorer.isLong);
  assert.ok(allLong.length>=267);
});
