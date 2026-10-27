# Frontend AERIS — laboratorio ambiental funcional

20-oct-2026. Rama `aeris-home-research`; sin commit, push, merge ni despliegue.

## Cinco mejoras implementadas

1. **Navegación de producto:** Inicio conserva su composición y datos reales,
   con acceso principal al laboratorio `/inicio/explorar`; las rutas anteriores
   siguen disponibles, incluida `/inicio/anterior` para comparar el primer diseño.
2. **Exploración coordinada:** municipio, estación, fuente, periodo y fechas UTC
   personalizadas. Mapa seleccionable, serie, cobertura y tabla responden a la
   consulta. Una estación por gráfica; ningún promedio municipal o estatal.
3. **Preparación multivariable honesta:** PM2.5 operativo; PM10, O3, NO2,
   temperatura, humedad y viento explícitamente deshabilitados hasta conectar
   series verificables. Se distingue tipo observado de estimación/pronóstico;
   estos últimos no se representan con valores ficticios.
4. **Investigación funcional:** cobertura y faltantes, comparación histórica
   mediante endpoint existente con evidencia de ventanas/método. Tendencias y
   correlaciones explican requisitos pendientes y no muestran resultados inventados.
5. **Móvil compacto y accesible:** vistas Serie / Mapa / Tabla intercambiables,
   tabla en páginas incrementales de 200 filas, fichas municipales de Inicio
   desplegables en móvil, estados de carga/error/ausencia y movimiento reducido.

## Contratos y separación de trabajo

`docs/frontend_backend_contract.md` registra endpoints actuales y necesidades
multivariables propuestas: capacidades, unidades, intervalos físicos, zona IANA,
procedencia, tipo de producto, calidad, cobertura, consistencia/paginación y estados
de abstención. Los nombres /api/v3 son propuestas NO implementadas ni consumidas.
Es el documento para revisar con Claude y la persona usuaria antes de integrar.

No se modificó ni se integró el worktree `AERIS-Claude` / `aeris-data-expansion`.
No se cambió el modelo de datos ni se escribió SQLite; la interfaz usa lectores
existentes, con visibilidad central y solo lectura. Tampoco se alteraron ingesta,
tareas, respaldos, ML, holdout, Railway ni el parche 5e483f1.

## Semántica de los filtros y resultados

- Periodos recientes: horas completas del endpoint existente. Historial completo:
  cobertura solo entre la primera y última observación, no cobertura anual.
- Personalizado: días UTC, inicio incluido y fin convertido a exclusivo; la
  ventana se limita a horas pasadas completas. Recorte solo en memoria del
  producto/estación seleccionados. No se interpolan ni almacenan mediciones.
- Reciente: última observación de la selección con antigüedad de hasta dos horas.
  Histórico: Archive o datos de un año anterior. Antiguo: observado hace más de
  dos horas. Estas etiquetas describen disponibilidad, no riesgo o validación.
- Estimaciones y pronósticos: ninguno conectado. Requieren procedencia y un
  contrato separado; no se sustituyen con observaciones de otra fuente.
- Comparación: dos ventanas de 24 h al final del historial, no necesariamente
  el periodo de la gráfica. Esto se informa antes de solicitarla; se publican
  periodos y método recibidos. No constituye una tendencia multianual.
- Los errores y cambios de selección retiran cifras/serie anteriores. AbortController
  y comprobación de identidad de consulta evitan respuestas fuera de orden.

## Validación realizada

**266 pruebas aprobadas en 13.384 s**. Se mantiene el harness de la entrega previa
para las pruebas aisladas de importación; no se entrenaron modelos productivos ni
se importaron observaciones. Tres nuevas pruebas cubren ruta/recursos, variables
deshabilitadas y error sin revelar rutas del servidor.

Chrome real headless en Windows: 1440, 390 y 320 px, sin desbordamiento horizontal
ni excepciones JavaScript, cero solicitudes externas en vista inicial. Probado:

- Gráfica y tabla de Corregidora/OpenAQ con 166 observaciones en la muestra reciente.
- Acceso rápido a las 333 filas históricas de El Marqués y paginación completa.
- Fechas personalizadas 10–11 septiembre 2021: 43 observaciones en el corte real.
- El Marqués / últimos 7 días: cero observaciones, sin gráfica anterior retenida.
- Municipio/estación, respuesta a cambios rápidos, vistas móviles de mapa y tabla.
- Comparación histórica mediante API y evidencia del método; no generación local
  de estadísticas nuevas. Error de red inducido sin datos de reemplazo.
- Variables no conectadas deshabilitadas, correlación declarada no disponible,
  reducción de movimiento y ausencia de nuevas dependencias.

HTTP 200: /inicio, /inicio/explorar, /inicio/anterior, /, /v2 y /v2/datos.
SQLite: integrity_check=ok, cero infracciones FK y hash idéntico durante las
verificaciones finales. Las ejecuciones independientes de la tarea pueden añadir
observaciones legítimas en otro momento; no se detuvieron.

No se certifica WCAG, rendimiento en móviles físicos ni comprensión de usuarios.
El mapa base en línea sigue siendo opcional y no fue necesario para estas pruebas.

## Evidencias y archivos

Evidencias en el directorio original `reports/`, fuera de los assets de la web:

- `aeris_frontend_lab_suite.log`, `aeris_frontend_lab_validation.json`,
  `aeris_lab_visual_validation.json`.
- `aeris_lab_1440_full.png`, `aeris_lab_390_full.png`, `aeris_lab_320_full.png`.
- `aeris_lab_1440_map.png` y equivalentes 390 / 320.
- `aeris_home_lab_1440_full.png` y equivalentes móviles: Inicio actualizado.

Código de esta entrega: routes.py, home.html, home.js, workspace.html,
workspace.css, workspace.js, test_workspace.py y estos documentos. No se modificó
`aeris_web/home.py` ni la lógica de los endpoints de observación/comparación.

## Abrir localmente

http://127.0.0.1:5050/inicio/explorar

Para reiniciar, desde PowerShell:

```powershell
cd C:\Users\MSI_COREi5\AERIS\reports\tmp_aeris_home
Get-ChildItem Env:AERIS_* | Remove-Item
$env:AERIS_ENV = "local"
$env:AERIS_DB_PATH = "C:\Users\MSI_COREi5\AERIS\data\aeris_air_quality.db"
C:\Users\MSI_COREi5\AERIS\.venv\Scripts\python.exe -B -m flask --app app:app run --host 127.0.0.1 --port 5050 --no-debugger --no-reload
```

No lanzar otro servidor si la vista previa ya ocupa el puerto. Ctrl+C detiene el
servidor iniciado desde esa terminal. No se cambia ExecutionPolicy.

## Pendientes

Conectar variables nuevas únicamente tras revisar contratos y evidencia del backend
de Claude, sin integrar automáticamente su rama. Tendencias, correlaciones y
estimaciones requieren método y datos compatibles. El explorador legado no recibe
el recorte personalizado UTC: el enlace lo declara y abre el historial completo.
No se crean descargas nuevas ni se modifica el CSV existente. No hay mapa municipal
interpolado, atribución causal o conclusión estatal de deterioro.
