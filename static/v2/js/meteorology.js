'use strict';
// Adapter for Claude's documented API. It never imports, writes or downloads source data.
(() => {
  const $=id=>document.getElementById(id), root='/api/ambiental/v1';
  let sites=[],variables=[],sources=[],charts=[],request,table=[],shown=0,map,marker;
  const number=new Intl.NumberFormat('es-MX',{maximumFractionDigits:2});
  const date=value=>new Intl.DateTimeFormat('es-MX',{timeZone:'America/Mexico_City',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(value));
  const iso=value=>new Date(value).toISOString();
  const make=(tag,text,className)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;};
  async function json(url,signal) {const response=await fetch(root+url,{signal,cache:'no-store'});if(!response.ok)throw new Error(response.status===413?'Demasiados puntos: reduce variables o periodo.':'Capa ambiental no disponible para esta selección.');return response.json();}
  function selectedSite(){return sites.find(s=>s.estacion_id===$('weatherStation').value);}
  function siteOptions(){
    const available=sites.filter(s=>s.fuente_id===$('weatherSource').value);
    $('weatherStation').replaceChildren(...available.map(s=>new Option(s.nombre,s.estacion_id)));variableOptions();
  }
  function variableOptions(){
    const s=selectedSite(), active=new Set((s?.variables||[]).filter(v=>v.observaciones>0).map(v=>v.variable_id));
    const available=variables.filter(v=>active.has(v.variable_id));
    const defaults=['temperatura_aire','humedad_relativa','viento_velocidad','viento_direccion',available.some(v=>v.variable_id==='presion_altimetro')?'presion_altimetro':'presion_superficie'];
    $('weatherVariables').replaceChildren(...available.map(v=>{const label=make('label');const input=document.createElement('input');input.type='checkbox';input.value=v.variable_id;input.checked=defaults.includes(v.variable_id);label.append(input,make('span',v.nombre+' · '+v.unidad));input.addEventListener('change',load);return label;}));
  }
  function clear(){charts.forEach(c=>c.destroy());charts=[];$('weatherCharts').replaceChildren();$('weatherRows').replaceChildren();table=[];shown=0;$('weatherMore').hidden=true;$('weatherCount').textContent='—';$('weatherMobileView').replaceChildren();$('weatherWindow').textContent='—';$('weatherMethod').textContent='Esperando la metodología de esta consulta.';$('weatherAttribution').textContent='Fuente pendiente de consulta.';$('weatherLicense').textContent='Condiciones pendientes de consulta.';}
  function page(){
    for(const item of table.slice(shown,shown+200)){
      const p=item.p;const row=make('tr');const flags=[p.marca_origen?'Marca del proveedor':null,p.fuera_de_rango?'Fuera de rango local':null,p.revisada?'Revisión posterior':null].filter(Boolean).join('; ')||'Sin estas marcas';
      for(const text of [item.name,p.fecha_utc,p.fecha_observacion_utc||p.fecha_utc,number.format(p.valor)+' '+item.unit,flags])row.append(make('td',text));$('weatherRows').append(row);
    }
    shown=Math.min(shown+200,table.length);$('weatherMore').hidden=shown>=table.length;$('weatherTableNote').textContent=`${shown} de ${table.length} valores originales devueltos. No se sustituyen por revisiones posteriores.`;
  }
  function mapSite(site){
    if(!window.L||!Number.isFinite(site.latitud)||!Number.isFinite(site.longitud))return;
    if(!map){map=L.map('weatherMap',{scrollWheelZoom:false,zoomAnimation:false,fadeAnimation:false});map.attributionControl.addAttribution('Ubicación: metadatos del proveedor');}
    if(marker)map.removeLayer(marker);
    const model=site.tipo_producto!=='observacion';
    marker=L.marker([site.latitud,site.longitud],{icon:L.divIcon({className:model?'weather-model-icon':'weather-station-icon',html:model?'▧':'□',iconSize:[24,24],iconAnchor:[12,12]})}).addTo(map);
    const label=make('span',site.nombre);marker.bindTooltip(label,{permanent:true,direction:'top',className:'station-label'});
    map.setView([site.latitud,site.longitud],10,{animate:false});
    $('weatherMapNote').textContent=model?'Símbolo tramado: coordenada de consulta de un producto de rejilla. No se dibuja una celda sin límites verificados.':'Cuadrado: estación meteorológica instrumental. Mide el tiempo, no PM2.5; no representa todo el municipio.';
    requestAnimationFrame(()=>map.invalidateSize({animate:false}));
  }
  // Rosa de vientos descriptiva: frecuencia por sector de 45° con dirección y velocidad del mismo
  // instante, sin marcas. Las calmas (velocidad 0) se cuentan aparte; no se promedian grados.
  function windRose(series,modeled,source){
    const dir=series.viento_direccion,speed=series.viento_velocidad;
    if(!dir||!speed||!window.Chart)return false;
    const ok=p=>!p.marca_origen&&!p.fuera_de_rango&&!p.revisada;
    const speeds=new Map(speed.puntos.filter(ok).map(p=>[p.fecha_observacion_utc||p.fecha_utc,p.valor]));
    const names=['N','NE','E','SE','S','SO','O','NO'],count=Array(8).fill(0),sum=Array(8).fill(0);let calm=0,total=0;
    for(const p of dir.puntos.filter(ok)){
      const v=speeds.get(p.fecha_observacion_utc||p.fecha_utc);if(v===undefined)continue;total++;
      if(v===0){calm++;continue;}
      const k=Math.round((p.valor%360)/45)%8;count[k]++;sum[k]+=v;
    }
    const moving=total-calm;if(moving<24)return false;
    const pct=count.map(c=>100*c/moving),max=Math.max(...pct);
    const card=make('article',undefined,'panel weather-chart-card weather-rose');card.dataset.variable='rosa';
    const header=make('div',undefined,'panel-head');const heading=make('div');
    heading.append(make('p',(modeled?'REANÁLISIS / ':'OBSERVACIÓN / ')+source,'eyebrow'),make('h3','Rosa de vientos'));
    header.append(heading,make('span','% horas','source-badge'));card.append(header);
    const body=make('div',undefined,'weather-canvas');const canvas=document.createElement('canvas');
    const top=names[pct.indexOf(max)];
    canvas.setAttribute('role','img');canvas.setAttribute('aria-label',`Rosa de vientos: ${moving} horas con viento; sector más frecuente ${top} (${number.format(max)}%).`);
    body.append(canvas);card.append(body);
    card.append(make('p',`${moving} horas con viento y dirección del mismo reporte. Dirección de donde sopla. Calmas: ${calm} (${number.format(100*calm/total)}%), fuera de los sectores. Sector más frecuente: ${top}.`,'panel-note'));
    card.append(make('p','Describe esta ventana; no demuestra el transporte de contaminantes ni representa todo el municipio.','panel-note weather-stat'));
    $('weatherCharts').append(card);
    const color=modeled?[230,199,137]:[117,239,210];
    charts.push(new Chart(canvas,{type:'polarArea',data:{labels:names,datasets:[{data:pct,
      backgroundColor:pct.map(v=>`rgba(${color},${.18+.62*(max?v/max:0)})`),borderColor:`rgb(${color})`,borderWidth:1}]},
      options:{responsive:true,maintainAspectRatio:false,animation:false,startAngle:-22.5,
        plugins:{legend:{display:false},tooltip:{callbacks:{label:i=>`${names[i.dataIndex]}: ${number.format(pct[i.dataIndex])}% · ${count[i.dataIndex]} h · media ${count[i.dataIndex]?number.format(sum[i.dataIndex]/count[i.dataIndex]):'—'} m/s`}}},
        scales:{r:{startAngle:-22.5,grid:{color:'#9bc8c926'},angleLines:{color:'#9bc8c926'},ticks:{color:'#b4cbd4',backdropColor:'transparent',font:{size:9},callback:v=>v+'%'},
          pointLabels:{display:true,centerPointLabels:true,color:'#d5e6ec',font:{size:11}}}}}}));
    return true;
  }
  async function load(){
    request?.abort();request=new AbortController();const active=request;
    clear();$('weatherCharts').setAttribute('aria-busy','true');$('weatherStatus').textContent='Consultando series y cobertura verificables…';
    const site=selectedSite(),wanted=[...$('weatherVariables').querySelectorAll('input:checked')].map(n=>n.value);
    if(!site||!wanted.length||wanted.length>6){$('weatherStatus').textContent='Elige entre una y seis variables con observaciones.';$('weatherCharts').setAttribute('aria-busy','false');return;}
    const available=site.variables.filter(v=>wanted.includes(v.variable_id));
    const latest=Math.max(...available.map(v=>Date.parse(v.ultima_utc)));
    const end=$('weatherAnchor').value==='latest'?Math.floor(latest/3600000)*3600000+3600000:Math.floor(Date.now()/3600000)*3600000;
    const start=end-Number($('weatherPeriod').value)*86400000;
    const query=new URLSearchParams({estacion:site.estacion_id,variable:wanted.join(','),desde:iso(start),hasta:iso(end)});
    try{
      const [data,coverage]=await Promise.all([json('/observaciones?'+query+'&resolucion=hora',active.signal),json('/cobertura?'+query,active.signal)]);
      if(request!==active)return;
      const modeled=data.estacion.tipo_producto!=='observacion';
      $('weatherProduct').textContent=modeled?'MODELADO · REANÁLISIS':'OBSERVACIÓN · METEOROLOGÍA';
      $('weatherProduct').classList.toggle('modeled',modeled);
      $('weatherWindow').textContent=iso(start)+' → '+iso(end)+' (fin exclusivo)';
      $('weatherMethod').textContent=data.metodo;
      $('weatherScope').textContent=data.estacion.municipio+': '+data.estacion.municipio_nota+' Alcance espacial: '+data.estacion.resolucion_espacial+'.';
      $('weatherAttribution').textContent=data.fuente.nombre+' — '+data.fuente.atribucion;
      $('weatherLicense').textContent='Condiciones: '+data.fuente.licencia;
      $('weatherContextTitle').textContent=modeled?'Una rejilla no es una estación.':'MMQT: contexto meteorológico, no contaminación.';
      $('weatherContextText').textContent=modeled?'Estos valores proceden de un producto modelado. La coordenada solicitada no convierte el reanálisis en una observación puntual.':'Los reportes del aeropuerto son instantáneos. Para cada hora se conserva el último reporte, no una media horaria. El instante real sigue en la tabla.';
      mapSite(data.estacion);
      let count=0;
      for(const [id,series] of Object.entries(data.series)){
        const points=series.puntos;
        if(points.some(p=>!Number.isFinite(p.valor)||!Number.isFinite(Date.parse(p.fecha_utc))))throw new Error('Serie incompatible; no se muestra.');
        count+=points.length;
        const c=coverage.variables.find(c=>c.variable_id===id);
        const card=make('article',undefined,'panel weather-chart-card');
        card.dataset.variable=id;if(count===points.length)card.classList.add('is-selected');
        const header=make('div',undefined,'panel-head');const heading=make('div');heading.append(make('p',modeled?'REANÁLISIS / '+data.fuente.fuente_id:'OBSERVACIÓN / '+data.fuente.fuente_id,'eyebrow'),make('h3',series.nombre));header.append(heading,make('span',series.unidad,'source-badge'));card.append(header);
        const description=`${points.length} valores · ${c?.horas_con_dato??0}/${c?.horas_esperadas??0} horas con dato (${c?.porcentaje??'—'}%). Último disponible: ${c?.ultima_utc||'sin dato'}.`;
        const body=make('div',undefined,'weather-canvas');const canvas=document.createElement('canvas');canvas.setAttribute('role','img');canvas.setAttribute('aria-label',series.nombre+'. '+description);body.append(canvas);card.append(body,make('p',description,'panel-note'));$('weatherCharts').append(card);
        const usable=points.filter(p=>!p.marca_origen&&!p.fuera_de_rango&&!p.revisada);
        const angular=id==='viento_direccion';
        const mean=usable.length&&!angular?usable.reduce((a,p)=>a+p.valor,0)/usable.length:null;
        card.append(make('p',mean!==null?`Media descriptiva de ${usable.length} valores sin estas marcas: ${number.format(mean)} ${series.unidad}. No es un índice de salud ni una media territorial.`:angular?'Dirección angular: no calculamos una media aritmética de grados.':'Sin valores suficientes sin marcas para resumir.','panel-note weather-stat'));
        for(const p of points)table.push({name:series.nombre,unit:series.unidad,p});
        if(!points.length){body.replaceChildren(make('p','Sin valores en esta ventana. No se rellenan horas ausentes.'));continue;}
        const plot=[];let previous;
        for(const p of points){const x=Date.parse(p.fecha_utc);if(previous!==undefined&&x-previous>3600000)plot.push({x:previous+3600000,y:null});plot.push({x,y:p.valor});previous=x;}
        if(window.Chart)charts.push(new Chart(canvas,{type:angular?'scatter':'line',data:{datasets:[{label:series.nombre+' · '+series.unidad,data:plot,
          borderColor:modeled?'#e6c789':'#75efd2',backgroundColor:modeled?'#e6c789':'#75efd2',borderDash:modeled?[5,3]:[],pointRadius:angular?2:0,pointHoverRadius:4,borderWidth:1.4,tension:0,spanGaps:false}]},options:{responsive:true,maintainAspectRatio:false,animation:false,parsing:false,interaction:{mode:'nearest',intersect:false},plugins:{legend:{display:false},tooltip:{callbacks:{title:items=>date(items[0].parsed.x)+' · Querétaro'}}},scales:{x:{type:'linear',min:start,max:end,grid:{color:'#9bc8c90a'},ticks:{color:'#b4cbd4',maxTicksLimit:4,font:{size:9},callback:value=>new Intl.DateTimeFormat('es-MX',{timeZone:'America/Mexico_City',day:'2-digit',month:'short'}).format(new Date(value))}},y:{min:angular?0:undefined,max:angular?360:undefined,grid:{color:'#9bc8c918'},ticks:{color:'#b4cbd4',font:{size:9}}}}}}));
        else body.replaceChildren(make('p','Gráfica no disponible; los valores siguen en la tabla.'));
      }
      const rose=windRose(data.series,modeled,data.fuente.fuente_id);
      $('weatherMobileView').replaceChildren(...Object.entries(data.series).map(([id,s])=>new Option(s.nombre+' · '+s.unidad,id)),...(rose?[new Option('Rosa de vientos','rosa')]:[]),new Option('Todas las gráficas','all'));
      page();$('weatherCount').textContent=count.toLocaleString('es-MX')+' valores en '+wanted.length+' variables, sin sumar unidades';
      $('weatherStatus').textContent=(modeled?'Reanálisis modelado':'Observaciones meteorológicas')+' · '+site.nombre+' · '+($('weatherAnchor').value==='latest'?'ventana al final del archivo, puede ser antigua.':'ventana referida a hoy, con posible latencia de publicación.');
    }catch(error){if(error.name!=='AbortError'){clear();$('weatherStatus').textContent=error.message+' No se conserva una gráfica anterior como actual.';}}
    finally{if(active===request)$('weatherCharts').setAttribute('aria-busy','false');}
  }
  document.querySelectorAll('[data-domain]').forEach(button=>button.addEventListener('click',()=>{
    const weather=button.dataset.domain==='weather';$('airWorkspace').hidden=button.dataset.domain!=='air';$('weatherWorkspace').hidden=!weather;
    const pollution=document.getElementById('pollutantWorkspace');if(pollution)pollution.hidden=button.dataset.domain!=='pollutants';
    document.querySelectorAll('[data-domain]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
    if(weather)load();else window.dispatchEvent(new Event('resize'));
  }));
  $('weatherFilters').addEventListener('submit',e=>{e.preventDefault();load();});
  $('weatherSource').addEventListener('change',()=>{siteOptions();load();});$('weatherStation').addEventListener('change',()=>{variableOptions();load();});
  $('weatherMore').addEventListener('click',page);
  $('weatherMobileView').addEventListener('change',()=>{document.querySelectorAll('.weather-chart-card').forEach(c=>c.classList.toggle('is-selected',$('weatherMobileView').value==='all'||c.dataset.variable===$('weatherMobileView').value));requestAnimationFrame(()=>charts.forEach(c=>c.resize()));});
  (async()=>{
    try{
      const [f,v,s]=await Promise.all([json('/fuentes'),json('/variables'),json('/estaciones')]);
      sites=s.estaciones.filter(s=>['noaa-ghcnh','nasa-power'].includes(s.fuente_id)&&s.variables.some(v=>v.observaciones>0));variables=v.variables;sources=f.fuentes.filter(f=>sites.some(s=>s.fuente_id===f.fuente_id));
      if(!sources.length)throw new Error('Sin series');
      $('weatherSource').replaceChildren(...sources.map(s=>new Option((s.tipo_producto==='observacion'?'Observación · ':'Reanálisis · ')+s.nombre,s.fuente_id)));
      if(sources.some(s=>s.fuente_id==='noaa-ghcnh'))$('weatherSource').value='noaa-ghcnh';siteOptions();
      $('weatherDomain').disabled=false;$('weatherAvailability').textContent=sources.length+' productos con series verificables';
      // Enlace directo desde el inicio (/inicio/explorar#tiempo).
      if(location.hash==='#tiempo')$('weatherDomain').click();
    }catch(error){$('weatherAvailability').textContent='Capa no disponible en esta base';$('weatherDomain').disabled=true;}
  })();
})();
