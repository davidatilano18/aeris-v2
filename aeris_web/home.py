"""Read-only availability overview, never a spatial air-quality estimate."""
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from data_ingestion.catalog import read_catalog
from data_ingestion.visibility import connect_readonly
from .data import SOURCES, instant, stamp


def read_home(path, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('A zoned clock is required')
    now = now.astimezone(timezone.utc)
    with closing(connect_readonly(Path(path))) as conn:
        conn.row_factory = sqlite3.Row
        catalog = read_catalog(conn)
        # The central reader applies batch visibility before this transaction.
        rows = conn.execute('''SELECT fuente, sensor_id, fecha_utc, valor, unidad
            FROM mediciones WHERE contaminante='pm25'
            AND fuente IN ('OpenAQ','OpenAQ-Archive')
            AND julianday(fecha_utc)<=julianday(?) ORDER BY julianday(fecha_utc)''',
            (stamp(now),)).fetchall()
        initial_quality = bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='calidad_mediciones'").fetchone())
    stations = {sid: {**meta, 'records': 0, 'sources': [], 'latest': None,
                     'fresh': False} for sid, meta in catalog.items()}
    groups = {}
    for row in rows:
        sid = row['sensor_id']
        if sid not in stations:
            continue
        value = float(row['valor'])
        if row['unidad'] != 'µg/m³' or not math.isfinite(value):
            raise RuntimeError('Incompatible observation')
        timestamp = stamp(instant(row['fecha_utc']))
        key = (sid, row['fuente'])
        group = groups.setdefault(key, {'source': row['fuente'], 'count': 0,
            'first': timestamp, 'latest': timestamp, 'months': set()})
        group['count'] += 1
        group['latest'] = timestamp
        group['months'].add(timestamp[:7])
        station = stations[sid]
        station['records'] += 1
        if station['latest'] is None or timestamp > station['latest']:
            station['latest'] = timestamp
        if row['fuente'] == 'OpenAQ' and 0 <= (now-instant(timestamp)).total_seconds() <= 7200:
            station['fresh'] = True
    for (sid, source), group in groups.items():
        group['months'] = sorted(group['months'])
        stations[sid]['sources'].append(group)
    stations = sorted(stations.values(), key=lambda s: (s['municipality'], s['name']))
    observed = [s for s in stations if s['records']]
    latest = max(observed, key=lambda s: s['latest']) if observed else None
    municipalities = []
    for name in sorted({s['municipality'] for s in stations}):
        subset = [s for s in stations if s['municipality'] == name]
        municipalities.append({'name': name, 'stations': subset,
            'records': sum(s['records'] for s in subset),
            'observed_stations': sum(bool(s['records']) for s in subset)})
    return {'stations': stations, 'municipalities': municipalities,
        'observed_stations': len(observed), 'catalog_stations': len(stations),
        'observed_municipalities': sum(m['observed_stations'] > 0 for m in municipalities),
        'total': sum(s['records'] for s in stations),
        'fresh_stations': sum(s['fresh'] for s in stations),
        'sources': [{'name': source, 'label': label,
            'count': sum(g['count'] for (sid, src), g in groups.items() if src == source),
            'months': sorted({month for (sid, src), g in groups.items() if src == source for month in g['months']})}
            for source, label in SOURCES.items()],
        'latest': latest, 'generated': stamp(now), 'quality_present': initial_quality,
        'marques': next((s for s in stations if s['sensor_id'] == 1352686), None)}
