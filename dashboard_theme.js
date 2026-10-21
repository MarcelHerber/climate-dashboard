/* Climate Dashboard: persistenter Dunkel-/Hellmodus, Chart.js-lesbar und
   helle PNG/PDF-Chart-Exporte. Datenreihen und Farbcodierungen bleiben gleich. */
(() => {
  "use strict";
  const STORAGE_KEY="climateDashboardThemeV1";
  const root=document.documentElement;
  const media=window.matchMedia?.("(prefers-color-scheme: dark)");
  let exportingLight=false;
  const textColors=new WeakMap();

  function preference(){
    try {
      const stored=window.localStorage.getItem(STORAGE_KEY);
      if(stored==="dark" || stored==="light") return stored;
    }catch(_error){}
    return media?.matches?"dark":"light";
  }
  function isDark(){return root.dataset.theme==="dark";}
  function chartTheme(){
    const dark=isDark()&&!exportingLight;
    return dark
      ? {text:"#dce8f7",grid:"rgba(161,185,213,.17)",border:"rgba(161,185,213,.38)"}
      : {text:"#666666",grid:"rgba(0,0,0,.10)",border:"rgba(0,0,0,.18)"};
  }
  function setChartDefaults(){
    if(!window.Chart)return;
    const theme=chartTheme();
    Chart.defaults.color=theme.text;
    Chart.defaults.borderColor=theme.grid;
  }
  function chartColors(chart){
    const mode=chartTheme();
    const options=chart.options;
    if(!options)return;
    if(!textColors.has(chart)){
      /* Only capture authored chart colors, not inherited dark Chart.defaults. */
      const authored=chart.config?.options||{};
      const plugins=authored.plugins||{};
      const scales=authored.scales||{};
      const original={
        title:plugins.title?.color,subtitle:plugins.subtitle?.color,
        legend:plugins.legend?.labels?.color,
        datalabels:plugins.datalabels?.color,axes:{}
      };
      for(const [key,axis] of Object.entries(scales)){
        original.axes[key]={
          ticks:axis?.ticks?.color,title:axis?.title?.color,
          grid:axis?.grid?.color,border:axis?.border?.color
        };
      }
      textColors.set(chart,original);
    }
    const first=textColors.get(chart);
    const dark=isDark()&&!exportingLight;
    const target=(saved,fallback)=>dark?fallback:(saved??fallback);
    if(options.plugins?.title){
      options.plugins.title.color=target(first.title,mode.text);
    }
    if(options.plugins?.subtitle){
      options.plugins.subtitle.color=target(first.subtitle,mode.text);
    }
    if(options.plugins?.legend?.labels){
      options.plugins.legend.labels.color=target(first.legend,mode.text);
    }
    if(options.plugins?.datalabels && typeof options.plugins.datalabels.color!=="function"){
      options.plugins.datalabels.color=target(first.datalabels,mode.text);
    }
    for(const [key,axis] of Object.entries(options.scales||{})){
      if(!axis)continue;
      const original=first.axes[key]||{};
      if(axis.ticks)axis.ticks.color=target(original.ticks,mode.text);
      if(axis.title)axis.title.color=target(original.title,mode.text);
      if(axis.grid)axis.grid.color=target(original.grid,mode.grid);
      if(axis.border)axis.border.color=target(original.border,mode.border);
    }
  }
  function refreshCharts(){
    if(!window.Chart)return;
    setChartDefaults();
    for(const chart of Object.values(Chart.instances||{})){
      try {chart.update("none");}
      catch(error){console.warn("Dark Mode: Chart-Aktualisierung:",error);}
    }
  }
  function updateButton(){
    const button=document.getElementById("dashboardThemeToggle");
    if(!button)return;
    const dark=isDark();
    button.setAttribute("aria-pressed",String(dark));
    button.setAttribute("aria-label",dark?"Hellen Modus einschalten":"Dark Mode einschalten");
    button.title=dark?"Hellen Modus einschalten":"Dark Mode einschalten";
    const label=button.querySelector(".action-label");
    if(label)label.textContent=dark?"Hell":"Dunkel";
    const svg=button.querySelector(".header-icon");
    if(svg)svg.innerHTML=dark
      ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32 1.41 1.41M2 12h2m16 0h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>'
      : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.5 13a8.5 8.5 0 0 1-9.5-9.5A8.5 8.5 0 1 0 20.5 13Z"/></svg>';
  }
  function apply(theme,save=false){
    root.dataset.theme=theme==="dark"?"dark":"light";
    if(save){try{localStorage.setItem(STORAGE_KEY,root.dataset.theme);}catch(_error){}}
    updateButton();
    refreshCharts();
    document.dispatchEvent(new CustomEvent("dashboardthemechange",{detail:{theme:root.dataset.theme}}));
  }
  function setup(){
    const button=document.getElementById("dashboardThemeToggle");
    button?.addEventListener("click",()=>{
      apply(isDark()?"light":"dark",true);
    });
    apply(preference());
  }
  if(window.Chart){
    Chart.register({
      id:"dashboardColorMode",
      beforeUpdate(chart){chartColors(chart);}
    });
    setChartDefaults();
  }
  /* Main dashboard exports call this synchronous helper. Redraw the axes and
     legend temporarily in dark-on-white, copy to the white export canvas,
     then immediately restore the on-screen dark version. */
  if(typeof window.chartCanvasWithWhiteBackground==="function"){
    const originalCopy=window.chartCanvasWithWhiteBackground;
    window.chartCanvasWithWhiteBackground=function(chart){
      if(!isDark())return originalCopy(chart);
      exportingLight=true;
      try{
        setChartDefaults();
        chart.update("none");
        return originalCopy(chart);
      }finally{
        exportingLight=false;
        setChartDefaults();
        chart.update("none");
      }
    };
  }
  if(media){
    const onChange=()=>{try{
      if(localStorage.getItem(STORAGE_KEY))return;
    }catch(_error){}
      apply(preference());
    };
    if(media.addEventListener)media.addEventListener("change",onChange);
    else if(media.addListener)media.addListener(onChange);
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",setup,{once:true});
  else setup();
})();