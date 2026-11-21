const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
let now='2026-11-21T12:00:00Z';
class FixedDate extends Date {constructor(...args){super(...(args.length?args:[now]));} static now(){return Date.parse(now);}}
function select(value,values){const options=values.map(value=>({value,disabled:false,textContent:value}));return {value,options,querySelectorAll(){return options;},querySelector(q){return options.find(o=>q===`option[value="${o.value}"]`)||null;}};}
const nodes={stateMonthlyParameter:select('temperature',['temperature','precipitation','sunshine']),stateMonthlyPeriod:select('month',['month','next_month','season','year']),stateMonthlyMetric:select('absolute',['absolute','anomaly','percent']),stateMonthlyReference:select('1991-2020',['1991-2020','1961-1990']),stateMonthlyRegion:{value:'Deutschland'},stateMonthlyView:select('four',['four','gefs','ifs']),stateMonthlyStatus:{},stateMonthlyTitle:{},stateMonthlyInfo:{}};
const context={window:{},document:{readyState:'loading',addEventListener(){},getElementById:id=>nodes[id]||null},console,Date:FixedDate,Intl};
const source=fs.readFileSync('state_monthly_ensemble.js','utf8').replace(/\}\)\(\);\s*$/,`window.test={setTemperature(doc){data=doc;},setHydro(param,doc,refs,normals){hydro[param]=doc;dailyRainReference=refs;dailySunReference=refs;monthlyNormals=normals;},periodDates,region,parameterDoc,filename,syncParameterControls,renderHeader,historicalMonthNormal,dailyHydroRunning,activeMonthDoc,datasetsFor,checkCalendarMonth};})();`);
vm.runInNewContext(source,context);
const api=context.window.test;
function fixture(month){const day=`2026-${month}-01`,r={observed_through:null,observed_current:null,observed_running:[null,null],climatology_running:[5,5],climatology_period_mean:5,models:{gefs:{run:'2026-11-21T00:00:00Z',forecast_from:day,forecast_through:day,stats:{mean:[3,null]}}}};return {year:2026,month:+month,dates:[day,`2026-${month}-02`],generated_at:now,observation_data_through:null,models_order:['gefs'],regions:{Deutschland:{...r,periods:{month:r,year:r,season:r}}},periods:{month:{dates:[day,`2026-${month}-02`]}}};}
const nov=fixture('11'),dec=fixture('12'),root={...nov,next_month:dec};
api.setTemperature(root);
nodes.stateMonthlyPeriod.value='next_month';
assert.equal(api.periodDates()[0],'2026-12-01');
assert.equal(api.region().observed_current,null);
assert.match(api.filename('png'),/2026_12_/);
api.renderHeader(api.region());
assert.match(nodes.stateMonthlyTitle.textContent,/Dezember 2026/);
assert.match(nodes.stateMonthlyInfo.innerHTML,/Noch keine Beobachtungen/);
assert.doesNotMatch(nodes.stateMonthlyStatus.textContent,/Modelle fehlen/);
for(const param of ['precipitation','sunshine']){
  nodes.stateMonthlyParameter.value=param;
  api.syncParameterControls();assert.equal(nodes.stateMonthlyPeriod.value,'next_month');
  const refs={months:{'11':{dates:['11-01','11-02'],regions:{Deutschland:{running_mm:[4,6],running_h:[4,6]}}},'12':{dates:['12-01','12-02'],regions:{Deutschland:{running_mm:[7,9],running_h:[7,9]}}}}};
  const normals={months:{'11':{[param]:{Deutschland:{month_total:90}}},'12':{[param]:{Deutschland:{month_total:60}}}}};
  api.setHydro(param,root,refs,normals);api.syncParameterControls();
  assert.equal(nodes.stateMonthlyPeriod.value,'next_month');
  assert.equal(api.periodDates()[0],'2026-12-01');
  assert.equal(api.historicalMonthNormal(param,'Deutschland'),60);
  assert.equal(api.dailyHydroRunning('Deutschland')[0],7);
  assert.match(api.filename('pdf'),/2026_12_/);
  api.renderHeader(api.region());assert.match(nodes.stateMonthlyInfo.innerHTML,/Noch keine Beobachtungen/);
}
now='2026-12-01T00:05:00+01:00';
nodes.stateMonthlyParameter.value='temperature';
assert.equal(api.checkCalendarMonth(),true);
assert.equal(nodes.stateMonthlyPeriod.value,'month');
assert.equal(api.periodDates()[0],'2026-12-01');
api.syncParameterControls();assert.equal(nodes.stateMonthlyPeriod.options.find(o=>o.value==='next_month').disabled,true);
api.setTemperature(nov);assert.equal(api.periodDates()[0],'2026-11-01');
api.syncParameterControls();assert.match(nodes.stateMonthlyPeriod.options[0].textContent,/zuletzt verfügbar/);
const isolated=api.datasetsFor('gefs',nov.regions.Deutschland).find(d=>d.label==='Ensemble-Mittel');
assert.ok(isolated.pointRadius>0);
assert.ok(api.datasetsFor('gefs',{...nov.regions.Deutschland,models:{}}).length>0);
console.log('Monthly rollover frontend tests passed');
