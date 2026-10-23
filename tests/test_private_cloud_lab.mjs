import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import worker from "../alpenwetter-worker/src/index.js";
import { LAB_JS } from "../alpenwetter-worker/src/cloud-lab-client.js";
import { LAB_CSS } from "../alpenwetter-worker/src/cloud-lab-style.js";
import { TMAX_JS } from "../alpenwetter-worker/src/europe-tmax-client.js";
import { europeTminPage } from "../alpenwetter-worker/src/europe-tmin.js";
globalThis.crypto ??= webcrypto;

const domain="https://climate-dashboard-alpenwetter.example.workers.dev";
const env={ALPENWETTER_PASSWORD:"safe-secret-for-test-only"};
const request=(route,opts={})=>worker.fetch(new Request(domain+route,opts),env);
const landing=await request("/wolkenlabor");
assert.equal(landing.status,200);
const login=await landing.text();
assert.match(login,/GESCHÜTZTER TESTBEREICH/);
assert.doesNotMatch(login,/id="filmCanvas"/);
const unauthTmin=await request("/wolkenlabor/europa-tmin");
assert.equal(unauthTmin.status,200);
assert.match(await unauthTmin.text(),/GESCHÜTZTER TESTBEREICH/);
const unauthTemperaturePage=await request("/wolkenlabor/europa-tmax");
assert.equal(unauthTemperaturePage.status,200);
const unauthTemperatureHtml=await unauthTemperaturePage.text();
assert.match(unauthTemperatureHtml,/GESCHÜTZTER TESTBEREICH/);
assert.doesNotMatch(unauthTemperatureHtml,/id="tmaxCanvas"/);
for(const path of ["/wolkenlabor/data/europa-tmax/current.json",
 "/wolkenlabor/data/europa-tmax/stations_catalog.json",
 "/wolkenlabor/data/europa-tmax/icon_tmax_raw_2026-10-24.png",
 "/wolkenlabor/data/europa-tmin/current.json",
 "/wolkenlabor/data/europa-tmin/stations_catalog.json",
 "/wolkenlabor/data/europa-tmin/icon_tmin_raw_2026-10-24.png",
 "/wolkenlabor/data/europa-tmax/icon_tmax_2026-10-24.png"]){
 const res=await request(path);
 assert.equal(res.status,401);
 assert.match(res.headers.get("cache-control"),/no-store/);
}
const unauthData=await request("/wolkenlabor/data/current.json");
assert.equal(unauthData.status,401);
const unauthD2Manifest=await request("/wolkenlabor/data/d2/current.json");
assert.equal(unauthD2Manifest.status,401);
const unauthD2Image=await request("/wolkenlabor/data/d2/frames/2026102006/clch_006.png");
assert.equal(unauthD2Image.status,401);
const unauthIFS01=await request("/wolkenlabor/data/mixer/ecmwf-ifs-0p1/current.json");
assert.equal(unauthIFS01.status,401);
const unauthIFS01Frame=await request("/wolkenlabor/data/mixer/ecmwf-ifs-0p1/frames/2026102000/clcl_003.png");
assert.equal(unauthIFS01Frame.status,401);
const protectedMixerManifest=await request("/wolkenlabor/data/mixer/gfs/current.json");
assert.equal(protectedMixerManifest.status,401);
const protectedMixerFrame=await request("/wolkenlabor/data/mixer/ecmwf-aifs/frames/2026102012/clcl_006.png");
assert.equal(protectedMixerFrame.status,401);
const unauthPrecipManifest=await request("/wolkenlabor/data/d2/precip.json");
assert.equal(unauthPrecipManifest.status,401);
const unauthPrecipImage=await request("/wolkenlabor/data/d2/precip/frames/2026102006/rain_003.png");
assert.equal(unauthPrecipImage.status,401);
const auth=new URLSearchParams({password:env.ALPENWETTER_PASSWORD,next:"/wolkenlabor"});
const session=await request("/login",{method:"POST",body:auth,redirect:"manual"});
assert.equal(session.status,303);
assert.equal(session.headers.get("location"),"/wolkenlabor");
const cookie=session.headers.get("set-cookie").split(";")[0];
assert.match(cookie,/alpenwetter_session=/);
const protectedPage=await request("/wolkenlabor",{headers:{Cookie:cookie}});
assert.equal(protectedPage.status,200);
const content=await protectedPage.text();
assert.match(content,/Europa Tmax/);
const temperaturePage=await request("/wolkenlabor/europa-tmax",{headers:{Cookie:cookie}});
assert.equal(temperaturePage.status,200);
const temperatureHtml=await temperaturePage.text();
const tminPage=await request("/wolkenlabor/europa-tmin",{headers:{Cookie:cookie}});
assert.equal(tminPage.status,200);
assert.match(tminPage.headers.get("cache-control"),/no-store/);
assert.match(tminPage.headers.get("x-robots-tag"),/noindex/);
const tminHtml=await tminPage.text();
assert.match(tminHtml,/Nachttiefsttemperaturen/);
assert.match(tminHtml,/MOSMIX-TN/);
assert.match(tminHtml,/TMIN_2M/);
assert.match(tminHtml,/18–06 UTC/);
assert.match(tminHtml,/Nacht zum/);
assert.match(tminHtml,/europe-tmin|europa-tmin/);
assert.doesNotMatch(tminHtml,/const PREFIX="\/wolkenlabor\/data\/europa-tmax\//);
assert.match(tminHtml,/const PREFIX="\/wolkenlabor\/data\/europa-tmin\//);
assert.match(tminHtml,/climate-europa-tmin-editor-v1/);
assert.match(tminHtml,/icon_tmin_raw_/);
assert.match(tminHtml,/tmin_c/);
assert.match(tminHtml,/\.tn/);
assert.doesNotMatch(tminHtml,/\bMOSMIX-TX\b/);
assert.doesNotThrow(()=>new Function(tminHtml.match(/<script>([\s\S]*?)<\/script>/)[1]));
assert.match(content,/Europa Tmin/);

for(const id of ["tmaxCanvas","tmaxPrev","tmaxNext","tmaxDays","tmaxStatus",
                 "tmaxField","tmaxPoints","tmaxNames","tmaxDensity","tmaxSave"]){
 assert.match(temperatureHtml,new RegExp('id="'+id+'"'));
}
assert.match(temperatureHtml,/06–18 UTC/);
assert.match(temperatureHtml,/noindex,nofollow/);
assert.match(temperaturePage.headers.get("cache-control"),/no-store/);
assert.match(temperaturePage.headers.get("x-robots-tag"),/noindex/);
assert.doesNotMatch(content,/id="tmaxCanvas"/);
assert.doesNotThrow(()=>new Function(TMAX_JS));
assert.match(TMAX_JS,/icon_tmax_/);
assert.match(TMAX_JS,/toBlob/);
assert.match(TMAX_JS,/ArrowLeft/);
assert.match(TMAX_JS,/const INSETS=\[/);
assert.match(TMAX_JS,/city:"Azoren"/);
assert.match(TMAX_JS,/city:"Kanaren"/);
assert.match(TMAX_JS,/const \[cx,cy\]=xy\(lon,lat,region\)/);
assert.doesNotMatch(TMAX_JS,/ctx\.lineTo\(position\.x/);
assert.match(TMAX_JS,/drawIconField\(image\)/);
assert.match(temperatureHtml,/Alle Vorlagenstädte/);
for(const id of ["tmaxEditorToggle","tmaxEditor","tmaxStage","tmaxFind",
                 "tmaxPinLabel","tmaxMatches","tmaxAdd","tmaxPin","tmaxMove",
                 "tmaxReset","tmaxStationList","tmaxEditNote"]){
 assert.match(temperatureHtml,new RegExp('id="'+id+'"'),"Missing editor control "+id);
}
for(const phrase of ["stations_catalog.json","pointerdown","pointermove",
                     "pointerup","localStorage.setItem","state.prefs.hidden",
                     "nearestStation","searchCandidates","createCustom"]){
 assert(TMAX_JS.includes(phrase),"Missing editor behavior "+phrase);
}
assert.match(TMAX_JS,/region\.west\+\(x-region\.x\)\/region\.w\*\(region\.east-region\.west\)/);

const pxCode=TMAX_JS.slice(TMAX_JS.indexOf("function xy("),TMAX_JS.indexOf("function rectPath("));
const geoCode=TMAX_JS.slice(TMAX_JS.indexOf("function lonlat("),TMAX_JS.indexOf("function availableValue("));
const mainMap={west:-24.8,east:62,south:33.5,north:71,x:220,y:108,w:1610,h:835};
const coords=new Function("MAIN",pxCode+geoCode+"return {xy,lonlat,geoDistance};")(mainMap);
const [cx,cy]=coords.xy(13.4,52.52);
const [lonBack,latBack]=coords.lonlat(cx,cy,mainMap);
assert(Math.abs(lonBack-13.4)<1e-9);
assert(Math.abs(latBack-52.52)<1e-9);
const azoresInset={west:-29,east:-23.4,south:36.5,north:39.8,x:22,y:526,w:178,h:177};
const [ix,iy]=coords.xy(-25.67,37.74,azoresInset);
const [al,at]=coords.lonlat(ix,iy,azoresInset);
assert(Math.abs(al+25.67)<1e-9&&Math.abs(at-37.74)<1e-9);
assert(coords.geoDistance(13.4,52.52,13.4,52.52)<0.01);
assert(coords.geoDistance(13.4,52.52,13.42,52.52)<3);

// Temperature overrides affect presentation only. Preserve raw DWD MOSMIX
// value, isolate manual values by date, and retain colors across dates.
for(const id of ["tmaxBoxEditor","tmaxBoxTitle","tmaxOriginal","tmaxValueOverride",
                 "tmaxBoxFill","tmaxBoxText","tmaxBoxBorder","tmaxStyleSave",
                 "tmaxValueReset","tmaxColorReset","tmaxStyleClose","tmaxGlobalFill",
                 "tmaxGlobalReset"]){
 assert.match(temperatureHtml,new RegExp('id="'+id+'"'),"Missing manual-temperature/color control "+id);
}
assert.match(temperatureHtml,/Originalwert/);
assert.match(temperatureHtml,/nur dieser Tag/);
assert.match(TMAX_JS,/Manuell angepasste Anzeige/);
assert.match(TMAX_JS,/ctx\.fillStyle=colors\.fill/);
assert.match(TMAX_JS,/ctx\.strokeStyle=colors\.border/);
assert.match(TMAX_JS,/ctx\.fillStyle=colors\.text/);
assert.match(TMAX_JS,/while\(font>15&&ctx\.measureText\(valueText\)\.width>w-5\)/);
const helperSection=TMAX_JS.slice(TMAX_JS.indexOf("function hex("),TMAX_JS.indexOf("const EDIT_STORAGE="));
const original={key:"base:Frankfurt",city:"Frankfurt",station_name:"FRANKFURT-SACHSENH.",tmax_c:13.6};
const day1={date:"2026-10-23",stations:[original]},day2={date:"2026-10-24",stations:[{...original,tmax_c:15.2}]};
const jsState={data:{days:[day1,day2]},index:0,selectedKey:"base:Frankfurt",
 prefs:{styles:{},values:{},globalFill:"#ffffff",autoBoxes:false,scale:{min:-35,max:45,colors:["#1b2572","#2352ad","#319ad2","#6ecad2","#53a976","#a7c567","#f6d762","#f9984e","#eb5f4b","#ce3e5f","#772b5e"]}}};
const el={tmaxBoxMode:{value:"manual"},tmaxBoxPresets:{querySelectorAll:()=>[]},tmaxBoxEditor:{hidden:true},tmaxBoxTitle:{},tmaxOriginal:{},tmaxValueOverride:{value:"14.5",focus(){}},
 tmaxBoxFill:{value:"#ffdc82"},tmaxBoxText:{value:"#172d41"},tmaxBoxBorder:{value:"#873d12"}};
let calls=0;
const paint=new Function("state","$","objectsForDay","dateLabel","renderEditorList","persist","render","note",
 helperSection+"return {boxColors,manualValue,shownValue,openBoxEditor,applyBoxEdits,resetBoxValue,resetBoxColor,contrast};"
)(jsState,id=>el[id],day=>day.stations,x=>x,()=>{},()=>{calls++},()=>{calls++},()=>{});
assert.equal(paint.shownValue(original,day1.date).value,13.6);
paint.applyBoxEdits();
assert.equal(original.tmax_c,13.6,"The original DWD MOS value must not be modified");
assert.equal(paint.shownValue(original,day1.date).value,14.5);
assert.equal(paint.shownValue(original,day1.date).manual,true);
assert.equal(paint.shownValue(day2.stations[0],day2.date).value,15.2);
assert.equal(paint.boxColors("base:Frankfurt").fill,"#ffdc82");
assert.equal(jsState.prefs.styles["base:Frankfurt"].mode,"manual");
assert.equal(paint.boxColors("base:Frankfurt").border,"#873d12");
assert.equal(paint.boxColors("base:Frankfurt").text,"#172d41");
assert(calls>=2,"Editor writes should persist and redraw");
paint.resetBoxValue();
assert.equal(paint.shownValue(original,day1.date).value,13.6);
assert.equal(paint.shownValue(original,day1.date).manual,false);
assert.equal(paint.boxColors("base:Frankfurt").fill,"#ffdc82");
paint.resetBoxColor();
assert.equal(paint.boxColors("base:Frankfurt").fill,"#ffffff");
jsState.prefs.globalFill="#111111";
assert.equal(paint.boxColors("base:Frankfurt").text,"#ffffff");
assert.equal(paint.contrast("#ffffff"),"#172d41");

for(const id of ["tmaxScaleEditor","tmaxScaleMin","tmaxScaleMax",
 "tmaxScaleStops","tmaxScalePreset","tmaxScaleReset","tmaxScalePreview",
 "tmaxAutoBoxes","tmaxBoxMode","tmaxBoxPresets"]){
 assert.match(temperatureHtml,new RegExp('id="'+id+'"'),"missing editor control "+id);
}
assert.match(TMAX_JS,/icon_tmax_raw_/);
assert.match(TMAX_JS,/colorizeIcon\(raw\)/);
assert.match(TMAX_JS,/drawLegend\(\)/);
const tempStops=new Function(TMAX_JS.slice(TMAX_JS.indexOf("const STOPS="),
 TMAX_JS.indexOf("const SCALE_PRESETS="))+"return STOPS;")();
const scaleSource=TMAX_JS.slice(TMAX_JS.indexOf("const SCALE_PRESETS="),
 TMAX_JS.indexOf("const state={"));
const colorsState={prefs:{scale:{min:-35,max:45,colors:tempStops.map(x=>x[1])}},
 rawPictures:new Map(),pictures:new Map(),data:{days:[]},index:0};
const palette=new Function("STOPS","state","document","$","render","persist","note","openBoxEditor",
 scaleSource+"return {sanitizedScale,scaleAt,scaleHex,paletteLut,colorizeIcon,defaultScale};"
)(tempStops,colorsState,null,()=>({}),()=>{},()=>{},()=>{},()=>{});
assert.equal(palette.scaleHex(-35),"#1b2572");
assert.equal(palette.scaleHex(45),"#772b5e");
assert.equal(palette.scaleHex(0),"#6ecad2");
const oldColor=palette.scaleHex(10);
colorsState.prefs.scale.min=-10;
colorsState.prefs.scale.max=30;
assert.notEqual(palette.scaleHex(10),oldColor,
 "Range adjustment must affect a given physical temperature");
colorsState.prefs.scale.colors[0]="#ffffff";
assert.equal(palette.scaleHex(-10),"#ffffff");
const lut=palette.paletteLut();
assert.equal(lut.length,3072);
assert.deepEqual(Array.from(lut.slice(0,3)),[255,255,255]);
colorsState.prefs.scale=palette.defaultScale();
assert.deepEqual(palette.sanitizedScale({min:30,max:-30}),palette.defaultScale());




assert.match(content,/id="filmCanvas"/);
assert.match(content,/Nur hohe Wolken/);
assert.match(content,/Nur mittelhohe Wolken/);
assert.match(content,/Nur tiefe Wolken/);
assert.match(content,/4er-Panel/);
assert.match(content,/id="showRain"/);
assert.match(content,/id="showSnow"/);
assert.match(content,/Full-HD PNG/);
assert.match(content,/id="previewBroadcast"/);
assert.match(content,/id="broadcastPreview"/);
assert.match(content,/Wolkengrau/);
assert.match(content,/id="winterLow"/);
assert.match(content,/id="winterSource"/);
for (const key of ["clcl","clcm","clch","clct"]) assert.match(content,new RegExp('id="source-'+key+'"'));
assert.match(content,/Modellmischer/);
assert.match(content,/icon-d2-ruc/);
assert.match(content,/ecmwf-aifs/);
assert.match(content,/ecmwf-ifs/);
assert.match(content,/ecmwf-ifs-0p1/);
assert.match(content,/ECMWF IFS · 0,1°/);
assert.match(content,/ECMWF IFS · 0,25°/);
assert.match(LAB_JS,/effectiveSource/);
assert.match(LAB_JS,/sourceTextureFor\("ecmwf-ifs",kind,when\)/);
assert.match(content,/gem/);
assert.match(LAB_JS,/matchingFrame/);
assert.match(LAB_JS,/diff===0|f\.valid_utc===when/);

assert.match(content,/Deckkraft/);
assert.match(content,/Kontrast/);
assert.match(content,/Grenzwert/);
assert.match(LAB_JS,/broadcast:false/);
assert.match(content,/precip\.json/);
assert.match(content,/id="modelD2"/);
assert.match(content,/Deutschland · ICON-D2/);
assert.match(content,/ICON-D2_Deutschland/);
assert.match(content,/const prefix=model/);

assert.doesNotMatch(content,/Polarlicht/);
const notFound=await request("/wolkenlabor/data/bad-thing",{headers:{Cookie:cookie}});
assert.equal(notFound.status,404);
assert.match(notFound.headers.get("cache-control"),/no-store/);
assert.match(protectedPage.headers.get("x-robots-tag"),/noindex/);
assert.match(LAB_JS,/MediaRecorder/);
assert.match(LAB_CSS,/\.stage/);
console.log("PASS: Cloud Lab private route, login session, anti-leakage and basic film controls.");
