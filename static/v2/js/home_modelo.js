'use strict';
// PM2.5 mensual: modelo CAMS de la celda de El Marqués (punteado) frente a una medición de esa celda (continua).
(() => {
  const data = document.getElementById('modeloDatos');
  const canvas = document.getElementById('modeloSerie');
  if (!data || !canvas || !window.Chart) return;
  const serie = JSON.parse(data.textContent);
  const cercana = canvas.dataset.cercana;
  const meses = [...new Set(Object.values(serie).flatMap(s => Object.keys(s)))].sort();
  const linea = (s, label, color, dash) => ({label, data: meses.map(m => s[m] ?? null), borderColor: color,
    backgroundColor: color + '22', borderDash: dash, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4,
    tension: .3, spanGaps: false});
  new Chart(canvas, {
    type: 'line',
    data: {labels: meses, datasets: [
      linea(serie.modelo, 'Modelo CAMS · El Marqués (y su celda)', '#e5bf79', [6, 4]),
      linea(serie.medido_cercana, 'Medido · ' + cercana, '#75efd2', []),
    ]},
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: {mode: 'index', intersect: false},
      plugins: {
        legend: {labels: {color: '#d5e6ec', boxWidth: 18, font: {size: 11}}},
        tooltip: {backgroundColor: '#0c1e2cee', borderColor: '#36535c', borderWidth: 1,
          filter: i => i.parsed.y != null,
          callbacks: {label: i => `${i.dataset.label}: ${i.parsed.y.toFixed(1)} µg/m³`}},
      },
      scales: {
        x: {grid: {color: '#9bc8c90d'}, ticks: {color: '#a8bfca', font: {size: 10}, maxTicksLimit: 9}},
        y: {beginAtZero: true, grid: {color: '#9bc8c91a'}, ticks: {color: '#a8bfca', font: {size: 10}, callback: v => v + ' µg/m³'}},
      },
    },
  });
})();
