"""API de solo lectura de la capa ambiental (/api/ambiental/v1). Nunca combina estaciones ni fuentes.

Cada serie pertenece a una estación de una fuente; el tipo de producto (observación o reanálisis)
acompaña siempre a los valores. resolucion=hora es una selección documentada, no un promedio.
"""
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify, request

from data_ingestion.visibility import connect_readonly

blueprint = Blueprint('ambiental_v1', __name__, url_prefix='/api/ambiental/v1')
MAX_FILAS = 20000
MAX_VARIABLES = 6
MAX_DIAS = 400
ZONA = ZoneInfo('America/Mexico_City')
# GHCNh etiqueta como FM-16 la mayoría de los METAR rutinarios de MMQT desde abril de 2026,
# por lo que el tipo de reporte no permite distinguir el rutinario; se usa el último de la hora.
METODO_HORA = ('Para reportes instantáneos (METAR) se toma, dentro de cada hora UTC, el último reporte '
               'publicado (FM-15 o FM-16), conservando su instante real en fecha_observacion_utc. '
               'Si la hora no tiene reportes queda vacía: no hay promedios ni interpolación. '
               'Los productos PT1H se devuelven sin cambios.')


class Solicitud(ValueError):
    pass


def ahora():
    return datetime.now(timezone.utc)


def iso(fecha):
    return fecha.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def fecha_param(nombre, defecto):
    valor = request.args.get(nombre)
    if valor is None:
        return defecto
    try:
        fecha = datetime.fromisoformat(valor.replace('Z', '+00:00'))
    except ValueError:
        raise Solicitud(f'{nombre} no es una fecha ISO 8601') from None
    if fecha.tzinfo is None:
        raise Solicitud(f'{nombre} requiere zona horaria explícita (p. ej. Z)')
    return fecha.astimezone(timezone.utc)


def permitir(*nombres):
    extra = set(request.args) - set(nombres)
    if extra:
        raise Solicitud('Parámetro no válido: ' + ', '.join(sorted(extra)))


def conexion():
    path = Path(current_app.extensions['aeris_ambiental_database']()).resolve()
    if not path.is_file():
        raise FileNotFoundError('Base ambiental no disponible')
    conn = connect_readonly(path)
    conn.row_factory = sqlite3.Row
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='amb_observaciones'").fetchone():
        conn.close()
        raise LookupError('Capa ambiental no migrada en esta base')
    return conn


def responder(funcion):
    try:
        with closing(conexion()) as conn:
            resultado = funcion(conn)
        respuesta = jsonify({'generado_utc': iso(ahora()), **resultado})
        respuesta.headers['Cache-Control'] = 'no-store'
        return respuesta
    except Solicitud as exc:
        return jsonify(error=str(exc)), 400
    except KeyError as exc:
        return jsonify(error=f'No encontrado: {exc.args[0]}'), 404
    except OverflowError as exc:
        return jsonify(error=str(exc)), 413
    except (LookupError, FileNotFoundError):
        return jsonify(error='Capa ambiental no disponible en esta base.'), 503
    except sqlite3.Error:
        return jsonify(error='No se pudieron leer datos ambientales compatibles.'), 503


def estacion(conn, estacion_id):
    fila = conn.execute('''SELECT e.*,f.tipo_producto,f.nombre fuente_nombre,f.licencia,f.atribucion
        FROM amb_estaciones e JOIN amb_fuentes f USING(fuente_id) WHERE estacion_id=?''', (estacion_id,)).fetchone()
    if fila is None:
        raise KeyError(estacion_id)
    return fila


def estacion_json(fila):
    return {'estacion_id': fila['estacion_id'], 'fuente_id': fila['fuente_id'], 'nombre': fila['nombre'],
            'municipio': fila['municipio'], 'municipio_nota': fila['municipio_nota'],
            'latitud': fila['latitud'], 'longitud': fila['longitud'], 'elevacion_m': fila['elevacion_m'],
            'tipo_sitio': fila['tipo_sitio'], 'resolucion_espacial': fila['resolucion_espacial'],
            'tipo_producto': fila['tipo_producto']}


