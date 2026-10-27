'use strict';
// Presentation of the existing daily export: no new environmental calculation.
(() => {
  function parseCSV(text) {
    const rows = []; let row = [], field = '', quoted = false;
    text = text.replace(/^\uFEFF/, '');
    for (let i = 0; i < text.length; i++) {
      const char = text[i];
      if (char === '"') {
        if (quoted && text[i + 1] === '"') { field += '"'; i++; }
        else quoted = !quoted;
      } else if (!quoted && (char === ',' || char === '\n')) {
        row.push(field); field = '';
        if (char === '\n') { rows.push(row); row = []; }
      } else if (char !== '\r' || quoted) field += char;
    }
    if (quoted) throw new Error('Incomplete CSV');
    if (field || row.length) { row.push(field); rows.push(row); }
    return rows;
  }
  function summarize(text) {
    const [header, ...rows] = parseCSV(text);
    const columns = ['fuente', 'sensor_id', 'fecha_local', 'horas_con_dato', 'horas_validas', 'clasificacion_nom172'];
    if (!header || columns.some(key => !header.includes(key))) throw new Error('Unexpected export');
    const index = Object.fromEntries(columns.map(key => [key, header.indexOf(key)]));
    let hours = 0, days = 0; const keys = new Set();
    for (const row of rows) {
      if (row.length === 1 && !row[0]) continue;
      if (row.length !== header.length) throw new Error('Incomplete row');
      const key = JSON.stringify([row[index.fuente], row[index.sensor_id], row[index.fecha_local]]);
      const totalText = row[index.horas_con_dato], validText = row[index.horas_validas];
      if (!/^\d+$/.test(totalText) || !/^\d+$/.test(validText)) throw new Error('Missing counts');
      const total = Number(totalText), valid = Number(validText);
      if (!Number.isSafeInteger(total) || !Number.isSafeInteger(valid) || valid > total || keys.has(key)) throw new Error('Invalid counts');
      keys.add(key); hours += total - valid;
      if (row[index.clasificacion_nom172] === 'En revisión') days++;
    }
    return {hours, days, rows: keys.size};
  }
  // Exported pure presentation helpers also support browser regression tests.
  window.AerisMethod = Object.freeze({parseCSV, summarize});
  const panel = document.getElementById('methodQuality');
  if (!panel) return;
  const status = document.getElementById('methodQualityStatus');
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  fetch('/inicio/datos/pm25-diario.csv', {cache: 'no-store', signal: controller.signal})
    .then(response => { if (!response.ok) throw new Error('Export unavailable'); return response.text(); })
    .then(text => {
      const result = summarize(text);
      document.getElementById('methodHours').textContent = result.hours.toLocaleString('es-MX');
      document.getElementById('methodDays').textContent = result.days.toLocaleString('es-MX');
      status.textContent = result.rows ? `Recuento del CSV diario: ${result.rows.toLocaleString('es-MX')} combinaciones de estación, fuente y día. Las fuentes permanecen separadas.` : 'El CSV diario no contiene observaciones; estos ceros no significan aire limpio.';
    }).catch(() => {
      document.getElementById('methodHours').textContent = '—';
      status.textContent = 'No se pudo consultar el CSV diario. El número de días, si aparece, procede del resumen de esta página. Consulta la descarga para verificar las horas.';
    }).finally(() => { clearTimeout(timeout); panel.setAttribute('aria-busy', 'false'); });
})();
