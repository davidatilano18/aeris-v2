'use strict';
// AERIS 3.0 · Capa de movimiento del laboratorio. No calcula nada: observa lo que workspace.js y
// meteorology.js ya escriben y anima la transición. El texto final siempre es exactamente el original.
(() => {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const numero = /^(-?[\d.,]+)(.*)$/;
  const leer = t => { const m = numero.exec((t || '').trim()); if (!m) return null;
    const v = Number(m[1].replace(/,/g, '')); return Number.isFinite(v) ? {v, resto: m[2], dec: (m[1].split('.')[1] || '').length} : null; };
  const animando = new WeakSet();

  function animar(nodo, desde, hasta, final) {
    animando.add(nodo);
    const inicio = performance.now(), dur = 650;
    const paso = ahora => {
      const k = Math.min(1, (ahora - inicio) / dur), e = 1 - Math.pow(1 - k, 3);
      if (k < 1) {
        nodo.textContent = (desde.v + (hasta.v - desde.v) * e).toLocaleString('es-MX',
          {minimumFractionDigits: hasta.dec, maximumFractionDigits: hasta.dec}) + hasta.resto;
        requestAnimationFrame(paso);
      } else { nodo.textContent = final; queueMicrotask(() => animando.delete(nodo)); }  // después del observador
    };
    requestAnimationFrame(paso);
  }

  // Cifras del panel: si cambian de un número a otro, se recorre el intervalo.
  for (const id of ['labCount', 'labCoverage', 'labQuality']) {
    const nodo = document.getElementById(id);
    if (!nodo) continue;
    let previo = nodo.textContent;
    new MutationObserver(() => {
      if (animando.has(nodo)) return;
      const final = nodo.textContent, a = leer(previo), b = leer(final);
      previo = final;
      if (a && b && a.v !== b.v && a.resto === b.resto) animar(nodo, a, b, final);
      nodo.closest('article, .kpi, div')?.classList.remove('cifra-nueva');
      void nodo.offsetWidth;
      nodo.closest('article, .kpi, div')?.classList.add('cifra-nueva');
    }).observe(nodo, {childList: true, characterData: true, subtree: true});
  }

  // Gráficas: marca de actualización para la transición CSS (el estado lo decide el script original).
  for (const id of ['labChartBox', 'weatherCharts']) {
    const nodo = document.getElementById(id);
    if (!nodo) continue;
    new MutationObserver(() => {
      if (nodo.getAttribute('aria-busy') === 'false') {
        nodo.classList.remove('recien-actualizado'); void nodo.offsetWidth; nodo.classList.add('recien-actualizado');
      }
    }).observe(nodo, {attributes: true, attributeFilter: ['aria-busy']});
  }
})();
