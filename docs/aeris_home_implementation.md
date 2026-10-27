# AERIS — nueva página Inicio, primera entrega local

19-oct-2026. Implementación para revisión visual, sin publicación.

## Ubicación y alcance

- Rama aislada: `aeris-home-research`, creada desde `origin/main` en
  `4f490cbf84443adba332111f67075823ff0a128c`.
- Worktree: `C:\Users\MSI_COREi5\AERIS\reports\tmp_aeris_home`.
- Nueva ruta: **/inicio**. Se mantienen `/`, `/v2`, `/v2/datos` y sus APIs.
- La interfaz anterior sigue disponible en el commit base de Git y en el
  workspace original. Además se guardaron 35 archivos de interfaz y sus hashes
  en `reports/home_interface_baseline`, fuera de la entrega; sus originales
  permanecen idénticos. No se hizo staging, commit, push, merge ni despliegue.
- La rama del parche Railway conserva HEAD `5e483f1282decc3ec28159898b3f645c6517c7b3`.

Se copió el código original necesario para ejecutar las pruebas completas al
worktree, incluidas utilidades de investigación/pruebas como soporte sin cambios.
Eso no significa que tales archivos sean parte de una futura entrega web.
El único cambio funcional a archivos anteriores es añadir la ruta en routes.py.
No se incorporó ninguna base SQLite al worktree.

## Implementado

Hero navy/turquesa con el mensaje aprobado, representación atmosférica decorativa
identificada como tal, entrada suave, ocho elementos decorativos animados mediante
transform/opacity, pausa explícita y movimiento reducido. Sin motores de partículas,
dependencias nuevas, fuentes externas ni carga automática de teselas.

Panorama generado en servidor: estaciones catalogadas y con registros, municipios
con registros, fuentes con datos, última observación con estación y hora local/UTC,
meses UTC con registros separados por fuente y estaciones con antigüedad de hasta
dos horas. Cada contador declara su alcance. No se calcula media estatal ni se
interpreta frescura como calidad o salud. El historial heredado bajo OpenAQ no
se certifica como descarga API v3.

Vista previa Leaflet con coordenadas catalogadas, estados con/sin observaciones,
fichas y marcadores accesibles por teclado, lista alternativa y teselas OSM
opcionales. Sin polígonos inventados, mapa de calor o interpolación. Es una
vista previa; la exploración completa enlaza a la experiencia existente.

Investigación como pregunta abierta; método de comparación existente accesible
en un desplegable y enlace a sus cálculos. Clasificador académico y pronósticos
separados; estos últimos deshabilitados. Tarjetas municipales y acceso destacado
al historial real de El Marqués, sin filtrar el inicio por ese municipio.
Accesos a gráficas y explorador técnico conservados.

Contenido principal y enlaces funcionan sin JavaScript. Hay estados explícitos
de base vacía, error de lectura y estaciones sin observaciones. Un error de
lectura responde 503 con explicación pública, sin imprimir rutas internas.

## Archivos del cambio

1. `aeris_web/routes.py`: nueva ruta.
2. `aeris_web/home.py`: resumen de disponibilidad con lector central de solo lectura.
3. `templates/v2/home.html`: contenido Jinja y estados.
4. `static/v2/css/home.css`: identidad, layout y movimiento accesible.
5. `static/v2/js/home.js`: mapa, fichas y controles de movimiento/teselas.
6. `tests/test_home.py`: nueve regresiones nuevas.
7. Este documento.

## Datos y seguridad

Se consulta la base original únicamente con connect_readonly: URI mode=ro,
query_only y la transacción consistente/política de lotes que ya aplica ese
lector. No se abre otra transacción encima. Se excluyen fuentes desconocidas,
sensores ajenos al catálogo e instantes futuros; unidades incompatibles o valores
no finitos provocan abstención. Los ceros se conservan. El panorama cuenta
registros disponibles, no observaciones certificadas; para revisión de calidad
remite al explorador. No se conectan campañas API/Archive para una tendencia.

