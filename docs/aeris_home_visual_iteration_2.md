# Inicio — segunda iteración visual local

20-oct-2026, Querétaro. Rama `aeris-home-research`, sin staging, commit ni publicación.

## Comparación disponible

- Nueva composición: http://127.0.0.1:5050/inicio
- Primera versión preservada: http://127.0.0.1:5050/inicio/anterior

Ambas usan las mismas observaciones actuales y el mismo lector. Comparar el diseño
no congela la base: sus conteos pueden cambiar por la tarea independiente. La
primera versión conserva plantilla, CSS y JS propios (`home_v1`); solo cambian sus
referencias a esos assets y la normalización de fin de línea de la plantilla.
Los hashes de CSS y JS son idénticos a los de la primera iteración; al restaurar
referencias y CRLF también coincide el hash original de la plantilla.

## Cambios visibles

La portada sustituye la gran esfera decorativa por una consola de observaciones:
total local, fecha ambiental identificada por estación, conteos separados por
fuente y extremos temporales. Son inventario, no un índice sanitario, mediciones
en vivo ni una serie continua entre extremos. No hay promedio estatal.

Navy continuo, líneas de separación y superficies oscuras reemplazan la sucesión
de tarjetas blancas. Los indicadores se compactan; procedencia, meses disponibles
y método se abren en detalles accesibles. El Marqués conserva acceso destacado
sin convertirse en filtro ni ámbito principal.

El mapa ocupa más ancho y tiene retícula geográfica calculada desde sus límites.
Las líneas son coordenadas, no observaciones, límites municipales o superficies
de contaminación. Los ocho puntos usan el catálogo; selección, teclado, fichas,
lista alternativa y teselas opcionales existentes permanecen. Las capturas usan
la vista sin teselas externas: no incluyen geografía fabricada.

Se incorpora una gráfica semanal usando exclusivamente `/api/v2/observations`,
con selección de estación y fuente. Línea sin suavizar, separadores reales de
ausencia, ceros conservados, fechas de Querétaro, µg/m³ y tabla de valores UTC
con estado de revisión. No se recalculan categorías sanitarias ni tendencias.
El resumen indica observaciones, ventana exacta y alertas/pendientes. Cada cambio
retira la gráfica anterior; AbortController impide que una petición obsoleta
reemplace la selección actual. Estados de carga, ausencia y error explícitos.

La gráfica no anima mediciones: `animation:false`, `tension:0`, `spanGaps:false`.
Las animaciones ambientales son transform/opacity de seis partículas y dos
anillos decorativos, con pausa, movimiento reducido y sin un motor de partículas.

## Validación

- **263 pruebas aprobadas en 11.900 s**, incluidas regresiones de ambas rutas,
  assets preservados, gráfica accesible y contrato de lectura de series.
- Chrome real headless en Windows, 1440 / 390 / 320 px. Ocho marcadores en cada
  vista, sin desbordamiento horizontal ni excepciones JavaScript.
- Comprobados: preferencia de movimiento reducido, pausa, apertura de ficha con
  teclado, gráfica real y tabla, selección de El Marqués sin datos en los últimos
  siete días, Archive sin registros recientes y error de red inducido sin datos
  de reemplazo ni conservación engañosa de la gráfica anterior.
- En el corte de prueba, Corregidora/OpenAQ mostró **159 observaciones** en la
  ventana horaria del 13 al 20-oct, terminada a las 08:00 locales, fin exclusivo.
  No se interpreta ese número como cobertura estatal ni como tendencia anual.
- Cero solicitudes externas en la vista inicial. La base del mapa sigue siendo
  una opción de red, no una dependencia obligatoria ni validada en estas capturas.
- HTTP 200 para /inicio, /inicio/anterior, /, /v2, /v2/datos y consulta histórica
  de El Marqués. `integrity_check=ok`, cero infracciones FK, hash SQLite idéntico
  antes/después de las comprobaciones finales. Sin escrituras a producción.
- Los 35 archivos originales preservados mantienen sus hashes. La rama del
  parche Railway sigue en `5e483f1282decc3ec28159898b3f645c6517c7b3`; main y
  origin/main no cambiaron. Índice de Git vacío y `git diff --check` correcto.

### Altura de página en condiciones comparables

Capturas completas con viewport de 960 px de alto y movimiento reducido:

| Ancho | Primera versión | Segunda versión | Observación |
|---|---:|---:|---|
| 1440 px | 4028 px | 3721 px | Menor altura, con nueva gráfica incluida |
| 390 px | 6480 px | 5477 px | Aproximadamente 15.5% menos altura |
| 320 px | 7259 px | 5974 px | Aproximadamente 17.7% menos altura |

La consola comienza a 136 / 489 / 629 px respectivamente: la información real
entra en la primera pantalla también en móvil. Estas métricas describen layout,
no demuestran comprensión de usuarios ni constituyen una auditoría de rendimiento.
CSS nuevo: 21,922 bytes; JS de mapa/movimiento: 5,141; JS de gráfica: 5,387.
Chart.js y Leaflet son los recursos locales existentes; no se añadieron paquetes.
Una petición final a /inicio tardó 61.97 ms localmente: muestra puntual, no SLA.
No se midieron FPS, GPU o rendimiento en dispositivos físicos de gama baja.

## Evidencias y archivos

En `C:\Users\MSI_COREi5\AERIS\reports`:

- `aeris_home_v2_suite.log`, `aeris_home_v2_validation.json`.
- `aeris_home_v2_visual_validation.json` y `aeris_home_v1_preservation.json`.
- `aeris_home_v2_1440_comparison_full.png` y equivalentes 390 / 320.
- `aeris_home_v1_1440_comparison_full.png` y equivalentes 390 / 320.
- Capturas separadas `_top.png` y `_map.png` para cada versión y ancho.

Cambios funcionales de esta iteración: `aeris_web/routes.py`,
`templates/v2/home.html`, `static/v2/css/home.css`, `static/v2/js/home.js`,
`static/v2/js/home_history.js`, `tests/test_home.py`. Preservación visual:
`home_v1.html`, `home_v1.css`, `home_v1.js`. Este documento registra el resultado.
`aeris_web/home.py`, SQL, ingesta, tareas, modelos y holdout no se modificaron.

La suite se ejecutó con el harness de la primera entrega: apunta la constante
de protección de producción al archivo original solo en memoria para validar
samefile; todas las pruebas de escritura/importación usan bases temporales.
No se copió SQLite al worktree ni se ejecutaron sincronizaciones manuales.

## Ejecutar y pendientes

El comando PowerShell del reporte `aeris_home_implementation.md` sigue vigente:
worktree `reports/tmp_aeris_home`, venv del proyecto original, AERIS_ENV=local,
AERIS_DB_PATH absoluto a la base original y Flask en 127.0.0.1:5050 sin debug ni
reload. Las rutas anteriores se conservan.

La gráfica de Inicio se limita a siete días; para historia se enlaza al explorador
existente. No se implementaron nuevas pantallas municipales, inferencia, análisis
estadísticos multianuales ni un mapa territorial completo. No hay certificación
WCAG, prueba con participantes o validación de dispositivos móviles físicos.
La aprobación visual del usuario es el siguiente paso. No se avanzó al despliegue.
