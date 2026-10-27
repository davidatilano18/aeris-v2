'use strict';
// El Marqués: observación METAR (MMQT) y reanálisis NASA POWER, siempre como series separadas.
(() => {
  const root = document.getElementById('tiempo');
  if (!root) return;
  const API = '/api/ambiental/v1';
  const OBS = 'ghcnh:MXI0000MMQT', MOD = 'power:mmqt';
  const $ = id => document.getElementById(id);
  const local = new Intl.DateTimeFormat('es-MX', {timeZone: 'America/Mexico_City', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'});
  const day = new Intl.DateTimeFormat('es-MX', {timeZone: 'America/Mexico_City', day: '2-digit', month: 'short'});
  const num = (v, d = 1) => v.toLocaleString('es-MX', {minimumFractionDigits: d, maximumFractionDigits: d});
  const HOUR = 3600e3;

  async function json(path) {
    const r = await fetch(API + path, {cache: 'no-store'});
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || 'Capa meteorológica no disponible.');
    return body;
  }
  const iso = t => new Date(t).toISOString().replace('.000Z', 'Z');
  const cardinal = deg => ['N', 'NE', 'E', 'SE', 'S', 'SO', 'O', 'NO'][Math.round(deg / 45) % 8];
  const usable = p => !p.marca_origen && !p.fuera_de_rango;

  function tile(id, value, unit, detail) {
    const box = $(id);
    box.querySelector('strong').textContent = value;
    box.querySelector('small').textContent = unit;
    box.querySelector('p').textContent = detail;
    box.classList.remove('is-loading');
  }

  function stats(pairs) {
    const n = pairs.length;
    if (n < 24) return null;  // Menos de un día de pares: no se describe.
    const mean = a => a.reduce((s, x) => s + x, 0) / a.length;
    const o = pairs.map(p => p[0]), m = pairs.map(p => p[1]);
    const mo = mean(o), mm = mean(m);
    const cov = mean(pairs.map(([a, b]) => (a - mo) * (b - mm)));
    const so = Math.sqrt(mean(o.map(a => (a - mo) ** 2))), sm = Math.sqrt(mean(m.map(b => (b - mm) ** 2)));
    return {n, bias: mean(pairs.map(([a, b]) => a - b)), mae: mean(pairs.map(([a, b]) => Math.abs(a - b))),
            r: so && sm ? cov / (so * sm) : null};
  }

  function draw(start, end, observed, modeled) {
    if (!window.Chart) { $('tiempoChartState').textContent = 'Gráfica no disponible; las cifras siguen arriba.'; return; }
    // Retícula horaria explícita: una hora sin dato queda en null y corta la línea.
    const grid = (map) => { const out = []; for (let t = start; t < end; t += HOUR) out.push({x: t, y: map.has(t) ? map.get(t) : null}); return out; };
    new Chart($('tiempoChart'), {
      type: 'line',
      data: {datasets: [
        {label: 'Observación MMQT (METAR)', data: grid(observed), borderColor: '#75efd2', backgroundColor: '#75efd233', borderWidth: 1.8, pointRadius: 0, spanGaps: false, tension: 0, fill: false},
        {label: 'Reanálisis NASA POWER (celda)', data: grid(modeled), borderColor: '#e6c789', borderDash: [5, 4], borderWidth: 1.4, pointRadius: 0, spanGaps: false, tension: 0},
      ]},
      options: {
        responsive: true, maintainAspectRatio: false, parsing: false, normalized: true,
        animation: false,  // La sección ya entra con transición; la curva aparece completa.
        interaction: {mode: 'index', intersect: false},
        plugins: {
          legend: {labels: {color: '#d5e6ec', boxWidth: 18, font: {size: 11}}},
          tooltip: {backgroundColor: '#0c1e2cee', borderColor: '#36535c', borderWidth: 1,
            callbacks: {title: items => local.format(new Date(items[0].parsed.x)) + ' · Querétaro',
                        label: item => item.parsed.y == null ? item.dataset.label + ': sin dato' : `${item.dataset.label}: ${num(item.parsed.y)} °C`}},
        },
        scales: {
          x: {type: 'linear', min: start, max: end, grid: {color: '#9bc8c90d'},
              ticks: {color: '#a8bfca', maxTicksLimit: 7, font: {size: 10}, callback: v => day.format(new Date(v))}},
          y: {grid: {color: '#9bc8c91a'}, ticks: {color: '#a8bfca', font: {size: 10}, callback: v => v + ' °C'}},
        },
      },
    });
    $('tiempoChartState').hidden = true;
    $('tiempoChartBox').removeAttribute('aria-busy');
  }

  (async () => {
    try {
      const {estaciones} = await json('/estaciones');
      const station = estaciones.find(e => e.estacion_id === OBS);
      const temp = station && station.variables.find(v => v.variable_id === 'temperatura_aire');
      if (!temp) throw new Error('Sin observaciones meteorológicas en esta base.');
      const latest = Date.parse(temp.ultima_utc);
      const end = Math.floor(latest / HOUR) * HOUR + HOUR, start = end - 7 * 24 * HOUR;
      const ventana = `&desde=${iso(start)}&hasta=${iso(end)}`;
      const [obs, mod] = await Promise.all([
        json(`/observaciones?estacion=${OBS}&variable=temperatura_aire,humedad_relativa,viento_velocidad,viento_direccion${ventana}&resolucion=hora`),
        json(`/observaciones?estacion=${MOD}&variable=temperatura_aire${ventana}`).catch(() => null),
      ]);
      const last = id => { const pts = obs.series[id].puntos.filter(usable); return pts[pts.length - 1]; };
      const t = last('temperatura_aire'), h = last('humedad_relativa'), w = last('viento_velocidad'), d = last('viento_direccion');
      const when = p => p ? 'Reporte ' + local.format(new Date(p.fecha_observacion_utc || p.fecha_utc)) : 'Sin reporte utilizable';
      if (t) tile('tiempoTemp', num(t.valor), '°C', when(t));
      if (h) tile('tiempoHum', num(h.valor, 0), '%', when(h));
      if (w) {
        const calm = w.valor === 0;
        tile('tiempoWind', calm ? 'Calma' : num(w.valor), calm ? '' : 'm/s',
             calm ? when(w) : (d && d.fecha_utc === w.fecha_utc ? `Desde el ${cardinal(d.valor)} (${num(d.valor, 0)}°) · ` : '') + when(w));
        const arrow = $('tiempoArrow');
        if (d && !calm) { arrow.style.setProperty('--dir', (d.valor + 180) + 'deg'); arrow.hidden = false; }
      }
      const hours = Math.max(0, (Date.now() - latest) / HOUR);
      tile('tiempoLag', hours >= 48 ? num(hours / 24, 1) : num(hours, 0), hours >= 48 ? 'días' : 'h',
           'Retraso de publicación de NOAA respecto a ahora. No es una falla de la estación.');
      $('tiempoLatest').textContent = local.format(new Date(latest));

      const observed = new Map(obs.series.temperatura_aire.puntos.filter(usable).map(p => [Date.parse(p.fecha_utc), p.valor]));
      const modeled = new Map(mod ? mod.series.temperatura_aire.puntos.map(p => [Date.parse(p.fecha_utc), p.valor]) : []);
      const pairs = [...observed].filter(([k]) => modeled.has(k)).map(([k, v]) => [v, modeled.get(k)]);
      const s = stats(pairs);
      if (s) {
        $('tiempoPairs').textContent = s.n.toLocaleString('es-MX');
        $('tiempoBias').textContent = (s.bias >= 0 ? '+' : '−') + num(Math.abs(s.bias)) + ' °C';
        $('tiempoMae').textContent = num(s.mae) + ' °C';
        $('tiempoR').textContent = s.r == null ? '—' : num(s.r, 2);
      } else {
        $('tiempoCompareNote').textContent = 'Menos de 24 horas coinciden entre ambos productos; no se describe la comparación.';
      }
      draw(start, end, observed, modeled);
      root.dataset.state = 'ready';
    } catch (error) {
      root.dataset.state = 'error';
      $('tiempoChartState').textContent = error.message + ' Las secciones de PM2.5 siguen disponibles.';
      for (const box of root.querySelectorAll('.weather-tile.is-loading')) box.querySelector('p').textContent = 'No disponible en esta base.';
    }
  })();
})();
