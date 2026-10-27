# AERIS 3.0 — experiencia inmersiva

Rama `aeris-inmersivo-3`, worktree `C:\Users\MSI_COREi5\AERIS-Inmersivo`, a partir de `42492c0`.
Integrada en la rama del congreso (`aeris-demo-integracion`) el 20/10/2026.

## Cómo verla

```powershell
cd C:\Users\MSI_COREi5\AERIS-Inmersivo
C:\Users\MSI_COREi5\AERIS\.venv\Scripts\python.exe -B scripts\run_local_demo.py `
  --manifest C:\Users\MSI_COREi5\AERIS-Demo-datos\corte-20261020\demo.json --offline --port 5080
```

- Inmersiva (predeterminada desde el 20/10/2026): http://127.0.0.1:5080/inicio
- Clásica: http://127.0.0.1:5080/inicio?experiencia=clasica (se recuerda en una galleta).
- En el pie de página hay un enlace para cambiar de experiencia.

## Escenas

| Escena | Contenido | Técnica |
|---|---|---|
| 1. Introducción | Cielo, nubes y partículas; «AERIS» letra por letra; botones Ir a los datos, Abrir laboratorio, Saltar animación, Pausar movimiento | WebGL2 propio (`static/v2/js/escena/atmosfera.js`), GSAP SplitText |
| 2. Entrar al aire | Descenso fijado con tres frases; la cámara avanza entre nubes | ScrollTrigger con `pin` y `scrub` |
| 3. Los datos | La atmósfera se desvanece y se detiene; entra «¿Cómo está el aire?» (datos reales sin cambios) | ScrollTrigger |
| 4. Puertas | Laboratorio, territorio, datos abiertos con cifras reales | GSAP + View Transitions |

La densidad de partículas es proporcional al promedio real de PM2.5 del último día completo de una
estación (desempate alfabético), citado en pantalla: `partículas = 1600 × µg/m³ / 15`, con un máximo
por dispositivo. Las cifras animadas terminan exactamente en el valor publicado que ya está en el HTML.

## Rendimiento y respaldo

- Dos niveles: completo (resolución 0.75, 5 octavas, ≤ 3,000 partículas) y ligero (0.5, 3 octavas,
  ≤ 900). Ligero en equipos con ≤ 4 núcleos o ≤ 4 GB, pantallas < 760 px o ahorro de datos; un
  regulador baja a ligero si el promedio supera 33 ms por cuadro.
- Densidad de píxeles limitada a 1.5; pausa en pestaña oculta, fuera de pantalla o con «Pausar movimiento».
- Fondo estático (CSS) sin WebGL2, con `prefers-reduced-motion`, sin JavaScript o si se pierde el contexto.
- Medido el 20/10/2026 en Intel UHD (Chrome sin interfaz, GPU real): 144 fps en reposo y en scroll,
  p95 7 ms, 0 tareas largas a 1440 px; con CPU ×4 igual; móvil 390 px CPU ×4: una tarea de 54 ms al
  iniciar. 6 MB de memoria JS. Falta confirmar en pantalla física y en el equipo del congreso.

## Dependencias locales (sin CDN)

GSAP 3.15.0 (gsap, ScrollTrigger, SplitText; licencia estándar sin costo de Webflow), Instrument Serif
5.3.0 e Inter 5.3.0 (OFL-1.1, @fontsource). Integridad verificada contra el registro npm y SHA-256 en
`static/v2/vendor/manifest.json`. Sin Three.js ni Lenis: no eran necesarios (ver propuesta).

## Laboratorio y vistas v2

- `laboratorio_vivo.js`: anima cambios de cifras y la aparición de gráficas observando lo que
  `workspace.js`/`meteorology.js` ya escriben; no calcula nada.
- `laboratorio3.css`: titulares editoriales, encabezado de vidrio, estados de carga y error.
- Eje de tiempo con horas en ventanas ≤ 48 h. Transiciones entre páginas en todas las vistas.
- El dashboard original (`/`) ya no depende de CDN para Leaflet, Chart.js e Inter.

## Datos abiertos y Aprende

- `/inicio/datos`: CSV de PM2.5 horario, PM2.5 diario (NOM-172), meteorología NOAA MMQT y reanálisis
  NASA POWER, con diccionario de columnas, origen y licencia (`aeris_web/datos_abiertos.py`).
- `/inicio/aprende`: PM2.5 y µg/m³, simulador de la escala oficial, recorrido de tres días reales,
  NOM-025 frente a OMS, índice horario y revisión de datos (`aeris_web/aprende.py`).

## Verificación

- 322 pruebas automáticas (`tests/test_inmersivo.py`: selección y galleta, recursos locales, cifras
  iguales a los datos, respaldo y movimiento reducido en el código).
- Navegador: 8 vistas × escritorio/móvil sin errores de JavaScript ni desborde horizontal.
- Accesibilidad: con movimiento reducido no hay WebGL ni fijado y las tres frases quedan legibles;
  con teclado, «Saltar animación» detiene las animaciones, apaga la atmósfera, lleva a los datos y
  mueve el foco al título.
