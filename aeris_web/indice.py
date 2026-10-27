"""Índice AIRE Y SALUD diario por estación con todos los contaminantes criterio (solo lectura).

NOM-172-SEMARNAT-2023 (DOF 25/01/2024):
- Tabla 3, reporte diario: PM2.5 y PM10 = promedio de 24 h; O3, NO2 y SO2 = máximo de los promedios
  horarios del día; CO = máximo de los promedios móviles de 8 h del día (cada uno con ≥ 6 horas, 5.2.5.2).
- 5.2.5.4: el promedio de 24 h exige ≥ 18 horas. Criterio de AERIS: también se exigen ≥ 18 horas para
  los máximos diarios, porque un día incompleto puede omitir el pico.
- Tabla 2 y reglas de redondeo: partículas a enteros, O3/NO2/SO2 a 3 decimales, CO a 2, «mitad hacia arriba».
- Tablas 4 a 9: bandas vigentes desde enero de 2026.
- 5.1.2.5: para un área se informa el contaminante con mayor deterioro; aquí, por estación y día.

PM2.5 sale de la tabla `mediciones` (horas con revisión pendiente excluidas); los demás contaminantes de
la capa ambiental (fuente openaq-archivo; horas marcadas o fuera de rango excluidas). Cada estación por separado.

Revisión automática de gases y PM10 (AERIS, versión gases-v1), análoga a la de PM2.5 (>100 µg/m³ o salto
de ≥100 en una hora): una hora requiere revisión si supera el inicio de «Extremadamente mala» o si cambia
más que el tope de «Mala» respecto de la hora inmediata anterior. Solo mira hacia atrás, no interpola y no
borra nada: la hora se excluye del cálculo y se cuenta. Una marca invita a revisar; no confirma un error.
"""
import json
import math
import threading
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from data_ingestion.visibility import connect_readonly

ZONA = ZoneInfo('America/Mexico_City')
HORAS_MINIMAS = 18
BANDAS = ('Buena', 'Aceptable', 'Mala', 'Muy mala', 'Extremadamente mala')
CONTAMINANTES = {
    # id: (nombre, unidad, decimales, topes de Buena..Muy mala, método diario)
    'pm25': ('PM2.5', 'µg/m³', 0, (15, 25, 79, 130), 'promedio 24 h'),
    'pm10': ('PM10', 'µg/m³', 0, (45, 50, 132, 213), 'promedio 24 h'),
    'o3': ('Ozono (O₃)', 'ppm', 3, (0.058, 0.090, 0.135, 0.175), 'máximo horario'),
    'no2': ('Dióxido de nitrógeno (NO₂)', 'ppm', 3, (0.053, 0.106, 0.160, 0.213), 'máximo horario'),
    'so2': ('Dióxido de azufre (SO₂)', 'ppm', 3, (0.035, 0.075, 0.185, 0.304), 'máximo horario'),
    'co': ('Monóxido de carbono (CO)', 'ppm', 2, (5.00, 9.00, 12.00, 16.00), 'máximo móvil 8 h'),
}


REVISION_GASES = 'gases-v1'


def requiere_revision(contaminante, horas):
    """Instantes marcados por la revisión gases-v1 (horas: {datetime: valor})."""
    topes = CONTAMINANTES[contaminante][3]
    extremo, salto = topes[3], topes[2]
    marcadas, previo = set(), None
    for t in sorted(horas):
        v = horas[t]
        # Diferencia entre instantes reales (UTC), no entre horas de reloj.
        adyacente = previo is not None and t.astimezone(timezone.utc) - previo[0].astimezone(timezone.utc) == timedelta(hours=1)
        if v > extremo or (adyacente and abs(v - previo[1]) > salto):
            marcadas.add(t)
        previo = (t, v)
    return marcadas


def decimal(valor):
    # repr() da la forma decimal más corta del dato recibido (25.455, no 25.45499999...).
    return valor if isinstance(valor, Decimal) else Decimal(repr(valor))


