# Publicación en Railway — versión del congreso

**Publicado el 20/10/2026** en https://aeris-qro.up.railway.app (servicio que sigue la rama
`aeris-demo-integracion`: cada push redespliega). Corte en `/dataset/corte-32/aeris.db`.

Estado previo (para referencia): **preparado, no publicado.** Builds de Railway disponibles de nuevo.
CLI 5.63.1 enlazada al servicio AERIS; variables de una preparación anterior (corte 003) ya cargadas:
**hay que actualizarlas al corte 32** (paso 5). Sin push ni despliegue de AERIS 3.3.

## Qué se publica

| Elemento | Valor |
|---|---|
| Repositorio | `https://github.com/davidatilano18/AERIS.git` |
| Rama a subir | `aeris-demo-integracion` (nueva en el remoto; **no** se fusiona con `main`) |
| Commit | cabeza de `aeris-demo-integracion` (AERIS 3.3); la 3.0.1 queda en la etiqueta `aeris-congreso-3.0.1` |
| Constructor | Dockerfile, forzado por `railway.json` (no Railpack) |
| Arranque | `python railway_start.py` → verifica el corte, baja a UID 10001, `exec gunicorn` |
| Datos | un solo archivo, `aeris.db`, en el volumen `aeris-volume` montado en `/dataset` |
| Corte | `corte-32`: 603,181,056 bytes, SHA-256 `e3639e93cc88d21b5c336b4b7c108f2f5f3db569de644d09f934b1743840ac43`, creado `2026-10-20T21:52:07+00:00`; 101,747 mediciones PM2.5 y 1,373,290 observaciones ambientales (archivo OpenAQ 2021–2026, CAMS, meteorología) |
| Archivo local del corte | `C:\Users\MSI_COREi5\AERIS-Demo-datos\corte-32-20261020\aeris.db` (con `manifest.json` y `demo.json`) |
| Corte anterior | `ambiental-demo-003` (107 MB, SHA `b9e8c20f…`), ya preparado para 3.0.1; no hace falta borrarlo |

La imagen contiene 101 archivos (AERIS 3.3): web (`app.py`, `wsgi.py`, `aeris_web/`, plantillas, estáticos),
`data_ingestion/{__init__,catalog,visibility}.py`, el catálogo público y los archivos de arranque.
**No** contiene ingesta, sincronizador, tarea programada, `forecasting/`, `models/`, holdout,
respaldos, `.secrets/` ni bases de datos (`.dockerignore` en lista blanca). En el corte, todas las
fuentes ambientales están `autorizada=0` y la web no tiene ninguna ruta de escritura.

## Verificaciones hechas localmente

- 363 pruebas automáticas, con la red bloqueada (incluye `test_railway_readiness`, `test_web_deployment`, `test_ambiental`).
- Imagen simulada a partir de los `COPY` del Dockerfile, perfil `AERIS_DEPLOYMENT_PROFILE=railway`
  contra el corte (`scripts/validate_ambiental_railway.py`): 19 rutas en 200, POST → 405,
  host no confiable → 400, hash sin cambios, sin módulos de ingesta/modelos disponibles.
- `railway_start.verify` sobre el corte: integridad, claves foráneas y fuentes admitidas correctas.
- Sintaxis de todos los `.py` de la imagen válida para Python 3.13 (versión del Dockerfile).
- Ninguna ruta de Windows ni nombre de usuario en archivos de la imagen; 29 referencias a
  plantillas/estáticos coinciden exactamente en mayúsculas (Linux distingue).
- Sin bases, modelos, respaldos ni credenciales rastreados en la rama.

**No verificado:** ejecución real en Linux con Gunicorn (no hay Docker ni WSL aquí), permisos POSIX
reales del volumen y espacio libre de `aeris-volume`. El arranque falla cerrado si algo no coincide.

## Procedimiento (solo tras autorización explícita)

1. **CLI** (una vez): `npm install -g @railway/cli`, `railway login`, y en `C:\Users\MSI_COREi5\AERIS-Demo`
   `railway link` eligiendo el proyecto, entorno y servicio existentes. Confirmar con `railway status`.
   No pegar tokens en documentos ni en variables de la app.
