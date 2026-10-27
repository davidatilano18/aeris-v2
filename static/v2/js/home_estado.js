'use strict';
// Perfil horario de PM2.5: una línea por fuente, nunca promediadas entre sí.
(() => {
  const data = document.getElementById('estadoPerfiles');
  const canvas = document.getElementById('estadoPerfil');
  if (!data || !canvas || !window.Chart) return;
  const perfiles = JSON.parse(data.textContent);
  const colores = {'OpenAQ': ['#75efd2', []], 'OpenAQ-Archive': ['#8fb3ff', [5, 4]]};
  const datasets = Object.entries(perfiles).map(([fuente, p]) => ({
    label: p.etiqueta || p.nombre, data: p.medias.map((y, x) => ({x, y})),
    borderColor: colores[fuente][0], backgroundColor: colores[fuente][0] + '22', borderDash: colores[fuente][1],
    borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: .35, fill: fuente === 'OpenAQ'}));
  new Chart(canvas, {
    type: 'line', data: {datasets},
    options: {
      responsive: true, maintainAspectRatio: false, parsing: false, animation: false,
      interaction: {mode: 'index', intersect: false},
      plugins: {
        legend: {labels: {color: '#d5e6ec', boxWidth: 18, font: {size: 11}}},
        tooltip: {backgroundColor: '#0c1e2cee', borderColor: '#36535c', borderWidth: 1,
          callbacks: {title: items => items[0].parsed.x + ':00 h', label: i => `${i.dataset.label}: ${i.parsed.y.toFixed(1)} µg/m³`}},
      },
      scales: {
        x: {type: 'linear', min: 0, max: 23, grid: {color: '#9bc8c90d'},
            ticks: {stepSize: 3, color: '#a8bfca', font: {size: 10}, callback: v => v + ':00'}},
        y: {beginAtZero: true, grid: {color: '#9bc8c91a'}, ticks: {color: '#a8bfca', font: {size: 10}, callback: v => v + ' µg/m³'}},
      },
    },
  });
})();
