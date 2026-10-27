"""Aprende: cómo se califica la calidad del aire, explicado con días reales de la base (solo lectura)."""
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, abort, current_app, render_template

from data_ingestion.visibility import connect_readonly

from .estado import BANDAS, HORAS_MINIMAS, OMS_24H, ZONA, banda, read_estado, registros_diarios
from .indice import CONTAMINANTES, redondear

blueprint = Blueprint('aprende', __name__)
FUENTE_INTERNA = {'OpenAQ API': 'OpenAQ', 'OpenAQ Archive': 'OpenAQ-Archive'}

# Educational copy only; numerical definitions always come from indice.CONTAMINANTES.
EXPLICACIONES = {
    'pm25': 'Partículas de hasta 2.5 micrómetros. Se miden por su masa en un volumen de aire.',
    'pm10': 'Partículas de hasta 10 micrómetros, que incluyen la fracción PM2.5. No son dos grupos independientes.',
    'o3': 'Ozono cerca del suelo: un gas que se forma mediante reacciones en la atmósfera. No es la capa de ozono de gran altura.',
    'no2': 'Dióxido de nitrógeno: un gas relacionado con procesos de combustión. Una concentración no identifica por sí sola su emisor.',
    'so2': 'Dióxido de azufre: un gas asociado a fuentes que contienen azufre. Medirlo no basta para atribuirlo a una instalación concreta.',
    'co': 'Monóxido de carbono: un gas que puede generarse por combustión incompleta. No es dióxido de carbono (CO₂).',
}
CLASES = ('b-buena', 'b-aceptable', 'b-mala', 'b-muymala', 'b-extrema')
RIESGOS = ('Bajo', 'Moderado', 'Alto', 'Muy alto', 'Extremadamente alto')


def configuracion_simulador():
    """Presentation contract, without querying or modifying any measurement."""
    salida = {}
    for clave, (nombre, unidad, decimales, topes, metodo) in CONTAMINANTES.items():
        fmt = lambda valor: f'{valor:.{decimales}f}'
        bandas = []
        for i, categoria in enumerate(BANDAS):
            limite = topes[i] if i < len(topes) else None
            intervalo = (f'≤ {fmt(limite)}' if i == 0 else
                         f'> {fmt(topes[i-1])}' + (f' a {fmt(limite)}' if limite is not None else ''))
            bandas.append({'nombre': categoria, 'tope': limite, 'intervalo': intervalo,
                           'clase': CLASES[i], 'riesgo': RIESGOS[i]})
        salida[clave] = {'nombre': nombre, 'unidad': unidad, 'decimales': decimales,
                         'metodo': metodo, 'explicacion': EXPLICACIONES[clave], 'bandas': bandas,
                         'tabla': {'pm10': 4, 'pm25': 5, 'o3': 6, 'no2': 7, 'so2': 8, 'co': 9}[clave],
                         'maximo': redondear(topes[-1] * 1.2, decimales),
                         'paso': 0.5 * 10 ** -decimales}
    return salida


def horas_del_dia(path, fuente, sensor, dia):
    """Las 24 horas locales de un día con su valor y su marca de revisión (None si no hubo medición)."""
    inicio = datetime(dia.year, dia.month, dia.day, tzinfo=ZONA).astimezone(timezone.utc)
    fin = inicio + timedelta(days=1)
    with closing(connect_readonly(path)) as conn:
        calidad = bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='calidad_mediciones'").fetchone())
        rev = 'COALESCE(q.requiere_revision,0)' if calidad else '0'
        union = 'LEFT JOIN calidad_mediciones q USING(fuente,sensor_id,fecha_utc,contaminante)' if calidad else ''
        filas = conn.execute(f'''SELECT m.fecha_utc,m.valor,{rev} FROM mediciones m {union}
            WHERE m.fuente=? AND m.sensor_id=? AND m.contaminante='pm25'
            AND julianday(m.fecha_utc)>=julianday(?) AND julianday(m.fecha_utc)<julianday(?)''',
            (fuente, sensor, inicio.isoformat().replace('+00:00', 'Z'), fin.isoformat().replace('+00:00', 'Z'))).fetchall()
    horas = [{'hora': h, 'valor': None, 'revision': False} for h in range(24)]
    for fecha, valor, marca in filas:
        h = datetime.fromisoformat(fecha.replace('Z', '+00:00')).astimezone(ZONA).hour
        horas[h] = {'hora': h, 'valor': valor, 'revision': bool(marca)}
    return horas


def ejemplo(path, registro, titulo, leccion):
    dia = datetime.fromisoformat(registro['fecha_local']).date()
    horas = horas_del_dia(path, FUENTE_INTERNA[registro['fuente']], registro['sensor_id'], dia)
    validas = [h['valor'] for h in horas if h['valor'] is not None and not h['revision']]
    media = sum(validas) / len(validas) if len(validas) >= HORAS_MINIMAS else None
    return {'titulo': titulo, 'leccion': leccion, 'estacion': registro['estacion'], 'municipio': registro['municipio'],
            'fuente': registro['fuente'], 'dia': dia.isoformat(), 'horas': horas,
            'con_dato': sum(h['valor'] is not None for h in horas), 'marcadas': sum(h['revision'] for h in horas),
            'validas': len(validas), 'media': media, 'banda': banda(media) if media is not None else None,
            'clasificacion': registro['clasificacion_nom172']}


@blueprint.get('/inicio/aprende')
def pagina():
    path = Path(current_app.extensions['aeris_v2_database']()).resolve()
    if not path.is_file():
        abort(503)
    ejemplos = []
    try:
        registros = [r for r in registros_diarios(path) if r['fuente'] == 'OpenAQ API']
        estado = read_estado(path)
        normal = None
        if estado and estado.get('dia_reciente'):
            dr = estado['dia_reciente']
            normal = next((r for r in registros if r['estacion'] == dr['nombre'] and r['fecha_local'] == dr['dia'].isoformat()), None)
        revision = max((r for r in registros if r['clasificacion_nom172'] == 'En revisión'), key=lambda r: r['fecha_local'], default=None)
        incompleto = max((r for r in registros if r['clasificacion_nom172'] == 'Sin promedio' and r['horas_con_dato'] >= 6),
                         key=lambda r: r['fecha_local'], default=None)
        for registro, titulo, leccion in (
                (normal, 'Un día con datos suficientes', 'Hay al menos 18 horas sin revisión pendiente: se promedian y se busca la banda. Esto no certifica la precisión del sensor.'),
                (revision, 'Un día en revisión', 'Hay horas marcadas por las reglas automáticas. Sin ellas no se alcanzan 18 horas: el día no se califica. No es una falla de sensor confirmada.'),
                (incompleto, 'Un día incompleto', 'Hubo menos de 18 horas con medición. Un promedio así no representaría el día, y no se calcula.')):
            if registro:
                ejemplos.append(ejemplo(path, registro, titulo, leccion))
    except (sqlite3.Error, RuntimeError, KeyError, ValueError):
        ejemplos = []  # La explicación funciona aunque no haya ejemplos reales disponibles.
    return render_template('v2/aprende.html', ejemplos=ejemplos, simulador=configuracion_simulador(),
                           oms=OMS_24H, horas_minimas=HORAS_MINIMAS)
