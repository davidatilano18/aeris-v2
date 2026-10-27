import {element, utc, fmt, age} from './format.js';
let map, group, tileLayer;
const markers = new Map();

export function initializeMap() {
  if (!window.L) {
    document.getElementById('mapNote').textContent = 'La biblioteca local del mapa no está disponible. Usa la lista de estaciones.';
    return;
  }
  map = window.L.map('stationMap', {scrollWheelZoom: false, preferCanvas: true, zoomControl: false});
  window.L.control.zoom({position: 'topright'}).addTo(map);
  group = window.L.layerGroup().addTo(map);
  map.attributionControl.addAttribution('Coordenadas: OpenAQ');
  document.getElementById('baseMap').addEventListener('click', event => {
    if (tileLayer) {
      map.removeLayer(tileLayer); tileLayer = null;
      event.currentTarget.textContent = 'Activar mapa base en línea'; event.currentTarget.setAttribute('aria-pressed', 'false');
      return;
    }
    tileLayer = window.L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18, className: 'mapa-base-oscura', attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map);
    tileLayer.on('tileerror', () => { document.getElementById('mapNote').textContent = 'El mapa base en línea no está disponible. Las posiciones del catálogo y la lista siguen funcionando.'; });
    event.currentTarget.textContent = 'Desactivar mapa base en línea'; event.currentTarget.setAttribute('aria-pressed', 'true');
  });
}

export function clearMap() {
  if (group) group.clearLayers();
  markers.clear();
  document.getElementById('stationList').replaceChildren(element('p', 'Consultando catálogo…', 'muted'));
}

export function renderStations(data, chooseStation) {
  clearMap();
  const list = document.getElementById('stationList'); list.replaceChildren();
  const coordinates = [];
  document.getElementById('directoryCount').textContent = `${data.stations.length} sensores`;
  for (const station of data.stations) {
    const status = station.count === 0 ? 'empty' : station.fresh ? 'fresh' : 'stale';
    const button = element('button', undefined, `station-item${String(station.sensor_id) === data.selection.station ? ' selected' : ''}`);
    button.type = 'button'; button.setAttribute('aria-pressed', String(String(station.sensor_id) === data.selection.station));
    const title = element('span', undefined, 'station-item-heading');
    const dot = element('i', undefined, `legend-dot ${status}`); dot.setAttribute('aria-hidden', 'true');
    title.append(dot, element('span', station.name));
    button.append(title, element('small', `${station.municipality} · Sensor ${station.sensor_id}`));
    button.append(element('small', station.count ? `${fmt(station.period_count)} en el filtro · ${age(station.age_hours)} de antigüedad` : 'Sin mediciones en esta fuente', 'station-item-data'));
    if (station.count) button.append(element('small', utc(station.latest_utc)));
    button.addEventListener('click', () => { chooseStation(String(station.sensor_id)); });
    list.append(button);
    if (!map || !Number.isFinite(station.lat) || !Number.isFinite(station.lon)) continue;
    coordinates.push([station.lat, station.lon]);
    const marker = window.L.circleMarker([station.lat, station.lon], {
      radius: String(station.sensor_id) === data.selection.station ? 10 : 7,
      color: status === 'fresh' ? '#0f766e' : status === 'stale' ? '#85590a' : '#718696',
      fillColor: status === 'fresh' ? '#0f766e' : '#fff', fillOpacity: .95, weight: 2,
      dashArray: status === 'empty' ? '3 3' : null,
    }).addTo(group);
    const popup = element('div');
    popup.append(element('strong', station.name), element('div', `Ubicación OpenAQ ${station.location_id}`));
    popup.append(element('div', station.count ? `${fmt(station.count)} observaciones en esta fuente` : 'Sin mediciones en esta fuente'));
    popup.append(element('div', station.latest_utc ? utc(station.latest_utc) : 'Sin observaciones'));
    popup.append(element('small', 'Ubicación del catálogo; vigencia histórica no verificada.'));
    marker.bindPopup(popup); marker.on('click', () => chooseStation(String(station.sensor_id)));
    markers.set(String(station.sensor_id), marker);
  }
  if (map && coordinates.length) {
    map.fitBounds(coordinates, {padding: [45, 45], maxZoom: 11, animate: false});
    const selected = markers.get(data.selection.station);
    if (selected) selected.openPopup();
    map.invalidateSize();
  }
  document.getElementById('mapNote').textContent = `Coordenadas del catálogo OpenAQ; no se demuestra su vigencia para 2021 o 2025. ${data.source === 'OpenAQ-Archive' ? 'Los puntos no georreferencian las mediciones del archivo histórico.' : 'Los marcadores muestran disponibilidad y antigüedad, no categorías de salud.'} El mapa base en línea es opcional.`;
}