def promedio(valores):
    """Promedio en aritmética decimal exacta: en binario, 484.5 / 19 sale 25.4999… y cambia la categoría."""
    valores = list(valores)
    return sum(map(decimal, valores)) / len(valores)


def redondear(valor, decimales):
    """Redondeo de la NOM-172 («mitad hacia arriba»), no el redondeo bancario de Python."""
    paso = Decimal(1).scaleb(-decimales)
    return float(decimal(valor).quantize(paso, rounding=ROUND_HALF_UP))


def banda(contaminante, valor):
    nombre, unidad, decimales, topes, metodo = CONTAMINANTES[contaminante]
    v = redondear(valor, decimales)
    for categoria, tope in zip(BANDAS, topes):
        if v <= tope:
            return categoria, v
    return BANDAS[-1], v


def concentracion_diaria(contaminante, horas):
    """horas: {datetime local de la hora: valor}. Devuelve la concentración base del día o None."""
    if len(horas) < HORAS_MINIMAS:
        return None
    metodo = CONTAMINANTES[contaminante][4]
    if metodo == 'promedio 24 h':
        return promedio(horas.values())
    if metodo == 'máximo horario':
        return max(horas.values())
    return None  # CO se calcula aparte (necesita horas del día anterior).


def maximo_movil_8h(serie, dia):
    """Máximo de los promedios móviles de 8 h que terminan en las horas del día (cada uno con ≥ 6 horas).
    Se recorre en UTC: con horario de verano (hasta 2022) el día local tiene 23 o 25 horas y la resta de
    horas sobre la hora de reloj desfasaría la ventana."""
    inicio = datetime(dia.year, dia.month, dia.day, tzinfo=ZONA).astimezone(timezone.utc)
    siguiente = dia + timedelta(days=1)
    fin = datetime(siguiente.year, siguiente.month, siguiente.day, tzinfo=ZONA).astimezone(timezone.utc)
    n = int((fin - inicio) / timedelta(hours=1))
    # Valores de las 7 horas previas al día y de las del día, cada uno convertido a decimal una sola vez.
    valores = [serie.get(inicio + timedelta(hours=k)) for k in range(-7, n)]
    valores = [None if v is None else decimal(v) for v in valores]
    promedios = []
    for h in range(n):
        ventana = [v for v in valores[h:h + 8] if v is not None]
        if len(ventana) >= 6:
            promedios.append(sum(ventana) / len(ventana))
    return max(promedios) if promedios else None


@lru_cache(maxsize=None)
def hora_local(fecha_utc):
    """Instante UTC almacenado -> hora de Querétaro. Las mismas horas se repiten en cada estación y variable."""
    return datetime.fromisoformat(fecha_utc.replace('Z', '+00:00')).astimezone(ZONA)


def revisar_series(series):
    """Copia de las series sin las horas que marca gases-v1, y cuántas se apartaron por serie.
    El PM2.5 no pasa por aquí: ya llega filtrado por su propia revisión versionada."""
    revisadas, revision = {}, defaultdict(int)
    for clave, horas in series.items():
        marcadas = requiere_revision(clave[1], horas) if clave[1] != 'pm25' else set()
        revisadas[clave] = {t: v for t, v in horas.items() if t not in marcadas}
        if marcadas:
            revision[clave] = len(marcadas)
    return revisadas, revision


