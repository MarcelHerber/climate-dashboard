(function(root){
  'use strict';
  const levels=[-6,-5,-4,-3,-2,-1,-.5,0,.5,1,2,3,4,5,6];
  const colors=['#6B03C6','#5E4FFC','#187DFD','#70B1FB','#C6E4FB','#DDEBF9','#EDF4FA','#FDFCFC','#FDF0BC','#FDE47C','#FDBD3E','#FC691C','#F93A19','#E51B75','#FC579B'];
  const rgb=colors.map(c=>[parseInt(c.slice(1,3),16),parseInt(c.slice(3,5),16),parseInt(c.slice(5,7),16)]);
  const boundaries=levels.slice(1).map((v,i)=>(v+levels[i])/2);
  function mapForReference(entry,ref,start,end){
    if((entry?.start_date&&start&&entry.start_date!==start)||(entry?.end_date&&end&&entry.end_date!==end))return null;
    return entry?.anomaly_by_reference?.[ref]||(ref==='1991-2020'?entry?.anomaly:null)||null;
  }
  function decodePlane(buffer,width,height){
    if(!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||buffer.byteLength!==2*width*height)throw Error('HYRAS-Rastergröße stimmt nicht');
    return {view:new DataView(buffer),width,height};
  }
  function cellAt(plane,x,y){
    if(!Number.isFinite(x)||!Number.isFinite(y)||x<0||x>=1||y<0||y>=1)return null;
    const v=plane.view.getInt16(2*(Math.floor(y*plane.height)*plane.width+Math.floor(x*plane.width)),true);
    return v===-32768?null:v/100;
  }
  function exactRaster(entry,ref,start,end){
    const dates=entry?.raster_dates_by_reference?.[ref];
    return dates?.[0]===start&&dates?.[1]===end&&entry.raster_by_reference?.[ref]&&entry.raster_grid ? {path:entry.raster_by_reference[ref],grid:entry.raster_grid}:null;
  }
  async function response(url){const r=await fetch(url);if(!r.ok)throw Error('HYRAS HTTP '+r.status);return r;}
  async function findRaster(cfg){
    const found=exactRaster(cfg.entry,cfg.reference,cfg.start,cfg.end);if(found)return found;
    if(cfg.parameter!=='tmean')return null;
    const index=await (await response(cfg.base+'/tmean/index.json?v='+encodeURIComponent(cfg.version))).json();
    const period=index.periods?.find(p=>p.key===cfg.key&&p.start_date===cfg.start&&p.end_date===cfg.end);
    const path=mapForReference(period,cfg.reference);
    return path&&index.grid_1km?{path,grid:index.grid_1km}:null;
  }
  async function mount(panel,cfg){
    if(!panel)return;
    const status=panel.querySelector('.hyras-temperature-raster-status');
    const live=()=>panel.isConnected;
    try{
      const item=await findRaster(cfg);if(!live())return;
      if(!item){status.textContent='Numerische Rasterabfrage für diesen Zeitraum noch nicht verfügbar.';return;}
      const r=await response(cfg.base+'/'+cfg.parameter+'/'+item.path+'?v='+encodeURIComponent(cfg.version));
      const compressed=await r.arrayBuffer();
      const raw=await new Response(new Blob([compressed]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
      const plane=decodePlane(raw,Number(item.grid.width),Number(item.grid.height));
      if(!live())return;
      const canvas=document.createElement('canvas');canvas.width=plane.width;canvas.height=plane.height;
      canvas.className='hyras-temperature-native-canvas';canvas.setAttribute('aria-label','Interaktive Deutschlandkarte, Temperaturabweichung in Kelvin');
      const ctx=canvas.getContext('2d'),pixels=ctx.createImageData(plane.width,plane.height);
      for(let i=0;i<plane.width*plane.height;i++){
        const q=plane.view.getInt16(i*2,true);if(q===-32768)continue;
        const value=q/100;let k=0;while(k<boundaries.length&&value>=boundaries[k])k++;
        pixels.data.set([...rgb[k],255],i*4);
      }
      ctx.putImageData(pixels,0,0);
      if(cfg.boundary){try{const bitmap=await createImageBitmap(await (await response(cfg.base+'/'+cfg.boundary)).blob());if(bitmap.width===plane.width&&bitmap.height===plane.height)ctx.drawImage(bitmap,0,0);bitmap.close();}catch(error){console.warn('HYRAS Grenzmaske',error);}}
      if(!live())return;
      const legend=document.createElement('div');legend.className='hyras-dynamic-legend hyras-temperature-native-legend';
      levels.forEach((v,i)=>{const span=document.createElement('span'),swatch=document.createElement('i');swatch.style.background=colors[i];span.append(swatch,document.createTextNode((v>0?'+':'')+String(v).replace('.',',')+' K'));legend.append(span);});
      const display=document.createElement('div');display.className='hyras-temperature-raster-value';display.textContent='Maus über die Karte bewegen oder Rasterzelle antippen';display.setAttribute('aria-live','polite');
      const inspect=event=>{const rect=canvas.getBoundingClientRect();const v=cellAt(plane,(event.clientX-rect.left)/rect.width,(event.clientY-rect.top)/rect.height);display.textContent=v===null?'Keine Daten für diese Rasterzelle':`Abweichung: ${v>0?'+':''}${v.toFixed(2).replace('.',',')} K`;};
      canvas.addEventListener('pointermove',e=>{if(e.pointerType==='mouse')inspect(e);});canvas.addEventListener('pointerup',inspect);
      const native=document.createElement('div');native.className='hyras-temperature-native';native.append(canvas,legend,display);
      const image=panel.querySelector('.hyras-tmean-anomaly-preview-link');if(image)image.hidden=true;
      const empty=panel.querySelector('.hyras-tmean-anomaly-preview-empty');if(empty)empty.hidden=true;
      status.before(native);status.textContent='DWD HYRAS-DE · Originalraster 1 km · '+cfg.reference.replace('-','–');
    }catch(error){if(live()){status.textContent='Rasterabfrage derzeit nicht verfügbar – vorhandene Karte bleibt sichtbar.';console.warn('HYRAS Temperatur-Raster:',error);}}
  }
  const api={mapForReference,cellAt,decodePlane,exactRaster,mount};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.HyrasTemperatureInteractive=api;
})(typeof globalThis==='object'?globalThis:this);