@blueprint.get('/fuentes')
def fuentes():
    def leer(conn):
        permitir()
        filas = conn.execute('''SELECT f.*,(SELECT COUNT(*) FROM amb_estaciones e WHERE e.fuente_id=f.fuente_id) n,
            (SELECT estado FROM amb_ingestas i WHERE i.fuente_id=f.fuente_id AND fin_utc IS NOT NULL ORDER BY fin_utc DESC LIMIT 1) ultimo_estado,
            (SELECT fin_utc FROM amb_ingestas i WHERE i.fuente_id=f.fuente_id AND fin_utc IS NOT NULL ORDER BY fin_utc DESC LIMIT 1) ultimo_fin
            FROM amb_fuentes f ORDER BY fuente_id''').fetchall()
        return {'fuentes': [{'fuente_id': f['fuente_id'], 'nombre': f['nombre'], 'organizacion': f['organizacion'],
                             'tipo_producto': f['tipo_producto'], 'url': f['url'], 'licencia': f['licencia'],
                             'atribucion': f['atribucion'], 'autorizada': bool(f['autorizada']),
                             'estaciones': f['n'], 'notas': f['notas'],
                             'ultima_ingesta': {'estado': f['ultimo_estado'], 'fin_utc': f['ultimo_fin']}}
                            for f in filas]}
    return responder(leer)


@blueprint.get('/variables')
def variables():
    def leer(conn):
        permitir()
        return {'variables': [dict(r) for r in conn.execute('SELECT * FROM amb_variables ORDER BY dominio,variable_id')]}
    return responder(leer)


@blueprint.get('/estaciones')
def estaciones():
    def leer(conn):
        permitir('fuente', 'municipio')
        condiciones, valores = [], []
        for parametro, columna in (('fuente', 'e.fuente_id'), ('municipio', 'e.municipio')):
            if request.args.get(parametro):
                condiciones.append(columna + '=?')
                valores.append(request.args[parametro])
        donde = ' WHERE ' + ' AND '.join(condiciones) if condiciones else ''
        filas = conn.execute('''SELECT e.*,f.tipo_producto FROM amb_estaciones e JOIN amb_fuentes f USING(fuente_id)'''
                             + donde + ' ORDER BY e.estacion_id', valores).fetchall()
        resumen = {}
        for r in conn.execute('''SELECT estacion_id,variable_id,COUNT(*) n,MIN(fecha_utc) primera,MAX(fecha_utc) ultima
                                 FROM amb_observaciones GROUP BY estacion_id,variable_id'''):
            resumen.setdefault(r['estacion_id'], []).append(
                {'variable_id': r['variable_id'], 'observaciones': r['n'],
                 'primera_utc': r['primera'], 'ultima_utc': r['ultima']})
        return {'estaciones': [{**estacion_json(f), 'variables': resumen.get(f['estacion_id'], [])} for f in filas]}
    return responder(leer)


def lista_variables(conn):
    texto = request.args.get('variable', '')
    pedidas = [v for v in texto.split(',') if v]
    if not pedidas:
        raise Solicitud('Indique variable=<id>[,<id>...]')
    if len(pedidas) > MAX_VARIABLES or len(set(pedidas)) != len(pedidas):
        raise Solicitud(f'Entre 1 y {MAX_VARIABLES} variables distintas')
    catalogo = {r['variable_id']: dict(r) for r in conn.execute('SELECT * FROM amb_variables')}
    desconocidas = [v for v in pedidas if v not in catalogo]
    if desconocidas:
        raise Solicitud('Variable desconocida: ' + ', '.join(desconocidas))
    return [catalogo[v] for v in pedidas]