2. **Subir la rama** (no toca `main`):
   ```powershell
   git -C C:\Users\MSI_COREi5\AERIS-Demo push origin aeris-demo-integracion
   ```
3. **Servicio → Settings** (antes de desplegar):
   - Source: rama `aeris-demo-integracion`, directorio raíz del repo. **Autodeploy desactivado.**
   - Builder: debe mostrar *Dockerfile* (lo indica `railway.json`); si muestra Railpack, detenerse.
   - Custom Start Command vacío (lo aporta `railway.json`). Pre-deploy y cron vacíos.
   - Una región, una réplica. Restart policy `NEVER` (de `railway.json`).
4. **Corte de datos** al volumen, en un directorio nuevo y sin sobrescribir:
   ```powershell
   railway volume list
   railway volume files --volume aeris-volume list /
   railway volume files --volume aeris-volume upload C:\Users\MSI_COREi5\AERIS-Demo-datos\corte-32-20261020\aeris.db /corte-32/aeris.db
   railway volume files --volume aeris-volume list /corte-32
   ```
   Confirmar antes con `railway volume --help` que la versión instalada ofrece `files`. Espacio:
   el corte ocupa 603 MB; la subida tarda más (una anterior se cortó por tiempo: reintentar, no sobrescribir).
5. **Variables** (Railway proporciona `PORT`):
   ```
   AERIS_ENV=beta
   AERIS_DB_PATH=/dataset/corte-32/aeris.db
   AERIS_SNAPSHOT_SHA256=e3639e93cc88d21b5c336b4b7c108f2f5f3db569de644d09f934b1743840ac43
   AERIS_SNAPSHOT_CREATED_UTC=2026-10-20T21:52:07+00:00
   AERIS_TRUSTED_HOSTS=localhost,127.0.0.1,healthcheck.railway.app
   AERIS_PROXY_HOPS=0
   AERIS_LOG_LEVEL=INFO
   RAILWAY_RUN_UID=0
   ```
   No definir `OPENAQ_API_KEY` (el arranque lo rechaza), `AERIS_AMBIENTAL_DB_PATH`,
   `AERIS_AMBIENTAL_DIARIO`, `AERIS_AMBIENTAL_BASE_PRINCIPAL` ni `AERIS_BACKUP_RETENTION`.
6. **Desplegar** una vez. En Deploy Logs debe aparecer
   `railway_snapshot_verified web_uid=10001 access=read-only` y Gunicorn escuchando en `PORT`;
   el healthcheck `/health/ready` debe pasar. Si el log dice `railway_start_failed type=…`,
   no reintentar en bucle: revisar ruta, SHA o permisos.
7. **Dominio público** (es publicar): Settings → Networking → *Generate Domain*. Añadir ese host
   exacto a `AERIS_TRUSTED_HOSTS` (p. ej. `…,aeris-production.up.railway.app`) y redesplegar.
   Mantener `AERIS_PROXY_HOPS=0` salvo que se verifique la cabecera del proxy.
8. **Aceptación** en el navegador: `/inicio`, `/inicio/explorar` (pestañas Aire y Tiempo),
   `/v2`, `/v2/datos`, `/api/ambiental/v1/fuentes`, `/health/ready`. Debe verse el aviso de copia
   estática con la fecha del corte. Opcional por SSH: `python railway_acceptance.py`.

## Reversión

- Railway: Deployments → redeploy del deployment anterior, o Source de vuelta a `main`.
- Retirar el dominio en Networking si hay cualquier duda. No borrar el volumen sin otra autorización.
- Local (plan alternativo, sin internet): `scripts\Iniciar-AERIS-Congreso.ps1` → http://127.0.0.1:5070/inicio,
  y capturas en `C:\Users\MSI_COREi5\AERIS-Demo-datos\capturas-congreso\`.

## Riesgos

- Primera ejecución Linux real: posibles diferencias de permisos del volumen (el arranque falla
  cerrado; no ejecutar Gunicorn como root como atajo).
- Si el servicio sigue con Railpack u otro start command, ignora `railway.json`: verificar en el paso 3.
- El dominio público expone datos sanitizados del corte; revisar el aviso de fecha antes de compartirlo.
- La CLI y `volume files` no se han probado contra la cuenta.
