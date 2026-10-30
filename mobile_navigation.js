/* Climate Dashboard Deutschland: one mobile-only, site-wide navigation.
   Desktop menus, scientific data and chart logic remain unchanged. */
(() => {
  "use strict";
  const LABEL="Climate Dashboard";
  const RECENT_KEY="climateDashboardMobileRecentV1";
  const MAX_RECENT=5;
  const CATEGORIES=[
    {id:"germany",name:"Deutschland",items:[
      ["monthly","Gebietsmittel"],["index","Klima-Index"],["accumulation","Seit Jahresbeginn"],
      ["hyras","HYRAS-Flächenkarten"],["daily","Tageshöchstwerte"],["extremes","Deutschland-Kenntage"],
      ["jahresextremwerte.html","Jahresextreme"],["dekadenrekorde.html","Dekadenrekorde"],
      ["feiertagsextremwerte.html","Feiertags-Extreme"]]},
    {id:"stations",name:"Stationen",items:[
      ["current","Aktuelle DWD-Stationen"],["stationObservations","Stations-Messwerte"],
      ["stationProfile","Stationsprofil"],["stationPrecip","Stationsniederschlag"],
      ["stationSnow","Schneehöhe"],["stationClimateDays","Stations-Kenntage"],
      ["stationHeatwaves","Stations-Hitzewellen"],["maps","Stationskarten"],["records","Stationsrekorde"]]},
    {id:"europe",name:"Europa & Prognosen",items:[
      ["europeHub","Europa-Überblick"],["europeStations","Europa-Stationen"],
      ["era5Europe","ERA5-Land Europa"],["era5Atmosphere","ERA5 Atmosphäre"],
      ["sst-europe","Meere / SST"],["t850-ensembles","Ensembleprognosen"],
      ["state-monthly-ensemble","Monatsausblick"],["saisonal_europa.html","Saisonale Prognose (SEAS5)"],
      ["wettergefahren.html","ICON-EU Wettergefahren"],["stratosphaere.html","Stratosphäre"],
      ["mosmix.html","MOSMIX"]]},
    {id:"synoptic",name:"Synoptik & Karten",items:[
      ["isobaren_original.html","Europa-Isobaren & Fronten"],
      ["weltweite_isobaren.html","Weltweite Isobaren"],
      ["tiefdruck_tracker.html","Tiefdruck-Tracker"]]},
    {id:"climate",name:"Klima & Indizes",items:[
      ["zirkulation.html","NAO, AO & Zirkulationsmuster"],["blocking.html","Blocking-Monitor"],
      ["enso.html","ENSO"],["qbo.html","QBO"],["mjo.html","MJO"],
      ["meereis.html","Meereis Arktis & Antarktis"],["eurasia_snow.html","Eurasien-Schnee"],
      ["ace.html","ACE · Tropische Wirbelstürme"]]},
    {id:"tools",name:"Weitere Werkzeuge",items:[
      ["compare","Vergleiche"],["datenstatus.html","Datenstatus"],["__alpenwetter__","Alpenwetter · geschützt"]]}
  ];
  const START={id:"overview",name:"Übersicht"};
  const flat=[START,...CATEGORIES.flatMap(g=>g.items.map(([id,name])=>({id,name,group:g.id,category:g.name})))];
  const byId=new Map(flat.map(x=>[x.id,x]));
  const isFile=id=>/^[a-zA-Z0-9_-]+\.html$/.test(id);
  const normalize=text=>String(text||"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase();
  function isHome(){
    const leaf=window.location.pathname.split("/").pop().toLowerCase();
    return !leaf||leaf==="index.html";
  }
  function current(){
    if(isHome()){
      const active=document.querySelector(".tab-content.active");
      const requested=decodeURIComponent((window.location.hash.match(/^#cd-tab=([^&]+)$/)||[])[1]||"");
      return byId.has(requested)?requested:active?.id||"overview";
    }
    return window.location.pathname.split("/").pop()||"overview";
  }
  function recent(){
    try{
      const data=JSON.parse(window.localStorage.getItem(RECENT_KEY)||"[]");
      return Array.isArray(data)?data.filter(id=>byId.has(id)).slice(0,MAX_RECENT):[];
    }catch(_){return [];}
  }
  function remember(id){
    if(!byId.has(id))return;
    const values=[id,...recent().filter(x=>x!==id)].slice(0,MAX_RECENT);
    try{window.localStorage.setItem(RECENT_KEY,JSON.stringify(values));}catch(_){}
  }
  function openItem(id){
    if(id==="__alpenwetter__"){
      close();
      if(isHome()&&typeof window.openAlpenwetter==="function"){window.openAlpenwetter();return;}
      window.location.assign("./index.html#cd-alpenwetter");
      return;
    }
    if(id==="overview"||!isFile(id)){
      remember(id);close();
      if(isHome()&&typeof window.switchTab==="function"){
        window.switchTab(id);
        window.scrollTo({top:0,behavior:"instant"});
      }else{
        window.location.assign("./index.html#cd-tab="+encodeURIComponent(id));
      }
      return;
    }
    remember(id);close();
    if(window.location.pathname.split("/").pop()!==id){
      window.location.assign("./"+id);
    }else window.scrollTo({top:0,behavior:"instant"});
  }
  let root,trigger,overlay,dialog,searchInput,sections,results,recentBlock,returnFocus,oldOverflow="";
  function el(tag,className,text){
    const node=document.createElement(tag);
    if(className)node.className=className;
    if(text!==undefined)node.textContent=text;
    return node;
  }
  function link(item,kind=""){
    const b=el("button","cdm-item"+(kind?" "+kind:""));
    b.type="button";
    b.textContent=item.name;
    if(item.id===current())b.setAttribute("aria-current","page");
    b.addEventListener("click",()=>openItem(item.id));
    return b;
  }
  function updateRecent(){
    recentBlock.replaceChildren();
    const ids=recent().filter(id=>id!==current());
    recentBlock.hidden=ids.length===0;
    if(!ids.length)return;
    recentBlock.appendChild(el("h3","cdm-section-title","Zuletzt geöffnet"));
    const list=el("div","cdm-recent-list");
    for(const id of ids){
      const entry=byId.get(id);
      if(entry)list.appendChild(link(entry,"cdm-recent-item"));
    }
    recentBlock.appendChild(list);
  }
  function buildGroups(){
    sections.replaceChildren();
    const active=current();
    for(const group of CATEGORIES){
      const detail=el("details","cdm-category");
      const summary=el("summary","cdm-category-summary");
      summary.appendChild(el("span","cdm-category-name",group.name));
      summary.appendChild(el("span","cdm-category-count",String(group.items.length)));
      detail.appendChild(summary);
      const container=el("div","cdm-category-links");
      for(const [id,name] of group.items){
        const b=link({id,name});
        container.appendChild(b);
      }
      detail.appendChild(container);
      if(group.items.some(item=>item[0]===active))detail.open=true;
      detail.addEventListener("toggle",()=>{
        if(!detail.open)return;
        sections.querySelectorAll("details.cdm-category").forEach(other=>{
          if(other!==detail)other.open=false;
        });
      });
      sections.appendChild(detail);
    }
  }
  function showSearch(){
    const term=normalize(searchInput.value.trim());
    const visible=term.length>0;
    sections.hidden=visible;
    recentBlock.hidden=visible||!recent().filter(id=>id!==current()).length;
    results.hidden=!visible;
    results.replaceChildren();
    if(!visible)return;
    const matching=flat.filter(x=>normalize(x.name+" "+(x.category||"")+" "+x.id).includes(term));
    results.appendChild(el("h3","cdm-section-title","Suchergebnisse · "+matching.length));
    if(!matching.length){
      results.appendChild(el("p","cdm-empty","Keine passenden Bereiche gefunden."));
      return;
    }
    for(const item of matching){
      const b=link(item,"cdm-search-item");
      if(item.category)b.appendChild(el("small","cdm-search-group",item.category));
      results.appendChild(b);
    }
  }
  function focusables(){
    return [...dialog.querySelectorAll('button:not([disabled]), input:not([disabled]), summary')]
      .filter(x=>x.getClientRects().length>0);
  }
  function handleKey(event){
    if(event.key==="Escape"){event.preventDefault();close();return;}
    if(event.key!=="Tab")return;
    const list=focusables();
    if(!list.length)return;
    const first=list[0],last=list[list.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
  }
  function open(){
    if(!overlay||!window.matchMedia("(max-width: 800px)").matches)return;
    returnFocus=document.activeElement;
    overlay.hidden=false;
    oldOverflow=document.body.style.overflow;
    document.body.style.overflow="hidden";
    trigger.setAttribute("aria-expanded","true");
    buildGroups();
    updateRecent();
    searchInput.value="";
    showSearch();
    document.addEventListener("keydown",handleKey);
    searchInput.focus();
  }
  function close(){
    if(!overlay||overlay.hidden)return;
    overlay.hidden=true;
    document.body.style.overflow=oldOverflow;
    trigger.setAttribute("aria-expanded","false");
    document.removeEventListener("keydown",handleKey);
    returnFocus?.focus?.();
  }
  function createInterface(){
    if(document.getElementById("cdMobileNav"))return;
    const home=isHome();
    document.body.classList.add("cd-mobile-ready");
    document.body.classList.toggle("cd-mobile-home",home);
    root=el("div","cdm-root");
    root.id="cdMobileNav";
    const mobileBar=el("div","cdm-mobile-bar");
    mobileBar.setAttribute("role","navigation");
    mobileBar.setAttribute("aria-label","Mobile Seitennavigation");
    const brand=el("a","cdm-brand",LABEL);
    brand.href="./index.html";
    brand.setAttribute("aria-label","Climate Dashboard – Startseite");
    mobileBar.appendChild(brand);
    const headerActions=home?document.querySelector(".dashboard-header .header-actions"):null;
    trigger=el("button","cdm-trigger");
    trigger.id="cdMobileMenuButton";
    trigger.type="button";
    trigger.setAttribute("aria-label","Navigationsmenü öffnen");
    trigger.setAttribute("aria-controls","cdMobileMenu");
    trigger.setAttribute("aria-expanded","false");
    const bars=el("span","cdm-menu-bars");bars.setAttribute("aria-hidden","true");
    trigger.appendChild(bars);trigger.appendChild(el("span","cdm-menu-caption","Menü"));
    trigger.addEventListener("click",()=>overlay.hidden?open():close());
    if(headerActions){
      headerActions.appendChild(trigger);
    }else{
      mobileBar.appendChild(trigger);
      root.appendChild(mobileBar);
      document.body.insertBefore(root,document.body.firstChild);
    }
    overlay=el("div","cdm-overlay");overlay.hidden=true;overlay.id="cdMobileMenu";
    const backdrop=el("button","cdm-backdrop");
    backdrop.type="button";backdrop.setAttribute("aria-label","Menü schließen");
    backdrop.addEventListener("click",close);overlay.appendChild(backdrop);
    dialog=el("aside","cdm-drawer");dialog.setAttribute("role","dialog");
    dialog.setAttribute("aria-modal","true");dialog.setAttribute("aria-label","Climate Dashboard Navigation");
    const heading=el("div","cdm-drawer-head");
    const title=el("div","cdm-drawer-title");
    title.appendChild(el("strong","",LABEL));title.appendChild(el("small","","Alle Wetter- und Klimabereiche"));
    heading.appendChild(title);
    const closeBtn=el("button","cdm-close","✕");closeBtn.type="button";
    closeBtn.setAttribute("aria-label","Menü schließen");closeBtn.addEventListener("click",close);
    heading.appendChild(closeBtn);dialog.appendChild(heading);
    const scroll=el("div","cdm-drawer-scroll");
    const searchWrap=el("label","cdm-search-label");
    searchWrap.appendChild(el("span","","Bereich suchen"));
    searchInput=el("input","cdm-search");searchInput.type="search";
    searchInput.placeholder="z. B. HYRAS, Isobaren, ENSO";
    searchInput.autocomplete="off";searchInput.setAttribute("aria-label","Alle Bereiche durchsuchen");
    searchInput.addEventListener("input",showSearch);
    searchWrap.appendChild(searchInput);scroll.appendChild(searchWrap);
    scroll.appendChild(link(START,"cdm-home-link"));
    recentBlock=el("section","cdm-recent");scroll.appendChild(recentBlock);
    sections=el("div","cdm-sections");scroll.appendChild(sections);
    results=el("div","cdm-results");results.hidden=true;scroll.appendChild(results);
    dialog.appendChild(scroll);overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    window.addEventListener("resize",()=>{
      if(!window.matchMedia("(max-width: 800px)").matches)close();
    },{passive:true});
  }
  function deepLink(){
    if(!isHome())return;
    const hash=window.location.hash;
    const found=hash.match(/^#cd-tab=([^&]+)$/);
    if(found){
      const id=decodeURIComponent(found[1]);
      if(byId.has(id)&&!isFile(id)&&typeof window.switchTab==="function"){
        window.switchTab(id);
        remember(id);
      }
    }else if(hash==="#cd-alpenwetter"&&typeof window.openAlpenwetter==="function"){
      window.openAlpenwetter();
    }
  }
  function init(){
    createInterface();
    if(isHome()){
      // The dashboard initializes its own preferred tab during document parsing;
      // apply cross-page deep links after all scripts have finished loading.
      if(document.readyState==="complete")deepLink();
      else window.addEventListener("load",deepLink,{once:true});
    }else{
      const page=current();
      if(byId.has(page))remember(page);
    }
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});
  else init();
})();