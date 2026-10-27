# Inventario de fuentes ambientales para Querétaro — 20/10/2026

Complementa la [investigación del 18/10/2026](aeris_data_expansion_plan.md) (OpenAQ API/Archive,
INECC 2022, SINAICA/SCICA, CeMCAQ), que no se repite aquí. Esta revisión añade fuentes de
**meteorología observada y modelada**, verifica la situación de **El Marqués** y documenta la
primera integración. Todas las cifras proceden de solicitudes reales hechas el 20/10/2026;
«verificado» significa descargado y analizado, no solo leído en un portal.

## Hallazgo principal: El Marqués

- **SINAICA, red Querétaro (`red.php?redId=78`)**: hoy publica 5 estaciones (IDs 169, 408, 450,
  454, 460), todas al oeste de −100.38° (zona metropolitana de Querétaro y Corregidora).
  **Ninguna está en El Marqués.** La única serie de calidad del aire de El Marqués conocida sigue
  siendo OpenAQ 235221 (sep‑2021, 333 horas).
- **Aeropuerto Intercontinental de Querétaro (MMQT)**: el título de concesión (DOF 2009) lo ubica
  en **El Marqués y Colón**. Emite METAR horarios con observaciones reales de temperatura, rocío,
  humedad, viento, presión y visibilidad. Es hoy la **única serie ambiental observada, horaria y
  vigente dentro de El Marqués**. No mide contaminantes.

## Fuentes evaluadas

| Fuente | Tipo | Cobertura Querétaro | Periodo | Variables (unidades) | Frecuencia / latencia | Licencia | Acceso | Estado |
|---|---|---|---|---|---|---|---|---|
| **NOAA GHCNh** (MXI0000MMQT) | Observación (METAR) | Aeropuerto MMQT, El Marqués/Colón, 20.6173, −100.1857, 1,919 m | ISD desde 1973; archivo 2025 y 2026 verificados | Temperatura y rocío (°C), HR (%), viento y ráfaga (m/s), dirección (°), altímetro (hPa), visibilidad (km); precipitación escasa | Reportes ~horarios + especiales; publicación diaria; último dato 18/10 03:41Z al consultar el 20/10 (≈2.5 días) | **CC0‑1.0** | HTTPS sin clave, PSV anual por estación, ETag | **Integrada** (primer conector) |
| **NASA POWER** horario | Reanálisis (MERRA‑2/GEOS‑IT) | Cualquier punto; celda ≈0.5°×0.625° | Desde 2001 (documentado) | T2M, T2MDEW (°C), RH2M (%), WS10M (m/s), WD10M (°), PS (kPa), PRECTOTCORR (mm/h) | Horaria; válido hasta 18/10 23Z al consultar el 20/10 | Datos públicos NASA, atribución solicitada | HTTPS sin clave, JSON, `time-standard=UTC` | **Integrada** como covariable modelada |
| Open‑Meteo Air Quality (CAMS) | Modelo de composición atmosférica | Celda devuelta 20.60, −100.30 (≈40 km, global) | Pronóstico y días pasados | PM2.5, PM10, O3, NO2, CO, SO2 (µg/m³) | Horaria | CC‑BY‑4.0 (datos); API gratuita solo no comercial | HTTPS sin clave | Verificada; **no integrada**: es estimación, no medición, y sus condiciones de uso exigen revisión |
| Open‑Meteo ERA5 | Reanálisis | Celda 20.5, −100.5 | Desde 1940 | Meteorología básica | Horaria | CC‑BY‑4.0; API no comercial | HTTPS sin clave | Verificada el 18/10; redundante con POWER para el primer paso |
| GHCNh 76626 «QUERETARO» y 76628 «QUERETARO UNV» | Observación | 20.58, −100.40 y 20.63, −100.55 | — | — | — | — | — | Listadas en el catálogo, **sin archivos** 2015/2024/2026 (HTTP 404) |
| Iowa Environmental Mesonet (METAR MMQT) | Observación (misma red METAR) | MMQT | Reciente | Igual que METAR | Casi tiempo real | Uso libre académico | HTTPS sin clave | Verificada; **coordenadas obsoletas** (20.5833, −100.40 = aeropuerto anterior). Solo útil como respaldo de latencia, no como fuente independiente |
| SMN/CONAGUA, EMA | Observación | Estaciones automáticas estatales | Variable | Viento, presión, T, HR, radiación, lluvia (10 min, UTC) | — | — | Sin descarga anónima verificada; conjuntos en datos.gob.mx con última actualización 2018‑2019 | Pendiente: solicitar acceso o catálogo vigente |
| RUOA‑UNAM, sitio Juriquilla | Observación (investigación) | Campus Juriquilla, 1,945 m | — | GEI y meteorología | — | Acceso abierto declarado | Portal ruoa.unam.mx | Pendiente: no se localizó descarga directa reproducible |
| SINAICA / SCICA | Observación validada | 5 estaciones ZM Querétaro | 2013–2025 según selector | PM2.5, PM10, O3, NO2, SO2, CO; meteorología | Horaria | Términos de SINAICA | Rutas internas web (POST) | Sin cambios respecto al 18/10; probable mismo origen que OpenAQ |
| CeMCAQ / SEDESU | Observación oficial estatal | Red estatal | — | — | — | — | Requiere sesión | Sin cambios; requiere solicitud institucional |

