# Contrato de API — capa ambiental v1

Prefijo: `/api/ambiental/v1`. Solo lectura (`mode=ro`, `query_only`), solo `GET`, JSON UTF‑8,
`Cache-Control: no-store`. Implementación: `aeris_web/ambiental.py`. Pruebas: `tests/test_ambiental.py`.
Independiente de `/api/v2/*`: no cambia ninguna respuesta existente.

## Reglas que el frontend debe respetar

1. **Una serie = una estación de una fuente.** La API nunca mezcla estaciones ni fuentes; no hay
   promedio estatal ni municipal. Para comparar, pedir cada estación por separado y mostrarlas
   como series distintas.
2. **`tipo_producto` siempre visible.** `observacion` (medición real) frente a `reanalisis`
   (modelo de rejilla). Un reanálisis no debe pintarse como una estación ni con el mismo símbolo.
3. **Fechas**: `fecha_utc` (ISO 8601 con `Z`) es la referencia; `fecha_local` ya viene convertida
   a `America/Mexico_City` con su desfase (−06:00; −05:00 en veranos anteriores a nov‑2022).
   Los parámetros `desde`/`hasta` exigen zona explícita (`Z` o `±HH:MM`); sin zona → 400.
4. **Ausencias**: una hora sin punto es una hora sin dato publicado. No interpolar ni unir con
   líneas a través de huecos (usar `spanGaps: false` o cortar la línea).
5. **Marcas**: `marca_origen` (QC del proveedor) y `fuera_de_rango` (rango físico AERIS) señalan
   revisión; no significan error confirmado. `revisada=true` indica que la fuente publicó después
   otro valor o código de calidad; el valor mostrado es el primero registrado.
6. **Atribución**: mostrar `fuente.atribucion` y `licencia` junto a cualquier gráfica.

## Errores

| Código | Cuándo | Cuerpo |
|---|---|---|
| 400 | Parámetro desconocido, fecha sin zona, ventana > 400 días, variable inexistente | `{"error": "..."}` |
| 404 | `estacion` inexistente | `{"error": "No encontrado: <id>"}` |
| 413 | Más de 20,000 puntos | `{"error": "Demasiadas observaciones; ..."}` |
| 503 | Base sin capa ambiental migrada o ilegible | `{"error": "Capa ambiental no disponible en esta base."}` |

El frontend debe tratar 503 como «capa no disponible todavía» (la base de producción aún no está
migrada) y ocultar el módulo, sin romper la página.

## `GET /fuentes`

Sin parámetros.

```json
{"generado_utc": "2026-10-20T16:17:27Z",
 "fuentes": [{"fuente_id": "noaa-ghcnh", "nombre": "Global Historical Climatology Network-hourly (GHCNh) v1",
   "organizacion": "NOAA National Centers for Environmental Information", "tipo_producto": "observacion",
   "url": "https://www.ncei.noaa.gov/products/global-historical-climatology-network-hourly",
   "licencia": "CC0-1.0 (sin protección de derechos de autor en EE. UU.)", "atribucion": "Menne et al. (2023) ...",
   "autorizada": true, "estaciones": 1, "notas": "Solo reportes METAR ...",
   "ultima_ingesta": {"estado": "sin_datos_nuevos", "fin_utc": "2026-10-20T16:16:40Z"}}]}
```

`ultima_ingesta.estado` ∈ `exito`, `sin_datos_nuevos`, `sin_publicacion`, `fallo`, o `null`.

## `GET /variables`

Catálogo de variables y unidades canónicas: `variable_id`, `nombre`, `unidad`, `dominio`
(`meteorologia` | `contaminante`), `minimo_fisico`, `maximo_fisico`. Los contaminantes están
catalogados para futuras fuentes; hoy no tienen observaciones en esta capa (PM2.5 sigue en `/api/v2`).

## `GET /estaciones?fuente=&municipio=`

Ambos filtros opcionales y exactos (`municipio=El%20Marqu%C3%A9s`).

```json
{"estaciones": [{"estacion_id": "ghcnh:MXI0000MMQT", "fuente_id": "noaa-ghcnh",
  "nombre": "Aeropuerto Intercontinental de Querétaro (MMQT)", "municipio": "El Marqués",
  "municipio_nota": "El aeródromo abarca El Marqués y Colón según su título de concesión (DOF 2009).",
  "latitud": 20.6173, "longitud": -100.1857, "elevacion_m": 1919.0,
  "tipo_sitio": "estacion", "resolucion_espacial": "punto", "tipo_producto": "observacion",
  "variables": [{"variable_id": "temperatura_aire", "observaciones": 7023,
                 "primera_utc": "2026-01-01T00:41:00Z", "ultima_utc": "2026-10-18T03:41:00Z"}]}]}
```

