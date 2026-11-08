const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(tag='div') {
    this.tagName=tag.toUpperCase();
    this.children=[];
    this.dataset={};
    this.style={};
    this.attributes={};
    this.className='';
    this.textContent='';
    this.open=false;
    this.parentElement=null;
    this.handlers={};
    this.classList={
      add:(...names)=>{this.className += ' '+names.join(' ');},
      toggle:(name,enabled)=>{if(enabled)this.className+=' '+name;}
    };
  }
  setAttribute(key,value){this.attributes[key]=String(value);}
  getAttribute(key){return this.attributes[key]??null;}
  append(...items){for(const item of items){this.children.push(item);item.parentElement=this;}}
  prepend(item){this.children.unshift(item);item.parentElement=this;}
  replaceChildren(...items){this.children=[];this.append(...items);}
  addEventListener(name,handler){this.handlers[name]=handler;}
  insertAdjacentElement(location,child){assert.equal(location,'afterend');this.inserted=child;child.parentElement=this.parentElement;}
  remove(){this.removed=true;}
  contains(child){return this===child||this.children.some(c=>c.contains(child));}
  closest(selector){if(selector==='button[data-action]'&&this.tagName==='BUTTON'&&this.dataset.action)return this;return null;}
  querySelector(selector){
    if(selector!=='details.strato-series-members')throw Error('Unexpected selector '+selector);
    function search(node) {
      if(node.tagName==='DETAILS'&&node.className.includes('strato-series-members'))return node;
      for(const child of node.children){const value=search(child);if(value)return value;}
      return null;
    }
    return search(this);
  }
  find(predicate) {
    if(predicate(this))return this;
    for(const child of this.children){const r=child.find(predicate);if(r)return r;}
    return null;
  }
}
let plugin, api;
const context={
  Chart:{register(value){plugin=value;}},
  document:{createElement:tag=>new Element(tag)},
  window:{}
};
vm.runInNewContext(fs.readFileSync('stratosphere_chart_visibility.js','utf8'),context);
api=context.window.stratoSeriesVisibility;
vm.runInNewContext(fs.readFileSync('stratosphere_chart_export.js','utf8'),context);
const png=context.window.stratoChartExport;


function fixture(datasets,id='stratoTestCanvas') {
  const wrapper=new Element('div');
  const canvas=new Element('canvas');canvas.id=id;canvas.parentElement=wrapper;
  const vis=new Map();
  const chart={
    canvas,data:{datasets},options:{plugins:{legend:{display:true}}},vis,
    setDatasetVisibility(index,on){vis.set(index,on);},
    isDatasetVisible(index){return vis.get(index)??!datasets[index].hidden;},
    update(){plugin.beforeUpdate(this);plugin.afterUpdate(this);},
  };
  chart.update();
  return {chart,wrapper,panel:()=>wrapper.inserted};
}
function button(panel,action,key){
  return panel.find(e=>e.tagName==='BUTTON'&&e.dataset.action===action&&(!key||e.dataset.key===key));
}
function click(panel,target){
  panel.handlers.click({target});
}
const datasets=[
  {label:'_Ensemble 5–95 % Untergrenze',data:[-2,1],borderColor:'transparent'},
  {label:'Ensemble 5–95 %',data:[3,6],borderColor:'transparent',fill:{target:'-1',above:'rgba(20,60,120,.2)'}},
  {label:'Mittel',data:[1,2],borderColor:'#c00'},
  {label:'31 GEFS-Mitglieder (einzeln)',data:[null,null],borderColor:'#333'},
  {label:'_c00',data:[2,3],borderColor:'#444'},
  {label:'_c01',data:[4,5],borderColor:'#555'},
  {label:'0 m/s',data:[0,0],borderColor:'#000'}
];

test('every filled interval is one switch with both bound datasets',()=>{
  assert.ok(plugin);
  const {chart,panel}=fixture(datasets);
  const groups=api.groups(chart);
  assert.deepEqual(Array.from(groups, x=>x.label),[
    'Ensemble 5–95 %','Mittel','c00','c01','0 m/s'
  ]);
  assert.deepEqual([...groups[0].indexes],[0,1]);
  assert.equal(groups[0].filled,true);
  assert.equal(chart.options.plugins.legend.display,false);
  const target=button(panel(),'toggle',groups[0].key);
  assert.equal(target.getAttribute('aria-pressed'),'true');
  click(panel(),target);
  assert.equal(chart.isDatasetVisible(0),false);
  assert.equal(chart.isDatasetVisible(1),false);
  assert.equal(chart.isDatasetVisible(2),true);
  const restored=button(panel(),'toggle',groups[0].key);
  assert.equal(restored.getAttribute('aria-pressed'),'false');
  click(panel(),restored);
  assert.equal(chart.isDatasetVisible(0),true);
  assert.equal(chart.isDatasetVisible(1),true);
});

