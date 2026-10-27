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
  if (!window.L) { status.textContent = 'No se pudo cargar el mapa. Usa la lista de estaciones.'; tileButton.disabled = true; return; }
  const stations = JSON.parse(document.getElementById('stationData').textContent);
  const valid = stations.filter(s => Number.isFinite(s.lat) && Number.isFinite(s.lon));
  const map = L.map('homeMap', {scrollWheelZoom: false, zoomAnimation: false, fadeAnimation: false});
  map.attributionControl.addAttribution('Ubicaciones: catálogo OpenAQ · no es un mapa de concentraciones');
  if (valid.length) map.fitBounds(valid.map(s => [s.lat, s.lon]), {padding: [40, 40], maxZoom: 11, animate: false});
  else { map.setView([20.6, -100.4], 9); status.textContent = 'No hay ubicaciones verificadas para mostrar. La vista geográfica de referencia no implica estaciones.'; }
  for (const station of valid) {
    const marker = L.circleMarker([station.lat, station.lon], {radius: station.sensor_id === 1352686 ? 9 : 6,
      color: station.records ? '#65ead1' : '#b2c6d1', fillColor: '#65ead1',
      fillOpacity: station.records ? .75 : 0, weight: 2});
    const box = document.createElement('div');
    const name = document.createElement('strong'); name.textContent = station.name; box.append(name);
    const place = document.createElement('p'); place.textContent = station.municipality; box.append(place);
    const dates = document.createElement('p'); dates.textContent = station.records ?
      `Con registros locales. Último instante: ${station.latest}. No indica frescura ni validación oficial.` : 'Sin observaciones locales. No describe el aire actual.';
    box.append(dates);
    const link = document.createElement('a'); link.textContent = 'Explorar esta estación →';
    const source = station.sources.some(s => s.source === 'OpenAQ') ? 'OpenAQ' : station.sources[0]?.source || 'OpenAQ';
    link.href = '/v2?' + new URLSearchParams({source, station: String(station.sensor_id), period: 'all'}); box.append(link);
    marker.bindPopup(box); marker.bindTooltip(() => { const label=document.createElement('span'); label.textContent=station.name; return label; }, {className: 'station-label'});
    marker.addTo(map);
    // Circle markers also need explicit keyboard access, not only pointer events.
    const path = marker.getElement(); path.setAttribute('tabindex', '0'); path.setAttribute('role', 'button');
    path.setAttribute('aria-label', `${station.name}, ${station.municipality}. ${station.records ? 'Con registros' : 'Sin registros locales'}`);
    path.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); marker.openPopup(); } });
  }
  let tiles;
  tileButton.addEventListener('click', () => {
    if (tiles) { map.removeLayer(tiles); tiles = null; tileButton.setAttribute('aria-pressed','false'); tileButton.textContent='Activar mapa base en línea'; status.textContent='Mapa base desactivado. Los puntos y la lista permanecen disponibles.'; return; }
    tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18, className: 'mapa-base-oscura', attribution: '© OpenStreetMap contributors'}).addTo(map);
    tiles.on('tileerror', () => { status.textContent='No se pudo cargar el mapa base. Usa los puntos o la lista de estaciones.'; });
    tileButton.setAttribute('aria-pressed','true'); tileButton.textContent='Desactivar mapa base'; status.textContent='Mapa base en línea activado; requiere conexión externa.';
  });
})();
