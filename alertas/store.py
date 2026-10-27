"""Base SQLite de suscripciones. Solo guarda el chat de Telegram, nunca nombre ni teléfono."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / 'data' / 'aeris_alertas.db'
MEDICIONES_DB = ROOT / 'data' / 'aeris_air_quality.db'
VERSION = 1
MAX_SUSCRIPCIONES = 10
TODAS = None  # sensor_id NULL = todas las estaciones

SCHEMA = '''
CREATE TABLE suscriptores (
    chat_id INTEGER PRIMARY KEY,
    alta_utc TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1 CHECK(activo IN (0,1)),
    silencio_desde INTEGER CHECK(silencio_desde BETWEEN 0 AND 23),
    silencio_hasta INTEGER CHECK(silencio_hasta BETWEEN 0 AND 23),
    CHECK((silencio_desde IS NULL) = (silencio_hasta IS NULL)));
CREATE TABLE suscripciones (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL REFERENCES suscriptores(chat_id) ON DELETE CASCADE,
    sensor_id INTEGER,
    umbral REAL NOT NULL CHECK(umbral > 0 AND umbral < 1000),
    creada_utc TEXT NOT NULL);
CREATE UNIQUE INDEX suscripciones_unicas ON suscripciones(chat_id, IFNULL(sensor_id, -1));
CREATE TABLE alertas_enviadas (
    id INTEGER PRIMARY KEY,
    suscripcion_id INTEGER NOT NULL REFERENCES suscripciones(id) ON DELETE CASCADE,
    sensor_id INTEGER NOT NULL,
    fecha_utc TEXT NOT NULL,
    valor REAL NOT NULL,
    tipo TEXT NOT NULL CHECK(tipo IN ('supera','normaliza')),
    enviada_utc TEXT NOT NULL);
CREATE INDEX alertas_por_suscripcion ON alertas_enviadas(suscripcion_id, sensor_id, id);
'''


def utc_now(): return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def conectar(path=DEFAULT_DB):
    path = Path(path).resolve()
    if path == MEDICIONES_DB.resolve():
        raise ValueError('Las alertas no pueden escribir en la base de mediciones')
    conn = sqlite3.connect(path, timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version == 0:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                raise sqlite3.DatabaseError('La base no es de alertas AERIS')
            with conn:
                conn.executescript(SCHEMA + f'PRAGMA user_version={VERSION};')
        elif version != VERSION:
            raise sqlite3.DatabaseError(f'Versión de esquema no soportada: {version}')
        return conn
    except BaseException:
        conn.close(); raise


def alta(conn, chat_id, now=None):
    """Registra o reactiva un chat. Devuelve True si es nuevo."""
    with conn:
        cur = conn.execute('INSERT OR IGNORE INTO suscriptores(chat_id,alta_utc) VALUES (?,?)',
                           (int(chat_id), now or utc_now()))
        conn.execute('UPDATE suscriptores SET activo=1 WHERE chat_id=?', (int(chat_id),))
    return cur.rowcount == 1


def baja(conn, chat_id):
    """Borra el chat y todo lo asociado (suscripciones e historial). Devuelve True si existía."""
    with conn:
        return conn.execute('DELETE FROM suscriptores WHERE chat_id=?', (int(chat_id),)).rowcount == 1


def pausar(conn, chat_id, pausado=True):
    with conn:
        return conn.execute('UPDATE suscriptores SET activo=? WHERE chat_id=?',
                            (0 if pausado else 1, int(chat_id))).rowcount == 1


def silenciar(conn, chat_id, desde=None, hasta=None):
    """Horario local sin avisos (desde-hasta, puede cruzar medianoche). None quita el silencio."""
    if (desde is None) != (hasta is None) or any(h is not None and not 0 <= int(h) <= 23 for h in (desde, hasta)):
        raise ValueError('Usa horas de 0 a 23')
    if desde is not None and int(desde) == int(hasta):
        raise ValueError('Las horas de inicio y fin deben ser distintas')
    with conn:
        return conn.execute('UPDATE suscriptores SET silencio_desde=?,silencio_hasta=? WHERE chat_id=?',
                            (None if desde is None else int(desde), None if hasta is None else int(hasta),
                             int(chat_id))).rowcount == 1


def suscriptor(conn, chat_id):
    row = conn.execute('SELECT chat_id,activo,silencio_desde,silencio_hasta FROM suscriptores WHERE chat_id=?',
                       (int(chat_id),)).fetchone()
    return dict(row) if row else None


def suscribir(conn, chat_id, sensor_id, umbral, now=None):
    """Crea o actualiza la suscripción del chat a una estación (o TODAS). Devuelve su id."""
    umbral = float(umbral)
    if not 0 < umbral < 1000:
        raise ValueError('El umbral debe estar entre 0 y 1000 µg/m³')
    with conn:
        if not conn.execute('SELECT 1 FROM suscriptores WHERE chat_id=?', (int(chat_id),)).fetchone():
            raise ValueError('Primero envía /start')
        sid = None if sensor_id is None else int(sensor_id)
        row = conn.execute('SELECT id FROM suscripciones WHERE chat_id=? AND IFNULL(sensor_id,-1)=IFNULL(?,-1)',
                           (int(chat_id), sid)).fetchone()
        if row:
            conn.execute('UPDATE suscripciones SET umbral=? WHERE id=?', (umbral, row['id']))
            return row['id']
        total = conn.execute('SELECT COUNT(*) FROM suscripciones WHERE chat_id=?', (int(chat_id),)).fetchone()[0]
        if total >= MAX_SUSCRIPCIONES:
            raise ValueError(f'Máximo {MAX_SUSCRIPCIONES} suscripciones por chat')
        return conn.execute('''INSERT INTO suscripciones(chat_id,sensor_id,umbral,creada_utc)
            VALUES (?,?,?,?)''', (int(chat_id), sid, umbral, now or utc_now())).lastrowid


def cancelar(conn, chat_id, sensor_id):
    with conn:
        return conn.execute('DELETE FROM suscripciones WHERE chat_id=? AND IFNULL(sensor_id,-1)=IFNULL(?,-1)',
                            (int(chat_id), None if sensor_id is None else int(sensor_id))).rowcount == 1


def suscripciones(conn, chat_id):
    return [dict(r) for r in conn.execute('''SELECT id,sensor_id,umbral
        FROM suscripciones WHERE chat_id=? ORDER BY IFNULL(sensor_id,-1)''', (int(chat_id),))]


def activas(conn):
    """Suscripciones de chats activos, para evaluar alertas."""
    return [dict(r) for r in conn.execute('''SELECT s.id,s.chat_id,s.sensor_id,s.umbral,u.silencio_desde,u.silencio_hasta
        FROM suscripciones s JOIN suscriptores u USING(chat_id) WHERE u.activo=1 ORDER BY s.id''')]


def ultimo_aviso(conn, suscripcion_id, sensor_id):
    row = conn.execute('''SELECT tipo,fecha_utc,valor,enviada_utc FROM alertas_enviadas
        WHERE suscripcion_id=? AND sensor_id=? ORDER BY id DESC LIMIT 1''', (suscripcion_id, int(sensor_id))).fetchone()
    return dict(row) if row else None


def registrar_aviso(conn, suscripcion_id, sensor_id, fecha_utc, valor, tipo, now=None):
    with conn:
        conn.execute('''INSERT INTO alertas_enviadas(suscripcion_id,sensor_id,fecha_utc,valor,tipo,enviada_utc)
            VALUES (?,?,?,?,?,?)''', (suscripcion_id, int(sensor_id), fecha_utc, float(valor), tipo, now or utc_now()))