test('individual ensemble members and group actions do not affect the mean',()=>{
  const {chart,panel}=fixture(datasets,'stratoMemberTestCanvas');
  const groups=api.groups(chart);
  const member=groups.find(g=>g.label==='c01');
  click(panel(),button(panel(),'toggle',member.key));
  assert.equal(chart.isDatasetVisible(5),false);
  assert.equal(chart.isDatasetVisible(4),true);
  const members=panel().querySelector('details.strato-series-members');
  assert.ok(members);
  members.open=true;
  click(panel(),button(panel(),'members-off'));
  assert.equal(chart.isDatasetVisible(4),false);
  assert.equal(chart.isDatasetVisible(5),false);
  assert.equal(chart.isDatasetVisible(2),true);
  assert.equal(panel().querySelector('details.strato-series-members').open,true);
  click(panel(),button(panel(),'members-on'));
  assert.equal(chart.isDatasetVisible(4),true);
  assert.equal(chart.isDatasetVisible(5),true);
});

test('visible selection persists on chart re-creation on same canvas ID',()=>{
  const id='stratoHistoryMainTest';
  const first=fixture(datasets,id);
  const mean=api.groups(first.chart).find(g=>g.label==='Mittel');
  click(first.panel(),button(first.panel(),'toggle',mean.key));
  assert.equal(first.chart.isDatasetVisible(2),false);
  plugin.beforeDestroy(first.chart);
  assert.equal(first.panel().removed,true);
  const second=fixture(datasets,id);
  assert.equal(second.chart.isDatasetVisible(2),false);
  click(second.panel(),button(second.panel(),'all-on'));
  assert.equal(second.chart.isDatasetVisible(2),true);
  click(second.panel(),button(second.panel(),'all-off'));
  assert.ok([0,1,2,4,5,6].every(i=>!second.chart.isDatasetVisible(i)));
});

test('hidden helper lines and individually selectable EPS members are parsed',()=>{
  const {chart}=fixture([
    {label:'_50% min',data:[1,2]},
    {label:'_50% max',data:[3,4],fill:{target:'-1',above:'#6796ca66'}},
    {label:'_EPS p01',data:[2,3],borderColor:'#000'},
    {label:'_EPS p02',data:[2,3],borderColor:'#000'},
    {label:'Klimamittel',data:[2,3],borderColor:'#f00'},
  ],'stratoEpsTestCanvas');
  const groups=api.groups(chart);
  assert.equal(groups.length,4);
  assert.equal(groups[0].label,'Perzentilfläche 50%');
  assert.equal(groups[1].member,true);
  assert.equal(groups[2].member,true);
  assert.equal(groups[3].member,false);
});


test('download metadata lists exactly the visible series, with no hidden bands',()=>{
  const {chart,panel}=fixture(datasets,'stratoExportLabelsTest');
  const bands=api.groups(chart).find(g=>g.filled);
  let entries=png.visibleEntries(chart);
  assert.ok(entries.some(e=>e.label==='Ensemble 5–95 %'&&e.filled));
  assert.ok(entries.some(e=>e.label==='c00'));
  assert.ok(entries.some(e=>e.label==='Mittel'));
  click(panel(),button(panel(),'toggle',bands.key));
  entries=png.visibleEntries(chart);
  assert.ok(!entries.some(e=>e.label==='Ensemble 5–95 %'));
  assert.ok(entries.some(e=>e.label==='Mittel'));
  const mean=api.groups(chart).find(g=>g.label==='Mittel');
  click(panel(),button(panel(),'toggle',mean.key));
  assert.ok(!png.visibleEntries(chart).some(e=>e.label==='Mittel'));
  // No inactive field may silently appear in the exported legend.
  assert.equal(png.visibleEntries(chart).length,3);
});

test('export honors hidden individual members, but shows other visible lines',()=>{
  const {chart,panel}=fixture(datasets,'stratoExportMembersTest');
  const entries=api.groups(chart);
  const member=entries.find(g=>g.label==='c01');
  click(panel(),button(panel(),'toggle',member.key));
  const listed=png.visibleEntries(chart).map(x=>x.label);
  assert.ok(listed.includes('c00'));
  assert.ok(!listed.includes('c01'));
  assert.ok(listed.includes('0 m/s'));
});


