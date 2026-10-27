'use strict';
// AERIS · Educational input, independent from the real PM2.5 walkthrough below.
// All bands, units, precision and daily methods are serialized from indice.py.
(() => {
  const $ = id => document.getElementById(id);
  const MINIMAS = 18;
  const fmt = (v, d = 1) => v.toLocaleString('es-MX', {minimumFractionDigits: d, maximumFractionDigits: d});

  // Round the decimal string, not a binary product (e.g. 5.005 * 100).
  // Only nonnegative, finite concentrations are valid educational inputs.
  function mitadArriba(raw, digits) {
    const text = String(raw).trim().replace(',', '.');
    if (text.length > 32 || !/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(text)) return null;
    const [whole = '0', fraction = ''] = text.split('.');
    const scale = 10n ** BigInt(digits);
    const kept = fraction.padEnd(digits + 1, '0');
    let units = BigInt(whole || '0') * scale + BigInt(kept.slice(0, digits) || '0');
    if (Number(kept[digits]) >= 5) units++;
    if (units > BigInt(Number.MAX_SAFE_INTEGER)) return null;
    return Number(units) / Number(scale);
  }

  // 1) Simulator: selection resets to a labelled input of zero, never a reading.
  const control = $('apValor');
  if (control && $('apContaminantes')) {
    const configs = JSON.parse($('apContaminantes').textContent);
    const selector = $('apContaminante'), input = $('apEntrada');
    const classify = (key, raw) => {
      const config = configs[key];
      if (!config) return null;
      const value = mitadArriba(raw, config.decimales);
      if (value === null) return null;
      const band = config.bandas.find(b => b.tope === null || value <= b.tope);
      return {value, band};
    };
    window.AerisAprende = Object.freeze({mitadArriba, classify});
    function actualizar() {
      const config = configs[selector.value];
      const result = classify(selector.value, input.value);
      input.setAttribute('aria-invalid', String(!result));
      $('apError').hidden = Boolean(result);
      $('apError').textContent = result ? '' : 'Escribe un número no negativo, con punto o coma decimal. No uses separadores de miles.';
      if (!result) {
        $('apNumero').textContent = '—'; $('apCategoria').textContent = 'Sin clasificación';
        $('apCategoria').className = ''; $('apRiesgo').textContent = 'El valor de prueba no es válido.';
        $('apNorma').textContent = ''; $('apOms').textContent = ''; $('apMarca').hidden = true;
        return;
      }
      const {value, band: b} = result;
      $('apNumero').textContent = fmt(value, config.decimales);
      const cat = $('apCategoria');
      cat.textContent = b.nombre; cat.className = b.clase;
      $('apRiesgo').textContent = 'Riesgo asociado a esta banda de referencia: ' + b.riesgo.toLowerCase() + '. No es una evaluación personal.';
      $('apNorma').textContent = `Valor de prueba tras redondear: ${fmt(value, config.decimales)} ${config.unidad}. Método diario: ${config.metodo}.`;
      if (Number(input.value.replace(',', '.')) > config.maximo) $('apNorma').textContent += ' Fuera del tramo del deslizador; la clasificación sigue usando el valor completo.';
      $('apOms').hidden = selector.value !== 'pm25';
      $('apOms').textContent = selector.value === 'pm25' ? 'La guía OMS 2021 de PM2.5 diario es 15 µg/m³; una referencia distinta de las bandas mexicanas.' : '';
      $('apMarca').hidden = false;
      $('apMarca').style.left = (Math.min(value, config.maximo) / config.maximo * 100) + '%';
      control.setAttribute('aria-valuetext', `${control.value} ${config.unidad}, valor de prueba; tras redondear: ${fmt(value, config.decimales)}, ${b.nombre}`);
    }
    function seleccionar() {
      const config = configs[selector.value];
      control.max = config.maximo; control.step = config.paso; control.value = '0'; input.value = '0';
      $('apUnidad').textContent = config.unidad; $('apEntradaUnidad').textContent = config.unidad;
      $('apDescripcion').textContent = config.explicacion;
      $('apMetodo').textContent = `Método diario: ${config.metodo} · ${config.unidad}`;
      $('apComplecion').textContent = selector.value === 'co'
        ? 'Cada ventana usa la hora de cierre y las siete anteriores (también del día previo), con al menos 6 horas. AERIS añade un mínimo diario de 18 horas válidas: es un criterio propio.'
        : ['o3', 'no2', 'so2'].includes(selector.value)
          ? 'Se toma el máximo horario del día. AERIS exige además 18 horas válidas para reducir el riesgo de omitir el pico; ese mínimo diario es un criterio propio.'
          : 'Día local desde las 00:00: al menos 18 de 24 horas. Las horas con revisión pendiente no entran al cálculo de AERIS.';
      $('apRedondeo').textContent = `Antes de clasificar: ${config.decimales} decimales, redondeo «mitad hacia arriba». El siguiente 5 incrementa la última cifra retenida.`;
      $('apTablaTitulo').textContent = `Tabla ${config.tabla} de la NOM-172-SEMARNAT-2023 · ${config.nombre} · referencia 2026`;
      $('apTablaUnidad').textContent = config.unidad;
      $('apTablaBandas').replaceChildren(...config.bandas.map(b => {
        const tr = document.createElement('tr');
        for (const text of [b.nombre, b.riesgo, b.intervalo]) { const td = document.createElement('td'); td.textContent = text; tr.append(td); }
        const dot = document.createElement('i'); dot.className = 'dot ' + b.clase; dot.setAttribute('aria-hidden', 'true'); tr.firstChild.prepend(dot);
        return tr;
      }));
      let previous = 0;
      const segments = config.bandas.map(b => {
        const end = b.tope === null ? config.maximo : b.tope;
        const segment = document.createElement('span'); segment.className = b.clase;
        segment.style.setProperty('--ancho', ((end - previous) / config.maximo * 100) + '%');
        previous = end; return segment;
      });
      $('apBarra').replaceChildren(...segments, $('apMarca'));
      $('apEjeMax').textContent = fmt(config.maximo, config.decimales) + ' ' + config.unidad;
      actualizar();
    }
    control.addEventListener('input', () => { input.value = control.value; actualizar(); });
    input.addEventListener('input', () => {
      if (mitadArriba(input.value, configs[selector.value].decimales) !== null) control.value = Math.min(Number(input.value.replace(',', '.')), configs[selector.value].maximo);
      actualizar();
    });
    selector.addEventListener('change', seleccionar); seleccionar();
  }

  // 2) Recorrido de un día real.
  const datos = $('apEjemplos');
  if (!datos) return;
  const ejemplos = JSON.parse(datos.textContent);
  let actual = 0, paso = 0;
  const pasos = [...document.querySelectorAll('#apPasos li')];

  function dibujar() {
    const e = ejemplos[actual];
    const tope = Math.max(30, ...e.horas.filter(h => h.valor !== null && !h.revision).map(h => h.valor), e.media || 0);
    const cont = $('apHoras');
    cont.replaceChildren(...e.horas.map(h => {
      const barra = document.createElement('span');
      barra.className = 'ap-hora' + (h.valor === null ? ' sin-dato' : '') + (h.revision ? ' marcada' : '');
      const alto = h.valor === null ? 100 : Math.min(100, h.valor / tope * 100);
      barra.style.setProperty('--alto', alto + '%');
      if (h.revision && h.valor > tope) barra.dataset.recorte = fmt(h.valor, 0);
      barra.title = `${h.hora}:00 · ` + (h.valor === null ? 'sin medición' : `${fmt(h.valor)} µg/m³${h.revision ? ' · marcada' : ''}`);
      return barra;
    }));
    if (e.media !== null) {
      const linea = document.createElement('i');
      linea.className = 'ap-media'; linea.style.setProperty('--nivel', Math.min(100, e.media / tope * 100) + '%');
      linea.dataset.texto = `promedio ${fmt(e.media)}`;
      cont.append(linea);
    }
    const textos = {
      con_dato: `${e.con_dato} de 24 horas tienen medición.`,
      marcadas: e.marcadas ? `${e.marcadas} horas marcadas como sospechosas no se usan.` : 'Ninguna hora está marcada.',
      validas: e.validas >= MINIMAS ? `Sí: ${e.validas} horas válidas.` : `No: solo ${e.validas}. El día no se califica.`,
      media: e.media !== null ? `${fmt(e.media)} µg/m³.` : 'No se calcula: faltan horas válidas.',
      banda: e.banda ? `${e.banda}.` : `Sin categoría (${e.clasificacion}).`,
    };
    pasos.forEach(li => { li.querySelector('[data-dato]').textContent = textos[li.querySelector('[data-dato]').dataset.dato]; });
    $('apDiaTitulo').textContent = `${e.estacion} · ${e.dia} · ${e.fuente}`;
    $('apLeccion').textContent = e.leccion;
    mostrar();
  }

  function mostrar() {
    const panel = $('apDia');
    panel.dataset.paso = String(paso);
    pasos.forEach((li, i) => { li.classList.toggle('hecho', i < paso); li.classList.toggle('activo', i === paso - 1); });
    $('apAnterior').disabled = paso === 0;
    $('apSiguiente').disabled = paso >= pasos.length;
    $('apSiguiente').textContent = paso === 0 ? 'Empezar →' : paso >= pasos.length ? 'Listo' : 'Siguiente paso →';
  }

  document.querySelectorAll('[data-ejemplo]').forEach(boton => boton.addEventListener('click', () => {
    actual = Number(boton.dataset.ejemplo); paso = 0;
    document.querySelectorAll('[data-ejemplo]').forEach(b => b.setAttribute('aria-selected', String(b === boton)));
    $('apDia').setAttribute('aria-labelledby', boton.id);
    dibujar();
  }));
  $('apSiguiente').addEventListener('click', () => { paso = Math.min(pasos.length, paso + 1); mostrar(); });
  $('apAnterior').addEventListener('click', () => { paso = Math.max(0, paso - 1); mostrar(); });
  document.documentElement.classList.add('ap-interactivo');
  dibujar();
})();
