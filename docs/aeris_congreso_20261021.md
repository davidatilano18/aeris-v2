# AERIS — demostración del congreso (21/10/2026, 9:30)

Rama `aeris-demo-integracion`, worktree `C:\Users\MSI_COREi5\AERIS-Demo` (AERIS 3.3: seis
contaminantes, modelo CAMS para El Marqués, Laboratorio de contaminantes). Solo lectura: no ingiere,
no migra, no predice.

## 1. Iniciar

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\MSI_COREi5\AERIS-Demo\scripts\Iniciar-AERIS-Congreso.ps1
```

Abre **http://127.0.0.1:5070/inicio** cuando el servidor responde (unos 10 s: verifica el hash del
corte y precalcula la portada). Detener: `Ctrl+C` en esa ventana.

- Sin internet por defecto (`--offline`). `-ConInternet` permite el mapa base de OpenStreetMap.
- Datos: `C:\Users\MSI_COREi5\AERIS-Demo-datos\corte-32-20261020\aeris.db` (603 MB, solo lectura,
  SHA-256 `e3639e93…ac43`).
- No usar 5060/5061 (Chrome los bloquea). Si 5070 está ocupado: `-Port 5076`.

**En línea:** https://aeris-qro.up.railway.app/inicio (Railway, misma versión y mismo corte; el mapa base
oscuro se carga solo cuando hay conexión).

**Plan B — AERIS 3.0.1 exacta** (la versión ensayada antes, con su corte original):
```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\MSI_COREi5\AERIS-Demo\scripts\Iniciar-AERIS-Congreso.ps1 -Respaldo
```
Corre la etiqueta `aeris-congreso-3.0.1` desde `C:\Users\MSI_COREi5\AERIS-Congreso-301`.
**Plan C — capturas:** `C:\Users\MSI_COREi5\AERIS-Demo-datos\capturas-32\` (3.3) y `capturas-congreso-3\` (3.0).

**Antes de presentar:** abre la portada. Si aparece la clásica, entra una vez a
`/inicio?experiencia=inmersiva`. Pantalla completa con `F11`. «Pausar movimiento» detiene la animación.

Ensayo (4 min): portada → «¿Cómo está el aire?» → «¿Qué es lo que empeora el aire?» → El Marqués →
Aprende (cambia de contaminante) → Laboratorio, pestaña Contaminantes → Datos.

## 2. Recorrido guiado (7 minutos)

Tesis: **cómo está y cómo ha estado el aire en Querétaro, qué lo empeora y dónde no sabemos.**

| Tiempo | Pantalla | Qué mostrar | Qué decir |
|---|---|---|---|
| 0:00–0:40 | `/inicio`, escena 1 | «AERIS» sobre el cielo; leyenda de partículas (dato real de ayer) | «Cada partícula en pantalla es proporcional a una medición real. Queríamos responder algo sencillo: ¿cómo está el aire que respiramos?» |
| 0:40–1:00 | Desliza | Descenso entre nubes | «Las PM2.5 son unas 30 veces más delgadas que un cabello.» |
| 1:00–2:00 | ¿Cómo está el aire? | 97 % de 149 días Buena (17 sep–19 oct 2026), ninguno Mala; 4 % sobre la OMS. «¿Y antes?»: sep 2021–sep 2026, 63 % de 3,641 días Buena, 277 Mala, 40 % sobre la OMS | «Ahora, en temporada de lluvias, casi todo es bueno. Pero con cinco años de archivo, uno de cada tres días no lo fue. No es tendencia: son temporadas distintas.» |
| 2:00–3:10 | ¿Qué es lo que empeora el aire? | 2023–2026, 4,863 días con los seis contaminantes: 49 % Buena, 40 % Aceptable, 11 % Mala. Ranking: ozono 64 %, PM2.5 50 % | «La norma califica cada día con el contaminante que peor esté. En Querétaro, cuando el aire no es bueno, casi siempre es por ozono o partículas finas. El NO₂, el SO₂ y el CO pesan poco.» |
| 3:10–4:10 | El Marqués (modelo) | Gráfica modelo vs medición; tarjeta: −3.2 µg/m³, 65 % misma categoría, detecta 39 % de días no buenos | «El Marqués no mide PM2.5 desde 2021. Un modelo de Copernicus estima 10 µg/m³, pero en las estaciones de su misma celda subestima y no detecta 6 de cada 10 días no buenos. Por eso no lo presentamos como medición: hace falta un sensor.» |
| 4:10–5:00 | **Aprende** | Simulador: cambia a ozono y a CO; abre «Un día en revisión» | «Cada contaminante tiene su unidad, su método diario y su redondeo. Y no todo pico es real: las horas imposibles se marcan y el día no se califica.» |
| 5:00–6:00 | **Laboratorio** → Contaminantes | Ozono de Corregidora en un año; luego CAMS, rotulado «Modelo, no medición» | «Cualquiera puede revisar hora por hora qué se midió y qué falta.» |
| 6:00–6:40 | **Datos** | Siete descargas; abre «Índice diario» | «Todo es abierto, con licencia y método; el modelo va aparte para no confundirlo con mediciones.» |
| 6:40–7:00 | Cierre | Portada | «El siguiente paso es predecir: el modelo está en prueba ciega hasta el 19 de noviembre; por rigor no mostramos pronósticos antes.» |

## 3. Funcionalidades

- **Portada 3.0** (WebGL + GSAP local): «¿Cómo está el aire?» (PM2.5, NOM-172), «¿Qué es lo que
  empeora el aire?» (seis contaminantes), El Marqués con el modelo CAMS y su validación, «Cómo
  trabajamos» (Codex), mapa con tres estados y aviso de brecha en El Marqués.
- **Aprende**: simulador de los seis contaminantes (bandas, unidad, método, redondeo), días reales.
- **Laboratorio**: Aire (PM2.5), Tiempo (NOAA MMQT, NASA POWER) y Contaminantes (archivo y CAMS).
- **Datos abiertos**: PM2.5 horario y diario, índice diario de seis contaminantes, PM10/O₃/NO₂/SO₂/CO
  horarios, modelo CAMS, meteorología y reanálisis.

## 4. Resumen técnico para estudiar

**Fuentes.**
- *OpenAQ Archive* (red estatal vía SINAICA), 2021–2026: 6,025 archivos diarios verificados por
  SHA-256. PM2.5 en `mediciones` (88,988 horas nuevas; las 8,737 ya existentes coincidieron); PM10,
  O₃, NO₂, SO₂ y CO en la capa ambiental (527,877 horas). Unidad original exigida (ppm, µg/m³); unos
  días de mayo de 2026 con ppb/µg/m³ para gases se descartaron, no se convirtieron. PM10 solo en
  Carrillo Puerto; Josefa Vergara sin PM2.5 desde 2022.
- *OpenAQ API v3*: PM2.5 reciente (sincronización horaria local).
- *CAMS global* vía Open-Meteo (CC BY 4.0, no comercial): modelo de rejilla de 0.4°, desde ago-2022.
- *NOAA GHCNh MMQT* (METAR) y *NASA POWER* (reanálisis): meteorología.

**Índice AIRE Y SALUD** (NOM-172-SEMARNAT-2023, Tablas 2–9): PM2.5 y PM10 promedio de 24 h; O₃, NO₂
y SO₂ máximo horario; CO máximo del promedio móvil de 8 h (≥ 6 horas). ≥ 18 horas válidas por día
(criterio de AERIS también para los máximos). Promedios en decimal exacto y redondeo «mitad hacia
arriba»; ventanas en UTC (horario de verano hasta 2022). La peor categoría define el día.

**Revisión automática.** PM2.5: `aeris_qc_v2` (> 100 µg/m³ o salto ≥ 100). Gases y PM10: `gases-v1`
(sobre el inicio de «Extremadamente mala» o salto mayor que el tope de «Mala»); 136 de 527,868 horas.
Sensibilidad publicada: sin ella cambiarían 21 días y habría 10 «Muy mala o peor» en vez de 1. Nunca
se borra; una marca no confirma un error.

**Modelo CAMS.** Ocho puntos (El Marqués y cada estación) caen en solo tres celdas: El Marqués comparte
celda con Carrillo Puerto, Félix Osores y Epigmenio González. Validación diaria en esa celda (2,055
días): sesgo −3.2 µg/m³, r 0.58, 65 % misma categoría, 39 % de días no buenos detectados. No se
corrige el sesgo ni se califica El Marqués con la norma.

**Arquitectura.** Flask + SQLite en solo lectura, Chart.js/Leaflet/GSAP locales, Gunicorn en Docker
para Railway. Resúmenes precalculados al arrancar (≈ 4 s, en segundo plano). 362 pruebas.

**Machine learning.** Candidato `aeris-pm25-20261017-v1` congelado; prueba ciega 19/10–19/11/2026.

**Preguntas probables.**
- *¿Por qué ozono?* Se forma con sol, NOₓ y compuestos orgánicos; el máximo horario de la tarde
  supera 0.058 ppm con frecuencia. Los datos no identifican la fuente.
- *¿Por qué no usar el modelo para El Marqués?* Su celda es la de la zona metropolitana y se equivoca
  justo en los días que importan.
- *¿Por qué no un mapa de calor?* Ocho puntos no describen un territorio; interpolar inventaría datos.
- *¿Por qué 2024 tiene pocos días?* El archivo tiene huecos ese año; las proporciones por año se
  comparan con cautela.

## 5. Railway

Estado: **preparado, no desplegado.** Builds de Railway ya disponibles; falta autorización para push
y despliegue. Procedimiento: [aeris_railway_publicacion_congreso.md](aeris_railway_publicacion_congreso.md).
El corte 32 pesa 603 MB (antes 107 MB): la subida al volumen tarda más; validador local correcto
(`scripts/validate_ambiental_railway.py`, 98 archivos en la imagen).

## 6. Limitaciones conocidas

- Corte del 20/10/2026; no se actualiza durante la demostración.
- Las bandas 2026 se aplican a todos los años para comparar con una vara; no es cumplimiento retroactivo.
- Cobertura desigual por estación, contaminante y año; los resúmenes no son promedios estatales.
- `gases-v1` impide por construcción ver «Extremadamente mala» en gases y PM10 (sensibilidad publicada).
- La meteorología y el modelo no miden contaminantes en sitio.
- Linux/Gunicorn real sin probar (solo perfil simulado en Windows).
