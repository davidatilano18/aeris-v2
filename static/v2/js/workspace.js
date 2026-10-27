'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const catalog = JSON.parse($('stationData').textContent);
  const fmt = new Intl.DateTimeFormat('es-MX',{timeZone:'America/Mexico_City',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'});
  const local = value => fmt.format(new Date(value));
  let chart, controller, applied, table = [], shown = 0, map, layer, tiles;
  const sourceLabel = value => value==='OpenAQ'?'OpenAQ · API e historial':'OpenAQ Archive';
  function refill(preferred) {
    const available=catalog.filter(s=>$('labMunicipality').value==='all'||s.municipality===$('labMunicipality').value);
    $('labStation').replaceChildren(...available.map(s=>new Option(s.name,String(s.sensor_id))));
    if (available.some(s=>String(s.sensor_id)===preferred)) $('labStation').value=preferred;
  }
  function selection() {
    return {source:$('labSource').value,station:$('labStation').value,period:$('labPeriod').value,
      from:$('dateFrom').value,to:$('dateTo').value};
  }
  function clear() {
    if (chart) {chart.destroy();chart=null;}
    table=[];shown=0;$('labRows').replaceChildren();$('labMore').hidden=true;
    for(const id of ['labCount','labCoverage','labLatest','labQuality']) $(id).textContent='—';
    $('labAge').textContent='No equivale a actualización de la base';
    $('labSummary').textContent='Esperando observaciones de esta selección.';
    $('researchCoverageText').textContent='Esperando una consulta válida para calcular cobertura.';
    $('labCoverageBasis').textContent='Sin consulta aplicada';
    $('comparisonResult').textContent='No se ha solicitado una comparación para esta selección.';
    $('comparisonEvidence').textContent='Sin resultado.';
  }
  function tablePage() {
    for (const p of table.slice(shown,shown+200)) {
      const tr=document.createElement('tr');
      const q=p.quality;
      const flag=!q.evaluated?'Pendiente':q.review||q.extreme||q.jump?'Con alerta · revisar':'Evaluada sin estas alertas';
      for(const text of [p.timestamp_utc,String(p.value),flag+(q.version?' · '+q.version:'')]) {
        const td=document.createElement('td');td.textContent=text;tr.append(td);
      }
      $('labRows').append(tr);
    }
    shown=Math.min(shown+200,table.length);$('labMore').hidden=shown>=table.length;
    $('labTableNote').textContent=`${shown} de ${table.length} filas observadas. Los huecos no son registros sintéticos.`;
  }
  function drawMap() {
    if (!window.L) {$('labMapNote').textContent='Mapa no disponible. Selecciona una estación desde los filtros.';return;}
    if (!map) {
      map=L.map('labMap',{scrollWheelZoom:false,zoomAnimation:false,fadeAnimation:false});
      layer=L.layerGroup().addTo(map);
      map.attributionControl.setPrefix(false);
      map.attributionControl.addAttribution('Ubicaciones: catálogo OpenAQ');
      if(document.body.dataset.offline!=='true')toggleTiles();
    }
    layer.clearLayers();
    const available=catalog.filter(s=>Number.isFinite(s.lat)&&Number.isFinite(s.lon)&&
      ($('labMunicipality').value==='all'||s.municipality===$('labMunicipality').value));
    if (available.length) map.fitBounds(available.map(s=>[s.lat,s.lon]),{padding:[45,45],maxZoom:12,animate:false});
    else map.setView([20.6,-100.4],9);
    for(const s of available) {
      const group=s.sources.find(g=>g.source===$('labSource').value);
      const selected=String(s.sensor_id)===$('labStation').value;
      const conDatos=Boolean(group?.count);
      // Halo y borde oscuro para que el punto contraste con cualquier fondo; la selección va en blanco.
      L.circleMarker([s.lat,s.lon],{radius:(selected?11:8)+6,stroke:false,fillColor:'#75efd2',fillOpacity:selected?.28:.14,interactive:false}).addTo(layer);
      const marker=L.circleMarker([s.lat,s.lon],{radius:selected?11:8,weight:selected?3:2,
        color:selected?'#ffffff':conDatos?'#06131d':'#75efd2',fillColor:conDatos?'#75efd2':'#06131d',fillOpacity:.95}).addTo(layer);
      const title=document.createElement('span');title.textContent=s.name;
      marker.bindTooltip(title,{className:'station-label'});
      const choose=()=>{$('labStation').value=String(s.sensor_id);load();};
      marker.on('click',choose);
      const path=marker.getElement();path.setAttribute('tabindex','0');path.setAttribute('role','button');
      path.setAttribute('aria-label',`${s.name}, ${s.municipality}. ${group?.count?'Con historial en esta fuente':'Sin registros de esta fuente'}. Seleccionar estación.`);
      path.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();choose();}});
    }
    $('labMapNote').textContent='Punto relleno: historial en esta fuente; contorno: sin registros locales. Borde blanco: selección. No representa todo el municipio.';
  }
  async function load() {
    controller?.abort(); controller=new AbortController();const request=controller;
    clear();applied=null;$('runComparison').disabled=true;
    $('labChartState').hidden=false;$('labChartBox').setAttribute('aria-busy','true');
    $('labChartState').textContent='Consultando observaciones…';$('labStatus').textContent='Leyendo datos locales, sin descargar nuevas mediciones…';
    const s=selection();$('customDates').hidden=s.period!=='custom';drawMap();
    try {
      if(!s.station) throw new Error('No hay una estación disponible.');
      if(s.period==='custom'&&(!s.from||!s.to||s.from>s.to)) throw new Error('Elige un inicio y un fin válidos, en UTC.');
      const query=new URLSearchParams({source:s.source,station:s.station,period:s.period==='custom'?'all':s.period});
      const response=await fetch('/api/v2/observations?'+query,{signal:request.signal,cache:'no-store'});
      if(!response.ok) throw new Error(response.status===413?'La selección excede el límite del lector. Abre el explorador y reduce el periodo.':'No se pudo leer una selección compatible.');
      const data=await response.json();if(request!==controller)return;
      const series=data.series.find(row=>String(row.sensor_id)===s.station);
      let points=series?.points||[];
      let start=Date.parse(data.window.from_utc),end=Date.parse(data.window.to_exclusive_utc);
      if(s.period==='custom') {
        start=Date.parse(s.from+'T00:00:00Z');end=Math.min(Date.parse(s.to+'T00:00:00Z')+86400000,end);
        if(start>=end) throw new Error('La ventana no contiene horas completas pasadas.');
        points=points.filter(p=>p.epoch_ms>=start&&p.epoch_ms<end);
      }
      const observed=points.filter(p=>!p.gap);
      if(s.period==='all'&&observed.length){start=observed[0].epoch_ms;end=observed.at(-1).epoch_ms+3600000;}
      const expected=Number.isFinite(start)?Math.round((end-start)/3600000):null;
      const alerts=observed.filter(p=>!p.quality.evaluated||p.quality.review||p.quality.extreme||p.quality.jump).length;
      const last=observed.at(-1);const age=last?(Date.now()-last.epoch_ms)/3600000:null;
      $('labCount').textContent=observed.length.toLocaleString('es-MX');
      $('labCoverage').textContent=expected?`${(observed.length/expected*100).toFixed(1)}%`:'Sin ventana';
      $('labCoverageBasis').textContent=expected?`${observed.length} de ${expected} horas · ${s.period==='all'?'entre extremos observados':'ventana seleccionada'}`:'Sin observaciones ni extremos disponibles';
      $('labLatest').textContent=last?local(last.epoch_ms):'Sin observaciones';
      $('labAge').textContent=last?`${age.toFixed(1)} h de antigüedad · hora de Querétaro`:'No se describe el aire actual';
      $('labQuality').textContent=String(alerts);
      const historical=s.source==='OpenAQ-Archive'||(last&&new Date(last.epoch_ms).getUTCFullYear()<new Date().getUTCFullYear());
      const state=!last?'Sin datos en el periodo':historical?'Histórico':age<=2&&age>=0?'Reciente · hasta 2 h':'Dato antiguo · más de 2 h';
      const name=$('labStation').selectedOptions[0].textContent;
      $('labStatus').textContent=`${state} · ${name} · ${sourceLabel(s.source)}. Solo observaciones.`;
      $('sourceBadge').textContent=sourceLabel(s.source);
      $('seriesTitle').textContent=name+' · PM2.5';
      const text=last?`${observed.length} observaciones. ${local(start)} a ${local(end)}, fin exclusivo. ${alerts} con alerta o revisión pendiente. Huecos sin rellenar; no demuestra una tendencia de años.`:'No hay observaciones en esta ventana. Cambia las fechas o consulta el historial; la ausencia no equivale a aire limpio.';
      $('labSummary').textContent=text;$('labChart').setAttribute('aria-label',text);
      $('researchCoverageText').textContent=expected?`${observed.length} de ${expected} horas tienen observaciones. Faltan ${expected-observed.length} horas. ${s.period==='all'?'Se mide solo entre primera y última observación, no la cobertura de un mes o año.':'Se incluyen huecos al inicio y al final de la ventana.'}`:'No existe una ventana con extremos observados para calcular cobertura.';
      table=observed;tablePage();applied=s;$('runComparison').disabled=false;
      $('labExplorer').href='/inicio/datos#pm25-horario';
      $('labExplorer').textContent='Descargar estos datos en CSV ↓';
      if(!observed.length){$('labChartState').textContent='Sin observaciones en esta selección.';return;}
      if(!window.Chart){$('labChartState').textContent='Gráfica no disponible. Consulta la tabla de valores.';return;}
      chart=new Chart($('labChart'),{type:'line',data:{datasets:[{label:'PM2.5 · µg/m³',data:points.map(p=>({x:p.epoch_ms,y:p.gap?null:p.value})),
        borderColor:'#75efd2',borderWidth:1.5,pointRadius:observed.length<40?2:0,pointHoverRadius:4,tension:0,spanGaps:false,fill:false}]},
        options:{responsive:true,maintainAspectRatio:false,animation:false,parsing:false,normalized:true,
          interaction:{mode:'nearest',intersect:false},plugins:{legend:{display:false},tooltip:{callbacks:{title:items=>local(items[0].parsed.x)+' · Querétaro'}}},
          scales:{x:{type:'linear',min:Number.isFinite(start)?start:undefined,max:end,grid:{color:'#9bc8c90a'},ticks:{color:'#b4cbd4',maxTicksLimit:5,font:{size:10},callback:value=>new Intl.DateTimeFormat('es-MX',(Number.isFinite(start)&&end-start<=172800000)?{timeZone:'America/Mexico_City',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}:{timeZone:'America/Mexico_City',day:'2-digit',month:'short'}).format(new Date(value))}},
            y:{beginAtZero:true,grid:{color:'#9bc8c918'},ticks:{color:'#b4cbd4',font:{size:10}},title:{display:true,text:'µg/m³',color:'#b4cbd4'}}}}});
      $('labChartState').hidden=true;
    } catch(error) {
      if(error.name==='AbortError')return;
      $('labChartState').textContent=error.message;
      $('labStatus').textContent='Selección no disponible. No se muestra una serie anterior como actual.';
      $('labSummary').textContent='Sin observaciones verificadas para interpretar esta consulta.';
      $('researchCoverageText').textContent='Sin consulta válida: no calculamos cobertura.';
    } finally {if(request===controller)$('labChartBox').setAttribute('aria-busy','false');}
  }
  $('labFilters').addEventListener('submit',e=>{e.preventDefault();load();});
  $('labMunicipality').addEventListener('change',()=>{refill($('labStation').value);load();});
  for(const id of ['labStation','labSource','labPeriod'])$(id).addEventListener('change',load);
  for(const id of ['dateFrom','dateTo'])$(id).addEventListener('change',()=>{controller?.abort();clear();applied=null;$('runComparison').disabled=true;$('labChartBox').setAttribute('aria-busy','false');$('labChartState').hidden=false;$('labChartState').textContent='Pulsa Aplicar selección para consultar estas fechas UTC.';});
  $('marquesShortcut').addEventListener('click',()=>{$('labMunicipality').value='El Marqués';refill('1352686');$('labSource').value='OpenAQ';$('labPeriod').value='all';load();});
  $('labMore').addEventListener('click',tablePage);
  function toggleTiles(){if(!map)return;if(tiles){map.removeLayer(tiles);tiles=null;$('labTiles').textContent='Mostrar mapa base';return;}
    // OpenStreetMap oscurecido por CSS (mapa_base.css) para que los puntos contrasten.
    tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,className:'mapa-base-oscura',attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'}).addTo(map);
    tiles.on('tileerror',()=>{$('labMapNote').textContent='Mapa base no disponible. Los puntos y filtros siguen funcionando.';});$('labTiles').textContent='Ocultar mapa base';}
  $('labTiles').addEventListener('click',toggleTiles);
  if(document.body.dataset.offline==='true'){$('labTiles').disabled=true;$('labTiles').textContent='Sin conexión · mapa local';}
  for(const button of document.querySelectorAll('[data-view]'))if(button.tagName==='BUTTON')button.addEventListener('click',()=>{
    $('labGrid').dataset.view=button.dataset.view;
    document.querySelectorAll('.mobile-views button').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
    if(button.dataset.view==='table')$('labTableDetails').open=true;
    requestAnimationFrame(()=>{map?.invalidateSize({animate:false});if(button.dataset.view==='map')drawMap();chart?.resize();});
  });
  const panels={coverage:'researchCoverage',comparison:'researchComparison',trend:'researchTrend',correlation:'researchCorrelation'};
  for(const b of document.querySelectorAll('[data-research]'))b.addEventListener('click',()=>{for(const [key,id] of Object.entries(panels))$(id).hidden=key!==b.dataset.research;document.querySelectorAll('[data-research]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));});
  $('runComparison').addEventListener('click',async()=>{
    if(!applied)return;const captured=applied;$('runComparison').disabled=true;$('comparisonResult').textContent='Consultando pares horarios compatibles…';
    try {
      const response=await fetch('/api/v2/comparison?'+new URLSearchParams({source:captured.source,station:captured.station,anchor:'latest'}),{cache:'no-store'});
      if(!response.ok)throw new Error();const result=await response.json();if(applied!==captured)return;
      $('comparisonResult').textContent=result.summary;
      $('comparisonEvidence').textContent=JSON.stringify({source:result.source,station:result.station_name,previous:result.previous,current:result.current,matched_hours:result.matched_hours,reasons:result.reason_messages,policy:result.policy},null,2);
    }catch(error){if(applied===captured)$('comparisonResult').textContent='Comparación no disponible. No se infiere cambio.';}
    finally{if(applied===captured)$('runComparison').disabled=false;}
  });
  const incoming=new URLSearchParams(location.search);if(catalog.some(s=>String(s.sensor_id)===incoming.get('station')))$('labStation').value=incoming.get('station');
  if(['OpenAQ','OpenAQ-Archive'].includes(incoming.get('source')))$('labSource').value=incoming.get('source');
  if(['24h','7d','30d','all'].includes(incoming.get('period')))$('labPeriod').value=incoming.get('period');
  // /inicio/explorar#comparacion abre «Comparación histórica» y la ejecuta con la selección cargada.
  Promise.resolve(load()).then(()=>{if(location.hash!=='#comparacion')return;
    document.querySelector('[data-research="comparison"]')?.click();$('research')?.scrollIntoView();
    if(!$('runComparison').disabled)$('runComparison').click();});
})();
