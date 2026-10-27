# Capa ambiental multivariable — arquitectura, operación y coordinación

Rama `aeris-data-expansion` (worktree `AERIS-Claude`). Fuentes: [inventario](aeris_fuentes_ambientales.md).
API para el frontend: [contrato v1](aeris_api_ambiental_v1.md).

## 1. Auditoría del esquema existente (solo lectura)

Base principal abierta con `mode=ro` el 20/10/2026: 15 tablas; `mediciones` 12,759 filas, todas PM2.5.

| Aspecto | Situación actual | Consecuencia para ampliar |
|---|---|---|
| Clave | `mediciones(fuente, sensor_id INTEGER, fecha_utc, contaminante)` | `sensor_id` entero es el ID de OpenAQ; otras fuentes usan textos (`MXI0000MMQT`) o coordenadas |
| Estaciones | `sensores` (catálogo PM2.5) y `estaciones` (descubrimiento OpenAQ) por separado | Sin tipo de producto ni municipio normalizado para fuentes no OpenAQ |
| Variables / unidades | `contaminante` libre, `unidad` opcional | Sin catálogo de unidades canónicas ni rangos |
| Tiempo | Solo `fecha_utc` | Hora local calculada en cada consulta |
| Calidad | Ledger inmutable con triggers (`evaluaciones_calidad`) y primera evaluación preservada | **Patrón reutilizado**: observaciones ambientales inmutables y revisiones aparte |
| Procedencia | `ingestas`, `respuestas_api`, `archivos_origen`, `observaciones_api` | Reutilizado como modelo (`amb_ingestas`, `amb_archivos`) |
| Lectores | `aeris_web`, `app.py`, `forecasting`, `catalog.read_catalog` consultan `mediciones` y `sensores` directamente | **Cualquier cambio en esas tablas rompería lectores y modelos** |

Decisión: **no modificar ninguna tabla existente**. La ampliación vive en tablas `amb_*` nuevas,
sin claves foráneas hacia el esquema legado, y se puede retirar sin dejar rastro.

## 2. Diseño (`data_ingestion/ambiental/`)

| Tabla | Propósito |
|---|---|
| `amb_migraciones` | Versión aplicada y SHA‑256 del SQL de cada migración |
| `amb_fuentes` | Organización, URL, licencia, atribución, `tipo_producto` (`observacion`, `reanalisis`, `modelo`, `estimacion`, `satelite`) y `autorizada` (0 por defecto) |
| `amb_estaciones` | `estacion_id` estable (`ghcnh:MXI0000MMQT`, `power:mmqt`), fuente, ID externo, municipio con nota de evidencia, coordenadas validadas, elevación, `tipo_sitio` (`estacion` / `celda_rejilla`) |
| `amb_variables` | Unidad canónica y rango físico por variable (meteorología y contaminantes) |
| `amb_observaciones` | Valor canónico + `valor_original` y `unidad_original` textuales, `fecha_utc` (CHECK de formato con `Z`), `fecha_local` (America/Mexico_City, con DST histórico), `periodo` (`instantaneo`, `PT1H`), `tipo_reporte`, códigos de medición y calidad del origen, `marca_origen`, `fuera_de_rango`, archivo e ingesta |
| `amb_revisiones` | Valor o código de calidad distinto publicado después para la misma clave; la observación original no cambia |
| `amb_ingestas`, `amb_archivos` | Bitácora por ejecución (conteos, estado, error) y archivo de origen (SHA‑256, ETag, Last‑Modified, ruta local) |
| `amb_estado` | Hasta dónde se consultó cada estación (para incrementales con solapamiento) |

Garantías implementadas y probadas:

- **Idempotencia**: clave única `(estacion_id, variable_id, fecha_utc, tipo_reporte)`. Reprocesar el
  mismo archivo produce solo `duplicadas`; un valor distinto produce una `revisión`, una sola vez.
