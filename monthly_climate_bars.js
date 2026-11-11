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
      opts.layout=opts.layout||{};
      opts.layout.padding={top:17,bottom:7};
      opts.plugins=opts.plugins||{};
      if(opts.plugins.title){
        opts.plugins.title.font={family:"system-ui, sans-serif",size:15,weight:"600"};
        opts.plugins.title.padding={top:6,bottom:16};
      }
      const legend=opts.plugins.legend||{};
      legend.position="bottom";
      legend.labels=legend.labels||{};
      legend.labels.usePointStyle=true;
      legend.labels.pointStyle="rectRounded";
      legend.labels.boxWidth=11;
      legend.labels.boxHeight=11;
      legend.labels.padding=18;
      legend.labels.font={family:"system-ui, sans-serif",size:12,weight:"500"};
      opts.plugins.legend=legend;
      const tooltip=opts.plugins.tooltip||{};
      Object.assign(tooltip,{
        enabled:true,backgroundColor:"#17263c",titleColor:"#ffffff",bodyColor:"#f1f6fc",
        borderColor:"#5a7390",borderWidth:1,cornerRadius:10,padding:13,
        displayColors:true,titleFont:{size:13,weight:"700"},bodyFont:{size:12},
        callbacks:tooltipCallbacks(chart)
      });
      opts.plugins.tooltip=tooltip;
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
        scales.x.grid=scales.x.grid||{};
        scales.x.grid.display=false;
        scales.x.ticks=scales.x.ticks||{};
        scales.x.ticks.maxRotation=0;
        scales.x.ticks.autoSkip=true;
        scales.x.ticks.font={family:"system-ui, sans-serif",size:11};
        scales.x.border=scales.x.border||{};
        scales.x.border.display=false;
      }
      if(scales.y){
        scales.y.grid=scales.y.grid||{};
        scales.y.grid.drawTicks=false;
        scales.y.ticks=scales.y.ticks||{};
        scales.y.ticks.padding=10;
        scales.y.ticks.font={family:"system-ui, sans-serif",size:11};
        scales.y.border=scales.y.border||{};
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