## Decisiones de calidad derivadas de los datos reales

1. **Solo METAR (FM‑15/FM‑16) de GHCNh.** En el mismo archivo, el SYNOP FM‑94 de 2026‑10‑18 03:00Z
   reporta 29.1 °C mientras el METAR de 03:41Z reporta 11.0 °C. Se excluyen SYNOP (FM‑12/FM‑94);
   el recuento de excluidos queda en el reporte de cada ingesta.
2. **El tipo de reporte no identifica el rutinario.** Desde abril de 2026 GHCNh etiqueta como FM‑16
   la mayoría de los METAR de MMQT al minuto :40 (ene: 726 FM‑15 / 13 FM‑16; jun: 202 / 551). La
   resolución horaria usa el **último reporte de la hora**, sin promedios.
3. **Códigos de calidad** (documentación GHCNh v1.1.0): letras a–z del QC integrado, 2/3/6/7 heredados
   y U/P/I/M/R → `marca_origen=1`. Código vacío = «sin marca», no «validado». Los datos recientes aún
   no tienen QC; cuando NOAA lo publique se registrará como revisión, sin sobrescribir.
4. **Dirección 999 con código `C`** = calma → 0° (convención documentada); 999 sin `C` se excluye.
5. **Precipitación METAR excluida**: es un total acumulado dentro de la hora (último reporte) y en
   2026 solo hay 14 valores. POWER sí aporta precipitación modelada (mm/h).
6. **POWER usa `time-standard=UTC`**; el valor de relleno −999 se descarta y nunca se imputa. Se valida
   que la celda devuelta corresponda al punto solicitado (±0.01°).

## Coherencia comprobada (sin combinar series)

En la base de desarrollo, la temperatura METAR de MMQT y la de POWER en la misma coordenada
(1/9–18/10/2026, 1,098 horas pareadas, último METAR de cada hora) muestran r = 0.921,
sesgo METAR − POWER = +1.56 °C y error absoluto medio 1.91 °C. Es una comprobación de
plausibilidad del conector, **no** una calibración: los productos se mantienen separados.

## Fuentes consultadas

- [GHCNh, NOAA NCEI](https://www.ncei.noaa.gov/products/global-historical-climatology-network-hourly) ·
  [documentación PDF](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh_DOCUMENTATION.pdf) ·
  [metadatos y licencia CC0](https://ncei.noaa.gov/metadata/geoportal/rest/metadata/item/gov.noaa.ncdc:C01688/html) ·
  [lista de estaciones](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-station-list.txt)
- [NASA POWER API horaria](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/)
- [Open‑Meteo Air Quality](https://open-meteo.com/en/docs/air-quality-api) · [condiciones](https://open-meteo.com/en/terms)
- [SINAICA, red Querétaro](https://sinaica.inecc.gob.mx/red.php?redId=78)
- [Aeropuerto Intercontinental de Querétaro](https://en.wikipedia.org/wiki/Quer%C3%A9taro_Intercontinental_Airport) ·
  [ubicación en El Marqués y Colón](https://www.aeropuertosdelmundo.net/aeropuerto-QRO/)
- [Iowa Environmental Mesonet, ASOS/METAR](https://mesonet.agron.iastate.edu/request/download.phtml)
- [Gaceta UNAM sobre RUOA](https://www.gaceta.unam.mx/acceso-abierto-a-la-red-universitaria-de-observatorios-atmosfericos/)
- [Conjuntos horarios de CONAGUA en datamx](https://www.datamx.io/dataset/informacion-de-vientos-horaria)