def leer_horas(path, revisar=True):
    """{(estacion_id, contaminante): {datetime local: valor}}; revisar=False omite gases-v1 (sensibilidad)."""
    series = defaultdict(dict)
    nombres = {}
    with closing(connect_readonly(Path(path))) as conn:
        tablas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'amb_estaciones' not in tablas:
            return series, nombres, {}
        sensores = {}
        for eid, nombre, municipio, meta in conn.execute(
                "SELECT estacion_id,nombre,municipio,metadatos_json FROM amb_estaciones WHERE fuente_id='openaq-archivo'"):
            nombres[eid] = {'nombre': nombre, 'municipio': municipio}
            sensor = json.loads(meta).get('sensor_pm25')
            if sensor:
                sensores[sensor] = eid
        for eid, variable, fecha, valor in conn.execute(
                """SELECT o.estacion_id,o.variable_id,o.fecha_utc,o.valor FROM amb_observaciones o
                   JOIN amb_estaciones e USING(estacion_id) WHERE e.fuente_id='openaq-archivo'
                   AND o.marca_origen=0 AND o.fuera_de_rango=0"""):
            series[(eid, variable)][hora_local(fecha)] = valor
        calidad = 'calidad_mediciones' in tablas
        union = 'LEFT JOIN calidad_mediciones q USING(fuente,sensor_id,fecha_utc,contaminante)' if calidad else ''
        filtro = 'AND COALESCE(q.requiere_revision,0)=0' if calidad else ''
        marcas = ','.join('?' for _ in sensores) or 'NULL'
        for sensor, fecha, valor in conn.execute(
                f"""SELECT m.sensor_id,m.fecha_utc,m.valor FROM mediciones m {union}
                    WHERE m.fuente='OpenAQ-Archive' AND m.contaminante='pm25' AND m.sensor_id IN ({marcas}) {filtro}""",
                list(sensores)):
            if math.isfinite(valor):
                series[(sensores[sensor], 'pm25')][hora_local(fecha)] = valor
    if not revisar:
        return series, nombres, {}
    revisadas, revision = revisar_series(series)
    return revisadas, nombres, revision


def dias(path, revisar=True):
    """Un registro por estación y día con la categoría de cada contaminante y la del día."""
    series, nombres, _ = leer_horas(path, revisar)
    return calcular_dias(series, nombres)


def calcular_dias(series, nombres):
    por_dia = defaultdict(lambda: defaultdict(dict))
    for (eid, contaminante), horas in series.items():
        for t, v in horas.items():
            por_dia[(eid, t.date())][contaminante][t] = v
    salida = []
    for (eid, dia), contaminantes in sorted(por_dia.items(), key=lambda x: (x[0][0], x[0][1])):
        resultado = {}
        for c, horas in contaminantes.items():
            if c == 'co':
                base = maximo_movil_8h(series[(eid, 'co')], dia) if len(horas) >= HORAS_MINIMAS else None
            else:
                base = concentracion_diaria(c, horas)
            if base is not None:
                categoria, redondeado = banda(c, base)
                resultado[c] = {'valor': redondeado, 'categoria': categoria, 'horas': len(horas)}
        if not resultado:
            continue
        peor = max(BANDAS.index(r['categoria']) for r in resultado.values())
        salida.append({'estacion_id': eid, **nombres.get(eid, {}), 'dia': dia, 'contaminantes': resultado,
                       'categoria': BANDAS[peor],
                       'determinantes': sorted(c for c, r in resultado.items() if BANDAS.index(r['categoria']) == peor)})
    return salida


DESDE_ANIO = 2023  # 2021 solo tiene unas dos semanas por estación en el archivo; se omite del resumen.
_CACHE = {}
# Un solo cálculo a la vez: quien llega mientras se calcula (p. ej. durante el precalentado) espera el resultado.
_CANDADO = threading.Lock()


def read_indice(path):
    """Resumen para la portada; se calcula una vez por versión del archivo (el corte es de solo lectura)."""
    path = Path(path)
    estado = path.stat()
    clave = (str(path.resolve()), estado.st_size, estado.st_mtime_ns)
    with _CANDADO:
        if clave not in _CACHE:
            _CACHE.clear()
            _CACHE[clave] = _resumir(path)
        return _CACHE[clave]


