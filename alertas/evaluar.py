"""Evalúa suscripciones contra la última lectura y envía avisos solo al cruzar el umbral."""
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from alertas import lecturas, store

LOCAL = ZoneInfo('America/Mexico_City')
MAX_EDAD_HORAS = 4  # OpenAQ publica con ~2-3 h de retraso; más antigua no se avisa
HISTERESIS = 0.9    # «volvió a bajar» solo por debajo del 90 % del umbral
PIE = 'Son lecturas horarias, no un índice de salud. /ahora muestra todas las estaciones.'


def en_silencio(desde, hasta, hora):
    if desde is None:
        return False
    return desde <= hora < hasta if desde < hasta else hora >= desde or hora < hasta


def planear(suscripciones, estaciones, ultimo, now):
    """Eventos a enviar. `ultimo(suscripcion_id, sensor_id)` devuelve el último aviso o None."""
    hora = now.astimezone(LOCAL).hour
    utiles = {e['sensor_id']: e for e in estaciones if e['valor'] > 0 and 0 <= e['edad_horas'] <= MAX_EDAD_HORAS}
    eventos = []
    for s in suscripciones:
        if en_silencio(s['silencio_desde'], s['silencio_hasta'], hora):
            continue
        for sid in (utiles if s['sensor_id'] is None else [s['sensor_id']]):
            e = utiles.get(sid)
            if e is None:
                continue
            previo = ultimo(s['id'], sid)
            fecha = e['fecha_utc'].isoformat(timespec='seconds').replace('+00:00', 'Z')
            if previo and previo['fecha_utc'] == fecha:
                continue
            alto = bool(previo) and previo['tipo'] == 'supera'
            if not alto and e['valor'] > s['umbral']:
                tipo = 'supera'
            elif alto and e['valor'] < s['umbral'] * HISTERESIS:
                tipo = 'normaliza'
            else:
                continue
            eventos.append({'suscripcion_id': s['id'], 'chat_id': s['chat_id'], 'sensor_id': sid,
                            'nombre': e['nombre'], 'valor': e['valor'], 'fecha_utc': fecha,
                            'hora': e['fecha_utc'].astimezone(LOCAL).strftime('%d/%m %H:%M'),
                            'umbral': s['umbral'], 'revision': e['revision'], 'tipo': tipo})
    return eventos


def mensaje(eventos):
    vistos, altos, bajos = set(), [], []
    for ev in eventos:
        if (ev['sensor_id'], ev['tipo']) in vistos:
            continue
        vistos.add((ev['sensor_id'], ev['tipo']))
        nota = ' (lectura en revisión)' if ev['revision'] else ''
        texto = f'- {ev["nombre"]}: {ev["valor"]:.0f} µg/m³ a las {ev["hora"]} (tu umbral: {ev["umbral"]:g}){nota}'
        (altos if ev['tipo'] == 'supera' else bajos).append(texto)
    partes = []
    if altos: partes.append('AERIS: PM2.5 por encima de tu umbral\n' + '\n'.join(altos))
    if bajos: partes.append('AERIS: PM2.5 volvió a bajar\n' + '\n'.join(bajos))
    return '\n\n'.join(partes + [PIE])


def evaluar(conn, api, mediciones, now=None, log=print):
    """Envía los avisos pendientes. Solo registra lo que Telegram confirmó."""
    from alertas.bot import TelegramError
    now = now or datetime.now(timezone.utc)
    eventos = planear(store.activas(conn), lecturas.estaciones(mediciones, now),
                      lambda sub, sid: store.ultimo_aviso(conn, sub, sid), now)
    por_chat = {}
    for ev in eventos:
        por_chat.setdefault(ev['chat_id'], []).append(ev)
    resumen = {'eventos': len(eventos), 'enviados': 0, 'pausados': 0, 'pendientes': 0}
    for chat_id, lista in por_chat.items():
        try:
            api.send(chat_id, mensaje(lista))
        except TelegramError as exc:
            if exc.code in (400, 403):  # bot bloqueado o chat inexistente
                store.pausar(conn, chat_id); resumen['pausados'] += 1
                continue
            resumen['pendientes'] += len(por_chat) - resumen['enviados'] - resumen['pausados']
            break  # 429 u otro error: se reintenta en la próxima evaluación
        except OSError:
            resumen['pendientes'] += len(por_chat) - resumen['enviados'] - resumen['pausados']
            break
        for ev in lista:
            store.registrar_aviso(conn, ev['suscripcion_id'], ev['sensor_id'], ev['fecha_utc'],
                                  ev['valor'], ev['tipo'], store.utc_now())
        resumen['enviados'] += 1
    log('evaluacion ' + ' '.join(f'{k}={v}' for k, v in resumen.items()))
    return resumen


def marca_sincronizacion(mediciones):
    """Hora de la última sincronización exitosa, o None si no se puede leer."""
    path = Path(mediciones).resolve().parent / 'sync_runtime' / 'scheduler' / 'last_success.json'
    try:
        audit = json.loads(path.read_text(encoding='utf8'))
        return audit['finished_at_utc'] if audit.get('status') == 'success' else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


class Vigilante:
    """Evalúa al arrancar y cada vez que termina una sincronización exitosa nueva."""
    def __init__(self, evaluar_fn, marca_fn):
        self.evaluar_fn, self.marca_fn, self.ultima = evaluar_fn, marca_fn, object()

    def __call__(self):
        marca = self.marca_fn()
        if marca is not None and marca != self.ultima:
            resumen = self.evaluar_fn()
            if not (resumen or {}).get('pendientes'):  # con pendientes se reintenta en la siguiente vuelta
                self.ultima = marca