test('PNG legend combines 50 visible EPS members, preserving colored summary and main lines',()=>{
  const all=[
    {label:'_90% min',data:[1,2],borderColor:'transparent'},
    {label:'_90% max',data:[3,4],borderColor:'transparent',
      fill:{target:'-1',above:'rgba(71,126,183,.18)'}},
    ...Array.from({length:50},(_,i)=>({
      label:'_EPS p'+String(i+1).padStart(2,'0'),
      data:[3+i/20,4+i/20],borderColor:'rgba(51,77,113,.40)'
    })),
    {label:'EPS-Mittel',data:[4,5],borderColor:'#d62828'},
    {label:'Kontrolllauf (IFS)',data:[3,5],borderColor:'#e59318'},
    {label:'0 m/s · Ostwindschwelle',data:[0,0],borderColor:'#273746'}
  ];
  const {chart,panel}=fixture(all,'stratoEpsSummary50Test');
  const raw=png.visibleEntries(chart);
  const legend=png.legendEntries(chart);
  assert.equal(raw.filter(x=>x.member).length,50,'Keep 50 individual toggles');
  assert.deepEqual(Array.from(legend,x=>x.label),[
    'Perzentilfläche 90%','50 EPS-Mitglieder','EPS-Mittel',
    'Kontrolllauf (IFS)','0 m/s · Ostwindschwelle'
  ]);
  assert.equal(legend[1].color,'rgba(51,77,113,.40)');
  assert.equal(legend[1].member,false);
  const members=api.groups(chart).filter(x=>x.member);
  for(let i=0;i<38;i++)click(panel(),button(panel(),'toggle',members[i].key));
  const reduced=png.legendEntries(chart);
  assert.equal(reduced[1].label,'12 EPS-Mitglieder');
  assert.equal(png.visibleEntries(chart).filter(x=>x.member).length,12);
  click(panel(),button(panel(),'members-off'));
  assert.ok(!png.legendEntries(chart).some(x=>x.label.includes('Mitglieder')));
  assert.ok(png.legendEntries(chart).some(x=>x.label==='EPS-Mittel'));
});

test('PNG legend summarizes GEFS c00-c30 without affecting individual controls',()=>{
  const members=Array.from({length:31},(_,i)=>({
    label:'_GEFS_c'+String(i).padStart(2,'0'),
    data:[i,i+1],borderColor:'rgba(35,46,62,.48)'
  }));
  const {chart,panel}=fixture([
    ...members,
    {label:'GEFS · Ensemble-Mittel',data:[1,2],borderColor:'#d62828'},
    {label:'GEFS · Kontrolllauf',data:[1,3],borderColor:'#ef9b10'}
  ],'stratoGefsSummary31Test');
  assert.deepEqual(Array.from(png.legendEntries(chart),x=>x.label),[
    '31 GEFS-Mitglieder','GEFS · Ensemble-Mittel','GEFS · Kontrolllauf'
  ]);
  const visible=api.groups(chart).filter(x=>x.member);
  for(let i=0;i<24;i++)click(panel(),button(panel(),'toggle',visible[i].key));
  assert.equal(png.legendEntries(chart)[0].label,'7 GEFS-Mitglieder');
});


test('Übersicht, Ensemble und Individuell independently control full GEFS chart and redraws',()=>{
  const data=[
    {label:'_GEFS 5–95 % Untergrenze',data:[0,1],borderColor:'transparent'},
    {label:'GEFS 5–95 %',data:[3,4],fill:{target:'-1',above:'#2266aa33'}},
    {label:'_GEFS 25–75 % Untergrenze',data:[1,2],borderColor:'transparent'},
    {label:'GEFS 25–75 %',data:[2,3],fill:{target:'-1',above:'#2266aa66'}},
    {label:'_c00',data:[1,2],borderColor:'#223344'},
    {label:'_c01',data:[2,3],borderColor:'#223344'},
    {label:'GEFS · Ensemble-Mittel',data:[2,4],borderColor:'#1665ad'},
    {label:'Kontrolllauf',data:[1,5],borderColor:'#d59221'},
    {label:'0 m/s · Windumkehrschwelle',data:[0,0],borderColor:'#333333'}
  ];
  const id='stratoEnsembleCanvas';
  const first=fixture(data,id);
  let profile=button(first.panel(),'profile','overview');
  assert.ok(profile,'Overview option must exist on GEFS chart');
  click(first.panel(),profile);
  assert.equal(first.chart.isDatasetVisible(0),true);
  assert.equal(first.chart.isDatasetVisible(1),true);
  assert.equal(first.chart.isDatasetVisible(2),false);
  assert.equal(first.chart.isDatasetVisible(3),false);
  assert.equal(first.chart.isDatasetVisible(4),false);
  assert.equal(first.chart.isDatasetVisible(5),false);
  assert.equal(first.chart.isDatasetVisible(6),true);
  assert.equal(api.profileSelections.get(id),'overview');
  plugin.beforeDestroy(first.chart);
  const recreated=fixture(data,id);
  assert.equal(recreated.chart.isDatasetVisible(4),false,'Overview persists after chart re-creation');
  assert.equal(recreated.chart.isDatasetVisible(3),false);
  click(recreated.panel(),button(recreated.panel(),'profile','ensemble'));
  assert.equal(recreated.chart.isDatasetVisible(4),true);
  assert.equal(recreated.chart.isDatasetVisible(3),true);
  assert.equal(api.profileSelections.get(id),'ensemble');
  const group=api.groups(recreated.chart).find(g=>g.label==='c00');
  click(recreated.panel(),button(recreated.panel(),'toggle',group.key));
  assert.equal(api.profileSelections.get(id),'individual');
  assert.equal(recreated.chart.isDatasetVisible(4),false);
  assert.equal(recreated.chart.isDatasetVisible(5),true);
  click(recreated.panel(),button(recreated.panel(),'profile','individual'));
  assert.equal(recreated.chart.isDatasetVisible(4),false,'Custom mode keeps selection');
});
