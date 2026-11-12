/* Climate Bars 2.0: modern red/blue charts, without changing data or orientation.
   This Chart.js plugin targets only the two Gebietsmittel bar canvases.
   The visuals are rendered on canvas and preserved in PNG/PDF exports. */
(() => {
  "use strict";
  if(!window.Chart || typeof window.Chart.register!=="function")return;
  const TARGETS=new Set(["monthlyChart","monthlyDeviationChart"]);
  const COLORS={
    temp:{high:[199,62,69],low:[39,103,190]},
    rain:{high:[39,111,184],low:[180,113,57]},
    sun:{high:[221,159,46],low:[86,120,167]}
  };
  const NEUTRAL=[129,145,163];
  const number=value=>{
    if(value===null||value===undefined||value==="")return null;
    const num=Number(value);
    return Number.isFinite(num)?num:null;
  };
  const rgba=(rgb,alpha)=>"rgba("+rgb.join(",")+","+Math.max(0,Math.min(1,alpha)).toFixed(3)+")";
  const format=value=>Number(value).toLocaleString("de-DE",{maximumFractionDigits:1});
  const isTarget=chart=>TARGETS.has(chart?.canvas?.id);
  const isDeviation=chart=>chart.canvas.id==="monthlyDeviationChart";
  const param=()=>document.getElementById("paramSelect")?.value||"temp";
  const isDark=()=>document.documentElement.dataset.theme==="dark";
  const unit=parameter=>parameter==="temp"?"°C":parameter==="rain"?"mm":"h";
  function baseline(chart){
    const mean=chart.data.datasets.find(ds=>ds.type==="line"&&/^Mittel\s/.test(ds.label||""));
    return number(mean?.data?.[0]);
  }
  function delta(chart,value,reference){
    return value===null?null:(isDeviation(chart)?value:reference===null?null:value-reference);
  }
  function shade(parameter,deviation,maximum,dim){
    if(deviation===null)return rgba(NEUTRAL,dim?.25:.68);
    if(Math.abs(deviation)<1e-9)return rgba(NEUTRAL,dim?.24:.76);
    const colors=COLORS[parameter]||COLORS.temp;
    const rgb=deviation>0?colors.high:colors.low;
    const intensity=maximum>0?Math.min(1,Math.abs(deviation)/maximum):.6;
    return rgba(rgb,dim?.22:.78+.20*intensity);
  }
  function primaryChart(chart){
    if(!isDeviation(chart))return chart;
    return window.Chart.getChart?.(document.getElementById("monthlyChart"))||chart;
  }
  function tooltipCallbacks(chart){
    return {
      title:items=>"Jahr "+(items[0]?.label??"–"),
      label:ctx=>{
        const val=number(ctx.raw);
        return " "+ctx.dataset.label+": "+(val===null?"–":format(val)+" "+unit(param()));
      },
      afterLabel:ctx=>{
        if(ctx.datasetIndex!==0)return [];
        const parameter=param(),main=primaryChart(chart);
        const actual=number(main?.data?.datasets?.[0]?.data?.[ctx.dataIndex]);
        const average=baseline(main);
        const difference=isDeviation(chart)?number(ctx.raw):delta(chart,number(ctx.raw),average);
        const rows=[];
        if(isDeviation(chart)&&actual!==null)rows.push("Jahreswert: "+format(actual)+" "+unit(parameter));
        if(average!==null)rows.push("Klimamittel: "+format(average)+" "+unit(parameter));
        if(difference!==null)rows.push("Abweichung: "+(difference>0?"+":"")+format(difference)+" "+unit(parameter));
        const all=chart.data.datasets[0].data.map(number).filter(n=>n!==null);
        const value=number(ctx.raw);
        if(value!==null&&all.length>1){
          rows.push("Rang: "+(1+all.filter(n=>n>value).length)+" von "+all.length+" (absteigend)");
        }
        return rows;
      }
    };
  }
  const COLOR_KEYS={
    temp:["Wärmer als Mittel","Kälter als Mittel"],
    rain:["Nasser als Mittel","Trockener als Mittel"],
    sun:["Sonniger als Mittel","Weniger Sonne als im Mittel"]
  };
  // A chart-local key explains the anomalous coloring without replacing
  // Chart.js datasets, changing their direction, or creating new values.
  function ensureColorKey(chart,parameter){
    const host=chart.canvas?.closest?.(".chart-container")||chart.canvas?.parentElement;
    if(!host||typeof document.createElement!=="function")return;
    let key=chart.$climateKey;
    if(!key){
      key=document.createElement("div");
      key.className="monthly-climate-key";
      key.setAttribute("role","note");
      host.appendChild(key);
      chart.$climateKey=key;
    }
    if(key.dataset.parameter===parameter)return;
    key.dataset.parameter=parameter;
    const names=COLOR_KEYS[parameter]||COLOR_KEYS.temp;
    const explain=document.createElement("span");
    explain.className="monthly-climate-key-title";
    explain.textContent=isDeviation(chart)?"Abweichung zum Klimamittel":"Farben zeigen die Abweichung";
    const makeEntry=(polarity,label)=>{
      const entry=document.createElement("span");
      entry.className="monthly-climate-key-entry";
      const dot=document.createElement("span");
      dot.className="monthly-climate-key-dot";
      dot.dataset.polarity=polarity;
      dot.setAttribute("aria-hidden","true");
      const copy=document.createElement("span");
      copy.textContent=label;
      entry.append(dot,copy);
      return entry;
    };
    key.replaceChildren(explain,makeEntry("positive",names[0]),makeEntry("negative",names[1]));
    key.setAttribute("aria-label",explain.textContent+". "+names.join(". "));
  }
  // The long year series can be inspected with keyboard arrows as well as
  // mouse/touch. Chart.js keeps drawing its own tooltip and bar geometry.
  function keyboardFocus(chart,index){
    const data=chart.data?.datasets?.[0]?.data||[];
    if(index<0){
      chart.$climateFocus=-1;
      chart.setActiveElements?.([]);
      chart.tooltip?.setActiveElements?.([],{x:0,y:0});
      chart.update("none");
      return;
    }
    chart.$climateFocus=index;
    const elements=[{datasetIndex:0,index}];
    chart.setActiveElements?.(elements);
    const bar=chart.getDatasetMeta?.(0)?.data?.[index];
    const position=bar?.tooltipPosition?.()||{x:0,y:0};
    chart.tooltip?.setActiveElements?.(elements,position);
    chart.update("none");
  }
  function setupKeyboard(chart){
    if(chart.$climateKeyboardBound)return;
    chart.$climateKeyboardBound=true;
    if(!chart.canvas?.addEventListener)return;
    chart.canvas.tabIndex=0;
    chart.canvas.setAttribute?.("aria-label",
      "Gebietsmittel-Balkendiagramm. Mit Pfeiltasten Jahre auswählen; Escape beendet die Auswahl.");
    chart.canvas.addEventListener("keydown",event=>{
      if(event.key==="Escape" && chart.$climateFocus>=0){
        event.preventDefault();
        keyboardFocus(chart,-1);
        return;
      }
      if(event.key!=="ArrowLeft"&&event.key!=="ArrowRight")return;
      const data=chart.data?.datasets?.[0]?.data||[];
      if(!data.length)return;
      const shift=event.key==="ArrowRight"?1:-1;
      let index=chart.$climateFocus<0?(shift===1?-1:0):chart.$climateFocus;
      for(let n=0;n<data.length;n++){
        index=(index+shift+data.length)%data.length;
        if(number(data[index])!==null){
          event.preventDefault();
          keyboardFocus(chart,index);
          break;
        }
      }
    });
    chart.canvas.addEventListener("blur",()=>{
      if(chart.$climateFocus>=0)keyboardFocus(chart,-1);
    });
  }
  function setupHover(chart){
    if(chart.$climateBarsStyled)return;
    chart.$climateBarsStyled=true;
    chart.$climateFocus=-1;
    const oldHover=chart.options.onHover;
    chart.options.onHover=(event,elements,instance)=>{
      const focused=elements?.find(item=>item.datasetIndex===0)?.index??-1;
      if(focused!==chart.$climateFocus){
        chart.$climateFocus=focused;
        chart.update("none");
      }
      if(typeof oldHover==="function")oldHover(event,elements,instance);
    };
    chart.canvas.addEventListener("mouseleave",()=>{
      if(chart.$climateFocus!==-1){
        chart.$climateFocus=-1;
        chart.update("none");
      }
    },{passive:true});
  }
  window.Chart.register({
    id:"monthlyClimateBars2026",
    beforeUpdate(chart){
      if(!isTarget(chart))return;
      setupHover(chart);
      setupKeyboard(chart);
      ensureColorKey(chart,param());
      const datasets=chart.data.datasets;
      const bars=datasets[0];
      if(!bars)return;
      const parameter=param();
      const reference=baseline(chart);
      const differences=bars.data.map(value=>delta(chart,number(value),reference));
      const maximum=differences.reduce((max,value)=>value===null?max:Math.max(max,Math.abs(value)),0);
      bars.backgroundColor=differences.map((value,i)=>
        shade(parameter,value,maximum,chart.$climateFocus>=0&&chart.$climateFocus!==i));
      bars.hoverBackgroundColor=differences.map(value=>shade(parameter,value,maximum,false));
      // Styling only: no indexAxis, no changes to labels or observed values.
      bars.borderRadius=6;
      bars.borderSkipped=false;
      bars.borderWidth=0;
      bars.hoverBorderWidth=1.5;
      bars.hoverBorderColor=isDark()?"#eaf3ff":"#ffffff";
      bars.categoryPercentage=.84;
      bars.barPercentage=.82;
      bars.maxBarThickness=29;
      for(const extra of datasets.slice(1)){
        if(extra.type==="bar"){
          extra.borderRadius=6;
          extra.borderSkipped=false;
          extra.maxBarThickness=29;
        }
      }
      const opts=chart.options;
      if(!opts.layout)opts.layout={};
      opts.layout.padding={top:17,bottom:7};
      if(!opts.plugins)opts.plugins={};
      if(opts.plugins.title){
        opts.plugins.title.font={family:"system-ui, sans-serif",size:15,weight:"600"};
        opts.plugins.title.padding={top:6,bottom:16};
      }
      const legend=opts.plugins.legend||{};
      legend.position="bottom";
      if(!legend.labels)legend.labels={};
      legend.labels.usePointStyle=true;
      legend.labels.pointStyle="rectRounded";
      legend.labels.boxWidth=11;
      legend.labels.boxHeight=11;
      legend.labels.padding=18;
      legend.labels.font={family:"system-ui, sans-serif",size:12,weight:"500"};
      if(!opts.plugins.legend)opts.plugins.legend=legend;
      const tooltip=opts.plugins.tooltip||{};
      Object.assign(tooltip,{
        enabled:true,backgroundColor:"#17263c",titleColor:"#ffffff",bodyColor:"#f1f6fc",
        borderColor:"#5a7390",borderWidth:1,cornerRadius:10,padding:13,
        displayColors:true,titleFont:{size:13,weight:"700"},bodyFont:{size:12},
        callbacks:tooltipCallbacks(chart)
      });
      if(!opts.plugins.tooltip)opts.plugins.tooltip=tooltip;
      opts.plugins.datalabels={
        display:ctx=>{
          if(ctx.datasetIndex!==0)return false;
          if(number(ctx.dataset.data[ctx.dataIndex])===null)return false;
          const space=(ctx.chart.chartArea?.width||ctx.chart.width-75)/
                       Math.max(1,ctx.chart.data.labels.length);
          // Hundreds of years: labels would overlap; tooltip stays available.
          return space>=50&&ctx.chart.data.labels.length<=24;
        },
        formatter:value=>number(value)===null?"":format(value),
        anchor:"end",align:"end",offset:5,clamp:true,clip:false,
        backgroundColor:"rgba(255,255,255,.95)",color:()=>"#192d45",
        borderRadius:5,padding:{top:3,right:5,bottom:3,left:5},
        font:{family:"system-ui, sans-serif",size:11,weight:"700"}
      };
      const scales=opts.scales||{};
      if(scales.x){
        if(!scales.x.grid)scales.x.grid={};
        scales.x.grid.display=false;
        if(!scales.x.ticks)scales.x.ticks={};
        scales.x.ticks.maxRotation=0;
        scales.x.ticks.autoSkip=true;
        scales.x.ticks.font={family:"system-ui, sans-serif",size:11};
        if(!scales.x.border)scales.x.border={};
        scales.x.border.display=false;
      }
      if(scales.y){
        if(!scales.y.grid)scales.y.grid={};
        scales.y.grid.drawTicks=false;
        if(!scales.y.ticks)scales.y.ticks={};
        scales.y.ticks.padding=10;
        scales.y.ticks.font={family:"system-ui, sans-serif",size:11};
        if(!scales.y.border)scales.y.border={};
        scales.y.border.display=false;
        if(scales.y.title)scales.y.title.font={size:12,weight:"600"};
      }
    },
    afterDraw(chart){
      if(!isTarget(chart)||!isDeviation(chart))return;
      const yScale=chart.scales?.y,area=chart.chartArea;
      if(!yScale||!area||yScale.min>0||yScale.max<0)return;
      const y=yScale.getPixelForValue(0);
      if(!Number.isFinite(y)||y<area.top||y>area.bottom)return;
      const ctx=chart.ctx;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(area.left,y+.5);
      ctx.lineTo(area.right,y+.5);
      ctx.lineWidth=1.7;
      ctx.strokeStyle=isDark()?"rgba(179,196,220,.86)":"rgba(89,106,131,.76)";
      ctx.stroke();
      ctx.restore();
    }
  });
})();
