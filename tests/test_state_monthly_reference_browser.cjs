#!/usr/bin/env node
"use strict";
// Real Chromium controls with the actual panel and frontend. Only forecast
// fetch / chart rendering is stubbed; the historical HYRAS file is real.
const { chromium } = require("playwright");
const fs = require("node:fs");
const { execFileSync } = require("node:child_process");
const assert = require("node:assert/strict");
const path = require("node:path");
const root = path.join(__dirname, "..");
const climate = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const panel = execFileSync("python", ["-c", "from scripts.patch_state_monthly_ensemble_frontend import PANEL; print(PANEL)"], {cwd:root, encoding:"utf8"});
const js = fs.readFileSync(path.join(root,"state_monthly_ensemble.js"),"utf8");
const css = fs.readFileSync(path.join(root,"state_monthly_ensemble.css"),"utf8");
const dates = Array.from({length:30},(_,i)=>"2026-11-"+String(i+1).padStart(2,"0"));
const observation = dates.map((_,i)=>i<15?9:null);
const forecast = dates.map((_,i)=>i>=15?8:null);
const stats = Object.fromEntries(["min","p05","p20","mean","p80","p95","max"].map(k=>[k,forecast]));
const region = {observed_through:dates[14],observed_running:observation,observed_current:9,climatology_running:dates.map(()=>6),climatology_month_mean:6,climatology_to_date:6,observed_anomaly_to_date:3,models:{gefs:{stats,control:forecast,member_count:31,forecast_through:dates.at(-1),support_points:2}}};
const doc = {schema_version:1,year:2026,month:11,generated_at:"2026-11-16T06:00:00Z",observation_data_through:dates[14],dates,regions_order:Object.keys(climate.regions),regions:Object.fromEntries(Object.keys(climate.regions).map(k=>[k,region]))};
(async()=>{
  const browser = await chromium.launch({executablePath:process.env.CHROMIUM_PATH||undefined,args:["--no-sandbox"]});
  try{
    for(const width of [1280,390]){
      const page = await browser.newPage({viewport:{width,height:900}});
      await page.route("**/*",route=>{
        const u=route.request().url();
        if(u.includes("state_monthly_ensemble.json"))return route.fulfill({json:doc,headers:{"access-control-allow-origin":"*"}});
        if(u.includes("climate_1961_1990.json"))return route.fulfill({json:climate,headers:{"access-control-allow-origin":"*"}});
        return route.abort();
      });
      await page.setContent('<meta name="viewport" content="width=device-width,initial-scale=1"><style>'+css+' .control-group{display:flex;flex-direction:column}select{max-width:100%;box-sizing:border-box}</style>'+panel.replace('class="tab-content"','class="tab-content active"'));
      await page.evaluate(()=>{window.rendered={}; window.Chart=class {
        constructor(canvas,config){window.rendered[canvas.id]=config;}
        destroy(){} resize(){}
      };});
      await page.addScriptTag({content:js});
      await page.waitForFunction(()=>window.rendered.stateMonthlyChart_gefs);
      assert.equal(await page.locator("#stateMonthlyReference").inputValue(),"1991-2020");
      await page.selectOption("#stateMonthlyReference","1961-1990");
      await page.waitForFunction(()=>window.rendered.stateMonthlyChart_gefs?.data.datasets.some(d=>d.isTemperatureClimate&&d.label.includes("1961–1990")));
      assert.match(await page.locator("#stateMonthlyInfo").innerText(),/3,97 °C/);
      const obs = await page.evaluate(()=>window.rendered.stateMonthlyChart_gefs.data.datasets[0].data[14]);
      assert.equal(obs,9);
      await page.selectOption("#stateMonthlyMetric","anomaly");
      const value=await page.evaluate(()=>window.rendered.stateMonthlyChart_gefs.data.datasets[0].data[14]);
      const baseline=dates.slice(0,15).reduce((s,d)=>s+climate.regions.Deutschland[d.slice(5)],0)/15;
      assert.ok(Math.abs(value-(9-baseline))<.002);
      assert.match(await page.locator("#stateMonthlyExportDescription").innerText(),/1961–1990/);
      await page.selectOption("#stateMonthlyReference","1991-2020");
      await page.waitForFunction(()=>window.rendered.stateMonthlyChart_gefs.data.datasets[0].data[14]===3);
      const bounds=await page.locator("#stateMonthlyReference").boundingBox();
      assert.ok(bounds.x>=0&&bounds.x+bounds.width<=width,"Reference selector fits viewport");
      await page.close();
      console.log("Browser:",width,"px, reference switch, observations, anomaly and mobile layout OK");
    }
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
