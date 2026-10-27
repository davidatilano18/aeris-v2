'use strict';
(() => {
  const source = document.getElementById('historySource');
  const station = document.getElementById('historyStation');
  const state = document.getElementById('historyState');
  const summary = document.getElementById('historySummary');
  const box = document.getElementById('historyChartBox');
  const rows = document.getElementById('historyRows');
  const canvas = document.getElementById('homeChart');
  const date = value => new Intl.DateTimeFormat('es-MX', {timeZone:'America/Mexico_City',
    day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit'}).format(new Date(value));
  let chart, controller;
  const cell = text => { const node=document.createElement('td'); node.textContent=text; return node; };
  async function load() {
    controller?.abort(); controller = new AbortController(); const request = controller;
    if (chart) { chart.destroy(); chart = null; }
    rows.replaceChildren(); state.hidden=false; state.textContent='Consultando observaciones…';
    box.setAttribute('aria-busy','true'); summary.textContent='Esperando datos de esta estación y fuente.';
    const query = new URLSearchParams({source:source.value, station:station.value, period:'7d'});
    document.getElementById('historyExplorer').href='/inicio/explorar?'+new URLSearchParams({source:source.value,station:station.value,period:'all'});
    if (!station.value) { state.textContent='No hay estaciones disponibles para consultar.'; summary.textContent='No se puede interpretar una concentración sin observaciones.'; box.setAttribute('aria-busy','false'); return; }
    try {
      const response = await fetch('/api/v2/observations?'+query, {signal:request.signal,cache:'no-store'});
      if (!response.ok) throw new Error('Unavailable');
      const data = await response.json(); if (request !== controller) return;
      const series = data.series.find(s => String(s.sensor_id)===station.value);
      const points = series?.points || []; const observed = points.filter(p => !p.gap);
      document.getElementById('historyCaption').textContent=`${station.selectedOptions[0].textContent} · ${data.source_label} · últimos 7 días completos por hora`;
      const interval = `${date(data.window.from_utc)} a ${date(data.window.to_exclusive_utc)} (fin exclusivo), hora de Querétaro`;
      if (!observed.length) {
        state.textContent='No hay observaciones de esta fuente y estación en los últimos siete días.';
        summary.textContent='Sin datos en esta ventana no inferimos una tendencia. Puedes abrir otras fechas en el explorador.';
        canvas.setAttribute('aria-label','Sin observaciones en el periodo seleccionado.'); return;
      }
      for (const p of points) {
        const tr=document.createElement('tr');
        const flag=p.gap?'Sin observación':!p.quality.evaluated?'Pendiente':
          p.quality.review||p.quality.extreme||p.quality.jump?'Con alerta · revisar':'Evaluada sin estas alertas';
        tr.append(cell(p.timestamp_utc || new Date(p.epoch_ms).toISOString()),cell(p.gap?'—':String(p.value)),cell(flag)); rows.append(tr);
      }
      const alerts = observed.filter(p => !p.quality.evaluated || p.quality.review || p.quality.extreme || p.quality.jump).length;
      summary.textContent=`${observed.length} observaciones reales · ${interval}. ${alerts} con alertas o revisión pendiente. Los huecos interrumpen la línea; esta semana no demuestra una tendencia de años.`;
      canvas.setAttribute('aria-label',`PM2.5 de ${station.selectedOptions[0].textContent}. ${summary.textContent}`);
      if (!window.Chart) { state.textContent='No se pudo cargar la gráfica. Los valores están disponibles en la tabla.'; return; }
      chart = new Chart(canvas, {type:'line', data:{datasets:[{label:'PM2.5 observado · µg/m³',
        data:points.map(p => ({x:p.epoch_ms,y:p.gap?null:p.value})),borderColor:'#75efd2',
        backgroundColor:'#75efd215',pointRadius:observed.length<40?2:0,pointHoverRadius:4,
        borderWidth:1.6,tension:0,spanGaps:false,fill:true}]},options:{
        responsive:true,maintainAspectRatio:false,animation:false,parsing:false,
        normalized:true,interaction:{mode:'nearest',intersect:false},
        plugins:{legend:{display:false},tooltip:{callbacks:{title:items=>date(items[0].parsed.x)+' · Querétaro',
          label:item=>`${item.parsed.y} µg/m³ · medición observada`}}},
        scales:{x:{type:'linear',grid:{color:'#b9e5e00a'},border:{display:false},
          ticks:{color:'#b3cbd5',maxTicksLimit:5,font:{size:10},callback:value=>new Intl.DateTimeFormat('es-MX',{timeZone:'America/Mexico_City',day:'2-digit',month:'short'}).format(new Date(value))}},
          y:{title:{display:true,text:'PM2.5 · µg/m³',color:'#b3cbd5',font:{size:10}},beginAtZero:true,
            grid:{color:'#b9e5e015'},border:{display:false},ticks:{color:'#b3cbd5',maxTicksLimit:5,font:{size:10}}}}}});
      state.hidden=true;
    } catch (error) {
      if (error.name==='AbortError') return;
      state.textContent='No pudimos leer esta selección. Cambia la estación o vuelve a intentarlo.';
      summary.textContent='No se conserva una gráfica anterior como si correspondiera a esta consulta.';
    } finally { if (request===controller) box.setAttribute('aria-busy','false'); }
  }
  source.addEventListener('change',load); station.addEventListener('change',load); load();
})();
