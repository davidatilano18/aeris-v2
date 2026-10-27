# AERIS · Aprende multivariable 3.2

Rama: `aeris-codex-3.2`. Worktree: `reports/tmp_aeris_codex_3_2`, creado desde
`7e8ef44c2f0124a1046dc15ab74bceaa1e82365f` de `aeris-demo-integracion`.
No se reutilizaron las ramas antiguas ni se modificó el worktree de Claude.

## Entrega

- `/inicio/aprende`: selector de PM2.5, PM10, O₃, NO₂, SO₂ y CO. Nombre, unidad,
  decimales, bandas y método se serializan desde `indice.CONTAMINANTES`.
- Explicación breve por contaminante, tabla accesible de intervalos, valor tecleado
  y deslizador, redondeo decimal mitad hacia arriba sin multiplicación binaria.
- La entrada se reinicia a cero al cambiar de variable: se etiqueta siempre como
  **valor de prueba, no medición de Querétaro**. El rango del deslizador limita solo
  su presentación; una entrada superior se clasifica completa y se explica el límite.
  Vacíos, negativos y entradas inválidas no reciben categoría. Acepta coma decimal.
- La guía OMS de PM2.5 no se aplica a otros contaminantes. No se emite veredicto
  de cumplimiento legal ni evaluación personal de salud.
- El recorrido de horas reales conserva PM2.5 y su fuente/fecha; se identifica como
  independiente del simulador. Se retuvo precisión de las horas antes de promediar,
  evitando el redondeo previo a dos decimales que tenía ese recorrido educativo.
  Los textos ya no atribuyen una falla instrumental confirmada a una marca automática.
- «Cómo trabajamos» documenta Archive multivariable desde 2021, gases-v1 y CAMS
  no integrado **en esta versión**. Los contadores existentes siguen siendo solo
  de PM2.5; no se presentan como totales multivariable. Diferencia la suficiencia
  de partículas del mínimo diario añadido por AERIS para gases.
- Diseño 3.0, fuentes locales, foco visible, mensajes accesibles, alternativa sin
  JavaScript y respeto al movimiento reducido. Ningún recurso nuevo de CDN.

## Corte usado y conservación

Se abrió exclusivamente el corte solicitado, mediante el launcher verificador:
`C:\Users\MSI_COREi5\AERIS-Demo-datos\corte-31-20261020\demo.json`.
Ambos datasets del manifiesto apuntan a `aeris.db`, SHA-256
`12300d7712268ffae3dcab449c55c302a42900c55d9db27a75a9150a8c687520`.
Lectura URI `mode=ro`; integridad `ok`, claves foráneas sin infracciones.

Consulta de solo lectura sobre `openaq-archivo`:

| Variable | Registros | Unidad |
|---|---:|---|
| PM10 | 20,454 | µg/m³ |
| O₃ | 126,952 | ppm |
| NO₂ | 126,665 | ppm |
| SO₂ | 126,908 | ppm |
| CO | 126,898 | ppm |

En las cinco series, primer instante 2021-09-07T21:00:00Z y último
2026-10-17T06:00:00Z. Son extremos globales, no cobertura continua ni cobertura
igual por estación. No hubo importaciones ni ingestas.

## Validación

- `python -B -m unittest discover -s tests`: **347 pruebas, OK**.
- Las cinco nuevas pruebas comprueban seis contratos publicados, solo lectura,
  rutas conservadas, precisión de horas y ausencia de ejemplos sin inventar registros.
- Se actualizó una prueba anterior que buscaba umbrales duplicados en JavaScript:
  ahora comprueba la configuración realmente publicada para los seis contaminantes.
- Chrome real: **1440, 390, 320 px**, 96 fronteras de bandas por ancho, más entradas
  inválidas, coma decimal, cero, valores fuera del deslizador, cambio de contaminante,
  ocultación de OMS, teclado, movimiento reducido y ausencia de solicitudes externas.
  Sin errores JS ni desbordamiento horizontal.
- `/`, `/v2`, `/v2/datos`, `/inicio` y `/inicio/aprende`: HTTP 200 con el corte real.
- Capturas y logs fuera de la entrega Git: proyecto original, carpeta
  `reports/aeris32_browser/`, y `reports/aeris32_unittest.txt`.

La [revisión independiente del índice](aeris_indice_nom172_review.md) contiene un
defecto aritmético reproducible y límites de gases-v1, cobertura y referencia temporal.
No se editó `indice.py` para resolverlos ni se habilitaron modelos.

## Ejecución local

Desde este worktree, PowerShell:

```powershell
C:\Users\MSI_COREi5\AERIS\.venv\Scripts\python.exe -B scripts/run_local_demo.py --manifest C:\Users\MSI_COREi5\AERIS-Demo-datos\corte-31-20261020\demo.json --port 5056 --offline
```

Abrir `http://127.0.0.1:5056/inicio/aprende` y `http://127.0.0.1:5056/inicio#metodo`.
Si el servidor ya sigue activo, no lanzar otro en ese puerto. Parar con Ctrl+C.

Prueba visual reproducible (requiere Chrome y websocket-client en el entorno de desarrollo):

```powershell
C:\Users\MSI_COREi5\AERIS\.venv\Scripts\python.exe -B scripts/validate_aprende_browser.py --port 5056 --output C:\Users\MSI_COREi5\AERIS\reports\aeris32_browser
```

El script de navegador no es una dependencia web ni ejecuta ingestión. Los valores
de sus casos de prueba solo entran al simulador educativo, nunca a SQLite.

## Archivos de la entrega

`aeris_web/aprende.py`, `static/v2/js/aprende.js`, `static/v2/css/aprende.css`,
`templates/v2/aprende.html`, `templates/v2/home_method.html`,
`tests/test_datos_aprende.py`, `tests/test_aprende_multi.py`,
`scripts/validate_aprende_browser.py` y estos dos documentos.

Sin cambios en `indice.py`, `datos_abiertos.py`, `routes.py`, `home_indice.html`,
`data_ingestion/`, escenas, Railway, datos productivos, respaldos, tareas o modelos.
Sin push, merge ni despliegue. La integración CAMS de Claude es una tarea separada;
al incorporarla más adelante habrá que actualizar el estado de fuente de esta portada.