- **Inmutabilidad**: triggers impiden `UPDATE`/`DELETE` en observaciones y revisiones.
- **Separación de productos**: observación y reanálisis son fuentes y estaciones distintas; la API
  exige `estacion` y nunca agrega entre estaciones.
- **No invención**: 404 de la fuente → `sin_publicacion`; valores de relleno, no finitos o futuros se
  descartan y se cuentan por motivo. Sin interpolación.
- **Base protegida**: escribir en una base que contenga `mediciones` exige `--permitir-base-principal`
  **y** `AERIS_AMBIENTAL_BASE_PRINCIPAL=autorizado`. Probado que migrar y revertir en una copia del
  esquema legado deja `sqlite_master` y los datos legados idénticos.
- **Reversible**: `revertir` elimina solo objetos `amb_*`; con datos exige `--descartar-datos`.
- **Identidad estable**: cambiar coordenadas o ID externo de una estación falla; debe crearse otra.
  Cambiar la unidad canónica de una variable o el tipo de producto de una fuente también falla.

Migraciones: **1** crea el esquema; **2** elimina `amb_observaciones_serie`, redundante con el índice
único (que ya cubre consultas por estación/variable/fecha, comprobado con `EXPLAIN QUERY PLAN`).
`esquema revertir --hasta-version 1` deshace solo la 2; sin `--hasta-version` elimina todo `amb_*`.
Propuesta futura (no implementada): vista de solo lectura de la serie PM2.5 legada con vocabulario `amb_*`.

## 3. Estado de la base de desarrollo

`AERIS-Claude/data/dev/aeris_ambiental_dev.db` (ignorada por Git), creada desde cero; **no es una
copia de producción**. Respuestas originales en `AERIS-Claude/data/raw/ambiental/` con su SHA‑256.

| Estación | Variables | Valores | Periodo UTC |
|---|---|---:|---|
| `ghcnh:MXI0000MMQT` | 8 (temperatura, rocío, HR, viento, dirección, ráfaga, altímetro, visibilidad) | 295,685 | 2021‑01‑01 → 2026‑10‑18 03:41 |
| `power:mmqt` | 7 | 84,840 | 2025‑06‑01 → 2026‑10‑18 23:00 |
| `power:cor` | 7 | 84,840 | 2025‑06‑01 → 2026‑10‑18 23:00 |

Segunda ejecución real: GHCNh respondió 304 por ETag (sin descarga) y POWER devolvió 1,008 valores,
todos duplicados. `integrity_check=ok`, 0 violaciones de claves foráneas. Cobertura de temperatura
MMQT del 1/9 al 18/10: 1,098 de 1,152 horas (95.3%); el hueco final es latencia de publicación.

## 4. Operación

```powershell
$py = 'C:\Users\MSI_COREi5\AERIS\.venv\Scripts\python.exe'
$db = 'data\dev\aeris_ambiental_dev.db'
& $py -B -m data_ingestion.ambiental.esquema --db $db migrar
& $py -B -m data_ingestion.ambiental.esquema --db $db autorizar --fuente noaa-ghcnh --fuente nasa-power
# Primera carga: --desde es obligatorio (evita ingestas masivas implícitas)
& $py -B -m data_ingestion.ambiental.actualizar --db $db --desde 2026-01-01T00:00:00Z --crudos data\raw\ambiental
# Incremental: 72 h de solapamiento sobre lo ya consultado
& $py -B -m data_ingestion.ambiental.actualizar --db $db --crudos data\raw\ambiental
# Recarga histórica desde una fecha anterior al estado (idempotente)
& $py -B -m data_ingestion.ambiental.actualizar --db $db --desde 2021-01-01T00:00:00Z --rellenar --crudos data\raw\ambiental
# Revertir (solo desarrollo)
& $py -B -m data_ingestion.ambiental.esquema --db $db revertir --descartar-datos
```