En las comprobaciones finales: integrity_check=ok, foreign_key_check sin filas,
hash de producción idéntico antes/después de las peticiones de validación.
La tarea independiente podría añadir observaciones posteriormente; no se detuvo.
No hubo ingesta manual, cambios de modelos, holdout o frescura, ni operaciones
en Railway. Las pruebas emplean fixtures aisladas, nunca datos simulados en la UI.

## Pruebas y evidencia

- **260 pruebas aprobadas en 10.567 s**: 251 existentes y nueve nuevas.
- Para la suite completa dentro de este worktree sin DB, el harness asigna
  `archive_controlled.PRODUCTION` a la ruta original solo en memoria para que sus
  comprobaciones de protección/samefile reconozcan el archivo real; las operaciones
  de importación/reversión de tests ocurren exclusivamente en fixtures temporales.
  No se cambia el archivo del módulo ni se copia producción al worktree.
- HTTP 200: /inicio, /, /v2, /v2/datos, /health/ready y consulta histórica de El Marqués.
- Nuevas regresiones: fuentes separadas y sin media estatal; lectura sin cambios;
  cero histórico; no datos; error sin revelar rutas; unidad inválida y futuro;
  assets locales y accesibilidad; reloj con zona; lotes revertidos fuera de Inicio
  y conservados físicamente para auditoría.
- Chrome headless real en Windows: **1440, 390 y 320 px**, ocho marcadores,
  sin desbordamiento horizontal ni excepciones JavaScript. Pausa y preferencia
  de movimiento reducido comprobadas. Cero peticiones externas en vista inicial.
- CSS nuevo 16,333 bytes y JS 4,236 bytes; Leaflet reutilizado localmente.
  GET /inicio observado en 62.03 ms durante la comprobación final. Es una muestra
  local, no una garantía de rendimiento ni un benchmark comparativo de FPS/memoria.
- No se certifica WCAG ni comprensión de usuarios: pendientes validación humana
  y medición exhaustiva de contraste y uso con lectores de pantalla.

Evidencias locales en el workspace original: `reports/aeris_home_suite.log`,
`reports/aeris_home_validation.json`, `reports/aeris_home_visual_validation.json`,
capturas `reports/aeris_home_1440.png`, `aeris_home_390.png`, `aeris_home_320.png`
y versiones `_full.png`. Son evidencias, no assets de la aplicación.

## Ejecutar en Windows

Desde una terminal PowerShell nueva:

```powershell
cd C:\Users\MSI_COREi5\AERIS\reports\tmp_aeris_home
Get-ChildItem Env:AERIS_* | Remove-Item
$env:AERIS_ENV = "local"
$env:AERIS_DB_PATH = "C:\Users\MSI_COREi5\AERIS\data\aeris_air_quality.db"
C:\Users\MSI_COREi5\AERIS\.venv\Scripts\python.exe -B -m flask --app app:app run --host 127.0.0.1 --port 5050 --no-debugger --no-reload
```

Abrir **http://127.0.0.1:5050/inicio**. La limpieza de variables afecta solo
esa terminal, no sus valores permanentes. No se activa el venv por .ps1 ni se
cambia ExecutionPolicy. Detener el servidor de esa terminal con Ctrl+C.
Si el puerto está ocupado por la vista previa ya iniciada, usarla o detener
esa instancia antes de lanzar otra; no ejecutar dos servidores innecesariamente.

## Pendientes para aprobación posterior

La interfaz anterior no se reemplazó. No se implementaron nuevas pantallas
municipales, análisis de tendencia, rediseño completo del mapa, fronteras
geográficas ni nueva gráfica de concentración: los accesos usan las herramientas
existentes. Las fechas indican lo observado, no actualización automática en el
navegador; recargar vuelve a consultar. El historial corto de El Marqués no
permite concluir deterioro multianual. La revisión visual humana de Inicio es
el siguiente paso; no avanzar de fase sin autorización.
