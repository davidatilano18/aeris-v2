# Alertas de PM2.5 por Telegram (prototipo local)

Rama `aeris-alertas`. No forma parte del sitio web ni de Railway: la web sigue siendo
de solo lectura y sin secretos.

## Datos

Base propia `data/aeris_alertas.db` (excluida de Git por `*.db`), creada por
`alertas.store.conectar()`. Se niega a abrir la base de mediciones o cualquier SQLite
que no sea de alertas.

| Tabla | Contenido |
|---|---|
| `suscriptores` | `chat_id` de Telegram, fecha de alta, si está activo y horario de silencio opcional. Sin nombre ni teléfono. |
| `suscripciones` | Estación (`sensor_id`, `NULL` = todas) y umbral en µg/m³. Máximo 10 por chat. |
| `alertas_enviadas` | Historial de avisos `supera` / `normaliza`, para avisar solo al cruzar el umbral. |

`/baja` borra el chat y, en cascada, sus suscripciones e historial.

## Token del bot

Se guarda cifrado con DPAPI para el usuario de Windows actual, igual que la clave de
OpenAQ. Desde la raíz del repositorio, en una ventana de PowerShell propia:

```powershell
New-Item -ItemType Directory -Path .secrets -Force | Out-Null
Read-Host 'Token del bot de Telegram' -AsSecureString | Export-Clixml -LiteralPath .secrets\telegram_bot_token.clixml
```

`.secrets/` está excluido de Git. El token nunca va en el código, en la línea de
comandos ni en los logs.

## Bot

```powershell
.venv\Scripts\python.exe -B -m alertas.bot
```

Long polling (`getUpdates`): no abre puertos ni requiere dominio. Solo responde en
chats privados, ignora textos de más de 200 caracteres y limita a 12 mensajes por
minuto por chat. Los logs no incluyen chats, textos ni el token.

| Comando | Efecto |
|---|---|
| `/start` | Alta del chat |
| `/ahora` | Última lectura horaria por estación (fuente OpenAQ, solo lectura) |
| `/estaciones` | Estaciones con datos en los últimos 7 días, numeradas por nombre |
| `/suscribir <número\|todas> [umbral]` | Umbral por defecto 25 µg/m³ (referencia de 24 h de la NOM-025-SSA1-2021 desde 2026) |
| `/cancelar <número\|todas>` | Quita una suscripción |
| `/mis_alertas` | Suscripciones, silencio y pausa |
| `/silencio <desde> <hasta>` / `/silencio no` | Horas sin avisos, hora del centro de México |
| `/pausa`, `/reanudar` | Pausa o reanuda todos los avisos |
| `/baja` | Borra el chat y todo lo asociado |

Los avisos comparan lecturas horarias con el umbral elegido; no son un índice de salud.

## Avisos

El mismo proceso del bot evalúa al arrancar y cada vez que cambia
`data/sync_runtime/scheduler/last_success.json` (sincronización exitosa nueva). La
ingesta (`data_ingestion/scheduled_sync.py`) y la tarea programada no se modifican:
una falla de alertas no puede afectar la recopilación.

- Se ignoran lecturas `<= 0` y las de más de 4 h (OpenAQ publica con ~2-3 h de retraso).
- `supera`: la lectura pasa de `<= umbral` a `> umbral`. No se repite mientras siga alta.
- `normaliza`: tras un `supera`, la lectura baja de `0.9 × umbral` (histéresis contra avisos alternos).
- Lecturas con `requiere_revision` (> 100 µg/m³ o salto de 100) se avisan con «lectura en revisión».
- En horario de silencio no se envía ni se registra; si sigue alto al terminar, se avisa entonces.
- Un mensaje por chat. Solo se registra lo que Telegram confirmó; 400/403 (bot bloqueado)
  pausa el chat; 429 o red caída deja el resto pendiente para reintentar.