Cada ejecución escribe un reporte en `<carpeta de la base>/sync_runtime/ambiental/<uuid>.json` y,
si todo fue correcto, `ultimo_correcto.json`. Código de salida 0 = correcto o «no corresponde».

## 4b. Contaminantes criterio y modelo CAMS (AERIS 3.1–3.3, 20/10/2026)

| Fuente | `tipo_producto` | Estaciones | Variables | Conector |
|---|---|---|---|---|
| `openaq-archivo` | observacion | `openaq:<ubicación>` (8 de la red; `metadatos.sensor_pm25` enlaza con `mediciones`) | pm10, o3, no2, so2, co | `openaq_archivo.py` (lee archivos ya descargados y verificados) |
| `open-meteo-cams` | modelo | `cams:marques` y `cams:<ubicación>` por estación (`tipo_sitio=punto_modelo`) | pm25, pm10 | `open_meteo_cams.py` (vía `actualizar`, mismo recorrido por bloques que POWER) |

- El PM2.5 del archivo va a `mediciones` con la herramienta existente (`openaq_archive.import_manifest`);
  aquí no se duplica. Unidades exigidas sin conversión (ppm para gases, µg/m³ para partículas).
- CAMS: `timezone=GMT`, `domains=cams_global`; horas futuras (pronóstico) descartadas. Los 8 puntos
  caen en 3 celdas: la validación lo detecta comparando series, no coordenadas (`aeris_web/modelo.py`).
- Índice AIRE Y SALUD y revisión `gases-v1`: `aeris_web/indice.py` (solo lectura, al consultar).

