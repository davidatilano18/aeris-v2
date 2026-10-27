# Contrato de integración — frontend AERIS / backend Claude

20-oct-2026. Propuesta para coordinación, no integración automática.

Responsabilidades: frontend y experiencia en `aeris-home-research`; nuevas fuentes,
modelos de datos y backend en `AERIS-Claude`, rama `aeris-data-expansion`. Ningún
archivo del worktree de Claude se modifica desde este trabajo. No se envían claves
ni bases. Este documento debe compartirse/revisarse antes de conectar otra API.

## Ya conectado y preservado

- `/api/v2/observations?source=OpenAQ|OpenAQ-Archive&station=<sensor>&period=24h|7d|30d|all`.
  JSON actual: source, source_label, selection, window.from_utc/to_exclusive_utc,
  stations, series[].sensor_id y points[].timestamp_utc/epoch_ms/value/quality.
  Los puntos de hueco son value=null, gap=true y NO son mediciones.
- quality: evaluated, version, review, extreme, jump, zero. La UI conserva ceros,
  muestra pendientes/alertas y no llama a esas reglas validación oficial.
- `/api/v2/comparison?source=...&station=...&anchor=latest`.
  Mantener summary/status, previous/current con extremos UTC y cobertura,
  matched_hours, reason_messages y policy. No cambiar su significado para producir
  conclusiones más atractivas. Su ventana es independiente de la gráfica.
- Las lecturas pasan por connect_readonly y exclusión central de lotes revertidos.
  Nuevas fuentes no deben saltarse ese contrato ni exponer mediciones retiradas.

El frontend no abre rutas de ingesta ni entrena. El filtro personalizado actual
recorta en memoria una serie de la misma estación y fuente, obtenida con period=all;
fechas de calendario UTC, hasta incluido, intervalo convertido a fin exclusivo.
No convierte ese recorte en una nueva serie almacenada. Ante 413 pide reducir
el alcance. La cobertura se calcula sobre horas completas; todo el historial usa
solo el tramo entre observaciones extremas, claramente rotulado.

## API multivariable propuesta, aún NO consumida

Versión explícita para no romper /api/v2: `/api/v3/capabilities`,
`/api/v3/series`, `/api/v3/research/comparison` y, solo cuando existan métodos
verificados, `/api/v3/research/trend` y `/api/v3/research/correlation`.
Estos nombres son una propuesta; Claude y el usuario deben acordarlos.

### Capabilities

Necesitamos schema_version, generated_at_utc, variables[] con id, label, unidad
canónica y resolución; fuentes con identificador estable, proveedor, licencia,
URL de procedencia, tipo observed/estimated/forecast, versiones de producto y
semántica temporal. Por estación: station_id estable, sensor_id/provider_id,
municipality documentado, coordenadas verificadas con fecha/alcance histórico,
variables disponibles por fuente, primer/último instante y estado de disponibilidad.
La ausencia de un contaminante es unavailable, no una columna rellena con ceros.

Variables candidatas: pm25, pm10, o3, no2, air_temperature, relative_humidity,
wind_speed, wind_direction. Las unidades no se deducen del nombre: O3/NO2 pueden
necesitar condiciones de conversión; viento exige distinguir dirección circular
y velocidad; meteorología de rejilla no es estación instrumental local.

### Series

Filtros requeridos: station_id, variable_id, source_id, from_utc inclusive,
to_utc exclusive, resolución/agregación explícita y cursor de paginación.
Municipio filtra estaciones, no crea un promedio territorial. Sin estimaciones
por defecto. Respuesta: schema_version, query aplicada, unidad, periodo físico
representado (inicio/fin de cada intervalo, no solo etiqueta horaria), zona IANA,
tipo de producto, provenance, quality_policy, expected_frequency solo cuando
justificable, cobertura y observed_count separados de valid_count.

Cada fila necesita identidad estable, timestamp UTC zonificado, intervalo,
value finito o ausencia explícita, unidad y fuente/producto, tipo observado o
estimado, evaluación de calidad (versión/flags/pending), vínculo de procedencia y
revisión. Ausencia no es cero. Los cambios de ubicación/sensor/producto deben
romper segmentos; nunca concatenarlos silenciosamente.

Requisitos operativos: cursor y límite documentados, orden cronológico estable,
no duplicados ambiguos, snapshot_id/ETag para consistencia entre páginas,
responses sin rutas locales/credenciales. Errores públicos con code/message/
request_id, sin stack ni secretos. 400 filtros, 413 exceso, 503 indisponibilidad;
200 con serie vacía y motivo documentado para ausencia legítima.

### Investigación

Comparación: mismos instrumentos, unidades, periodo y productos compatibles;
muestras/horas emparejadas y cobertura, método/versiones, extremos y motivos de
abstención. Tendencia: método aprobado, estacionalidad/autocorrelación, suficiencia,
estimación/unidad, incertidumbre, periodo y limitaciones. Correlación: emparejamiento
temporal, N efectivo, faltantes, unidades/productos, método/versiones e incertidumbre;
separar análisis exploratorio de causalidad. Nunca generar p-valores de ejemplo.

Los estados de investigación serán available/abstained/unavailable/error, con
reason_codes legibles. Actualmente tendencia y correlación son unavailable.

## Puerta de integración

No habilitar variables por detectar su nombre ni por una propuesta de esquema.
Primero: ejemplos reales sanitizados + documentación de unidades/horario/origen;
después pruebas de contrato sobre fixtures aisladas, errores, paginación, revisión,
fuentes incompatibles y datos ausentes; finalmente conectar un adaptador versionado
con autorización. Observado, estimado y pronosticado nunca comparten silenciosamente
una curva ni leyenda. Una base o CSV académico no se usa como sustituto temporal.

No se cambia en esta fase SQLite, sincronizador, tarea, respaldos, ML, holdout
ni Railway. No se mezcla ni integra automáticamente la rama de Claude.