`tipo_sitio` ∈ `estacion` | `celda_rejilla` | `punto_modelo`. Las celdas (`power:mmqt`, `power:cor`)
representan un área de ≈0.5°×0.625°, no un punto.

Identificadores actuales: `ghcnh:MXI0000MMQT`, `power:mmqt`, `power:cor`.

## `GET /observaciones`

| Parámetro | Obligatorio | Valores |
|---|---|---|
| `estacion` | sí | `estacion_id` |
| `variable` | sí | 1–6 `variable_id` separados por coma |
| `desde`, `hasta` | no | ISO 8601 con zona; por defecto últimos 7 días; máximo 400 días |
| `resolucion` | no | `original` (defecto) \| `hora` |
| `incluir_marcadas` | no | `1` (defecto) \| `0` excluye `marca_origen` y `fuera_de_rango` |

`resolucion=hora`: para METAR, el **último reporte publicado de cada hora UTC**; `fecha_utc` y
`fecha_local` son el inicio de la hora y `fecha_observacion_utc`/`fecha_observacion_local` el instante
real. No hay promedios. Los productos `PT1H` (POWER) no cambian.

```json
{"estacion": {"estacion_id": "ghcnh:MXI0000MMQT", "tipo_producto": "observacion", "...": "..."},
 "fuente": {"fuente_id": "noaa-ghcnh", "nombre": "...", "licencia": "...", "atribucion": "..."},
 "ventana": {"desde_utc": "2026-10-17T18:00:00Z", "hasta_utc": "2026-10-17T20:00:00Z"},
 "resolucion": "hora", "metodo": "Para reportes instantáneos (METAR) se toma ...",
 "series": {"temperatura_aire": {"nombre": "Temperatura del aire", "unidad": "°C", "puntos": [
   {"fecha_utc": "2026-10-17T18:00:00Z", "fecha_local": "2026-10-17T12:00:00-06:00",
    "fecha_observacion_utc": "2026-10-17T18:52:00Z", "fecha_observacion_local": "2026-10-17T12:52:00-06:00",
    "valor": 14.0, "periodo": "instantaneo", "tipo_reporte": "FM-15", "calidad_origen": "",
    "marca_origen": false, "fuera_de_rango": false, "revisada": false}]}}}
```

Ejemplo POWER (`estacion=power:mmqt&variable=viento_velocidad`): puntos con
`"periodo": "PT1H"`, `"tipo_reporte": "POWER-horario"`.

## `GET /cobertura?estacion=&variable=&desde=&hasta=`

Por variable: `horas_esperadas`, `horas_con_dato`, `porcentaje`, `huecos_3h_o_mas` (máx. 100),
`huecos_total`, `ultima_utc`, `latencia_horas`. «Hora con dato» = al menos una observación en esa
hora UTC; no mide calidad ni disponibilidad del instrumento.

```json
{"variable_id": "temperatura_aire", "horas_esperadas": 1152, "horas_con_dato": 1098, "porcentaje": 95.31,
 "huecos_3h_o_mas": [{"desde_utc": "2026-10-18T04:00:00Z", "hasta_utc": "2026-10-19T00:00:00Z", "horas": 20}],
 "huecos_total": 1, "ultima_utc": "2026-10-18T03:41:00Z", "latencia_horas": 60.6}
```

El hueco final suele ser **latencia de publicación** (GHCNh ≈2–3 días), no falla de la estación:
mostrarlo como «pendiente de publicación» cuando toca el extremo derecho de la ventana.

## `GET /ingestas?fuente=&limite=`

Bitácora de actualizaciones (`limite` 1–200, defecto 20): `ingesta_id`, `fuente_id`, `inicio_utc`,
`fin_utc`, `estado`, `leidas`, `insertadas`, `duplicadas`, `revisiones`, `descartadas`, `error_tipo`.

## Configuración local

```powershell
$env:AERIS_AMBIENTAL_DB_PATH = "C:\Users\MSI_COREi5\AERIS-Claude\data\dev\aeris_ambiental_dev.db"
.\.venv\Scripts\python.exe app.py
```

Sin la variable, la API lee la base principal y responde 503 hasta que se autorice migrarla. En
perfil `beta` la variable se ignora: solo se sirve la instantánea verificada.
