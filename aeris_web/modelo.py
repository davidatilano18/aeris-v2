"""PM2.5 estimado por el modelo CAMS para El Marqués, con su validación contra la red (solo lectura).

El Marqués no tiene medición de PM2.5 desde 2021. El modelo se muestra como estimación, nunca como
medición, y siempre junto a cuánto se equivoca donde sí se puede comparar: para cada estación con PM2.5,
días con ≥ 18 horas en la medición (horas en revisión excluidas) y ≥ 18 horas en el modelo, en el
mismo punto. No se corrige el sesgo ni se mezcla el modelo con observaciones.

La rejilla CAMS es gruesa: puntos distintos pueden caer en la misma celda y recibir exactamente la misma
serie. Las estaciones con serie idéntica a la de El Marqués se detectan comparando los datos, no por
coordenadas, y su validación se informa aparte: es el error del modelo en esa misma celda.
"""
import math
import threading
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from data_ingestion.visibility import connect_readonly

from .indice import HORAS_MINIMAS, banda, hora_local, leer_horas, promedio

CERCANA = 'openaq:480392'  # Epigmenio González, la estación con PM2.5 más cercana (≈ 8 km).
_CACHE = {}
# Un solo cálculo a la vez: quien llega mientras se calcula (p. ej. durante el precalentado) espera el resultado.
_CANDADO = threading.Lock()


def diarios_modelo(conn):
    """{estacion_id: {día local: [valores]}} del PM2.5 de CAMS."""
    dias = defaultdict(lambda: defaultdict(list))
    for eid, fecha, valor in conn.execute(
            """SELECT o.estacion_id,o.fecha_utc,o.valor FROM amb_observaciones o JOIN amb_estaciones e USING(estacion_id)
               WHERE e.fuente_id='open-meteo-cams' AND o.variable_id='pm25' AND o.fuera_de_rango=0"""):
        dias[eid][hora_local(fecha).date()].append(valor)
    return dias


def correlacion(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else None


def validar(pares):
    """pares: [(medido, modelo)] de promedios diarios (exactos; se clasifican antes de pasar a float)."""
    medido, modelo = [float(p[0]) for p in pares], [float(p[1]) for p in pares]
    categorias = [(banda('pm25', m)[0], banda('pm25', c)[0]) for m, c in pares]
    no_buenos = [c for c in categorias if c[0] != 'Buena']
    return {'dias': len(pares), 'medido': sum(medido) / len(pares), 'modelo': sum(modelo) / len(pares),
            'sesgo': (sum(modelo) - sum(medido)) / len(pares), 'r': correlacion(medido, modelo),
            'misma_categoria': 100 * sum(a == b for a, b in categorias) / len(pares),
            'no_buenos': len(no_buenos),
            'no_buenos_detectados': 100 * sum(b != 'Buena' for _, b in no_buenos) / len(no_buenos) if no_buenos else None}


def mensual(dias):
    meses = defaultdict(list)
    for d, v in dias.items():
        meses[(d.year, d.month)].append(float(v))
    return {f'{a}-{m:02d}': sum(v) / len(v) for (a, m), v in sorted(meses.items()) if len(v) >= 15}


def lista(nombres):
    return ' y '.join([', '.join(nombres[:-1]), nombres[-1]]) if len(nombres) > 1 else ''.join(nombres)


def read_modelo(path):
    path = Path(path)
    estado = path.stat()
    clave = (str(path.resolve()), estado.st_size, estado.st_mtime_ns)
    with _CANDADO:
        if clave not in _CACHE:
            _CACHE.clear()
            _CACHE[clave] = _resumir(path)
        return _CACHE[clave]


def _resumir(path):
    with closing(connect_readonly(path)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='amb_estaciones'").fetchone():
            return None
        nombres = dict(conn.execute("SELECT estacion_id,nombre FROM amb_estaciones WHERE fuente_id='openaq-archivo'"))
        modelo = diarios_modelo(conn)
    if not modelo.get('cams:marques'):
        return None
    modelo = {e: {d: promedio(v) for d, v in dias.items() if len(v) >= HORAS_MINIMAS} for e, dias in modelo.items()}
    series, _, _ = leer_horas(path)
    medidos = defaultdict(lambda: defaultdict(list))
    for (eid, c), horas in series.items():
        if c == 'pm25':
            for t, v in horas.items():
                medidos[eid][t.date()].append(v)
    medidos = {e: {d: promedio(v) for d, v in dias.items() if len(v) >= HORAS_MINIMAS} for e, dias in medidos.items()}
    marques = modelo['cams:marques']
    pares_todos, pares_celda, estaciones = [], [], []
    for eid, dias in sorted(medidos.items()):
        propio = modelo.get('cams:' + eid.split(':')[1], {})
        pares = [(dias[d], propio[d]) for d in sorted(dias) if d in propio]
        if len(pares) >= 30:
            misma = propio == marques
            pares_todos += pares
            pares_celda += pares if misma else []
            estaciones.append({'nombre': nombres.get(eid, eid), 'misma_celda': misma, **validar(pares)})
    if not pares_todos:
        return None
    sobre_guia = sum(v > 15 for v in marques.values())
    return {
        'desde': min(marques), 'hasta': max(marques), 'dias': len(marques),
        'media': float(promedio(marques.values())), 'sobre_guia': sobre_guia,
        'validacion': validar(pares_todos), 'estaciones': estaciones,
        'celda': [e['nombre'] for e in estaciones if e['misma_celda']],
        'celda_texto': lista([e['nombre'] for e in estaciones if e['misma_celda']]),
        'validacion_celda': validar(pares_celda) if pares_celda else None,
        'cercana': nombres.get(CERCANA, CERCANA),
        'serie': {'modelo': mensual(marques), 'medido_cercana': mensual(medidos.get(CERCANA, {}))},
    }