def _resumir(path):
    crudas, nombres, _ = leer_horas(path, revisar=False)  # una sola lectura de la base
    series, revision = revisar_series(crudas)
    registros = [r for r in calcular_dias(series, nombres) if r['dia'].year >= DESDE_ANIO]
    if not registros:
        return None
    total = dict.fromkeys(BANDAS, 0)
    determinantes = defaultdict(int)
    estaciones, anios = {}, {}
    for r in registros:
        total[r['categoria']] += 1
        e = estaciones.setdefault(r['estacion_id'], {'nombre': r['nombre'], 'municipio': r['municipio'],
                                                     'conteo': dict.fromkeys(BANDAS, 0), 'determinantes': defaultdict(int),
                                                     'contaminantes': set(), 'primero': r['dia'], 'ultimo': r['dia']})
        e['conteo'][r['categoria']] += 1
        e['contaminantes'] |= set(r['contaminantes'])
        e['primero'], e['ultimo'] = min(e['primero'], r['dia']), max(e['ultimo'], r['dia'])
        a = anios.setdefault(r['dia'].year, dict.fromkeys(BANDAS, 0))
        a[r['categoria']] += 1
        if r['categoria'] != 'Buena':
            for c in r['determinantes']:
                determinantes[c] += 1
                e['determinantes'][c] += 1
    n = len(registros)
    no_buenos = n - total['Buena']
    # Sensibilidad (revisión de Codex, hallazgo B): la regla gases-v1 impide por construcción ver
    # «Extremadamente mala» en gases y PM10. Se publica qué cambiaría sin ella.
    con = {(r['estacion_id'], r['dia']): r['categoria'] for r in registros}
    sin = {(r['estacion_id'], r['dia']): r['categoria'] for r in calcular_dias(crudas, nombres) if r['dia'].year >= DESDE_ANIO}
    graves = ('Muy mala', 'Extremadamente mala')
    sensibilidad = {'dias_que_cambian': sum(con.get(k) != v for k, v in sin.items()),
                    'graves_con': sum(v in graves for v in con.values()),
                    'graves_sin': sum(v in graves for v in sin.values()),
                    'dias_sin': len(sin)}
    filas = []
    for eid, e in sorted(estaciones.items(), key=lambda x: x[1]['nombre']):
        dias_e = sum(e['conteo'].values())
        principal = max(e['determinantes'].items(), key=lambda x: x[1], default=(None, 0))
        filas.append({**e, 'estacion_id': eid, 'dias': dias_e,
                      'porcentajes': {b: 100 * v / dias_e for b, v in e['conteo'].items()},
                      'principal': CONTAMINANTES[principal[0]][0] if principal[0] else None,
                      'contaminantes': [CONTAMINANTES[c][0] for c in CONTAMINANTES if c in e['contaminantes']],
                      'sin': [CONTAMINANTES[c][0] for c in CONTAMINANTES if c not in e['contaminantes']]})
    return {
        'dias': n, 'estaciones': len(estaciones), 'desde': min(r['dia'] for r in registros),
        'hasta': max(r['dia'] for r in registros), 'conteo': total,
        'porcentajes': {b: 100 * v / n for b, v in total.items()},
        'determinantes': [{'id': c, 'nombre': CONTAMINANTES[c][0], 'dias': v, 'pct': 100 * v / no_buenos if no_buenos else 0}
                          for c, v in sorted(determinantes.items(), key=lambda x: -x[1])],
        'no_buenos': no_buenos, 'filas': filas,
        'anios': [{'anio': a, 'dias': sum(v.values()), 'conteo': v,
                   'porcentajes': {b: 100 * x / sum(v.values()) for b, x in v.items()}} for a, v in sorted(anios.items())],
        'horas_revision': sum(revision.values()), 'revision': REVISION_GASES, 'sensibilidad': sensibilidad,
        'horas_gases': sum(len(v) for (e, c), v in series.items() if c != 'pm25'),
    }
