"""Última lectura horaria de PM2.5 por estación. Solo lectura, misma política que la web."""
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

from data_ingestion.catalog import read_catalog
from data_ingestion.visibility import connect_readonly

FUENTE = 'OpenAQ'
DIAS_ACTIVA = 7  # una estación sin datos en este plazo no se ofrece


def instante(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Fecha sin zona horaria')
    return parsed.astimezone(timezone.utc)


def estaciones(path, now=None):
    """Estaciones activas ordenadas por nombre, numeradas desde 1, con su última lectura."""
    now = now or datetime.now(timezone.utc)
    desde = (now - timedelta(days=DIAS_ACTIVA)).isoformat(timespec='seconds').replace('+00:00', 'Z')
    with closing(connect_readonly(path)) as conn:
        conn.row_factory = sqlite3.Row
        catalogo = read_catalog(conn)
        has_qc = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='calidad_mediciones'").fetchone()
        revision = 'q.requiere_revision' if has_qc else 'NULL'
        join = 'LEFT JOIN calidad_mediciones q USING(fuente,sensor_id,fecha_utc,contaminante)' if has_qc else ''
        rows = conn.execute(f'''SELECT m.sensor_id,m.fecha_utc,m.valor,m.unidad,{revision} revision
            FROM mediciones m {join} WHERE m.fuente=? AND m.contaminante='pm25'
            AND julianday(m.fecha_utc)>=julianday(?) AND julianday(m.fecha_utc)<=julianday(?)''',
            (FUENTE, desde, now.isoformat(timespec='seconds'))).fetchall()
    ultimas = {}
    for r in rows:
        valor = float(r['valor'])
        if r['sensor_id'] not in catalogo or r['unidad'] != 'µg/m³' or not math.isfinite(valor):
            continue
        cuando = instante(r['fecha_utc'])
        if r['sensor_id'] not in ultimas or cuando > ultimas[r['sensor_id']]['fecha']:
            ultimas[r['sensor_id']] = {'fecha': cuando, 'valor': valor,
                                       'revision': None if r['revision'] is None else bool(r['revision'])}
    lista = sorted(({'sensor_id': sid, 'nombre': catalogo[sid]['name'], 'municipio': catalogo[sid]['municipality'],
                     'fecha_utc': u['fecha'], 'valor': u['valor'], 'revision': u['revision'],
                     'edad_horas': (now - u['fecha']).total_seconds() / 3600} for sid, u in ultimas.items()),
                   key=lambda e: e['nombre'])
    for i, e in enumerate(lista, 1):
        e['numero'] = i
    return lista
