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
 const fast={station_count:459,source_file_count:14,latest_measurement_utc:'2026-11-15T19:20:00Z',generated_at_utc:'2026-11-15T19:29:00Z'};
 const radar={updated_utc:'2026-11-15T19:28:00Z',products:{dbzh:{frames:[{utc:'2026-11-15T19:15:00Z'},{utc:'2026-11-15T19:10:00Z'},{utc:'2026-11-15T19:05:00Z'},{utc:'2026-11-15T19:00:00Z'}]}}};
 const updated=context.mergeLiveMetadata(rows,fast,radar,now);
 assert.equal(updated[0].status,'current');assert.equal(updated[0].latest,fast.latest_measurement_utc);
 assert.equal(updated[1].status,'current');assert.equal(updated[1].latest,'2026-11-15T19:15:00Z');
 const older=context.mergeLiveMetadata(updated,{...fast,latest_measurement_utc:'2026-11-15T17:00:00Z'},null,now);
 assert.equal(older[0].latest,fast.latest_measurement_utc);
 const future=context.mergeLiveMetadata(updated,{...fast,latest_measurement_utc:'2026-11-15T19:40:00Z'},null,now);
 assert.equal(future[0].latest,fast.latest_measurement_utc);
});
