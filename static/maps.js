/* Leaflet street maps, road geometry and a clock that never simulates GPS. */
const mapRuntime = {maps:[], epoch:0, geometry:new Map()};
let clockOffset = 0;

function hasRoadLocations(){return state.problem.locations.every(l=>Number.isFinite(l.lat)&&Number.isFinite(l.lng));}
function needsRoadRefresh(){const p=state.problem,r=p.routing;if(r?.kind==='pending')return true;if(!r||r.kind!=='osrm')return false;return JSON.stringify(r.coordinates)!==JSON.stringify(p.locations.map(l=>[+l.lng?.toFixed(6),+l.lat?.toFixed(6)]))||JSON.stringify(r.location_ids)!==JSON.stringify(p.locations.map(l=>l.id));}
function mapView(){return hasRoadLocations()?'<div class="street-map" data-street-map role="region" aria-label="Interactive Dublin street map"></div><div class="road-map-status" data-road-status>OpenStreetMap · Dublin</div>':schematicMapView();}
function mapSubtitle(){return `${days[state.day]} routes · ${hasRoadLocations()?'Dublin street map':'schematic map'}`;}
function sourceNote(){const r=state.problem.routing;if(!hasRoadLocations())return 'Legacy schematic. Load a Dublin example to use real roads.';if(needsRoadRefresh())return 'Locations changed. Refresh road times before generating a roster.';if(r?.kind!=='osrm')return 'Manual travel matrix · street map for location context. No live traffic.';return `OSRM road-driving estimates · retrieved ${new Date(r.retrieved_at).toLocaleString('en-IE',{timeZone:'Europe/Dublin',dateStyle:'medium',timeStyle:'short'})} Dublin time. No live traffic. Rounded up to minutes.`;}
function teardownMaps(){mapRuntime.epoch++;mapRuntime.maps.forEach(m=>m.remove());mapRuntime.maps=[];}
async function mountMaps(){
  const nodes=[...document.querySelectorAll('[data-street-map]')];
  if(!nodes.length||typeof L==='undefined')return;
  const epoch=mapRuntime.epoch,p=state.problem,ks=carers();
  const bound=[];
  for(const node of nodes){
    const map=L.map(node,{scrollWheelZoom:false,attributionControl:true}).setView([53.3498,-6.2603],12);
    mapRuntime.maps.push(map);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'}).addTo(map);
    p.locations.forEach(l=>{
      bound.push([l.lat,l.lng]);
      L.circleMarker([l.lat,l.lng],{radius:l.id==='hub'?7:6,color:'#fff',weight:2,fillColor:l.id==='hub'?'#b79550':'#217467',fillOpacity:1})
        .bindPopup(`<strong>${esc(l.name)}</strong><br><small>Demo location · ${l.lat.toFixed(5)}, ${l.lng.toFixed(5)}</small>`).addTo(map);
    });
    map.fitBounds(L.latLngBounds(bound),{padding:[22,22],maxZoom:14});
    requestAnimationFrame(()=>{if(epoch===mapRuntime.epoch)map.invalidateSize();});
  }
  if(!accepted())return;
  const result=state.result,day=state.day;
  const key=JSON.stringify([p.locations.map(l=>[l.id,l.lat,l.lng]),result.routes.filter(r=>r.day===day).map(r=>[r.carer_id,r.shift_index,r.visits.map(v=>v.location)])]);
  let geometry=mapRuntime.geometry.get(key);
  const setStatus=text=>nodes.forEach(n=>{const label=n.nextElementSibling;if(label?.matches('[data-road-status]'))label.textContent=text;});
  if(!geometry){
    setStatus('Loading road routes… · No live traffic');
    try{geometry=await api('/api/road-routes',{problem:p,routes:result.routes,day});mapRuntime.geometry.set(key,geometry);}
    catch(err){if(epoch===mapRuntime.epoch)setStatus('Road lines unavailable. Saved travel estimates are retained.');return;}
  }
  if(epoch!==mapRuntime.epoch)return;
  geometry.routes.forEach(route=>mapRuntime.maps.forEach(map=>L.geoJSON(route.geometry,{style:{color:safeColor(ks[route.carer_id]?.color),weight:4,opacity:.85}})
    .bindTooltip(`${esc(ks[route.carer_id]?.name)} · planned road route`).addTo(map)));
  setStatus(geometry.warnings.length?'Some road lines unavailable; schedule still uses saved estimates.':`${geometry.routes.length} planned road route${geometry.routes.length===1?'':'s'} · OSRM · No GPS tracking`);
}

function dublinParts(){const now=new Date(Date.now()+clockOffset);return Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Dublin',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(now).map(p=>[p.type,p.value]));}
function tickDublinClock(){const p=dublinParts();const el=document.getElementById('dublin-time');if(!el)return;el.textContent=`${p.hour}:${p.minute}:${p.second}`;document.getElementById('dublin-date').textContent=new Intl.DateTimeFormat('en-IE',{timeZone:'Europe/Dublin',weekday:'short',day:'numeric',month:'short'}).format(new Date(Date.now()+clockOffset))+' · Dublin';}
async function syncDublinClock(){const sent=Date.now();try{const r=await api('/api/clock');clockOffset=Date.parse(r.utc)-(sent+Date.now())/2;document.querySelector('.dublin-clock').title='Live Dublin clock, synchronized with the local server';}catch{document.querySelector('.dublin-clock').title='Live Dublin clock using this device’s time';}tickDublinClock();}
function showToday(){const p=dublinParts();const today=`${p.year}-${p.month}-${p.day}`,start=state.problem.settings.week_start;const day=Math.round((Date.parse(today+'T12:00:00Z')-Date.parse(start+'T12:00:00Z'))/86400000);if(day<0||day>6){toast(`Today is outside this roster (${weekLabel()}). Change the week in Settings to plan today.`);return;}state.day=day;state.mode='routes';render();}
tickDublinClock();setInterval(tickDublinClock,1000);setInterval(syncDublinClock,300000);
