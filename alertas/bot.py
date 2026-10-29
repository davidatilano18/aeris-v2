"""Bot de Telegram de AERIS por long polling: sin puertos abiertos ni dominio.

Uso: python -B -m alertas.bot [--key-file .secrets/telegram_bot_token.clixml]
El token nunca se imprime; los logs no incluyen chats ni textos de mensajes.
Además envía los avisos: evalúa al arrancar y tras cada sincronización exitosa nueva.
"""
import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from alertas import evaluar, lecturas, store, vinculos

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ZoneInfo('America/Mexico_City')
UMBRAL_NORMA = 25.0  # NOM-025-SSA1-2021, referencia de 24 h vigente desde enero de 2026
MAX_TEXTO = 200
MAX_MENSAJES_POR_MINUTO = 12
COMANDOS = [
    ('ahora', 'Última lectura de PM2.5 por estación'),
    ('estaciones', 'Lista de estaciones con su número'),
    ('suscribir', 'Recibir avisos: /suscribir <número|todas> [umbral]'),
    ('cancelar', 'Dejar de recibir avisos de una estación'),
    ('mis_alertas', 'Ver tus suscripciones'),
    ('silencio', 'Horas sin avisos: /silencio 23 7 o /silencio no'),
    ('desvincular', 'Desconectar este chat de tu cuenta web'),
    ('pausa', 'Pausar todos los avisos'),
    ('reanudar', 'Reanudar los avisos'),
    ('baja', 'Borrar todos tus datos'),
    ('ayuda', 'Cómo usar el bot'),
]
AYUDA = ('Comandos:\n' + '\n'.join(f'/{c} - {d}' for c, d in COMANDOS) +
         f'\n\nEjemplo: /suscribir 2 {UMBRAL_NORMA:g}\nSi no pones umbral se usa {UMBRAL_NORMA:g} µg/m³, la referencia '
         'de 24 horas de la NOM-025-SSA1-2021. Los avisos comparan lecturas horarias: no son un índice de salud.')
BIENVENIDA = ('Hola, soy el bot de AERIS, el observatorio de PM2.5 de Querétaro.\n'
              'Te aviso cuando la lectura horaria de una estación supere el umbral que elijas.\n'
              'Solo guardo el número de este chat; con /baja se borra todo.\n\n')
SIN_DATOS = 'No pude leer las mediciones en este momento. Intenta más tarde.'
DESDE_CUENTA = ('Este chat está vinculado a tu cuenta de AERIS: tus estaciones y tu umbral se eligen en la web, '
                'en «Mi cuenta» → «Elegir estaciones». Aquí puedes usar /pausa, /silencio y /ahora.')


class TelegramError(Exception):
    def __init__(self, code, retry_after=None):
        super().__init__(f'telegram_error code={code}')
        self.code, self.retry_after = code, retry_after


