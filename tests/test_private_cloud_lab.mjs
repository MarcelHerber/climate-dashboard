import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import worker from "../alpenwetter-worker/src/index.js";
import { LAB_JS } from "../alpenwetter-worker/src/cloud-lab-client.js";
import { LAB_CSS } from "../alpenwetter-worker/src/cloud-lab-style.js";
import { TMAX_JS } from "../alpenwetter-worker/src/europe-tmax-client.js";
globalThis.crypto ??= webcrypto;

const domain="https://climate-dashboard-alpenwetter.example.workers.dev";
const env={ALPENWETTER_PASSWORD:"safe-secret-for-test-only"};
const request=(route,opts={})=>worker.fetch(new Request(domain+route,opts),env);
const landing=await request("/wolkenlabor");
assert.equal(landing.status,200);
const login=await landing.text();
assert.match(login,/GESCHÜTZTER TESTBEREICH/);
assert.doesNotMatch(login,/id="filmCanvas"/);
const unauthTemperaturePage=await request("/wolkenlabor/europa-tmax");
assert.equal(unauthTemperaturePage.status,200);
const unauthTemperatureHtml=await unauthTemperaturePage.text();
assert.match(unauthTemperatureHtml,/GESCHÜTZTER TESTBEREICH/);
assert.doesNotMatch(unauthTemperatureHtml,/id="tmaxCanvas"/);
for(const path of ["/wolkenlabor/data/europa-tmax/current.json",
 "/wolkenlabor/data/europa-tmax/stations_catalog.json",
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
assert.match(content,/Europa Tmax · MOS \+ ICON/);
const temperaturePage=await request("/wolkenlabor/europa-tmax",{headers:{Cookie:cookie}});
assert.equal(temperaturePage.status,200);
const temperatureHtml=await temperaturePage.text();
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
