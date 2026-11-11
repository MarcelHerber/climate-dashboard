import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
const src=readFileSync(new URL("../mosmix.js",import.meta.url),"utf8");
new Function(src);
const from=src.indexOf("  function berlinDateParts(iso) {");
const to=src.indexOf("  function hasMeteogramValues(detail, param) {",from);
assert.ok(from>=0&&to>from);
const helpers=src.slice(from,to);
function hours(start,length){
 const t=Date.parse(start);
 return Array.from({length},(_,i)=>new Date(t+i*3600000).toISOString());
}
function verify(start,days){
 const timesteps=hours(start,196);
 const {berlinDateParts,mosmixBerlinMidnightPlugin,baseChartOptions}=new Function("data","window",helpers+
  "\nreturn {berlinDateParts,mosmixBerlinMidnightPlugin,baseChartOptions};")({timesteps},{});
 const opts=baseChartOptions("°C");
 assert.equal(opts.plugins.mosmixBerlinMidnight,true);
 const first=6,last=6+days*24;
 const lines=[],labels=[];
 const ctx={save(){},restore(){},beginPath(){},moveTo(x){this.x=x},lineTo(){},stroke(){lines.push(this.x)},fillText(text,x,y){labels.push({text,x,y})}};
 const chart={options:opts,scales:{x:{min:first,max:last,getPixelForValue:i=>100+i*8}},
  chartArea:{left:100+first*8,right:100+last*8,top:20,bottom:260},ctx};
 mosmixBerlinMidnightPlugin.afterDraw(chart);
 const expected=timesteps.map((time,i)=>({time,i,local:berlinDateParts(time)}))
   .filter(v=>v.i>=first&&v.i<=last&&v.local.hour===0);
 assert.equal(lines.length,expected.length);
 for(let j=0;j<lines.length;j++)assert.equal(lines[j],Math.round(100+expected[j].i*8)+0.5);
 assert.ok(expected.length>=days-1);
 assert.equal(labels.filter(row=>row.text==="00 Uhr").length,expected.length);
 console.log("PASS",days,"days",start,"midnight indices",expected.map(x=>x.i).join(","));
}
for(const start of ["2026-11-10T00:00:00Z","2026-06-10T00:00:00Z","2026-03-27T00:00:00Z","2026-10-23T00:00:00Z"]){
 verify(start,3);verify(start,5);
}
