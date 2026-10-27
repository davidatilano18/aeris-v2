"""¿Cómo está el aire en Querétaro? Resumen diario de PM2.5 según la normativa mexicana, solo lectura.

Reglas (NOM-172-SEMARNAT-2023, DOF 25/01/2024):
- Promedio de 24 horas: día local desde las 00:00 con al menos 18 promedios horarios (5.2.5.4).
- Bandas de PM2.5 (Tabla 5) vigentes desde enero de 2026 aplicadas a TODOS los días, para comparar
  periodos con una sola vara. El límite de «Aceptable» (25) coincide con el valor de 24 h de la
  NOM-025-SSA1-2021 desde 2026; en 2024-2025 era 33 y se informa como dato de contexto.
- Horas con revisión automática pendiente (`requiere_revision`) no entran al promedio: un día que
  queda con menos de 18 horas limpias se informa como «en revisión», nunca se rellena.
- Cada estación y fuente se resume por separado; no hay promedios estatales ni municipales.
"""
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from data_ingestion.catalog import read_catalog
from data_ingestion.visibility import connect_readonly

from .indice import promedio, redondear

ZONA = ZoneInfo('America/Mexico_City')
OMS_24H = 15.0
HORAS_MINIMAS = 18
BANDAS = ('Buena', 'Aceptable', 'Mala', 'Muy mala', 'Extremadamente mala')
FUENTES = {'OpenAQ': 'OpenAQ API', 'OpenAQ-Archive': 'OpenAQ Archive'}


LIMITES = (15, 25, 79, 130)  # Buena, Aceptable, Mala, Muy mala; Tabla 5, a partir de enero de 2026.
LIMITE_ACEPTABLE_2024_2025 = 33


def banda(valor):
    """Clasifica tras redondear a entero «mitad hacia arriba», como exige la NOM-172 para PM2.5."""
    valor = redondear(valor, 0)
    for nombre, tope in zip(BANDAS, LIMITES):
        if valor <= tope:
            return nombre
    return BANDAS[-1]


MESES = ('ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic')


def rango_meses(inicio, fin):
    """«Sep–oct 2026» o, si cruza de año, «Sep 2021 – oct 2026». Un inicio tras el día 24 cuenta desde el mes siguiente."""
    if inicio.day >= 25 and (inicio.year, inicio.month) < (fin.year, fin.month):
        inicio = inicio.replace(day=1, month=inicio.month % 12 + 1, year=inicio.year + (inicio.month == 12))
    a, b = MESES[inicio.month - 1], MESES[fin.month - 1]
    if inicio.year != fin.year:
        return f'{a.capitalize()} {inicio.year} – {b} {fin.year}'
    return f'{a.capitalize()} {fin.year}' if inicio.month == fin.month else f'{a.capitalize()}–{b} {fin.year}'


