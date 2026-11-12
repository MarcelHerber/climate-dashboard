/* Verify SST UI uses last available date per region, not global archive maximum. */
const fs=require("fs");
const vm=require("vm");
const assert=require("node:assert/strict");
const src=fs.readFileSync("sst_europe.js","utf8");
const nodes={
  sstDataThrough:{textContent:""},
  sstDate:{min:"",max:"",value:""},
  sstStatus:{textContent:"",hidden:false},
};
const document={
  getElementById(id){return nodes[id]||null;},
  addEventListener(){},
};
const window={setTimeout(){},clearTimeout(){}};
const injected='window.__tests={setManifest(doc){sstManifest=doc;},'+
 'setRegion(region){sstState.region=region;},setView(view){sstState.view=view;},'+
 'setDate(date){sstState.date=date;},latest:sstLatestDateForRegion,'+
 'bounds:sstUpdateDateBounds,render:sstRenderMap};})();';
const code=src.replace(/\}\)\(\);\s*$/,injected);
const context={document,window,console,Date,Intl,AbortController,MutationObserver:class{}};
vm.runInNewContext(code,context);
const app=window.__tests;
assert.ok(app);
const example={
  schema_version:1,
  archive_start:"2020-01-01",
  data_through:"2026-11-10",
  available_dates:["2026-10-29","2026-11-09","2026-11-10"],
  regions:{
    europe:{label:"Europa gesamt"},
    pacific:{label:"Pazifik"},
  },
  dates:{
    "2026-10-29":{regions:{europe:{absolute:"e.webp",anomaly:"ea.webp"}}},
    "2026-11-09":{regions:{pacific:{absolute:"p9.webp",anomaly:"p9a.webp"}}},
    "2026-11-10":{regions:{pacific:{absolute:"p10.webp",anomaly:"p10a.webp"}}},
  }
};
app.setManifest(example);
app.setRegion("europe");
app.setView("absolute");
app.setDate("2026-10-29");
assert.equal(app.latest(),"2026-10-29");
app.bounds();
assert.equal(nodes.sstDate.max,"2026-10-29");
app.render();
assert.match(nodes.sstDataThrough.textContent,/Europa gesamt: 2026-10-29/);
assert.doesNotMatch(nodes.sstDataThrough.textContent,/2026-11-10/);

app.setRegion("pacific");
app.setDate("2026-11-10");
assert.equal(app.latest(),"2026-11-10");
app.bounds();
assert.equal(nodes.sstDate.max,"2026-11-10");
app.render();
assert.match(nodes.sstDataThrough.textContent,/Pazifik: 2026-11-10/);
console.log("SST regional dates distinguish MUR and OISST.");
