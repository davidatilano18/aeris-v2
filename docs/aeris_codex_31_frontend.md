# Portada del congreso · frontend 3.1

Rama: `aeris-codex-3.1`. Worktree: `reports/tmp_aeris_codex_3_1`.
Base: etiqueta `aeris-congreso-3.0.1`, commit `2e858dfb1ff494e45db026b9d4f42f49d5213f90`.

## Cambios

- `/inicio`, en sus dos experiencias, incorpora «Cómo trabajamos»: procedencia,
  decisiones de integración, revisión automática, reglas diarias y brechas.
- Las decisiones de fuentes proceden del inventario `docs/aeris_fuentes_ambientales.md`
  del 20/10/2026. No se hicieron nuevas consultas a proveedores para este frontend.
- Mapa y lista distinguen reciente (campo `fresh` del resumen existente, hasta dos
  horas), solo historial y sin observaciones. Los estados son de disponibilidad,
  no sanitarios. Historial usa trazo discontinuo y fecha real en el popup/lista;
  cada marcador conserva acceso por teclado. La meteorología mantiene su símbolo separado.
- El aviso de El Marqués muestra la fecha real del catálogo/resumen, nunca una
  fecha inventada ni un estado del aire extrapolado al municipio.
- Recursos locales, tipografía y escenas existentes conservados; corrección de
  encogimiento de las gráficas existentes a 320 px, sin esconder desbordamientos.

## Contrato de datos existente

Sin endpoints ni SQL nuevos. `overview.stations` aporta identidad, coordenadas,
`records`, `fresh`, `latest` y fuentes; `estado.revisiones` permite el resumen sin JS.
`/inicio/datos/pm25-diario.csv` aporta los recuentos: suma de `horas_con_dato` menos
`horas_validas` y filas `clasificacion_nom172 = En revisión`. La unidad de conteo
diario es fuente + sensor + día local: no días estatales únicos. No mezclar fuentes.

No se reemplazó el cálculo del backend: menos de 18 horas totales es «Sin promedio»;
18 o más con menos de 18 utilizables es «En revisión». Las horas excluidas no son
el total de todas las alertas almacenadas. Tampoco constituyen errores confirmados.
El cliente rechaza filas truncadas, recuentos vacíos/imposibles y claves duplicadas.
Ante timeout/error conserva guiones para las horas y explica el origen del resumen
diario si sigue visible. Cero solo se muestra después de leer correctamente el CSV.

Se preserva la clasificación existente; el texto aclara que usar la referencia 2026
en el historial no acredita cumplimiento normativo retroactivo. No se habilitan pronósticos.

## Validación local

- Tres nuevas pruebas de integración: experiencias clásica/inmersiva y lectura
  inmutable, El Marqués histórico con fecha real, indisponibilidad sin cifras inventadas.
- Chrome real, movimiento reducido: 1440, 390 y 320 px, sin errores JavaScript ni
  desbordamiento horizontal. Prueba del parser con fuentes separadas y rechazo de
  recuento ausente. Capturas fuera de Git: `reports/aeris31_method_<ancho>.png`
  y `reports/aeris31_map_<ancho>.png` en el proyecto original.
- Corte inmutable usado: `reports/beta_snapshots/congreso-20261020T163940Z/demo.json`.
  Su CSV diario devuelve 556 combinaciones estación/fuente/día, 14 horas excluidas
  y 1 día en revisión; mapa: 0 recientes, 6 con historial, 2 sin registros.
  Son resultados de ese corte, no del estado productivo actual.
- Suite completa: ver cierre de validación. Existe un fallo en
  `test_ambiental.ActualizarTests.test_cli_escribe_reporte_sin_borrar_nada`:
  se parchea `actualizar.descargar`, pero `ejecutar(..., bajar=descargar)` retiene
  la función original capturada al definirla. El mock no aísla esa llamada.
  Corrección sugerida a Claude: inyectar el descargador al ejecutar el CLI o
  sustituirlo explícitamente en la prueba. No se cambió el actualizador ni su prueba.

### Cierre de validación

`python -B -m unittest discover -s tests`: **333 pruebas ejecutadas, 332 aprobadas
y 1 fallo**, el del CLI ambiental descrito arriba. Las tres pruebas nuevas pasan.
No se creó commit local con esta suite pendiente; los siete archivos de frontend,
pruebas y documentación permanecen preparados sin staging en la rama nueva.

Los archivos reservados a Claude no tienen diferencias contra la etiqueta base.
No hubo escrituras productivas, sincronizaciones manuales, push, merge ni despliegue.

## Abrir esta versión

Desde el worktree nuevo, en PowerShell:

```powershell
C:\Users\MSI_COREi5\AERIS\.venv\Scripts\python.exe -B scripts/run_local_demo.py --manifest C:\Users\MSI_COREi5\AERIS\reports\beta_snapshots\congreso-20261020T163940Z\demo.json --port 5054 --offline
```

Abrir `http://127.0.0.1:5054/inicio`. El servidor puede estar ya iniciado; no abrir
otro sobre el mismo puerto. El launcher verifica el corte y no activa ingesta.
