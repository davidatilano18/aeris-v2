# Laboratorio de contaminantes · Codex 3.3

Rama `aeris-codex-3.3`, worktree `reports/tmp_aeris_codex_3_3`, desde
`678800d62c0551e88d792a86152c7d1300ca9d16` de `aeris-demo-integracion`.
Entrega exclusivamente frontend; ningún archivo reservado de backend tiene diferencias.

## Interfaz

En `/inicio/explorar` aparece la pestaña **Contaminantes**. Se conservan las vistas
anteriores de PM2.5 y Tiempo. El nuevo acceso directo es `/inicio/explorar#contaminantes`.

- Producto: observaciones `openaq-archivo` o modelo `open-meteo-cams`, sin combinarlos.
- Municipio, estación/punto de consulta y variable proceden del catálogo de la API.
  PM10, O₃, NO₂, SO₂ y CO se consultan como observaciones. CAMS ofrece PM2.5 y PM10
  en el corte utilizado; otras variables se identifican como sin registros.
- Ventanas de 48 h, 7 y 30 días, ancladas al último registro de la variable o a la
  fecha actual; fechas históricas UTC explícitas, máximo 400 días. El último día
  elegido se incluye sumando un día al límite exclusivo de la consulta.
- Gráfica horaria con huecos, unidad propia, ejes/tooltip locales y tabla UTC/local
  accesible con 200 filas por página. No hay medias municipales ni categorías sanitarias.
- CAMS lleva siempre **«Modelo, no medición»**: producto, aviso, selección de sitio,
  leyenda de la gráfica, tooltip, resumen y tabla. Trazo discontinuo y explicación
  del punto de rejilla; no se dibuja una superficie ni se supone un sensor en el punto.
- La revisión muestra las marcas que ya devuelve la API, sin ejecutar gases-v1 en
  JavaScript ni reemplazar los originales por revisiones posteriores. La cobertura
  incluye horas marcadas: disponibilidad no equivale a precisión instrumental.
- Errores, abortos, cambios de fuente y datos ausentes limpian gráfica y valores
  anteriores. Se verifican identidad de fuente/sitio, tipo, unidades, fechas, orden y
  valores finitos antes de presentar la serie.

La vista Tiempo queda limitada a NOAA GHCNh y NASA POWER. Así no aparece CAMS
rotulado como reanálisis meteorológico ni el archivo de contaminantes como tiempo.
El controlador de pestañas existente se amplió para ocultar las otras dos vistas.

## Contrato reutilizado

Sin endpoints nuevos: `/api/ambiental/v1/fuentes`, `/variables`, `/estaciones`,
`/observaciones` y `/cobertura`. Las observaciones se piden con `estacion`, una
`variable`, `desde`, `hasta`, `resolucion=hora` e `incluir_marcadas=1`.
La fuente está determinada por la identidad del sitio; no se intercambian estaciones
o modelos si una variable no tiene registros. Se conserva el instante original que
devuelve la resolución horaria. El texto del método y la atribución vienen de la API.

## Corte y resultados verificables

Se usó únicamente `C:\Users\MSI_COREi5\AERIS-Demo-datos\corte-32-20261020\demo.json`
con el launcher de demostración. SHA-256 del archivo, coincidente al terminar:
`e3639e93cc88d21b5c336b4b7c108f2f5f3db569de644d09f934b1743840ac43`.
El launcher verificó hash, integridad y claves foráneas antes del arranque en modo lectura.
No se consultó ni escribió SQLite productiva.

Resultados de las consultas reales de navegador, ventana de siete días al final del
historial de cada variable en `openaq:235220`: PM10 115 valores, O₃ 112, NO₂ 114,
SO₂ 114 y CO 112. Las fechas finales pueden diferir por variable: no es una comparación
entre contaminantes. PM10 observado solo aparece en esa estación dentro de este corte;
las demás estaciones no reciben valores sustitutos.

El Marqués (`openaq:235221`), O₃, septiembre de 2021: **334 valores**, siempre
identificados como historia. CAMS (`cams:marques`), ventana final de siete días:
**168 valores de PM2.5 y 168 de PM10**, identificados como modelo, no medición.
Estos recuentos pertenecen a la copia de demostración, no afirman cobertura actual.

## Validación

- `python -B -m unittest discover -s tests`: **359 pruebas, OK** (4 nuevas).
  Existen advertencias heredadas de cierre de archivos de pruebas; no hubo fallos.
- Chrome real a **1440, 390 y 320 px** con movimiento reducido: cinco variables
  observadas, dos modeladas, historia de El Marqués, paginación, teclado, unidades,
  consultas sin datos, fechas invertidas, fallo de red y cambios rápidos de producto.
  Sin errores JavaScript ni desbordamiento horizontal; sin recursos externos.
- `/`, `/v2`, `/v2/datos`, `/inicio` y `/inicio/explorar`: HTTP 200 con este corte.
- `git diff --check` sin errores. Backend reservado, ingesta, modelos y holdout intactos.

Capturas y log, fuera de Git en el proyecto original:
`reports/aeris33_browser/{contaminants_<ancho>.png,contaminants_chart_<ancho>.png,contaminants_<ancho>_full.png,browser.json}`
y `reports/aeris33_unittest.txt`.

## Ejecutar y reproducir

Desde este worktree, PowerShell:

```powershell
C:\Users\MSI_COREi5\AERIS\.venv\Scripts\python.exe -B scripts/run_local_demo.py --manifest C:\Users\MSI_COREi5\AERIS-Demo-datos\corte-32-20261020\demo.json --port 5058 --offline
```

Abrir `http://127.0.0.1:5058/inicio/explorar#contaminantes`. Si el servidor ya está
activo, no abrir otro en ese puerto. Se detiene con Ctrl+C.

```powershell
C:\Users\MSI_COREi5\AERIS\.venv\Scripts\python.exe -B scripts/validate_contaminants_browser.py --port 5058 --output C:\Users\MSI_COREi5\AERIS\reports\aeris33_browser
```

El script requiere Chrome y websocket-client solo para desarrollo. No modifica la
API ni SQLite; simula un fallo de transporte exclusivamente en ese navegador.

## Archivos y límites

Modificados: `templates/v2/workspace.html`, `static/v2/js/meteorology.js`.
Nuevos: `templates/v2/contaminants.html`, `static/v2/js/contaminants.js`,
`static/v2/css/contaminants.css`, `tests/test_contaminants_frontend.py`,
`scripts/validate_contaminants_browser.py` y este documento.

Sin cambios en `indice.py`, `modelo.py`, `datos_abiertos.py`, `routes.py` ni
`data_ingestion/`. Sin ingestas, entrenamientos, cambios productivos, tareas Windows,
Railway, commits, push, merge o despliegue. Las estadísticas del índice y la validación
de CAMS siguen siendo responsabilidad del backend; esta vista no genera análisis causal,
comparaciones entre productos ni pronósticos nuevos.
