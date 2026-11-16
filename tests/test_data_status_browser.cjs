const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../datenstatus.html'),'utf8');
// Execute the actual page, stubbing DOM and preventing the initial fetch.
const script=html.split('<script>')[1].split('</script>')[0].replace(/\nrefresh\(\);\s*$/, '\n');
const context=vm.createContext({document:{getElementById:()=>({addEventListener(){}})},setInterval(){}});
vm.runInContext(script,context);
test('an hourly archive ages even without a new Pages publication',()=>{
 const now=new Date('2026-11-15T17:00:00Z');
 const entry={latest:'2026-11-15T15:00:00Z',status:'current',cadence:'hourly',allowed_delay:1.25,incomplete:false};
 const result=context.refreshAge(entry,now);
 assert.equal(result.status,'delayed'); assert.equal(result.lag,2);
});
test('historical incompleteness and unknown sources are not hidden',()=>{
 const now=new Date('2026-11-15T17:00:00Z');
 const entry={latest:'2026-11-14',status:'incomplete',cadence:'daily',allowed_delay:4,incomplete:true};
 assert.equal(context.refreshAge(entry,now).status,'incomplete');
 assert.equal(context.refreshAge({...entry,status:'unknown',latest:null},now).status,'unknown');
});
test('threshold compares exact age and expires the first Tmin night at 06 UTC',()=>{
 const row={latest:'2026-11-15T13:58:00Z',status:'current',cadence:'hourly',allowed_delay:3};
 assert.equal(context.refreshAge(row,new Date('2026-11-15T17:00:00Z')).status,'delayed');
 assert.equal(context.refreshAge({...row,latest:'2026-11-15T12:00:00Z',allowed_delay:24,expires_utc:'2026-11-16T06:00:00Z'},new Date('2026-11-16T06:00:00Z')).status,'delayed');
});
test('monthly and day age use UTC calendar dates, not elapsed hours',()=>{
 const now=new Date('2026-11-15T00:01:00Z');
 assert.equal(context.refreshAge({latest:'2026-10',status:'current',cadence:'monthly',allowed_delay:2},now).lag,1);
 assert.equal(context.refreshAge({latest:'2026-11-14',status:'current',cadence:'daily',allowed_delay:2},now).lag,1);
});
test('new live manifests refresh published rows without waiting for Pages',()=>{
 const now=new Date('2026-11-15T19:30:00Z');
 const rows=[{id:'fast_live',latest:'2026-11-15T17:10:00Z',status:'delayed',cadence:'hourly',allowed_delay:.75},{id:'opera_dbzh',latest:'2026-11-15T17:10:00Z',status:'delayed',cadence:'hourly',allowed_delay:.75}];
 const fast={schema_version:1,station_count:459,source_file_count:14,latest_measurement_utc:'2026-11-15T19:20:00Z',generated_at_utc:'2026-11-15T19:29:00Z'};
 const radar={schema:1,updated_utc:'2026-11-15T19:28:00Z',products:{dbzh:{frames:['15','10','05','00'].map(m=>({utc:`2026-11-15T19:${m}:00Z`,image:`frames/dbzh_2026111519${m}.png`,stats:{coverage:.38,min_physical:-32,max_physical:65,echo_fraction:.08,undetect_fraction:.3}}))}}};
 const updated=context.mergeLiveMetadata(rows,fast,radar,now);
 assert.equal(updated[0].status,'current');assert.equal(updated[0].latest,fast.latest_measurement_utc);
 assert.equal(updated[1].status,'current');assert.equal(updated[1].latest,'2026-11-15T19:15:00Z');
 const older=context.mergeLiveMetadata(updated,{...fast,latest_measurement_utc:'2026-11-15T17:00:00Z'},null,now);
 assert.equal(older[0].latest,fast.latest_measurement_utc);
 const future=context.mergeLiveMetadata(updated,{...fast,latest_measurement_utc:'2026-11-15T19:40:00Z'},null,now);
 assert.equal(future[0].latest,fast.latest_measurement_utc);
 const invalid=context.mergeLiveMetadata(rows,{...fast,station_count:1},{...radar,products:{dbzh:{frames:[{utc:'2026-11-15T19:15:00Z'}]}}},now);
 assert.equal(invalid[0].status,'delayed');assert.equal(invalid[1].status,'delayed');
 const noZone=context.mergeLiveMetadata(rows,{...fast,latest_measurement_utc:'2026-11-15T19:20:00'},null,now);
 assert.equal(noZone[0].status,'delayed');
});
test('MTG uses the oldest verified core observation and never the report creation time',()=>{
 const now=new Date('2026-11-16T05:30:00Z');
 const rows=[{id:'satellite_mtg',latest:'2026-11-16T01:20:00Z',updated:'2026-11-16T02:00:38Z',status:'delayed',cadence:'hourly',allowed_delay:3}];
 const products=Object.fromEntries(['geocolour','dust','ir105','firetemperature'].map(k=>[k,{map_ok:true,latest_verified_time:'2026-11-16T04:40:00Z'}]));
 products.dust.latest_verified_time='2026-11-16T04:20:00Z';
 const report={schema:1,capabilities_ok:true,generated_at:'2026-11-16T05:00:00Z',products};
 const [updated]=context.mergeLiveMetadata(rows,null,null,now,report);
 assert.equal(updated.latest,'2026-11-16T04:20:00Z');
 assert.equal(updated.status,'current');
 assert.equal(updated.updated,report.generated_at);
 const [older]=context.mergeLiveMetadata([updated],null,null,now,{...report,generated_at:'2026-11-16T04:00:00Z'});
 assert.equal(older.updated,report.generated_at);
 const [partial]=context.mergeLiveMetadata([updated],null,null,now,{...report,generated_at:'2026-11-16T05:10:00Z',products:{...products,dust:{map_ok:false,latest_verified_time:null}}});
 assert.equal(partial.status,'incomplete');
 assert.equal(partial.coverage,'3/4 Kernprodukte bestätigt');
 const [unknown]=context.mergeLiveMetadata([updated],null,null,now,{...report,generated_at:'2026-11-16T05:10:00Z',products:{}});
 assert.equal(unknown.status,'unknown');
 const [future]=context.mergeLiveMetadata([updated],null,null,now,{...report,generated_at:'2026-11-16T06:00:00Z'});
 assert.equal(future.updated,report.generated_at);
});
