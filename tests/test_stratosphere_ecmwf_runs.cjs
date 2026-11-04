const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {test}=require('node:test');

const source=fs.readFileSync('stratosphere_ecmwf_runs.js','utf8');
const helpers=source.slice(source.indexOf('function dateOf('),source.indexOf('function isRun('));
const renderer=source.slice(source.indexOf('function valuePoints('),source.indexOf('async function reload('));

class Element{
  constructor(){this.textContent='';this.children=[];this.disabled=true;this.checked=false;this.value='';}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(){this.children=[];this.textContent='';}
}
function renderWith(gefs){
  const nodes=new Map();
  const $=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
  $('stratoEcmwfCount').value='all';$('stratoEcmwfHorizon').value='30';
  const run={cycle_utc:'2026-11-03T00:00:00Z',steps_hours:[0,12,72,84,168,180,240,252],values:[1,2,3,4,5,6,7,8]};
  const context={$,document:{createElement:()=>new Element()},window:{stratoGefsEnsemble:gefs},
    archive:{run_count:1,runs:[run]},observations:new Map(),climatology:null,chart:null,lastData:[],
    COLORS:['#f59e0b'],Chart:class{constructor(canvas,config){this.canvas=canvas;this.data=config.data;}}};
  vm.createContext(context);vm.runInContext(helpers+renderer,context);
  context.render();
  function text(node){return node.textContent+' '+node.children.map(text).join(' ');}
  return {nodes,diagnostic:text($('stratoModelDiagnostics'))};
}
for(const [label,gefs,want] of [
  ['06 UTC GEFS',{provider:'NOAA GEFS',member_count:31,cycle_utc:'2026-11-03T06:00:00Z',valid_dates:['2026-11-06'],quantiles:{mean:[12]}},'06 UTC'],
  ['12 UTC GEFS',{provider:'NOAA GEFS',member_count:31,cycle_utc:'2026-11-03T12:00:00Z',valid_dates:['2026-11-06'],quantiles:{mean:[12]}},'12 UTC'],
  ['GEFS not yet loaded',undefined,'GEFS derzeit nicht geladen']
]){
  test('IFS run comparison enables downloads with '+label,()=>{
    const {nodes,diagnostic}=renderWith(gefs);
    assert.equal(nodes.get('stratoEcmwfPng').disabled,false);
    assert.equal(nodes.get('stratoEcmwfCsv').disabled,false);
    assert(diagnostic.includes(want));
    assert(diagnostic.includes('4.0 m/s'),'12 UTC IFS forecast must reach the diagnostics table');
  });
}