def ventana_param():
    hasta = fecha_param('hasta', ahora())
    desde = fecha_param('desde', hasta - timedelta(days=7))
    if desde >= hasta:
        raise Solicitud('desde debe ser anterior a hasta')
    if hasta - desde > timedelta(days=MAX_DIAS):
        raise Solicitud(f'La ventana máxima es de {MAX_DIAS} días')
    return desde, hasta


@blueprint.get('/observaciones')
def observaciones():
    def leer(conn):
        permitir('estacion', 'variable', 'desde', 'hasta', 'resolucion', 'incluir_marcadas')
        if not request.args.get('estacion'):
            raise Solicitud('Indique estacion=<estacion_id>; las series nunca se combinan entre estaciones')
        sitio = estacion(conn, request.args['estacion'])
        variables_pedidas = lista_variables(conn)
        desde, hasta = ventana_param()
        resolucion = request.args.get('resolucion', 'original')
        if resolucion not in ('original', 'hora'):
            raise Solicitud('resolucion debe ser original u hora')
        marcadas = request.args.get('incluir_marcadas', '1')
        if marcadas not in ('0', '1'):
            raise Solicitud('incluir_marcadas debe ser 0 o 1')
        series = {}
        total = 0
        for v in variables_pedidas:
            filtro = '' if marcadas == '1' else ' AND o.marca_origen=0 AND o.fuera_de_rango=0'
            filas = conn.execute('''SELECT o.id,o.fecha_utc,o.fecha_local,o.valor,o.periodo,o.tipo_reporte,o.calidad_origen,
                o.marca_origen,o.fuera_de_rango,EXISTS(SELECT 1 FROM amb_revisiones r WHERE r.observacion_id=o.id) revisada
                FROM amb_observaciones o WHERE o.estacion_id=? AND o.variable_id=? AND o.fecha_utc>=? AND o.fecha_utc<?'''
                + filtro + ' ORDER BY o.fecha_utc,o.tipo_reporte LIMIT ?',
                (sitio['estacion_id'], v['variable_id'], iso(desde), iso(hasta), MAX_FILAS + 1)).fetchall()
            if len(filas) > MAX_FILAS:
                raise OverflowError('Demasiadas observaciones; reduzca la ventana o use resolucion=hora')
            puntos = [{'fecha_utc': f['fecha_utc'], 'fecha_local': f['fecha_local'], 'valor': f['valor'],
                       'periodo': f['periodo'], 'tipo_reporte': f['tipo_reporte'],
                       'calidad_origen': f['calidad_origen'], 'marca_origen': bool(f['marca_origen']),
                       'fuera_de_rango': bool(f['fuera_de_rango']), 'revisada': bool(f['revisada'])} for f in filas]
            if resolucion == 'hora':
                puntos = por_hora(puntos)
            total += len(puntos)
            if total > MAX_FILAS:
                raise OverflowError('Demasiadas observaciones; reduzca la ventana o el número de variables')
            series[v['variable_id']] = {'unidad': v['unidad'], 'nombre': v['nombre'], 'puntos': puntos}
        return {'estacion': estacion_json(sitio),
                'fuente': {'fuente_id': sitio['fuente_id'], 'nombre': sitio['fuente_nombre'],
                           'licencia': sitio['licencia'], 'atribucion': sitio['atribucion']},
                'ventana': {'desde_utc': iso(desde), 'hasta_utc': iso(hasta)}, 'resolucion': resolucion,
                'metodo': METODO_HORA if resolucion == 'hora' else 'Valores tal como los publica la fuente.',
                'series': series}
    return responder(leer)


def por_hora(puntos):
    """Último reporte de cada hora UTC para instantáneos; productos PT1H intactos."""
    elegidos = {}
    for p in puntos:
        hora = p['fecha_utc'][:13] + ':00:00Z'
        if p['periodo'] != 'instantaneo' or hora not in elegidos or p['fecha_utc'] > elegidos[hora]['fecha_observacion_utc']:
            local = datetime.fromisoformat(hora.replace('Z', '+00:00')).astimezone(ZONA).isoformat(timespec='seconds')
            elegidos[hora] = {**p, 'fecha_utc': hora, 'fecha_local': local, 'fecha_observacion_utc': p['fecha_utc'],
                              'fecha_observacion_local': p.get('fecha_local')}
    return [elegidos[h] for h in sorted(elegidos)]


