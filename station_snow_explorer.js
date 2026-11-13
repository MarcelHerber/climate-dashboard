/* Climate Dashboard – fast DWD snow station explorer.
 * All catalogue operations use the index in memory; only selecting a station
 * is allowed to fetch its detailed daily profile / historical curves.
 * Leaflet is loaded lazily and stations are grid-clustered without third-party
 * cluster dependencies. Never treat missing measurement data as measured zero.
 */
(function(root){
  "use strict";
  const normalize=value=>String(value??"").normalize("NFD")
    .replace(/[\u0300-\u036f]/g,"").toLocaleLowerCase("de-DE").trim();
  const byId=id=>document.getElementById(id);
  const validCoordinate=s=>Number.isFinite(Number(s?.lat)) &&
    Number.isFinite(Number(s?.lon)) &&
    Number(s.lat)>=47 && Number(s.lat)<=56 &&
    Number(s.lon)>=5 && Number(s.lon)<=16;
  const isLong=s=>Number(s?.accepted_history_years||0)>=30;

  function rank(station,query){
    const q=normalize(query);
    if(!q)return 0;
    const name=normalize(station.name),id=String(station.id||"");
    if(id===q||name===q)return 0;
    if(id.startsWith(q))return 1;
    if(name.startsWith(q))return 2;
    if(name.split(/[\s-]+/).some(part=>part.startsWith(q)))return 3;
    if(name.includes(q))return 4;
    if(id.includes(q))return 5;
    return 100;
  }
  function suggestions(stations,query,limit=15){
    if(!normalize(query))return [];
    return stations.map(s=>({station:s,score:rank(s,query)}))
      .filter(item=>item.score<100)
      .sort((a,b)=>a.score-b.score ||
        Number(b.station.accepted_history_years||0)-Number(a.station.accepted_history_years||0) ||
        String(a.station.name).localeCompare(String(b.station.name),"de"))
      .slice(0,limit).map(item=>item.station);
  }

  function clusters(stations,project,cell=55){
    const groups=new Map();
    for(const station of stations){
      if(!validCoordinate(station))continue;
      const point=project(Number(station.lat),Number(station.lon));
      if(!point||!Number.isFinite(point.x)||!Number.isFinite(point.y))continue;
      // Stable pixel grid. Markers are merged ONLY while zoomed out.
      const key=Math.floor(point.x/cell)+":"+Math.floor(point.y/cell);
      const group=groups.get(key);
      if(group){
        group.count++;
        group.lat+=Number(station.lat);
        group.lon+=Number(station.lon);
        group.stations.push(station);
      }else groups.set(key,{
        count:1,lat:Number(station.lat),lon:Number(station.lon),
        stations:[station]
      });
    }
    // Neighboring grid cells can create overlapping clickable 40px icons.
    // Merge nearby centroids so mobile taps select the intended cluster.
    const output=[...groups.values()].map(group=>({
      count:group.count,lat:group.lat/group.count,lon:group.lon/group.count,
      stations:group.stations
    }));
    const minSeparation=48;
    let changed=true;
    while(changed){
      changed=false;
      outer: for(let i=0;i<output.length;i++){
        const a=output[i],pa=project(a.lat,a.lon);
        for(let j=i+1;j<output.length;j++){
          const b=output[j],pb=project(b.lat,b.lon);
          if(Math.hypot(pa.x-pb.x,pa.y-pb.y)>=minSeparation)continue;
          const count=a.count+b.count;
          a.lat=(a.lat*a.count+b.lat*b.count)/count;
          a.lon=(a.lon*a.count+b.lon*b.count)/count;
          a.count=count;a.stations.push(...b.stations);
          output.splice(j,1);changed=true;break outer;
        }
      }
    }
    return output;
  }
  const detailsFor=station=>{
    if(!station)return "";
    const observed=Number(station.observed_history_years||0);
    const accepted=Number(station.accepted_history_years||0);
    const reference=Number(station.reference_years_available||0);
    const current=!!station.current_available;
    const source=station.source?.includes("RR+KL")?"RR + KL · SH_TAG / SHK_TAG":station.source?.includes("RR")?"RR · SH_TAG":"KL · SHK_TAG";
    return {
      name:station.name,
      secondary:[station.state||"ohne Bundesland",
        station.height!==null && station.height!==undefined && Number.isFinite(Number(station.height))?Math.round(Number(station.height))+" m":"Höhe unbekannt",
        station.id].join(" · "),
      detail:observed+" Jahre mit Tageswerten · "+accepted+" vollständig (≥98 %) · "+
        reference+"/30 Referenzjahre"+(current?" · aktuelle Saison":""),
      source
    };
  };

  let opts=null,all=[],currentMeta=new Map(),activeId=null,matched=[],map=null;
  let layer=null,selectedLayer=null,mapBusy=false,mapReady=false;
  let mapRefreshTimer=null,queryTimer=null,lastFilterText="";
  let initialized=false;
  const formatCount=n=>Number(n).toLocaleString("de-DE");

  function metadataFor(s){
    return {...s,current_available:currentMeta.get(String(s.id))?.current_available===true ||
      s.current_available===true};
  }
  function updateSelectedCard(){
    const el=byId("stationSnowSelectedMeta");
    if(!el)return;
    const station=all.find(s=>String(s.id)===String(activeId));
    if(!station){el.textContent="Keine Station ausgewählt.";return;}
    const d=detailsFor(metadataFor(station));
    el.replaceChildren();
    const strong=document.createElement("strong");
    strong.textContent=d.name+" ("+station.id+")";
    const summary=document.createElement("span");
    summary.textContent=d.secondary+" · "+d.detail+" · "+d.source;
    el.append(strong,summary);
  }

  function renderSuggestions(){
    const list=byId("stationSnowSuggestions");
    const search=byId("stationSnowSearch");
    if(!list||!search)return;
    const query=search.value.trim();
    const matches=query?suggestions(matched,query,15):[];
    list.replaceChildren();
    if(!query||!matches.length){
      list.hidden=true;
      search.setAttribute("aria-expanded","false");
      return;
    }
    const fragment=document.createDocumentFragment();
    for(const station of matches){
      const data=detailsFor(metadataFor(station));
      const button=document.createElement("button");
      button.type="button";
      button.className="station-snow-suggestion";
      button.setAttribute("role","option");
      button.dataset.stationId=String(station.id);
      const name=document.createElement("strong");
      name.textContent=data.name+" ("+station.id+")";
      const meta=document.createElement("small");
      meta.textContent=data.secondary+" · "+data.detail;
      button.append(name,meta);
      button.addEventListener("click",()=>{
        list.hidden=true;
        search.setAttribute("aria-expanded","false");
        opts?.onSelect?.(String(station.id));
      });
      fragment.appendChild(button);
    }
    list.appendChild(fragment);
    list.hidden=false;
    search.setAttribute("aria-expanded","true");
  }

  function scheduleMapRefresh(){
    if(mapRefreshTimer)clearTimeout(mapRefreshTimer);
    mapRefreshTimer=setTimeout(()=>{mapRefreshTimer=null;renderMap()},110);
  }

  function update(stations,selectedId,allStations,currentLookup){
    if(Array.isArray(allStations))all=allStations;
    if(currentLookup instanceof Map)currentMeta=currentLookup;
    matched=Array.isArray(stations)?stations:[];
    activeId=selectedId||null;
    updateSelectedCard();
    renderSuggestions();
    scheduleMapRefresh();
  }
  function onSearchInput(){
    if(queryTimer)clearTimeout(queryTimer);
    queryTimer=setTimeout(()=>{
      queryTimer=null;
      // Chart is NOT updated here; this updates only the compact option list.
      opts?.onSearchChanged?.();
    },140);
  }
  function hideSuggestions(){
    const list=byId("stationSnowSuggestions");
    if(list)list.hidden=true;
    byId("stationSnowSearch")?.setAttribute("aria-expanded","false");
  }

  function makeMapSelected(station){
    if(!map||!root.L||!validCoordinate(station))return;
    if(selectedLayer){selectedLayer.remove();selectedLayer=null;}
    selectedLayer=root.L.circleMarker([station.lat,station.lon],{
      radius:10,color:"#15365f",weight:3,fillColor:"#fbbf24",fillOpacity:.95,
      interactive:false
    }).addTo(map);
  }

  function renderMap(){
    if(!mapReady||!map||!layer)return;
    const target=byId("stationSnowMap");
    const details=byId("stationSnowMapDetails");
    if(!target||!details?.open||!target.offsetWidth)return;
    map.invalidateSize({animate:false});
    layer.clearLayers();
    const stations=matched.filter(validCoordinate);
    const status=byId("stationSnowMapStatus");
    if(!stations.length){
      if(status)status.textContent="Für diese Filter sind keine Stationen mit Kartokoordinaten verfügbar.";
      if(selectedLayer){selectedLayer.remove();selectedLayer=null;}
      return;
    }
    // Map projection is only needed for point grouping. O(N), independent of
    // expensive per-station snow history files.
    const groups=clusters(stations,(lat,lon)=>map.latLngToLayerPoint([lat,lon]),
      map.getZoom()>=10?25:map.getZoom()>=8?40:65);
    const leaflet=root.L;
    const zoom=map.getZoom();
    for(const item of groups){
      if(item.count===1){
        const station=item.stations[0];
        const chosen=String(station.id)===String(activeId);
        const marker=leaflet.circleMarker([station.lat,station.lon],{
          radius:chosen?7:5,weight:chosen?2.5:1.2,
          color:chosen?"#15365f":"#e3f2f7",
          fillColor:chosen?"#f9ad26":"#176ca0",fillOpacity:.88
        });
        marker.bindTooltip(station.name+" ("+station.id+") · "+
          Number(station.accepted_history_years||0)+" vollständige Jahre");
        marker.on("click",()=>opts?.onSelect?.(String(station.id)));
        marker.addTo(layer);
      }else{
        const count=item.count;
        const clusterIcon=leaflet.divIcon({
          className:"station-snow-cluster-icon",
          html:'<span aria-hidden="true">'+formatCount(count)+"</span>",
          iconSize:[36,36],iconAnchor:[18,18]
        });
        const group=leaflet.marker([item.lat,item.lon],{icon:clusterIcon,
          keyboard:true,title:formatCount(count)+" Schneestationen"});
        group.on("click",()=>{
          // Each cluster drills down; at high zoom same-location stations can
          // still be picked using the search rather than silently selecting.
          if(map.getZoom()<12){
            map.setView([item.lat,item.lon],Math.min(map.getZoom()+2,12),{animate:false});
          }else{
            const candidates=item.stations.slice().sort((a,b)=>
              String(a.name).localeCompare(String(b.name),"de"));
            const popup=document.createElement("div");
            popup.className="station-snow-cluster-popup";
            const heading=document.createElement("strong");
            heading.textContent=count+" Stationen an diesem Kartenpunkt";
            popup.appendChild(heading);
            for(const s of candidates.slice(0,20)){
              const b=document.createElement("button");b.type="button";
              b.textContent=s.name+" · "+s.id;
              b.addEventListener("click",()=>{
                map.closePopup();opts?.onSelect?.(String(s.id));
              });
              popup.appendChild(b);
            }
            if(count>20){
              const note=document.createElement("small");
              note.textContent="Weitere Stationen über die Suche auswählen.";
              popup.appendChild(note);
            }
            group.bindPopup(popup).openPopup();
          }
        });
        group.addTo(layer);
      }
    }
    const selected=all.find(s=>String(s.id)===String(activeId));
    if(selected)makeMapSelected(selected);
    if(status)status.textContent=formatCount(stations.length)+" Stationen mit Koordinaten · "+
      formatCount(groups.length)+" Marker/Cluster · Klick auf Punkt oder Cluster zur Auswahl.";
  }

  async function createMap(){
    if(mapBusy||mapReady)return;
    const container=byId("stationSnowMap");
    if(!container||!byId("stationSnowMapDetails")?.open)return;
    mapBusy=true;
    const status=byId("stationSnowMapStatus");
    if(status)status.textContent="Deutschlandkarte und Stationscluster werden geladen …";
    try{
      const L=root.L?.map?root.L:await root.ensureEuropeStationLeaflet?.();
      if(!L?.map)throw new Error("Kartenbibliothek nicht verfügbar");
      map=L.map(container,{preferCanvas:true,scrollWheelZoom:false,
        attributionControl:true,zoomControl:true,touchZoom:true,
        maxZoom:13,minZoom:5,zoomSnap:.5}).setView([51.1,10.35],6);
      map.getContainer().style.backgroundColor="#eaf1f5";
      layer=L.layerGroup().addTo(map);
      // Bundled Natural Earth data: no dependence on third-party map tiles.
      fetch("wettergefahren_basemap.json",{cache:"force-cache"})
        .then(response=>{if(!response.ok)throw new Error("HTTP "+response.status);return response.json();})
        .then(data=>{
          const countries=(data.countries||[]).filter(c=>Array.isArray(c.p)&&c.p.length);
          if(!countries.length)throw new Error("Keine Landgrenzen");
          const fc={type:"FeatureCollection",features:countries.map(c=>({
            type:"Feature",properties:{name:c.n},
            geometry:{type:"MultiPolygon",coordinates:c.p}
          }))};
          L.geoJSON(fc,{interactive:false,style:feature=>({
            color:feature.properties.name==="Germany"?"#4e687e":"#a6b5c2",
            weight:feature.properties.name==="Germany"?1.9:.7,
            fillColor:feature.properties.name==="Germany"?"#dbe8f0":"#f2f6fa",
            fillOpacity:1
          })}).addTo(map).bringToBack();
        }).catch(err=>{
          console.warn("Schneestationskarte ohne Landesgrenzen",err);
          if(status)status.textContent="Kartenumriss nicht erreichbar; Stationspunkte bleiben auswählbar.";
        });
      map.on("zoomend moveend",scheduleMapRefresh);
      mapReady=true;
      setTimeout(()=>{map?.invalidateSize({animate:false});renderMap()},130);
    }catch(error){
      if(status)status.textContent="Karte derzeit nicht verfügbar: "+error.message+
        ". Stationssuche und Diagramme funktionieren weiterhin.";
      console.warn("Schneestationskarte:",error);
    }finally{mapBusy=false;}
  }

  function init(options){
    if(initialized)return;
    initialized=true;
    opts=options;
    const search=byId("stationSnowSearch");
    if(search){
      search.setAttribute("role","combobox");
      search.setAttribute("aria-autocomplete","list");
      search.setAttribute("aria-controls","stationSnowSuggestions");
      search.setAttribute("aria-expanded","false");
      search.addEventListener("keydown",event=>{
        if(event.key==="Escape")hideSuggestions();
        else if(event.key==="Enter"){
          const button=byId("stationSnowSuggestions")?.querySelector("button");
          if(button){event.preventDefault();button.click();}
        }
      });
      search.addEventListener("blur",()=>setTimeout(hideSuggestions,180));
    }
    const details=byId("stationSnowMapDetails");
    if(details){
      details.open=!root.matchMedia?.("(max-width: 700px)").matches;
      details.addEventListener("toggle",()=>{
        if(details.open){
          createMap().then(()=>{map?.invalidateSize({animate:false});scheduleMapRefresh()});
        }
      });
      if(details.open)createMap();
    }
  }

  root.StationSnowExplorer={
    init,update,onSearchInput,renderMap,hideSuggestions,
    // Testable, deterministic business logic:
    normalize,rank,suggestions,clusters,validCoordinate,isLong,detailsFor,
    getState:()=>({
      initialized,mapReady,shown:matched.length,
      selectedId:activeId,mapZoom:mapReady?map.getZoom():null,clusterCount:mapReady?clusters(matched,
        (lat,lon)=>map.latLngToLayerPoint([lat,lon])).length:0
    })
  };
  if(typeof module!=="undefined"&&module.exports){
    module.exports={normalize,rank,suggestions,clusters,validCoordinate,isLong,detailsFor};
  }
})(typeof window!=="undefined"?window:globalThis);
