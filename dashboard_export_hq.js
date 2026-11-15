/* Climate Dashboard – print-quality exports independent of mobile viewport.
   Keeps source chart data and all scientific values unchanged. */
(function(root){
  "use strict";
  const WIDTH=2200, HEIGHT=1470, MARGIN=72, HEADER=168, FOOTER=118;
  // Select one timestamp per UTC day. Prefer midnight, but never change
  // the original categorical coordinates or forecast/tooltip timestamps.
  function forecastDateTicks(labels,min=0,max=labels.length-1,limit=9){
    const days=[];
    for(let i=Math.max(0,Math.ceil(min));i<=Math.min(labels.length-1,Math.floor(max));i++){
      const match=String(labels[i]??"").match(/^(\d{1,2}\.\d{1,2}\.)\s+(\d{2})Z$/i);
      if(!match)continue;
      const last=days[days.length-1];
      if(last?.text===match[1]){if(match[2]==="00")last.index=i;}
      else days.push({index:i,text:match[1]});
    }
    const step=Math.max(1,Math.ceil(days.length/Math.max(1,limit)));
    return days.filter((_,i)=>i%step===0);
  }
  function compactCanvas(source,metadata){
    const out=document.createElement("canvas");out.width=WIDTH;out.height=HEIGHT;
    const ctx=out.getContext("2d",{alpha:false});
    if(!ctx)throw Error("Export-Canvas konnte nicht erstellt werden.");
    ctx.fillStyle="#fff";ctx.fillRect(0,0,WIDTH,HEIGHT);ctx.textBaseline="top";
    ctx.fillStyle="#19324a";line(ctx,metadata.title,MARGIN,30,WIDTH-2*MARGIN,37,true);
    ctx.fillStyle="#58697c";line(ctx,metadata.subtitle,MARGIN,83,WIDTH-2*MARGIN,21,false);
    ctx.drawImage(source,MARGIN,122,WIDTH-2*MARGIN,HEIGHT-184);
    ctx.fillStyle="#52677b";line(ctx,metadata.source||"Climate Dashboard Deutschland",MARGIN,HEIGHT-42,WIDTH-2*MARGIN,18,false);
    return out;
  }
  function copy(value,seen){
    if(value===null || typeof value!=="object")return value;
    seen=seen||new WeakMap();
    if(seen.has(value))return seen.get(value);
    // Chart.js time scales and scientific series can contain Date objects.
    // A plain-object copy turns those into {}, breaking export timestamps.
    if(value instanceof Date){
      const result=new Date(value.getTime());seen.set(value,result);return result;
    }
    if(ArrayBuffer.isView(value) && !(value instanceof DataView)){
      const result=new value.constructor(value);seen.set(value,result);return result;
    }
    if(Array.isArray(value)){
      const result=[];seen.set(value,result);
      value.forEach((entry,i)=>{result[i]=copy(entry,seen);});
      return result;
    }
    const result={};seen.set(value,result);
    for(const key of Object.keys(value))result[key]=copy(value[key],seen);
    return result;
  }
  function line(ctx,text,x,y,maxWidth,size,bold){
    ctx.font=(bold?"700 ":"400 ")+size+"px Arial, Helvetica, sans-serif";
    ctx.fillText(String(text||""),x,y,maxWidth);
  }
  function composeCanvas(source,metadata){
    if(!source || !source.width || !source.height)throw Error("Grafik ist leer.");
    const out=document.createElement("canvas");
    out.width=WIDTH;out.height=HEIGHT;
    const ctx=out.getContext("2d",{alpha:false});
    if(!ctx)throw Error("Export-Canvas konnte nicht erstellt werden.");
    ctx.fillStyle="#ffffff";ctx.fillRect(0,0,WIDTH,HEIGHT);
    ctx.textBaseline="top";
    ctx.fillStyle="#19324a";
    line(ctx,metadata.title||"Climate Dashboard Deutschland",MARGIN,46,WIDTH-MARGIN*2,39,true);
    ctx.fillStyle="#58697c";
    line(ctx,metadata.subtitle||"Climate Dashboard Deutschland · hochauflösender Export",
      MARGIN,105,WIDTH-MARGIN*2,20,false);
    ctx.strokeStyle="#cfd9e4";ctx.lineWidth=2;
    ctx.beginPath();ctx.moveTo(MARGIN,145);ctx.lineTo(WIDTH-MARGIN,145);ctx.stroke();
    const availableW=WIDTH-MARGIN*2,availableH=HEIGHT-HEADER-FOOTER;
    const scale=Math.min(availableW/source.width,availableH/source.height);
    const drawW=source.width*scale,drawH=source.height*scale;
    ctx.drawImage(source,(WIDTH-drawW)/2,HEADER+(availableH-drawH)/2,drawW,drawH);
    ctx.strokeStyle="#cfd9e4";
    ctx.beginPath();ctx.moveTo(MARGIN,HEIGHT-FOOTER+12);
    ctx.lineTo(WIDTH-MARGIN,HEIGHT-FOOTER+12);ctx.stroke();
    ctx.fillStyle="#405369";
    const provenance=String(metadata.source||"Quelle und Bezugszeitraum: siehe Diagramm/Kartenlegende.");
    // Keep provenance readable, even for very long station or model names:
    // split into at most two short lines instead of horizontally squashing text.
    const lines=[];
    const ctxWidth=WIDTH-MARGIN*2;
    const words=provenance.split(/\s+/).filter(Boolean);
    let current="";
    ctx.font="400 19px Arial, Helvetica, sans-serif";
    for(const word of words){
      const next=current?current+" "+word:word;
      if(current&&ctx.measureText?.(next).width>ctxWidth){
        lines.push(current);current=word;
      }else current=next;
    }
    if(current)lines.push(current);
    for(let i=0;i<Math.min(2,lines.length);i++)
      line(ctx,lines[i],MARGIN,HEIGHT-FOOTER+27+i*25,ctxWidth,19,false);
    ctx.fillStyle="#52677b";
    line(ctx,"Erstellt: "+new Date().toLocaleString("de-DE")+" · Climate Dashboard Deutschland"
      +" · Werte und Einheiten unverändert",
      MARGIN,HEIGHT-FOOTER+83,ctxWidth,16,false);
    return out;
  }
  function renderChart(chart,metadata){
    if(!chart || !chart.data || !root.Chart)throw Error("Diagramm nicht verfügbar.");
    const canvas=document.createElement("canvas");
    canvas.width=WIDTH-MARGIN*2;canvas.height=metadata.compact?HEIGHT-184:HEIGHT-HEADER-FOOTER;
    const originalOptions=chart.config?._config?.options || chart.config?.options || {};
    const options=copy(originalOptions);
    options.responsive=false;
    options.maintainAspectRatio=false;
    options.animation=false;
    options.devicePixelRatio=1;
    options.plugins=options.plugins||{};
    // The site-wide mobile Chart.js plugin must not reduce export tick labels.
    options.plugins.climateMobileLegibilityV1=false;
    options.plugins.zoom=false;
    options.plugins.datalabels={display:false};
    if(metadata.compact){options.plugins.title={display:false};options.plugins.subtitle={display:false};}
    const legend=options.plugins.legend||{};
    if(metadata.showLegend){legend.display=true;legend.position="bottom";legend.labels=legend.labels||{};if(metadata.legendFilter)legend.labels.filter=metadata.legendFilter;}
    if(legend.display!==false){
      legend.display=true;
      legend.labels=legend.labels||{};
      legend.labels.font={...(legend.labels.font||{}),size:18};
      legend.labels.boxWidth=24;
      legend.labels.color="#22374d";
    }
    options.plugins.legend=legend;
    for(const [axis,config] of Object.entries(options.scales||{})){
      if(!config || typeof config!=="object")continue;
      config.ticks=config.ticks||{};
      if(config.ticks.display!==false && config.ticks.autoSkip!==false){
        config.ticks.maxTicksLimit=Math.max(Number(config.ticks.maxTicksLimit)||0,axis==="x"?17:10);
        config.ticks.maxRotation=axis==="x"?35:0;
      }
      if(metadata.preserveLimits){
        const scale=chart.scales?.[axis];
        if(Number.isFinite(scale?.min)&&Number.isFinite(scale?.max)){
          config.min=scale.min;config.max=scale.max;
        }
      }
      config.ticks.font={...(config.ticks.font||{}),size:19};
      config.ticks.color="#24384d";
      if(config.grid?.display!==false)config.grid={...(config.grid||{}),color:"#d9e1e8"};
      if(config.title?.display){
        config.title.font={...(config.title.font||{}),size:22};
        config.title.color="#24384d";
      }
    }
    if(options.plugins.title?.display){
      options.plugins.title.font={...(options.plugins.title.font||{}),size:25};
      options.plugins.title.padding=16;
      options.plugins.title.color="#19324a";
    }
    // Preserve user-controlled visibility without modifying the source chart.
    const datasets=chart.data.datasets.map((dataset,index)=>{
      const cloned=copy(dataset);
      cloned.hidden=typeof chart.isDatasetVisible==="function"
        ?!chart.isDatasetVisible(index):Boolean(dataset.hidden);
      return cloned;
    });
    const config={
      type:chart.config.type,
      data:{labels:copy(chart.data.labels),datasets},
      options
    };
    const scopedPlugins=chart.config?._config?.plugins;
    if(Array.isArray(scopedPlugins))config.plugins=scopedPlugins;
    let cloneChart;
    try{
      cloneChart=new root.Chart(canvas,config);
      if(typeof metadata.prepareChart==="function")metadata.prepareChart(cloneChart);
      cloneChart.update("none");
      return metadata.compact?compactCanvas(canvas,metadata):composeCanvas(canvas,metadata);
    }finally{
      if(cloneChart)cloneChart.destroy();
    }
  }
  function renderChartGroup(entries){
    if(!entries.length)throw Error("Keine Diagramme verfügbar.");
    if(entries.length===1)return renderChart(entries[0].chart,entries[0].metadata);
    // Stay below mobile canvas area limits even for five panels.
    const panelWidth=1800,panelHeight=Math.round(HEIGHT*panelWidth/WIDTH);
    const out=document.createElement("canvas");out.width=panelWidth*2;out.height=panelHeight*Math.ceil(entries.length/2);
    const ctx=out.getContext("2d",{alpha:false});ctx.fillStyle="#fff";ctx.fillRect(0,0,out.width,out.height);
    entries.forEach((entry,i)=>{
      const x=i===entries.length-1&&entries.length%2?panelWidth/2:(i%2)*panelWidth,y=Math.floor(i/2)*panelHeight;
      if(entry.chart)ctx.drawImage(renderChart(entry.chart,entry.metadata),x,y,panelWidth,panelHeight);
      else{ctx.fillStyle="#52677b";line(ctx,entry.metadata.title+" · keine Daten verfügbar",x+MARGIN,y+60,panelWidth-2*MARGIN,30,true);}
    });
    return out;
  }
  root.DashboardExportHQ=Object.freeze({copy,composeCanvas,renderChart,renderChartGroup,forecastDateTicks,WIDTH,HEIGHT});
})(window);
