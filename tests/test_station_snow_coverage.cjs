const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");

const index=JSON.parse(fs.readFileSync("station_snow_height_index.json","utf8"));
const html=fs.readFileSync("index.html","utf8");
const short=(index.stations||[]).filter(s=>Number(s.accepted_history_years||0)<30);
const long=(index.stations||[]).filter(s=>Number(s.accepted_history_years||0)>=30);

test("KL profile builder publishes short snow histories instead of dropping them",()=>{
  assert.equal(index.ready,true);
  assert.ok(index.stations.length>=299,"Old 32 stations must be added to 267");
  assert.ok(short.length>=32,"At least 32 short-coverage KL stations required");
  assert.ok(long.length>=267,"All previously-qualified KL stations retained");
  assert.equal(index.station_count,index.stations.length);
  assert.equal(new Set(index.stations.map(s=>s.id)).size,index.stations.length);
  assert.equal(index.stations_meeting_30_year_filter,long.length);
  assert.equal(index.stations_below_30_quality_years,short.length);
});

test("each published KL station has actual per-day data and profile reference",()=>{
  for(const station of index.stations){
    assert.ok(station.year_file&&fs.existsSync(station.year_file),station.id);
    assert.ok(station.file&&fs.existsSync(station.file),station.id);
    const profile=JSON.parse(fs.readFileSync(station.file,"utf8"));
    assert.equal(profile.daily.length,366,station.id);
    assert.equal(profile.quality.accepted_history_years,station.accepted_history_years,station.id);
    const archive=JSON.parse(fs.readFileSync(station.year_file,"utf8"));
    assert.equal(archive.month_days.length,366,station.id);
    assert.ok(archive.years.some(y=>y.values.some(v=>v!==null)),station.id+" has no real observations");
    assert.equal(station.meets_30_year_filter,station.accepted_history_years>=30);
  }
});

test("years without sufficient 1991-2020 reference remain intentionally null",()=>{
  for(const station of short.slice(0,15)){
    const profile=JSON.parse(fs.readFileSync(station.file,"utf8"));
    if(profile.quality.reference_years_available<10){
      assert.ok(profile.daily.every(row=>row[2]===null),"Unexpected climatology: "+station.id);
    }
  }
});

test("30-year checkbox filters at runtime without removing short-station data",()=>{
  const start=html.indexOf("function stationSnowQualifiesForLongSeries(");
  const end=html.indexOf("function populateStationSnowStations(",start);
  assert.ok(start>0&&end>start);
  const code=html.slice(start,end);
  const filters={stationSnowStateSelect:{value:"Deutschland"},
    stationSnowSearch:{value:""},
    stationSnowLongSeriesOnly:{checked:false}};
  const context={stationSnowIndex:index,document:{
    getElementById(id){return filters[id]||null;}
  }};
  vm.runInNewContext(code,context);
  assert.equal(context.filteredStationSnowStations().length,index.stations.length);
  filters.stationSnowLongSeriesOnly.checked=true;
  assert.equal(context.filteredStationSnowStations().length,long.length);
  filters.stationSnowLongSeriesOnly.checked=false;
  assert.equal(context.filteredStationSnowStations().length,index.stations.length);
  filters.stationSnowSearch.value=short[0].name;
  assert.ok(context.filteredStationSnowStations().some(s=>s.id===short[0].id));
});

test("additional RR index is optional and never duplicates KL stations",()=>{
  assert.match(html,/station_snow_height_additional_index\.json/);
  assert.match(html,/id="stationSnowLongSeriesOnly"/);
  assert.match(html,/id="stationSnowFilterStatus"/);
  const path="station_snow_height_additional_index.json";
  if(!fs.existsSync(path))return;
  const additional=JSON.parse(fs.readFileSync(path,"utf8"));
  assert.equal(additional.station_count,additional.stations.length);
  const base=new Set(index.stations.map(s=>s.id));
  for(const row of additional.stations){
    assert.ok(!base.has(row.id),"Duplicate station: "+row.id);
    assert.ok(row.source.includes("SH_TAG")||row.source.includes("SHK_TAG"));
    assert.ok(row.year_file&&row.file);
  }
});
