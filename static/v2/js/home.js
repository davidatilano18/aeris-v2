'use strict';
(() => {
  const motion = document.getElementById('motionToggle');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const updateMotion = () => {
    const paused = reduced.matches || document.body.classList.contains('motion-paused');
    motion.textContent = reduced.matches ? 'Movimiento reducido' : paused ? 'Reanudar movimiento' : 'Pausar movimiento';
    motion.setAttribute('aria-pressed', String(paused));
    motion.disabled = reduced.matches;
  };
  motion.addEventListener('click', () => { document.body.classList.toggle('motion-paused'); updateMotion(); });
  reduced.addEventListener('change', updateMotion); updateMotion();
  const status = document.getElementById('mapStatus');
  const tileButton = document.getElementById('tilesToggle');
  const offline = document.body.dataset.offline === 'true';
  if (offline) { tileButton.disabled = true; tileButton.textContent = 'Mapa base desactivado · sin conexión'; }
  if (!window.L) { status.textContent = 'No se pudo cargar el mapa. Usa la lista de estaciones.'; tileButton.disabled = true; return; }
  const stations = JSON.parse(document.getElementById('stationData').textContent);
  const valid = stations.filter(s => Number.isFinite(s.lat) && Number.isFinite(s.lon));
  const map = L.map('homeMap', {scrollWheelZoom: false, zoomAnimation: true, fadeAnimation: true, zoomSnap: .5});
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution('Ubicaciones: catálogo OpenAQ · no es un mapa de concentraciones');
  const puntos = valid.map(s => [s.lat, s.lon]);
  // Vistas rápidas: las estaciones metropolitanas están a pocos km entre sí y San Juan del Río a ~50 km.
  const vistas = {
    todo: puntos,
    metro: valid.filter(s => s.lon < -100.2).map(s => [s.lat, s.lon]),
    sjr: valid.filter(s => s.lon > -100.2).map(s => [s.lat, s.lon]),
  };
  const encuadrar = (clave, animar) => {
    const destino = vistas[clave]?.length ? vistas[clave] : puntos;
    if (!destino.length) return;
    // Margen derecho mayor: los nombres se dibujan a la derecha de cada punto.
    map.fitBounds(destino, {paddingTopLeft: [48, 48], paddingBottomRight: [150, 48], maxZoom: clave === 'todo' ? 11 : 13, animate: animar && !reduced.matches});
  };
  if (puntos.length) encuadrar('todo', false);
  else { map.setView([20.6, -100.4], 9); status.textContent = 'No hay ubicaciones verificadas para mostrar. La vista geográfica de referencia no implica estaciones.'; }
  // Retícula de coordenadas: solo sin mapa base. Son coordenadas, nunca una superficie medida.
  const reticula = L.layerGroup();
  const bounds = map.getBounds().pad(.5);
  for (let lat = Math.ceil(bounds.getSouth() * 10) / 10; lat < bounds.getNorth(); lat += .1) {
    L.polyline([[lat, bounds.getWest()], [lat, bounds.getEast()]], {interactive: false, color: '#91c6c7', opacity: .15, weight: .6}).addTo(reticula);
  }
  for (let lon = Math.ceil(bounds.getWest() * 10) / 10; lon < bounds.getEast(); lon += .1) {
    L.polyline([[bounds.getSouth(), lon], [bounds.getNorth(), lon]], {interactive: false, color: '#91c6c7', opacity: .15, weight: .6}).addTo(reticula);
  }
  const counts = {recent: 0, historical: 0, empty: 0};
  const marcadores = new Map();
  const colores = {recent: '#65ead1', historical: '#f2c46d', empty: '#b2c6d1'};
  for (const station of valid) {
    const state = station.records > 0 ? (station.fresh === true ? 'recent' : 'historical') : 'empty';
    counts[state]++;
    const label = {recent: 'Datos recientes (hasta 2 horas)', historical: 'Solo historial', empty: 'Sin registros locales'}[state];
    const color = colores[state];
    const radio = station.sensor_id === 1352686 ? 9 : 8;
    // Halo suave para separar el punto de cualquier fondo; no es interactivo.
    L.circleMarker([station.lat, station.lon], {radius: radio + 7, stroke: false, fillColor: color, fillOpacity: state === 'empty' ? .08 : .18, interactive: false}).addTo(map);
    const marker = L.circleMarker([station.lat, station.lon], {radius: radio, color: state === 'empty' ? color : '#06131d', weight: state === 'empty' ? 2.5 : 2,
      fillColor: state === 'empty' ? '#06131d' : color, fillOpacity: .95});
    const box = document.createElement('div');
    const name = document.createElement('strong'); name.textContent = station.name; box.append(name);
    const place = document.createElement('p'); place.textContent = station.municipality; box.append(place);
    const dates = document.createElement('p'); dates.textContent = station.records ?
      `${label}. Última medición: ${new Date(station.latest).toLocaleString("es-MX", {timeZone: "America/Mexico_City", dateStyle: "long", timeStyle: "short"})} (Querétaro); ${station.latest} UTC. Disponibilidad, no categoría sanitaria.` : 'Sin observaciones locales. No describe el aire actual.';
    box.append(dates);
    const link = document.createElement('a'); link.textContent = 'Explorar esta estación →';
    const source = station.sources.some(s => s.source === 'OpenAQ') ? 'OpenAQ' : station.sources[0]?.source || 'OpenAQ';
    link.href = '/inicio/explorar?' + new URLSearchParams({source, station: String(station.sensor_id), period: 'all'}); box.append(link);
    marker.bindPopup(box);
    // Nombre permanente; el CSS lo muestra solo con zoom suficiente para que no se encimen.
    marker.bindTooltip(station.name.replace(/ \(ubicación \d+\)/, ''), {permanent: true, direction: 'right', offset: [12, 0], className: 'station-tag'});
    marker.addTo(map);
    marcadores.set(String(station.sensor_id), marker);
    // Circle markers also need explicit keyboard access, not only pointer events.
    const path = marker.getElement(); path.setAttribute('tabindex', '0'); path.setAttribute('role', 'button');
    path.setAttribute('aria-label', `${station.name}, ${station.municipality}. ${label}${station.records ? '. '+station.latest+' UTC' : ''}`);
    path.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); marker.openPopup(); } });
  }
  const etiquetas = () => map.getContainer().classList.toggle('mostrar-etiquetas', map.getZoom() >= 11.5);
  map.on('zoomend', etiquetas); etiquetas();
  if (valid.length) status.textContent=`${valid.length} ubicaciones PM2.5: ${counts.recent} recientes, ${counts.historical} solo historial, ${counts.empty} sin registros. Estados al consultar la página; no es un mapa de concentraciones.`;
  // Vistas rápidas y lista: llevan el mapa a la estación sin salir de la página.
  for (const boton of document.querySelectorAll('[data-vista]')) {
    boton.addEventListener('click', () => {
      document.querySelectorAll('[data-vista]').forEach(b => b.setAttribute('aria-pressed', String(b === boton)));
      map.closePopup(); encuadrar(boton.dataset.vista, true);
    });
  }
  for (const boton of document.querySelectorAll('.station-focus')) {
    boton.addEventListener('click', () => {
      const marker = marcadores.get(boton.dataset.sensor);
      if (!marker) return;
      document.querySelectorAll('[data-vista]').forEach(b => b.setAttribute('aria-pressed', 'false'));
      if (matchMedia('(max-width: 760px)').matches) document.getElementById('homeMap').scrollIntoView({behavior: reduced.matches ? 'auto' : 'smooth', block: 'center'});
      if (reduced.matches) map.setView(marker.getLatLng(), 13.5, {animate: false}); else map.flyTo(marker.getLatLng(), 13.5, {duration: .8});
      map.once('moveend', () => marker.openPopup());
    });
  }
  // Estaciones meteorológicas observadas (cuadrado): miden el tiempo, no contaminantes.
  fetch('/api/ambiental/v1/estaciones?fuente=noaa-ghcnh', {cache: 'no-store'}).then(r => r.ok ? r.json() : null).then(data => {
    for (const site of data?.estaciones || []) {
      const icon = L.divIcon({className: 'weather-mmqt-icon', iconSize: [16, 16], iconAnchor: [8, 8]});
      const marker = L.marker([site.latitud, site.longitud], {icon, keyboard: true, title: site.nombre});
      const box = document.createElement('div');
      const name = document.createElement('strong'); name.textContent = site.nombre;
      const place = document.createElement('p'); place.textContent = site.municipio + ' · estación meteorológica (NOAA GHCNh)';
      const note = document.createElement('p'); note.textContent = 'Mide temperatura, humedad, viento y presión. No mide PM2.5.';
      const link = document.createElement('a'); link.href = '#tiempo'; link.textContent = 'Ver el tiempo en El Marqués →';
      box.append(name, place, note, link);
      marker.bindPopup(box).bindTooltip('Aeropuerto (meteorología)', {permanent: true, direction: 'right', offset: [10, 0], className: 'station-tag'}).addTo(map);
    }
    if (data?.estaciones?.length) {
      const key = document.createElement('span'); key.innerHTML = '<i class="key weather-key" aria-hidden="true"></i> Estación meteorológica (no mide contaminantes)';
      document.querySelector('.map-aside .legend')?.append(key);
    }
  }).catch(() => {});
  // Mapa base: OpenStreetMap con un filtro oscuro y desaturado (CSS) para que los puntos contrasten.
  let tiles;
  const activarBase = () => {
    tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18, className: 'mapa-base-oscura',
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'}).addTo(map);
    tiles.on('tileerror', () => { status.textContent = 'No se pudo cargar el mapa base. Usa los puntos o la lista de estaciones.'; });
    map.removeLayer(reticula);
    tileButton.setAttribute('aria-pressed', 'true'); tileButton.textContent = 'Ocultar mapa base';
  };
  const desactivarBase = () => {
    if (tiles) map.removeLayer(tiles);
    tiles = null; reticula.addTo(map);
    tileButton.setAttribute('aria-pressed', 'false'); tileButton.textContent = offline ? 'Mapa base desactivado · sin conexión' : 'Mostrar mapa base';
  };
  tileButton.addEventListener('click', () => { tiles ? desactivarBase() : activarBase(); });
  if (offline) reticula.addTo(map); else activarBase();
  // El mapa ocupa la altura del panel; Leaflet necesita recalcular al cambiar el tamaño.
  new ResizeObserver(() => map.invalidateSize()).observe(document.getElementById('homeMap'));
})();

