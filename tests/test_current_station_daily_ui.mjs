import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
const html=readFileSync(new URL("../index.html",import.meta.url),"utf8");
const liveStart=html.indexOf("function currentHasNumber(");
const fastEnd=html.indexOf("const CURRENT_GERMAN_STATES=",liveStart);
assert.ok(liveStart>0&&fastEnd>liveStart);
const helpers=html.slice(liveStart,fastEnd);
const nowDate=new Date().toLocaleDateString("sv-SE",{timeZone:"Europe/Berlin"});
function createHelpers(schema=5){
 const liveIndex={schema_version:schema};
 const api=new Function("currentFastByStation","currentLiveIndex",helpers+
  "\nreturn {currentMergeFastIntoIndex,currentMergeFastProfile,currentHasNumber,currentDayValue};")
  (new Map(),liveIndex);
 return {api,liveIndex};
}
{
 const {api}=createHelpers();
 assert.equal(api.currentHasNumber(null),false,"null must not become zero");
 assert.equal(api.currentHasNumber(undefined),false);
 assert.equal(api.currentHasNumber(0),true);
 const base={
  schema_version:5, latest_measurement_utc:"2026-11-11T15:00:00Z",
  stations:[{id:"00150",temperature_utc:"2026-11-11T14:00:00Z",
   wind_utc:"2026-11-11T14:00:00Z",gust_utc:"2026-11-11T14:00:00Z",
   latest_utc:"2026-11-11T15:00:00Z",today_date:nowDate,
   today_max_c:13.4,today_min_c:3.2,today_max_gust_ms:21,
   today_precip_sum_mm:8.5,temperature_c:9,humidity_pct:75,pressure_hpa:1002}]
 };
 const f={station_id:"00150",time_utc:"2026-11-11T14:20:00Z",
  temperature_c:15.6,gust_speed_ms:29,humidity_pct:null,pressure_hpa:null};
 const merged=api.currentMergeFastIntoIndex(base,{stations:[f],latest_measurement_utc:f.time_utc});
 const m=merged.stations[0];
 assert.equal(m.temperature_c,15.6,"new fast report is still displayed as current");
 assert.equal(m.today_max_c,13.4,"fast report cannot replace real TX_10");
 assert.equal(m.today_min_c,3.2,"fast report cannot replace real TN_10");
 assert.equal(m.today_max_gust_ms,21,"fast report cannot replace real FX_10 daily peak");
 assert.equal(m.today_precip_sum_mm,8.5,"rain day sum must be CDC only");
 assert.equal(m.humidity_pct,75,"missing fast humidity cannot be coerced into zero");
 assert.equal(m.pressure_hpa,1002,"missing fast pressure cannot be coerced into zero");
 const profile=api.currentMergeFastProfile({station:{id:"00150"},
  latest:{temperature_utc:"2026-11-11T14:00:00Z",temperature_c:9},
  today:{date:nowDate,max_c:13.4,min_c:3.2,precip_sum_mm:8.5}});
 assert.equal(profile.today.max_c,13.4);
 assert.equal(profile.today.min_c,3.2);
 assert.equal(profile.today.precip_sum_mm,8.5);
 const old=api.currentMergeFastIntoIndex(base,{stations:[{...f,time_utc:"2026-11-11T13:00:00Z",temperature_c:19}]});
 assert.equal(old.stations[0].temperature_c,9,"stale fast reports cannot override CDC");
 assert.equal(api.currentDayValue({today_date:"2020-01-01",today_max_c:44},"today_max_c"),null);
 assert.equal(api.currentDayValue({today_date:nowDate,today_precip_sum_mm:0},"today_precip_sum_mm"),0);
}
{
 const {api}=createHelpers(4);
 assert.equal(api.currentDayValue({today_date:nowDate,today_max_c:25},"today_max_c"),null,
  "obsolete schema 4 momentary max must not be presented as actual TX_10");
}
for(const key of ["currentHumidityMax","currentDewpointMax","currentPressureMax","currentGroundTempMax"]){
 assert.ok(html.includes('id="'+key+'"'),"daily maximum DOM missing: "+key);
}
assert.ok(html.includes('currentNum(today.precip_sum_mm,"mm",1)'),"rain card must display daily sum");
assert.ok(html.includes('currentDayValue(s,"today_max_gust_ms")'),"overview must use day's gust peak");
for(const id of ["today_temp_max","today_temp_min","today_wind","today_gust","today_humidity",
 "today_dewpoint","today_pressure","today_ground_temp"]){
 assert.ok(html.includes('option value="'+id+'"'),"map selection missing "+id);
}
console.log("PASS: real station-day extremes, rain day sum, fast SYNOP safeguards, empty values, map and stat cards.");
