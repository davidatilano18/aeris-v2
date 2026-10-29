# Cuentas de usuario (fases A y B)

Rama `aeris-cuentas`. Registro con correo y contraseña, verificación de correo,
inicio de sesión, recuperación de contraseña, perfil y aviso de privacidad.

## Modos

| Modo | Comportamiento |
|---|---|
| `local` | Activas. Base `data/aeris_usuarios.db`, clave de sesión en `.secrets/aeris_session_key` (se crea sola) y correos impresos en la consola. |
| `beta` (Railway) | Apagadas: no se registran rutas ni enlaces. Con `AERIS_CUENTAS_DB_PATH` el arranque se detiene a propósito hasta configurar clave de sesión y envío real de correos (fase H). |

La base de mediciones sigue en solo lectura; `cuentas.store.conectar()` se niega a abrirla.

## Rutas

| Ruta | Uso |
|---|---|
| `/cuenta/registro` | Alta con aceptación del aviso de privacidad |
| `/cuenta/verificar/<token>` | Confirma el correo (24 h) |
| `/cuenta/entrar` | Inicio de sesión; `siguiente` solo acepta rutas internas |
| `/cuenta/salir` | POST con CSRF |
| `/cuenta/recuperar`, `/cuenta/restablecer/<token>` | Enlace de 1 h, de un solo uso |
| `/cuenta` | Perfil, cambio de contraseña y borrado de cuenta |
| `/privacidad` | Aviso de privacidad (borrador: completar responsable y contacto) |

## Seguridad

- Contraseñas con scrypt (Werkzeug), de 10 a 128 caracteres. Tokens aleatorios de un
  solo uso; en la base solo se guarda su SHA-256.
- CSRF en todos los formularios. Cookie `aeris_sesion` HttpOnly y SameSite=Lax; en
  despliegue se añadirá `Secure`.
- Cambiar o restablecer la contraseña sube `sesion_version` y cierra las demás sesiones.
- Límites: 5 intentos de inicio por correo y 20 por IP cada 15 min; 5 registros o
  recuperaciones por IP y 3 correos por cuenta cada hora.
- Respuestas iguales para correo inexistente o contraseña errónea, en registro
  duplicado y en recuperación. El tiempo de respuesta tampoco lo delata.
- Páginas con `Cache-Control: no-store` y `Referrer-Policy: no-referrer`.

## Probar en local

```powershell
.venv\Scripts\python.exe -B app.py
```

Abre `http://127.0.0.1:5000/cuenta/registro`. El enlace de verificación aparece en
la consola del servidor, entre `--- correo local (no enviado) ---` y `--- fin del correo ---`.

## Fase C: estaciones favoritas

- `/cuenta/estaciones`: la persona marca hasta 20 estaciones con datos en los últimos
  7 días (vía `alertas/lecturas.py`, solo lectura) y elige umbral: la referencia de
  25 µg/m³ (NOM-025-SSA1-2021, 24 h) o uno propio.
- `/inicio` muestra «Tus estaciones» antes de «¿Cómo está el aire?» solo con sesión
  iniciada: última lectura horaria, hora local y si queda por encima o por debajo del umbral.
- `/cuenta` resume las estaciones elegidas.
- Esquema v2 (`favoritos`, `usuarios.umbral`); una base v1 se migra sola al abrir.

## Fase D: alertas por Telegram desde la cuenta

- «Mi cuenta» → «Conectar Telegram» genera `https://t.me/AERIS_QRO_BOT?start=<código>`:
  de un solo uso, 15 minutos, 5 por hora; solo se guarda su SHA-256.
- El bot (`--cuentas data/aeris_usuarios.db`) recibe `/start <código>` y vincula el chat.
  Una cuenta, un chat; un chat, una cuenta. Cuentas sin verificar o desactivadas no se vinculan.
- `alertas/vinculos.py` copia en cada vuelta del bot (≤ 30 s) las estaciones y el umbral
  de la cuenta (o 25 µg/m³) a las suscripciones del chat. Respeta `/pausa`, `/silencio`
  y el historial de avisos. `/suscribir` y `/cancelar` remiten a la web.
- Se desvincula con «Desconectar Telegram», `/desvincular`, `/baja` o al borrar la cuenta;
  el bot quita esas suscripciones y lo avisa en el chat.
- Esquemas: cuentas v3 (`telegram_vinculos`, `telegram_codigos`) y alertas v2
  (`chats_vinculados`), con migración automática.

## Prototipo local: correos

Sin servicio de correo, el enlace de verificación o recuperación se imprime en la
consola y además se muestra en la página. Solo ocurre en modo `local` con el envío de
consola; con un envío real nunca aparece en pantalla.

## Fase F: panel de administración

- `/admin` (resumen) y `/admin/usuarios` (lista, búsqueda y acciones), solo para rol
  `admin`. Sin sesión redirige a iniciar sesión; con otro rol responde 404.
- Resumen: cifras de cuentas; ingesta según los reportes que ya escribe la
  sincronización (`data/sync_runtime/scheduler`, sin ejecutarla); última lectura por
  estación (atrasada si pasa de 4 h); base del bot en solo lectura; bitácora.
- Acciones: confirmar correo, activar o desactivar (cierra sus sesiones), dar o quitar
  admin y borrar. Nadie puede aplicárselas a sí mismo y siempre queda al menos un admin
  activo. Todas quedan en `admin_eventos` (esquema v4).
- Rol desde la consola:

```powershell
.venv\Scripts\python.exe -B -m cuentas.admin listar
.venv\Scripts\python.exe -B -m cuentas.admin rol correo@ejemplo.mx admin
```

## Pruebas sin tocar las bases reales

Algunas pruebas importan la app real, que abre (y migra) las bases configuradas. Para
no tocar las del prototipo, apunta las variables a una carpeta temporal:

```powershell
$t = New-Item -ItemType Directory -Path (Join-Path $env:TEMP ([guid]::NewGuid()))
$env:AERIS_DB_PATH = 'C:\Users\MSI_COREi5\AERIS\data\aeris_air_quality.db'
$env:AERIS_CUENTAS_DB_PATH = "$t\u.db"; $env:AERIS_ALERTAS_DB_PATH = "$t\a.db"
.venv\Scripts\python.exe -B -m unittest discover -s tests
```