// Compact municipality navigation; existing station links remain available.
(() => {
  const mobile = matchMedia('(max-width: 760px)');
  const entries=[];
  for (const card of document.querySelectorAll('.municipality:not(.featured)')) {
    const list=card.querySelector('ul');if(!list)continue;
    const details=document.createElement('details');const summary=document.createElement('summary');
    summary.textContent='Explorar estaciones';list.before(details);details.append(summary,list);entries.push(details);
  }
  const sync=()=>entries.forEach(d=>d.open=!mobile.matches);
  mobile.addEventListener('change',sync);sync();
})();

// Entrada suave de secciones y navegación que sigue la lectura; sin JS todo queda visible.
(() => {
  const sections = [...document.querySelectorAll('main > section, main > .section')];
  if ('IntersectionObserver' in window) {
    document.documentElement.classList.add('js-reveal');
    const reveal = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) { entry.target.classList.add('is-visible'); reveal.unobserve(entry.target); }
    }, {rootMargin: '0px 0px -8% 0px', threshold: .06});
    for (const section of sections) {
      if (section.classList.contains('hero') || section.classList.contains('escena')) continue;  // las escenas 3.0 las anima GSAP
      section.classList.add('reveal');
      reveal.observe(section);
    }
    const links = new Map([...document.querySelectorAll('.site-header nav a[href^="#"]')].map(a => [a.getAttribute('href').slice(1), a]));
    const current = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting && links.has(entry.target.id)) {
        links.forEach(a => a.classList.remove('is-current')); links.get(entry.target.id).classList.add('is-current');
      }
    }, {rootMargin: '-40% 0px -55% 0px'});
    sections.filter(s => links.has(s.id)).forEach(s => current.observe(s));
  }
})();
