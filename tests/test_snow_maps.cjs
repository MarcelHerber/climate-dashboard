const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('snow_maps.js', 'utf8');
const settle = async () => { for (let i=0;i<12;i++) await new Promise(resolve=>setImmediate(resolve)); };

function browser({deferImages=false, unavailable=false}={}) {
  const elements=new Map(), pending=[], downloads=[], failures=new Set();
  class Element {
    constructor(id=''){this.id=id;this.dataset={};this.listeners={};this.value=id==='snowMapRegion'?'hemisphere':'';this.hidden=false;this.disabled=false;this.tagName=id==='snowMapDate'||id==='snowMapRegion'?'SELECT':'BUTTON';}
    addEventListener(name,fn){this.listeners[name]=fn;}
    replaceChildren(...children){this.children=children;this.value=children[0]?.value||'';}
    click(){if(this.download) downloads.push(this.download); else if(!this.disabled)this.listeners.click?.();}
  }
  const get=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);};
  const records=['2026-11-03','2026-11-02','2026-11-01'].map(date=>({date,valid_utc:date+'T00:00:00Z',cover:`images/${date}_cover.png`,anomaly:`images/${date}_anomaly.png`,europe_cover:`images/${date}_europe_cover.png`,europe_anomaly:`images/${date}_europe_anomaly.png`,reference_years:Array.from({length:20},(_,i)=>2001+i),minimum_samples:15}));
  const manifest={schema:1,reference_period:[2001,2020],maps:records,source_errors:[]};
  class Image {
    set src(url){const action=()=>failures.has(url)?this.onerror():this.onload();if(deferImages)pending.push({url,action});else queueMicrotask(action);}
  }
  const context={document:{baseURI:'https://dashboard.example/eurasia_snow.html',getElementById:get,createElement:()=>new Element()},Image,URL,Blob,AbortSignal,Intl,Date,
    Option:class {constructor(text,value){this.text=text;this.value=value;}},
    setTimeout:(fn,ms)=>{const timer=setTimeout(fn,ms);timer.unref();return timer;},clearTimeout,
    fetch:async url=>{
      if(unavailable)throw new Error('Source unavailable');
      return {ok:true,json:async()=>manifest,blob:async()=>new Blob(['png'],{type:'image/png'})};
    }};
  vm.runInNewContext(source,context);
  return {get,pending,downloads,failures,records,flush:()=>{for(const item of pending.splice(0))item.action();}};
}

test('both maps follow previous/next and use date-specific download names',async()=>{
  const b=browser();await settle();
  assert.equal(b.get('snowMapDate').value,'2026-11-03');
  assert.equal(b.get('snowMapNext').disabled,true);
  b.get('snowMapPrevious').click();await settle();
  assert.equal(b.get('snowMapDate').value,'2026-11-02');
  for(const [id,kind] of [['snowCoverImage','cover'],['snowAnomalyImage','anomaly']]){
    assert.equal(b.get(id).hidden,false);
    assert.match(b.get(id).src,new RegExp(`2026-11-02_${kind}.png$`));
  }
  b.get('snowCoverDownload').click();await settle();
  b.get('snowAnomalyDownload').click();await settle();
  assert.deepEqual(b.downloads,['NOAA_IMS_Nordhalbkugel_Schneebedeckung_2026-11-02.png','NOAA_IMS_Nordhalbkugel_Abweichung_2001-2020_2026-11-02.png']);
});

test('fast date changes cannot replace the newest selection with an older image response',async()=>{
  const b=browser({deferImages:true});await settle();b.flush();await settle();
  b.get('snowMapPrevious').click();
  b.get('snowMapPrevious').click();
  const older=b.pending.splice(0,2),newer=b.pending.splice(0);
  for(const item of newer)item.action();await settle();
  for(const item of older)item.action();await settle();
  assert.match(b.get('snowCoverImage').src,/2026-11-01_cover.png$/);
  assert.match(b.get('snowAnomalyImage').src,/2026-11-01_anomaly.png$/);
  assert.equal(b.get('snowMapDate').value,'2026-11-01');
});

test('a missing second map hides both images and blocks downloads until a successful retry',async()=>{
  const b=browser({deferImages:true});await settle();
  b.failures.add(b.pending[1].url);b.flush();await settle();
  assert.equal(b.get('snowMapStatus').dataset.kind,'warn');
  assert.equal(b.get('snowCoverImage').hidden,true);
  assert.equal(b.get('snowAnomalyImage').hidden,true);
  assert.equal(b.get('snowCoverDownload').disabled,true);
  assert.equal(b.get('snowAnomalyDownload').disabled,true);
  b.failures.clear();b.get('snowMapRefresh').click();await settle();b.flush();await settle();
  assert.equal(b.get('snowCoverImage').hidden,false);
  assert.equal(b.get('snowAnomalyImage').hidden,false);
  assert.equal(b.get('snowCoverDownload').disabled,false);
});

test('unreachable source gives a visible status and leaves retry available',async()=>{
  const b=browser({unavailable:true});await settle();
  assert.equal(b.get('snowMapStatus').dataset.kind,'warn');
  assert.match(b.get('snowMapStatus').textContent,/nicht erreichbar/);
  assert.equal(b.get('snowMapDate').disabled,true);
  assert.equal(b.get('snowMapRefresh').disabled,false);
});

test('Europe extent keeps date and loads matching verified images and download names',async()=>{
  const b=browser();await settle();
  const region=b.get('snowMapRegion');
  region.value='europe';region.listeners.change();await settle();
  assert.equal(b.get('snowMapDate').value,'2026-11-03');
  assert.match(b.get('snowCoverImage').src,/2026-11-03_europe_cover.png$/);
  assert.match(b.get('snowAnomalyImage').src,/2026-11-03_europe_anomaly.png$/);
  assert.match(b.get('snowMapReference').textContent,/Island bis Ural/);
  b.get('snowCoverDownload').click();await settle();
  assert.equal(b.downloads[0],'NOAA_IMS_Europa_Island-Ural_Schneebedeckung_2026-11-03.png');
  region.value='hemisphere';region.listeners.change();await settle();
  assert.match(b.get('snowCoverImage').src,/2026-11-03_cover.png$/);
});

test('switching extent while images load cannot mix Europe and hemisphere layers',async()=>{
  const b=browser({deferImages:true});await settle();b.flush();await settle();
  const region=b.get('snowMapRegion');
  region.value='europe';region.listeners.change();
  region.value='hemisphere';region.listeners.change();
  const first=b.pending.splice(0,2),last=b.pending.splice(0);
  for(const pending of last)pending.action();await settle();
  for(const pending of first)pending.action();await settle();
  assert.match(b.get('snowCoverImage').src,/2026-11-03_cover.png$/);
  assert.match(b.get('snowAnomalyImage').src,/2026-11-03_anomaly.png$/);
});
