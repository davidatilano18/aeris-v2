'use strict';
// Read-only presentation of /api/ambiental/v1, never a second scientific/QC engine.
(() => {
  const $ = id => document.getElementById(id), api = '/api/ambiental/v1';
  if (!$('pollutantWorkspace')) return;
  const allowed = ['pm10', 'o3', 'no2', 'so2', 'co', 'pm25'];
  const product = () => $('pollutantSource').value === 'open-meteo-cams' ? 'Modelo, no medición' : 'Observación · OpenAQ Archive';
  const modeled = () => $('pollutantSource').value === 'open-meteo-cams';
  const number = new Intl.NumberFormat('es-MX', {maximumFractionDigits: 8});
  const local = value => new Intl.DateTimeFormat('es-MX', {timeZone: 'America/Mexico_City', dateStyle: 'medium', timeStyle: 'short'}).format(new Date(value));
  const make = (tag, text) => { const n = document.createElement(tag); n.textContent = text; return n; };
  let sites = [], variables = [], sources = [], chart, pending, table = [], shown = 0;
  const site = () => sites.find(s => s.estacion_id === $('pollutantStation').value);
  const variable = () => variables.find(v => v.variable_id === $('pollutantVariable').value);

  async function json(path, signal) {
    const response = await fetch(api + path, {cache: 'no-store', signal});
    if (!response.ok) throw new Error(response.status === 413 ? 'La consulta supera el límite de la API; reduce el periodo.' : 'La API no pudo resolver esta consulta.');
    return response.json();
  }
  function identify() {
    const label = product();
    $('pollutantProduct').textContent = label;
    $('pollutantProduct').classList.toggle('modeled', modeled());
    $('pollutantType').classList.toggle('modeled', modeled());
    $('pollutantType').textContent = modeled()
      ? 'Modelo, no medición · CAMS distribuido por Open-Meteo. El punto es una consulta de rejilla, no un sensor ni una medición de todo el municipio.'
      : 'Observación · Archivo OpenAQ. Solo la estación elegida, sin extrapolar al municipio ni mezclarla con la API reciente.';
    $('pollutantChartKind').textContent = label;
    $('pollutantTableKind').textContent = label;
    $('pollutantCaption').textContent = label + '. Valores de la selección; UTC y hora de Querétaro. No son categorías sanitarias.';
  }
  function clear() {
    chart?.destroy(); chart = null; table = []; shown = 0;
    $('pollutantRows').replaceChildren(); $('pollutantMore').hidden = true;
    for (const id of ['pollutantCount', 'pollutantCoverage', 'pollutantLatest', 'pollutantUnit']) $(id).textContent = '—';
    $('pollutantTableNote').textContent = '';
    $('pollutantChartTitle').textContent = 'Serie por consultar';
    $('pollutantSummary').textContent = 'Sin serie para esta selección. No se conserva una gráfica anterior como actual.';
    $('pollutantScope').textContent = 'Alcance por consultar.';
    $('pollutantWindow').textContent = 'Sin periodo consultado.';
    $('pollutantMethod').textContent = 'Método por consultar.';
    $('pollutantAttribution').textContent = ''; $('pollutantLicense').textContent = '';
    $('pollutantChartState').hidden = false;
    $('pollutantChartState').textContent = 'Consultando serie…';
  }
  function municipalities() {
    const items = sites.filter(s => s.fuente_id === $('pollutantSource').value);
    $('pollutantMunicipality').replaceChildren(new Option('Todos los disponibles', 'all'),
      ...[...new Set(items.map(s => s.municipio))].sort().map(m => new Option(m, m)));
  }
  function stationOptions() {
    const old = $('pollutantStation').value;
    const matches = sites.filter(s => s.fuente_id === $('pollutantSource').value &&
      ($('pollutantMunicipality').value === 'all' || s.municipio === $('pollutantMunicipality').value));
    $('pollutantStation').replaceChildren(...matches.map(s => new Option((modeled() ? 'Modelo, no medición · ' : '') + s.nombre, s.estacion_id)));
    if (matches.some(s => s.estacion_id === old)) $('pollutantStation').value = old;
    variableOptions();
  }
  function variableOptions() {
    const old = $('pollutantVariable').value;
    const ids = modeled() ? ['pm25', ...allowed.filter(v => v !== 'pm25')] : allowed.filter(v => v !== 'pm25');
    const ordered = ids.map(id => variables.find(v => v.variable_id === id)).filter(Boolean);
    $('pollutantVariable').replaceChildren(...ordered.map(v => {
      const has = site()?.variables.some(s => s.variable_id === v.variable_id && s.observaciones > 0);
      return new Option(`${v.nombre} · ${v.unidad}${has ? '' : ' · sin registros'}`, v.variable_id);
    }));
    if (ordered.some(v => v.variable_id === old)) $('pollutantVariable').value = old;
  }
  function page() {
    const v = variable();
    for (const p of table.slice(shown, shown + 200)) {
      const tr = document.createElement('tr');
      const flags = [p.marca_origen ? 'Marca del proveedor' : '', p.fuera_de_rango ? 'Fuera de rango' : '', p.revisada ? 'Tiene revisión posterior' : ''].filter(Boolean).join('; ') || 'Sin estas marcas; no certifica validación';
      for (const text of [p.fecha_utc, p.fecha_observacion_utc || p.fecha_utc,
        local(p.fecha_observacion_utc || p.fecha_utc), number.format(p.valor) + ' ' + v.unidad, flags]) tr.append(make('td', text));
      $('pollutantRows').append(tr);
    }
    shown = Math.min(shown + 200, table.length);
    $('pollutantMore').hidden = shown >= table.length;
    $('pollutantTableNote').textContent = `${product()} · ${shown} de ${table.length} valores devueltos. Los originales no se sustituyen por revisiones posteriores.`;
  }
  function windowFor(metadata) {
    const hour = 3600000, day = 24 * hour;
    let start, end;
    if ($('pollutantPeriod').value === 'custom') {
      const from = $('pollutantFrom').value, to = $('pollutantTo').value;
      if (!/^\d{4}-\d{2}-\d{2}$/.test(from) || !/^\d{4}-\d{2}-\d{2}$/.test(to)) throw new Error('Indica ambas fechas UTC.');
      start = Date.parse(from + 'T00:00:00Z'); end = Date.parse(to + 'T00:00:00Z') + day;
    } else {
      end = $('pollutantAnchor').value === 'latest' ? Math.floor(Date.parse(metadata.ultima_utc) / hour) * hour + hour : Math.floor(Date.now() / hour) * hour;
      start = end - Number($('pollutantPeriod').value) * day;
    }
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || end - start > 400 * day) throw new Error('La ventana debe ser válida, ordenada y de hasta 400 días.');
    return {start, end};
  }
  async function load() {
    pending?.abort(); const request = new AbortController(); pending = request;
    clear(); identify();
    $('pollutantChartBox').setAttribute('aria-busy', 'true');
    $('pollutantStatus').textContent = product() + ' · Consultando la selección…';
    const timer = setTimeout(() => request.abort('timeout'), 15000);
    try {
      const s = site(), v = variable();
      const metadata = s?.variables.find(p => p.variable_id === v?.variable_id && p.observaciones > 0);
      if (!s || !v || !metadata) throw new Error('Sin registros de este contaminante en el sitio elegido, según el catálogo. No se sustituye por otra estación ni un modelo.');
      const {start, end} = windowFor(metadata);
      const query = new URLSearchParams({estacion: s.estacion_id, variable: v.variable_id,
        desde: new Date(start).toISOString(), hasta: new Date(end).toISOString()});
      const [data, coverage] = await Promise.all([json('/observaciones?' + query + '&resolucion=hora&incluir_marcadas=1', request.signal), json('/cobertura?' + query, request.signal)]);
      if (pending !== request) return;
      const series = data.series?.[v.variable_id];
      const c = coverage.variables?.find(item => item.variable_id === v.variable_id);
      if (data.fuente?.fuente_id !== s.fuente_id || data.estacion?.estacion_id !== s.estacion_id ||
          coverage.estacion?.estacion_id !== s.estacion_id || series?.unidad !== v.unidad || !Array.isArray(series?.puntos) || !c ||
          (modeled() ? data.estacion.tipo_producto === 'observacion' : data.estacion.tipo_producto !== 'observacion')) throw new Error('Identidad, unidad o tipo de producto incompatible.');
      const points = series.puntos; let previous;
      const plot = [];
      for (const p of points) {
        const x = Date.parse(p.fecha_utc);
        if (!Number.isFinite(p.valor) || !Number.isFinite(x) || x < start || x >= end || (previous !== undefined && x <= previous)) throw new Error('Serie horaria incompatible; no se muestra.');
        if (previous !== undefined && x - previous > 3600000) plot.push({x: previous + 3600000, y: null});
        plot.push({x, y: p.valor}); previous = x;
      }
      $('pollutantScope').textContent = `${s.nombre} · ${data.estacion.municipio}. ${data.estacion.municipio_nota} Alcance espacial: ${data.estacion.resolucion_espacial}.`;
      $('pollutantWindow').textContent = `Ventana UTC: ${new Date(start).toISOString()} → ${new Date(end).toISOString()} (fin exclusivo).`;
      $('pollutantMethod').textContent = data.metodo;
      $('pollutantAttribution').textContent = `${data.fuente.nombre} · ${data.fuente.atribucion}`;
      $('pollutantLicense').textContent = 'Condiciones: ' + data.fuente.licencia;
      $('pollutantCount').textContent = points.length.toLocaleString('es-MX');
      $('pollutantCoverage').textContent = `${c.horas_con_dato} / ${c.horas_esperadas} (${c.porcentaje ?? '—'}%)`;
      $('pollutantLatest').textContent = c.ultima_utc || 'Sin fecha disponible';
      $('pollutantUnit').textContent = series.unidad;
      $('pollutantChartTitle').textContent = `${series.nombre} · ${s.nombre}`;
      $('pollutantChart').setAttribute('aria-label', `${product()}: ${series.nombre}, ${points.length} valores, ${series.unidad}.`);
      $('pollutantSummary').textContent = `${product()} · ${points.length} valores de ${series.nombre}, ${series.unidad}. Huecos sin rellenar; marcas visibles en la tabla. No demuestra una tendencia de años ni un estado sanitario.`;
      table = points; page();
      $('pollutantStatus').textContent = `${product()} · ${s.nombre}. ${$('pollutantPeriod').value === 'custom' ? 'Periodo histórico explícito.' : $('pollutantAnchor').value === 'latest' ? 'Ventana al final del historial de esta variable; puede ser antigua.' : 'Ventana referida a la fecha actual.'}`;
      if (!points.length) { $('pollutantChartState').textContent = 'Sin valores en esta ventana. Cambia las fechas; no se rellenan huecos.'; return; }
      if (!window.Chart) { $('pollutantChartState').textContent = 'Gráfica no disponible. Los valores permanecen en la tabla.'; return; }
      chart = new Chart($('pollutantChart'), {type: 'line', data: {datasets: [{
        label: `${product()} · ${series.nombre} · ${series.unidad}`, data: plot,
        borderColor: modeled() ? '#e6c789' : '#75efd2', backgroundColor: modeled() ? '#e6c789' : '#75efd2',
        borderDash: modeled() ? [6, 4] : [], pointRadius: 0, pointHoverRadius: 4, borderWidth: 1.5, spanGaps: false, tension: 0
      }]}, options: {responsive: true, maintainAspectRatio: false, animation: false, parsing: false,
        interaction: {mode: 'nearest', intersect: false}, plugins: {legend: {display: false}, tooltip: {callbacks: {
          title: items => `${product()} · ${local(new Date(items[0].parsed.x).toISOString())} · Querétaro`,
          label: item => `${number.format(item.parsed.y)} ${series.unidad}`}}},
        scales: {x: {type: 'linear', min: start, max: end, title: {display: true, text: 'Hora de Querétaro', color: '#c9dce3'},
          ticks: {maxTicksLimit: 4, color: '#c9dce3', callback: value => new Intl.DateTimeFormat('es-MX', {timeZone: 'America/Mexico_City', month: 'short', day: 'numeric', hour: '2-digit'}).format(new Date(value))}, grid: {color: '#9bc8c912'}},
          y: {title: {display: true, text: series.unidad, color: '#c9dce3'}, ticks: {color: '#c9dce3'}, grid: {color: '#9bc8c918'}}}}});
      $('pollutantChartState').hidden = true;
    } catch (error) {
      if (pending !== request) return;
      clear(); identify();
      const message = request.signal.aborted ? 'La consulta se interrumpió o agotó su tiempo.' : error.message;
      $('pollutantStatus').textContent = product() + ' · ' + message;
      $('pollutantChartState').textContent = message;
    } finally {
      clearTimeout(timer);
      if (pending === request) $('pollutantChartBox').setAttribute('aria-busy', 'false');
    }
  }
  $('pollutantFilters').addEventListener('submit', event => { event.preventDefault(); load(); });
  $('pollutantSource').addEventListener('change', () => { $('pollutantVariable').value = ''; municipalities(); stationOptions(); load(); });
  $('pollutantMunicipality').addEventListener('change', () => { stationOptions(); load(); });
  $('pollutantStation').addEventListener('change', () => { variableOptions(); load(); });
  $('pollutantVariable').addEventListener('change', load);
  $('pollutantPeriod').addEventListener('change', () => {
    const custom = $('pollutantPeriod').value === 'custom';
    $('pollutantDates').hidden = !custom; $('pollutantAnchor').disabled = custom;
    load();
  });
  $('pollutantAnchor').addEventListener('change', load);
  $('pollutantMore').addEventListener('click', page);
  document.querySelectorAll('[data-domain]').forEach(button => button.addEventListener('click', () => {
    if (button.dataset.domain === 'pollutants') load();
    else pending?.abort();
  }));
  (async () => {
    const init = new AbortController(); const timer = setTimeout(() => init.abort(), 15000);
    try {
      const [f, v, s] = await Promise.all([json('/fuentes', init.signal), json('/variables', init.signal), json('/estaciones', init.signal)]);
      sites = s.estaciones.filter(s => ['openaq-archivo', 'open-meteo-cams'].includes(s.fuente_id));
      variables = v.variables.filter(v => allowed.includes(v.variable_id));
      sources = f.fuentes.filter(f => ['openaq-archivo', 'open-meteo-cams'].includes(f.fuente_id) && sites.some(s => s.fuente_id === f.fuente_id));
      sources.sort((a, b) => (a.fuente_id === 'openaq-archivo' ? -1 : 1) - (b.fuente_id === 'openaq-archivo' ? -1 : 1));
      if (!sources.length || !variables.length) throw new Error('Sin productos de contaminantes disponibles.');
      $('pollutantSource').replaceChildren(...sources.map(s => new Option(s.fuente_id === 'open-meteo-cams' ? 'CAMS · Modelo, no medición' : 'Observación · OpenAQ Archive', s.fuente_id)));
      municipalities(); stationOptions(); identify();
      for (const id of ['pollutantSource', 'pollutantStation', 'pollutantVariable', 'pollutantApply', 'pollutantDomain']) $(id).disabled = false;
      $('pollutantAvailability').textContent = sources.length + ' productos disponibles, sin mezclarlos';
      if (location.hash === '#contaminantes') $('pollutantDomain').click();
    } catch (error) {
      $('pollutantAvailability').textContent = 'Capa no disponible en este corte';
      $('pollutantStatus').textContent = 'No se pudo cargar el catálogo. No se muestran datos sustitutos.';
    } finally { clearTimeout(timer); }
  })();
})();