def agrupar(path, now=None):
    """Horas por (fuente, sensor, día local): limpias y totales. Base común del resumen y del CSV diario."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    with closing(connect_readonly(Path(path))) as conn:
        catalogo = read_catalog(conn)
        calidad = bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='calidad_mediciones'").fetchone())
        revision = 'COALESCE(q.requiere_revision,0)' if calidad else '0'
        union = 'LEFT JOIN calidad_mediciones q USING(fuente,sensor_id,fecha_utc,contaminante)' if calidad else ''
        filas = conn.execute(f'''SELECT m.fuente,m.sensor_id,m.fecha_utc,m.valor,{revision}
            FROM mediciones m {union} WHERE m.contaminante='pm25' AND m.fuente IN ('OpenAQ','OpenAQ-Archive')''').fetchall()
    dias = defaultdict(lambda: {'limpias': [], 'total': 0})
    horas = defaultdict(list)
    for fuente, sensor, fecha, valor, en_revision in filas:
        if sensor not in catalogo or not math.isfinite(valor):
            continue
        local = datetime.fromisoformat(fecha.replace('Z', '+00:00')).astimezone(ZONA)
        if local.astimezone(timezone.utc) > now:
            continue
        clave = (fuente, sensor, local.date())
        dias[clave]['total'] += 1
        if not en_revision:
            dias[clave]['limpias'].append(valor)
            horas[(fuente, local.hour)].append(valor)
    return catalogo, dias, horas


def registros_diarios(path, now=None):
    """Un registro por estación, fuente y día local, con el mismo criterio que el resumen."""
    catalogo, dias, _ = agrupar(path, now)
    for (fuente, sensor, dia), d in sorted(dias.items(), key=lambda x: (x[0][0], x[0][1], x[0][2])):
        n = len(d['limpias'])
        exacta = promedio(d['limpias']) if n >= HORAS_MINIMAS else None
        media = float(exacta) if exacta is not None else None
        if exacta is not None:
            estado = banda(exacta)
        elif d['total'] >= HORAS_MINIMAS:
            estado = 'En revisión'
        else:
            estado = 'Sin promedio'
        yield {'fuente': FUENTES[fuente], 'sensor_id': sensor, 'estacion': catalogo[sensor]['name'],
               'municipio': catalogo[sensor]['municipality'], 'fecha_local': dia.isoformat(),
               'horas_con_dato': d['total'], 'horas_validas': n, 'promedio_24h_ug_m3': media,
               'clasificacion_nom172': estado, 'supera_guia_oms': (exacta > OMS_24H) if exacta is not None else None}


def read_estado(path, now=None):
    catalogo, dias, horas = agrupar(path, now)
    series = {}
    picos = []
    for (fuente, sensor, dia), d in dias.items():
        s = series.setdefault((fuente, sensor), {
            'fuente': fuente, 'fuente_nombre': FUENTES[fuente], 'sensor_id': sensor,
            'nombre': catalogo[sensor]['name'], 'municipio': catalogo[sensor]['municipality'],
            'conteo': dict.fromkeys(BANDAS, 0), 'validos': 0, 'revision': 0, 'oms': 0,
            'primero': dia, 'ultimo': dia, 'ultimo_valido': None, 'medias': []})
        s['primero'], s['ultimo'] = min(s['primero'], dia), max(s['ultimo'], dia)
        if len(d['limpias']) >= HORAS_MINIMAS:
            exacta = promedio(d['limpias'])
            media = float(exacta)
            s['conteo'][banda(exacta)] += 1
            s['validos'] += 1
            s['oms'] += exacta > OMS_24H
            s['medias'].append(media)
            s['ultimo_valido'] = max(filter(None, (s['ultimo_valido'], dia)))
            picos.append({'dia': dia, 'media': media, 'banda': banda(exacta), 'nombre': s['nombre'],
                          'fuente': FUENTES[fuente], 'horas': len(d['limpias'])})
        elif d['total'] >= HORAS_MINIMAS:
            s['revision'] += 1  # Habría sido un día completo; las horas marcadas lo dejan sin promedio.

    lista = []
    for s in series.values():
        if not s['validos'] and not s['revision']:
            continue
        n = s['validos']
        s['porcentajes'] = {b: (100 * c / n if n else 0) for b, c in s['conteo'].items()}
        s['pct_buena'] = s['porcentajes']['Buena']
        s['pct_oms'] = 100 * s['oms'] / n if n else 0
        s['media'] = sum(s['medias']) / n if n else None
        s.pop('medias')
        lista.append(s)
    # API: cada serie con su propio rango (las horas antiguas de una estación no se unen a las actuales).
    # Archivo: un grupo con el rango de toda la fuente; cada fila conserva sus propias fechas.
    for s in lista:
        s['periodo'] = f"{rango_meses(s['primero'], s['ultimo_valido'] or s['ultimo'])} · {s['fuente_nombre']}"
    archivo = [s for s in lista if s['fuente'] == 'OpenAQ-Archive']
    if archivo:
        rango = rango_meses(min(s['primero'] for s in archivo), max(s['ultimo_valido'] or s['ultimo'] for s in archivo))
        for s in archivo:
            s['periodo'] = f"{rango} · {s['fuente_nombre']}"
    # Primero el periodo más reciente; dentro, por municipio y nombre.
    lista.sort(key=lambda s: (-s['ultimo'].toordinal(), s['municipio'], s['nombre']))

    reciente = max((s['ultimo'] for s in lista), default=None)
    actuales = [s for s in lista if reciente and (reciente - s['ultimo']).days <= 7 and s['fuente'] == 'OpenAQ']
    total = sum(s['validos'] for s in actuales)
    resumen = None
    if total:
        conteo = {b: sum(s['conteo'][b] for s in actuales) for b in BANDAS}
        resumen = {'dias': total, 'estaciones': len(actuales),
                   'desde': min(s['primero'] for s in actuales),
                   'hasta': max(s['ultimo_valido'] for s in actuales if s['ultimo_valido']),
                   'pct_buena': 100 * conteo['Buena'] / total,
                   'pct_buena_aceptable': 100 * (conteo['Buena'] + conteo['Aceptable']) / total,
                   'malos': conteo['Mala'] + conteo['Muy mala'] + conteo['Extremadamente mala'],
                   'pct_oms': 100 * sum(s['oms'] for s in actuales) / total,
                   'revision': sum(s['revision'] for s in actuales)}

    # Antes del periodo actual (otra fuente y otras temporadas): contexto, no tendencia.
    corte = resumen['desde'] if resumen else None
    previos = [(sensor, dia, promedio(d['limpias'])) for (fuente, sensor, dia), d in dias.items()
               if fuente == 'OpenAQ-Archive' and len(d['limpias']) >= HORAS_MINIMAS and (corte is None or dia < corte)]
    anterior = None
    if previos:
        n = len(previos)
        bandas = [banda(m) for _, _, m in previos]
        anterior = {'periodo': f"{rango_meses(min(d for _, d, _ in previos), max(d for _, d, _ in previos))} · OpenAQ Archive",
                    'estaciones': len({s for s, _, _ in previos}), 'dias': n,
                    'pct_buena': 100 * bandas.count('Buena') / n,
                    'malos': sum(b in BANDAS[2:] for b in bandas),
                    'pct_oms': 100 * sum(m > OMS_24H for _, _, m in previos) / n}

    perfiles = {}
    for fuente in FUENTES:
        puntos = [(h, horas[(fuente, h)]) for h in range(24)]
        if all(len(v) >= 20 for _, v in puntos):
            medias = [sum(v) / len(v) for _, v in puntos]
            manana = max(range(5, 12), key=lambda h: medias[h])
            tarde = max(range(16, 24), key=lambda h: medias[h])
            minimo = min(range(24), key=lambda h: medias[h])
            dias_fuente = [dia for (f, _, dia) in dias if f == fuente]
            perfiles[fuente] = {'nombre': FUENTES[fuente], 'medias': [round(m, 2) for m in medias],
                                'etiqueta': f"{rango_meses(min(dias_fuente), max(dias_fuente))} ({FUENTES[fuente]})",
                                'n': [len(v) for _, v in puntos], 'manana': manana, 'tarde': tarde,
                                'minimo': minimo, 'razon': medias[max(manana, tarde, key=lambda h: medias[h])] / medias[minimo]
                                if medias[minimo] else None}
    # Día completo más reciente de UNA estación (la API más reciente); sirve de dato para la portada.
    recientes = [p for p in picos if p['fuente'] == FUENTES['OpenAQ']]
    dia_reciente = None
    if recientes:
        ultimo_dia = max(p['dia'] for p in recientes)
        # Desempate neutral (orden alfabético), sin elegir el valor más alto ni el más bajo.
        dia_reciente = min((p for p in recientes if p['dia'] == ultimo_dia), key=lambda p: p['nombre'])
    picos.sort(key=lambda p: -p['media'])
    revisiones = sum(s['revision'] for s in lista)
    return {'resumen': resumen, 'anterior': anterior, 'dia_reciente': dia_reciente, 'series': lista, 'perfiles': perfiles, 'picos': picos[:3],
            'revisiones': revisiones, 'oms': OMS_24H, 'bandas': BANDAS, 'limites': LIMITES,
            'limite_aceptable_2024_2025': LIMITE_ACEPTABLE_2024_2025}
