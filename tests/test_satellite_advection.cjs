const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const scope={window:{}};
vm.runInNewContext(fs.readFileSync('satellite_advection.js','utf8'),scope);
const api=scope.window.SatelliteAdvection;
const bbox=[-27,24,49,73];
const warm={lon:0,lat:50,advection:5,u:4,v:12};
const cold={lon:20,lat:39,advection:-3,u:12,v:-6};
test('warm and cold arrows point in the actual direction of flow',()=>{
 const [a,b]=api.layout([warm,cold],bbox,1000,650,8);
 assert.equal(a.label,'WLA');assert.equal(a.color,'#ff515d');
 assert.ok(a.end[0]>a.start[0]&&a.end[1]<a.start[1]);
 assert.equal(b.label,'KLA');assert.equal(b.color,'#53b9ff');
 assert.ok(b.end[0]>b.start[0]&&b.end[1]>b.start[1]);
 assert.ok(a.length>b.length);
});
test('small or edge and overlapping annotations are excluded',()=>{
 const markers=[warm,{...warm,lon:.1,advection:3},{...cold,advection:-1},
  {...cold,lon:49,advection:-10},{...cold,lat:200}];
 const result=api.layout(markers,bbox,320,210,8);
 assert.equal(result.length,1);assert.equal(result[0].label,'WLA');
});
test('only a verified advection frame and selected level can be used',()=>{
 const frame={valid_utc:'2026-11-16T05:00:00Z',advection_method:'ifs_temperature_advection_v1',temperature_advection:{850:[warm],925:[],700:[cold]}};
 assert.equal(api.frameMarkers(frame,850,'2026-11-16T05:00:00Z').length,1);
 assert.equal(api.frameMarkers(frame,925,'2026-11-16T05:00:00Z').length,0);
 assert.equal(api.frameMarkers(frame,850,'2026-11-16T05:10:00Z'),null);
 assert.equal(api.frameMarkers({...frame,advection_method:undefined},850,frame.valid_utc),null);
});
test('Pages publishes and syntax-checks shared advection renderer',()=>{
 const build=fs.readFileSync('scripts/build_pages_site.sh','utf8');
 assert.match(build,/^  satellite_advection\.js$/m);
 assert.match(build,/node --check _site\/satellite_advection\.js/);
});