class Telegram:
    def __init__(self, token, timeout=45):
        self._base, self._timeout = f'https://api.telegram.org/bot{token}/', timeout

    def __repr__(self): return 'Telegram(<token oculto>)'

    def call(self, method, **params):
        request = urllib.request.Request(self._base + method, data=json.dumps(params).encode(),
                                         headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.load(response)
        except urllib.error.HTTPError as exc:
            try: body = json.load(exc)
            except ValueError: body = {}
            raise TelegramError(exc.code, (body.get('parameters') or {}).get('retry_after')) from None
        except urllib.error.URLError as exc:
            raise OSError(f'red no disponible: {type(exc.reason).__name__}') from None
        if not body.get('ok'):
            raise TelegramError(body.get('error_code'))
        return body['result']

    def send(self, chat_id, text):
        return self.call('sendMessage', chat_id=chat_id, text=text, disable_web_page_preview=True)


def hora_local(instante): return instante.astimezone(LOCAL).strftime('%d/%m %H:%M')


def numero(valor):
    try: return float(valor.replace(',', '.'))
    except ValueError: raise ValueError('El umbral debe ser un número, por ejemplo 25') from None


def linea(e):
    nota = ' (en revisión)' if e['revision'] else ''
    vieja = f' - hace {e["edad_horas"]:.0f} h' if e['edad_horas'] >= 3 else ''
    return f'{e["numero"]}. {e["nombre"]}: {e["valor"]:.0f} µg/m³ a las {hora_local(e["fecha_utc"])}{nota}{vieja}'


class Bot:
    def __init__(self, conn, mediciones, now=lambda: datetime.now(timezone.utc), cuentas=None):
        self.conn, self.mediciones, self.now, self.cuentas = conn, mediciones, now, cuentas

    def estaciones(self): return lecturas.estaciones(self.mediciones, self.now())

    def estacion(self, arg, lista):
        if arg.lower() in ('todas', 'todos'):
            return store.TODAS, 'todas las estaciones'
        if arg.isdigit() and 1 <= int(arg) <= len(lista):
            e = lista[int(arg) - 1]
            return e['sensor_id'], e['nombre']
        raise ValueError(f'No hay estación «{arg}». Usa /estaciones para ver los números.')

    def nombres(self):
        try: return {e['sensor_id']: e['nombre'] for e in self.estaciones()}
        except (sqlite3.Error, OSError, RuntimeError, ValueError, KeyError): return {}

    def responder(self, chat_id, texto):
        partes = texto.strip().split()
        if not partes or not partes[0].startswith('/'):
            return 'Usa /ayuda para ver los comandos.'
        comando, args = partes[0][1:].split('@', 1)[0].lower(), partes[1:]
        if comando == 'start':
            nuevo = store.alta(self.conn, chat_id, store.utc_now())
            if args:
                return self.vincular(chat_id, args[0])
            return BIENVENIDA + AYUDA if nuevo or not store.es_vinculado(self.conn, chat_id) else AYUDA
        if comando == 'ayuda':
            return AYUDA
        if comando == 'baja':
            if self.cuentas is not None:
                from cuentas import store as cuentas
                cuentas.desvincular_telegram(self.cuentas, chat_id=chat_id)
            return ('Listo: borré este chat, tus suscripciones y tu historial. Con /start vuelves cuando quieras.'
                    if store.baja(self.conn, chat_id) else 'No tenía datos de este chat.')
        if comando in ('ahora', 'estaciones'):
            try: lista = self.estaciones()
            except (sqlite3.Error, OSError, RuntimeError, ValueError, KeyError): return SIN_DATOS
            if not lista: return 'No hay estaciones con datos recientes.'
            if comando == 'estaciones':
                return 'Estaciones:\n' + '\n'.join(f'{e["numero"]}. {e["nombre"]} ({e["municipio"]})' for e in lista)
            return 'PM2.5, última lectura horaria:\n' + '\n'.join(linea(e) for e in lista)
        if store.suscriptor(self.conn, chat_id) is None:
            return 'Primero envía /start.'
        if comando in ('suscribir', 'cancelar') and store.es_vinculado(self.conn, chat_id):
            return DESDE_CUENTA
        if comando == 'desvincular':
            if not store.es_vinculado(self.conn, chat_id):
                return 'Este chat no está vinculado a ninguna cuenta.'
            from cuentas import store as cuentas
            cuentas.desvincular_telegram(self.cuentas, chat_id=chat_id)
            store.liberar(self.conn, chat_id)
            return 'Listo: desconecté este chat de tu cuenta y quité esas suscripciones.'
        if comando == 'suscribir':
            if not 1 <= len(args) <= 2:
                return f'Uso: /suscribir <número|todas> [umbral]. Ejemplo: /suscribir 2 {UMBRAL_NORMA:g}'
            try: lista = self.estaciones()
            except (sqlite3.Error, OSError, RuntimeError, ValueError, KeyError): return SIN_DATOS
            sensor_id, nombre = self.estacion(args[0], lista)
            umbral = numero(args[1]) if len(args) == 2 else UMBRAL_NORMA
            store.suscribir(self.conn, chat_id, sensor_id, umbral, store.utc_now())
            return f'Listo: te aviso cuando {nombre} supere {umbral:g} µg/m³ en una lectura horaria, y cuando vuelva a bajar.'
        if comando == 'cancelar':
            if len(args) != 1: return 'Uso: /cancelar <número|todas>'
            try: lista = self.estaciones()
            except (sqlite3.Error, OSError, RuntimeError, ValueError, KeyError): return SIN_DATOS
            sensor_id, nombre = self.estacion(args[0], lista)
            return (f'Cancelada la suscripción de {nombre}.' if store.cancelar(self.conn, chat_id, sensor_id)
                    else f'No tenías suscripción de {nombre}.')
        if comando == 'mis_alertas':
            subs, quien = store.suscripciones(self.conn, chat_id), store.suscriptor(self.conn, chat_id)
            vinculado = store.es_vinculado(self.conn, chat_id)
            if not subs:
                return ('Tu cuenta no tiene estaciones elegidas. Elígelas en la web, en «Mi cuenta».' if vinculado
                        else 'No tienes suscripciones. Ejemplo: /suscribir todas')
            nombres = self.nombres()
            lineas = [f'- {"Todas las estaciones" if s["sensor_id"] is None else nombres.get(s["sensor_id"], "Estación sin datos recientes")}: '
                      f'{s["umbral"]:g} µg/m³' for s in subs]
            if quien['silencio_desde'] is not None:
                lineas.append(f'Silencio de {quien["silencio_desde"]}:00 a {quien["silencio_hasta"]}:00')
            if not quien['activo']:
                lineas.append('Avisos en pausa. Usa /reanudar.')
            if vinculado:
                lineas.append('Se administran desde tu cuenta web.')
            return 'Tus alertas:\n' + '\n'.join(lineas)
        if comando == 'silencio':
            if args == ['no']:
                store.silenciar(self.conn, chat_id)
                return 'Quité el horario de silencio.'
            if len(args) != 2 or not all(a.isdigit() for a in args):
                return 'Uso: /silencio <desde> <hasta> en horas de 0 a 23 (ej. /silencio 23 7) o /silencio no'
            store.silenciar(self.conn, chat_id, int(args[0]), int(args[1]))
            return f'No te enviaré avisos de {int(args[0])}:00 a {int(args[1])}:00 (hora del centro de México).'
        if comando == 'pausa':
            store.pausar(self.conn, chat_id)
            return 'Avisos en pausa. Usa /reanudar cuando quieras.'
        if comando == 'reanudar':
            store.pausar(self.conn, chat_id, False)
            return 'Avisos reanudados.'
        return 'No conozco ese comando. Usa /ayuda.'

    def vincular(self, chat_id, codigo):
        if self.cuentas is None:
            return 'La vinculación con cuentas no está disponible en este momento.'
        from cuentas import store as cuentas
        u = cuentas.vincular_telegram(self.cuentas, codigo, chat_id)
        if u is None:
            return 'El enlace no es válido o ya venció. Genera uno nuevo en «Mi cuenta» de AERIS.'
        vinculos.sincronizar(self.conn, self.cuentas)
        n = len(store.suscripciones(self.conn, chat_id))
        umbral = u['umbral'] if u['umbral'] is not None else vinculos.UMBRAL_REFERENCIA
        detalle = (f'Te avisaré de tus {n} estaciones con umbral de {umbral:g} µg/m³.' if n else
                   'Aún no eliges estaciones: hazlo en «Mi cuenta» → «Elegir estaciones».')
        return f'Listo: este chat quedó vinculado a la cuenta {vinculos.ocultar(u["correo"])}. {detalle}'


class Limitador:
    def __init__(self, maximo=MAX_MENSAJES_POR_MINUTO, ventana=60, reloj=time.monotonic):
        self.maximo, self.ventana, self.reloj, self.vistos = maximo, ventana, reloj, defaultdict(deque)

    def permite(self, chat_id):
        ahora, cola = self.reloj(), self.vistos[chat_id]
        while cola and ahora - cola[0] > self.ventana: cola.popleft()
        if len(cola) >= self.maximo: return False
        cola.append(ahora); return True


def procesar(bot, update, limitador):
    """Devuelve (chat_id, respuesta) o None si el mensaje se ignora."""
    message = update.get('message') or {}
    chat, texto = message.get('chat') or {}, message.get('text')
    if chat.get('type') != 'private' or not isinstance(texto, str) or not isinstance(chat.get('id'), int):
        return None
    if len(texto) > MAX_TEXTO or not limitador.permite(chat['id']):
        return None
    try:
        return chat['id'], bot.responder(chat['id'], texto)
    except ValueError as exc:
        return chat['id'], str(exc)


def log(evento): print(f'{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {evento}', flush=True)


def run(api, bot, stop=lambda: False, pausa=time.sleep, tarea=None):
    api.call('setMyCommands', commands=[{'command': c, 'description': d} for c, d in COMANDOS])
    log('bot_iniciado')
    offset, limitador, espera = None, Limitador(), 5
    while not stop():
        if tarea:
            try: tarea()
            except Exception as exc:  # una falla de alertas nunca detiene el bot
                log(f'evaluacion_fallida type={type(exc).__name__}')
        try:
            updates = api.call('getUpdates', offset=offset, timeout=30, allowed_updates=['message'])
            espera = 5
        except TelegramError as exc:
            log(f'telegram_error code={exc.code}')
            if exc.code == 401: raise
            pausa(exc.retry_after or espera); espera = min(espera * 2, 300); continue
        except OSError as exc:
            log(f'red_error {exc}'); pausa(espera); espera = min(espera * 2, 300); continue
        for update in updates:
            offset = update['update_id'] + 1
            try:
                resultado = procesar(bot, update, limitador)
            except sqlite3.Error as exc:
                log(f'db_error type={type(exc).__name__}'); resultado = None
            if resultado:
                try: api.send(*resultado)
                except (TelegramError, OSError) as exc: log(f'envio_fallido type={type(exc).__name__}')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Bot de Telegram de alertas AERIS (local)')
    parser.add_argument('--key-file', default=ROOT / '.secrets' / 'telegram_bot_token.clixml', type=Path)
    parser.add_argument('--db', default=store.DEFAULT_DB, type=Path)
    parser.add_argument('--mediciones', default=store.MEDICIONES_DB, type=Path)
    parser.add_argument('--cuentas', type=Path, help='Base de cuentas web para vincular chats (opcional)')
    args = parser.parse_args(argv)
    from data_ingestion.windows_credentials import load_key
    api = Telegram(load_key(args.key_file))
    conn = store.conectar(args.db)
    cuentas_conn = None
    if args.cuentas:
        from cuentas import store as cuentas
        cuentas_conn = cuentas.conectar(args.cuentas)
    vigilante = evaluar.Vigilante(lambda: evaluar.evaluar(conn, api, args.mediciones, log=log),
                                  lambda: evaluar.marca_sincronizacion(args.mediciones))

    def tarea():
        if cuentas_conn is not None:  # los cambios hechos en la web llegan en la siguiente vuelta
            for chat_id, texto in vinculos.sincronizar(conn, cuentas_conn):
                try: api.send(chat_id, texto)
                except (TelegramError, OSError) as exc: log(f'envio_fallido type={type(exc).__name__}')
        vigilante()

    try:
        run(api, Bot(conn, args.mediciones, cuentas=cuentas_conn), tarea=tarea)
    except KeyboardInterrupt:
        log('bot_detenido')
    finally:
        conn.close()
        if cuentas_conn is not None:
            cuentas_conn.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'bot_fallo type={type(exc).__name__}', file=sys.stderr)
        sys.exit(1)
