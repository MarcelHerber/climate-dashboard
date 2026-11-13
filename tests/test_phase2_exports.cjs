"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");

const read=path=>fs.readFileSync(path,"utf8");
const monthly=read("monthly_frequency.js");
const ensemble=read("t850_ensembles.js");
const mosmix=read("mosmix.js");
const vectors=read("mosmix_vector_export.js");
const css=read("mobile_content.css");
const builder=read("scripts/build_pages_site.sh");
const mobileBuild=read("scripts/inject_mobile_navigation.py");

test("temperature, sunshine and precipitation frequency PNG/PDF share HQ export",()=>{
 const start=monthly.indexOf("async function monthlyFrequencyExportCanvas()");
 const end=monthly.indexOf("function triggerDownload",start);
 const block=monthly.slice(start,end);
 assert.ok(start>0 && end>start);
 assert.match(block,/window\.DashboardExportHQ/);
 assert.match(block,/hq\.composeCanvas\(captured/);
 assert.match(block,/config\.unit/);
 assert.match(block,/Quelle: DWD/);
 for(const kind of ["Png","Pdf"]){
  const pos=monthly.indexOf("async function downloadMonthlyFrequency"+kind+"()");
  assert.ok(pos>start,kind+" missing");
  assert.match(monthly.slice(pos,pos+210),/monthlyFrequencyExportCanvas\(\)/);
 }
 assert.doesNotMatch(block,/\.data\.datasets\s*=/);
});

test("ensemble PNG/PDF use the identical metadata-bearing screenshot",()=>{
 const start=ensemble.indexOf("function exportMetadata()");
 const end=ensemble.indexOf("function wrapExportLine",start);
 const meta=ensemble.slice(start,end);
 for(const term of ["UTC (Z)","Quelle: Open-Meteo Ensemble API","Erstellt: ","Climate Dashboard Deutschland"]){
  assert.ok(meta.includes(term),term);
 }
 const first=ensemble.indexOf("function withExportHeader(source)");
 const second=ensemble.indexOf("async function exportCanvas()",first);
 assert.ok(first>0 && second>first);
 assert.match(ensemble.slice(second,second+500),/withExportHeader\(captured\)/);
 assert.match(ensemble,/async function png\(\).*?exportCanvas\(\)/s);
 assert.match(ensemble,/async function pdf\(\).*?exportCanvas\(\)/s);
});

test("MOSMIX PNG/SVG/PDF preserve vector layers and the same UTC and provenance",()=>{
 const scene=vectors.slice(vectors.indexOf("const footer=["),vectors.indexOf("function svgEl("));
 assert.match(scene,/Rohzeiten UTC \(Z\)/);
 assert.match(scene,/MEZ\/MESZ/);
 assert.match(scene,/Erstellt:/);
 assert.match(scene,/Deutscher Wetterdienst/);
 assert.match(vectors,/inkscape:groupmode="layer"/);
 const pdf=mosmix.slice(mosmix.indexOf("function exportCombinedPdf()"),mosmix.indexOf("function singleMeteogramFilename"));
 assert.doesNotMatch(pdf,/\.addImage\(/);
 const one=mosmix.slice(mosmix.indexOf("function exportSinglePng("),mosmix.indexOf("function exportSinglePdf("));
 const all=mosmix.slice(mosmix.indexOf("function exportCombinedPng()"),mosmix.indexOf("function vectorMeteogramEntries"));
 for(const segment of [all,one]){
  assert.match(segment,/Erstellt:/);
  assert.match(segment,/UTC \(Z\)/);
 }
});

test("responsive scientific modules keep download controls within mobile viewport",()=>{
 for(const cls of [".mosmix-chart-export-actions",".monthly-frequency-export-bar",
    ".t850-export",".hyras-map-actions",".era5-atmos-layout"]){
  assert.ok(css.includes(cls),cls);
 }
 assert.match(css,/@media\(max-width:430px\)/);
 assert.match(css,/grid-template-columns:repeat\(3,minmax\(0,1fr\)\)/);
 assert.match(css,/grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
 assert.match(css,/overflow-x:auto/);
 assert.ok(!css.includes("Phase 2: change observed meteorological values"));
});

test("Pages includes cache-busted presentation assets and all mobile pages",()=>{
 assert.match(builder,/for filename in \("monthly_frequency\.js","t850_ensembles\.js"\)/);
 assert.match(builder,/filename\+"\?v=20261113-phase2-exports-v1"/);
 assert.match(builder,/mosmix\.js\?v=20261113-phase2-exports-v1/);
 assert.match(builder,/test_mosmix_vector_exports\.mjs/);
 assert.match(mobileBuild,/CONTENT_VERSION="20261113-phase2-responsive-v2"/);
});