@blueprint.get('/cobertura')
def cobertura():
    def leer(conn):
        permitir('estacion', 'variable', 'desde', 'hasta')
        if not request.args.get('estacion'):
            raise Solicitud('Indique estacion=<estacion_id>')
        sitio = estacion(conn, request.args['estacion'])
        desde, hasta = ventana_param()
        resultado = []
        for v in lista_variables(conn):
            horas = [r[0] for r in conn.execute('''SELECT DISTINCT substr(fecha_utc,1,13) FROM amb_observaciones
                WHERE estacion_id=? AND variable_id=? AND fecha_utc>=? AND fecha_utc<? ORDER BY 1''',
                (sitio['estacion_id'], v['variable_id'], iso(desde), iso(hasta)))]
            inicio = desde.replace(minute=0, second=0, microsecond=0)
            if inicio < desde:
                inicio += timedelta(hours=1)
            esperadas = int((hasta - inicio).total_seconds() // 3600)
            huecos, previa = [], inicio - timedelta(hours=1)
            for h in [datetime.fromisoformat(x + ':00:00+00:00') for x in horas] + [hasta.replace(minute=0, second=0, microsecond=0)]:
                faltan = int((h - previa).total_seconds() // 3600) - 1
                if faltan >= 3:
                    huecos.append({'desde_utc': iso(previa + timedelta(hours=1)), 'hasta_utc': iso(h), 'horas': faltan})
                previa = h
            ultima = conn.execute('SELECT MAX(fecha_utc) FROM amb_observaciones WHERE estacion_id=? AND variable_id=?',
                                  (sitio['estacion_id'], v['variable_id'])).fetchone()[0]
            resultado.append({
                'variable_id': v['variable_id'], 'horas_esperadas': esperadas, 'horas_con_dato': len(horas),
                'porcentaje': round(100 * len(horas) / esperadas, 2) if esperadas else None,
                'huecos_3h_o_mas': huecos[:100], 'huecos_total': len(huecos), 'ultima_utc': ultima,
                'latencia_horas': round((ahora() - datetime.fromisoformat(ultima.replace('Z', '+00:00'))).total_seconds() / 3600, 1)
                if ultima else None})
        return {'estacion': estacion_json(sitio), 'ventana': {'desde_utc': iso(desde), 'hasta_utc': iso(hasta)},
                'definicion': 'Hora con dato = al menos una observación de cualquier tipo de reporte en esa hora UTC. '
                              'No mide disponibilidad del instrumento ni calidad.',
                'variables': resultado}
    return responder(leer)


@blueprint.get('/ingestas')
def ingestas():
    def leer(conn):
        permitir('fuente', 'limite')
        limite = request.args.get('limite', '20')
        if not limite.isdigit() or not 1 <= int(limite) <= 200:
            raise Solicitud('limite debe estar entre 1 y 200')
        condicion, valores = ('WHERE fuente_id=?', [request.args['fuente']]) if request.args.get('fuente') else ('', [])
        filas = conn.execute(f'''SELECT ingesta_id,fuente_id,inicio_utc,fin_utc,estado,ventana_desde_utc,ventana_hasta_utc,
            leidas,insertadas,duplicadas,revisiones,descartadas,error_tipo FROM amb_ingestas {condicion}
            ORDER BY inicio_utc DESC LIMIT ?''', (*valores, int(limite))).fetchall()
        return {'ingestas': [dict(f) for f in filas]}
    return responder(leer)


def register_ambiental(app, database_getter):
    app.extensions['aeris_ambiental_database'] = database_getter
    app.register_blueprint(blueprint)