Construcción del corte 32 (copias en `C:\Users\MSI_COREi5\AERIS-Demo-datos\`, nunca producción):

1. `corte-31`: copia de `ambiental-demo-003` → `esquema.sembrar` → `openaq_archive.import_manifest`
   (PM2.5) y `openaq_archivo.importar` (gases) con `data/manifests/openaq_archivo_2021_2026_completo.json`
   (6,025 archivos, un reintento registrado) → sanitizar rutas de `ingestas.reporte_json` → `VACUUM`.
2. `corte-32`: copia de `corte-31` → `sincronizar_fuente('open-meteo-cams', desde 2022-08-04)` →
   sellado (sin rutas locales, `integrity_check`, fuentes `autorizada=0`, `manifest.json`, `demo.json`).

## 5. Actualización diaria a las 08:00 — auditoría y propuesta

**Automatización existente** (consultada con `Get-ScheduledTask`, sin cambios):
`\AERIS-OpenAQ-Hourly`, estado *Ready*, disparo horario al minuto :05 desde 17/10/2026 22:05,
acción `python -B -m data_ingestion.scheduled_sync --db ...\aeris_air_quality.db --key-file ...`,
último resultado 0. El flujo toma `aeris_air_quality.db.sync.lock`, crea y verifica un respaldo antes
de escribir, protege el ledger de calidad y no aplica retención salvo `AERIS_BACKUP_RETENTION=apply`.
Zona del equipo: *Central Standard Time (Mexico)*.

**Propuesta (no aplicada):** no crear otra tarea. `actualizar.diario()` (equivale a `--si-corresponde`
con base principal) está implementado e **inactivo salvo `AERIS_AMBIENTAL_DIARIO=apply`**; nunca lanza
ni cambia el resultado de OpenAQ. Ejecuta como máximo
una vez por día local y solo a partir de las 08:00 de Querétaro, por lo que basta invocarlo desde el
disparador horario existente. La primera ejecución útil sería la de 08:05.

```
08:05 tarea horaria existente
  ├─ scheduled_sync (OpenAQ, sin cambios)            → libera .sync.lock
  └─ ambiental.actualizar --si-corresponde            → si ya hubo una ejecución correcta hoy: no_corresponde
        ├─ toma .ambiental.lock y .sync.lock (base principal) → nunca escribe a la vez que OpenAQ
        ├─ solo fuentes con autorizada=1
        ├─ por estación: ventana = consultado_hasta − 72 h; ETag; reintentos 503/429 con Retry-After
        ├─ inserta solo claves nuevas; revisiones aparte; 404 → sin_publicacion
        └─ reporte JSON + amb_ingestas; nunca borra respaldos ni archivos
```

Si una ejecución falla (red, límite de API), no se marca el día como hecho y la siguiente hora lo
reintenta automáticamente; los fallos quedan en `amb_ingestas` y en el reporte.

**Requisitos antes de activarlo en producción** (cada uno necesita tu autorización):

1. Migrar la base principal con respaldo verificado previo (`esquema migrar --permitir-base-principal`
   con la variable de autorización) y decidir la ventana inicial (`--desde`).
2. **Respaldo antes de escribir (implementado)**: en una base con `mediciones`, `actualizar` toma
   `.sync.lock`, crea `backups/aeris_before_ambiental_<UTC>_<id>.db` con la API de respaldo, compara la
   huella lógica completa con el original y, al terminar, exige que las tablas no `amb_*` sigan idénticas.
   Nunca elimina respaldos: cada ejecución diaria añade una copia (~25 MB hoy); la retención es decisión aparte.
3. Encadenar `diario()` en `scheduled_sync.main` (tres líneas, después de liberar el bloqueo de OpenAQ).
   **No aplicado**: la edición de ese archivo quedó bloqueada por permisos y requiere tu autorización.
4. Confirmar la publicación de los datos ambientales en la instantánea de Railway (hoy no incluida).

## 5b. Ensayo sobre copia de producción (20/10/2026)

Copia por API de respaldo (lectura `mode=ro`), migración, ingesta GHCNh 2026 y POWER sep–oct sobre la
copia: 49,250 + 16,128 valores, respaldo verificado, `legado_intacto=true`; respuestas de `/api/v2/*`
idénticas antes y después (excluyendo `generated_at_utc`/`age_hours`, que dependen del reloj);
tras `revertir` la huella de las tablas existentes coincide exactamente.

## 5c. Railway: instantánea de demostración y validación

- **Compatibilidad**: la imagen (`Dockerfile`) copia `aeris_web/` completo y solo `catalog.py`,
  `visibility.py` e `__init__.py` de `data_ingestion`. `aeris_web/ambiental.py` solo importa Flask,
  `zoneinfo` (tzdata 2026.5 está en `requirements-web-linux.lock`) y `connect_readonly`: no requiere
  dependencias nuevas ni cambios en Dockerfile, lock, `railway.json` o `railway_start.py`.
- **Rutas SQLite**: en beta/Railway la API ambiental lee **la misma** instantánea `AERIS_DB_PATH`
  verificada por SHA-256; `AERIS_AMBIENTAL_DB_PATH` solo se acepta en `AERIS_ENV=local`.
- **Solo lectura**: `mode=ro` + `query_only`, únicamente `GET` (POST → 405), host no confiable → 400.
- **Sin ingesta**: la web nunca migra ni descarga; en el derivado todas las fuentes quedan `autorizada=0`;
  `diario()` está desactivado por defecto y el código de ingesta no está en la imagen.
- **Holdout y modelos**: viven en `forecasting/` y `models/`, fuera de la imagen y fuera de SQLite.

Generar y validar (producción solo se lee):

```powershell
& $py -B scripts\prepare_ambiental_demo_snapshot.py --source C:\Users\MSI_COREi5\AERIS\data\aeris_air_quality.db `
    --dev-db data\dev\aeris_ambiental_dev.db --output-dir reports\beta_snapshots\<nuevo-corte>
& $py -B scripts\validate_ambiental_railway.py --snapshot-dir reports\beta_snapshots\<nuevo-corte>
```

El generador reutiliza `prepare_web_snapshot.prepare` (sanitiza `ruta_local`, `reporte_json`, `url`),
añade la capa ambiental desde 2025-06-01, ejecuta `ANALYZE`/`VACUUM`, comprueba que las tablas
existentes no cambian y aplica `railway_start.verify`. El validador reconstruye la imagen a partir de
los `COPY` del Dockerfile, arranca `wsgi:application` en perfil Railway y mide cada ruta.

Corte `ambiental-demo-003`: 106.7 MB, SHA-256 `b9e8c20f9f6ed3884ecdeadc251ace8bc48fa14bfcacfb84b64569d92de210c6`,
254,485 observaciones ambientales. Medianas locales: `/estaciones` 45 ms, observaciones horarias de un año
72 ms (2.7 MB), resto < 30 ms. Validación hecha en Windows/Python 3.15 con el contexto de la imagen
simulado; **la prueba real Linux/Gunicorn sigue pendiente** del primer arranque en Railway.

## 6. Coordinación con Codex (`aeris-home-research`)

- **Archivos que toco y que Codex también podría tocar**: solo `app.py` (4 líneas al final, después de
  `register_v2`) y `.gitignore` (una línea). Codex no ha modificado `app.py` en su worktree.
- **Archivos nuevos sin conflicto**: `aeris_web/ambiental.py`, `data_ingestion/ambiental/*`,
  `tests/test_ambiental.py`, `docs/aeris_{fuentes_ambientales,api_ambiental_v1,capa_ambiental}.md`.
- **Dependencias**: `aeris_web/ambiental.py` importa `data_ingestion.visibility.connect_readonly`
  (Codex solo cambió fines de línea en ese archivo). El conector usa `data_ingestion.operations`,
  que existe en `aeris-v2` pero **no** en la base de la rama de Codex (`4f490cb`): integrar sobre
  `aeris-v2`.
- **Riesgo**: el worktree de Codex muestra ~126 archivos modificados, casi todos solo por fines de
  línea (LF→CRLF). Conviene normalizarlos antes de fusionar para no ocultar cambios reales.

## 7. Propuestas visuales para Codex (revisión de capturas `aeris_home_v2_*`)

Correcciones puntuales:

1. Errata en la tarjeta del mapa (390 px): «Encuentra **tupunto** de observación».
2. A 390 px las etiquetas de latitud del mapa quedan recortadas («.9° N» en lugar de «20.9° N»).
3. «19/10/2026 · 22:00 −0600»: mostrar «22:00 (hora de Querétaro, UTC−6)»; el desfase crudo es poco legible.

Nuevas visualizaciones con la capa ambiental:

4. **El Marqués deja de estar vacío**: añadir MMQT al mapa con símbolo distinto (cuadrado = estación
   meteorológica; círculo = calidad del aire) y leyenda «mide meteorología, no contaminantes».
5. **Celdas de reanálisis** como cuadros de trazo discontinuo del tamaño aproximado de la celda, nunca
   como puntos, con la etiqueta «modelo».
6. **Panel «Condiciones del aire y del tiempo»**: múltiplos pequeños con eje temporal compartido
   (PM2.5 de una estación + temperatura, humedad y viento de MMQT), con huecos visibles y cursor
   sincronizado. Insignias «Observación»/«Reanálisis» en cada serie.
7. **Rosa de vientos** de MMQT por periodo (dirección × velocidad); útil para discutir transporte
   de contaminantes hacia la zona metropolitana.
8. **Calendario de cobertura** (días × horas) a partir de `/cobertura`, distinguiendo «sin publicar
   todavía» (latencia) de «hueco».
9. **Frescura por fuente** desde `/fuentes.ultima_ingesta` y `latencia_horas`: «NOAA, publicado con
   ~2.5 días de retraso» evita leer la latencia como falla.
10. Pie de atribución generado desde `/fuentes` (GHCNh CC0 con DOI; NASA POWER con versión).
