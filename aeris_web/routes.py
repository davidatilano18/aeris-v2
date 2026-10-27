import sqlite3
from flask import Blueprint,current_app,jsonify,make_response,render_template,request,send_from_directory
from .data import read_dashboard,TooManyRows
from .public_data import explain
from .comparisons import read_comparison

blueprint=Blueprint('dashboard_v2',__name__)


@blueprint.get('/favicon.ico')
def favicon():
    return send_from_directory(current_app.static_folder, 'logo.png', mimetype='image/png', max_age=86400)


# AERIS 3.0: la experiencia inmersiva se elige en el servidor (sin destellos) y se recuerda.
EXPERIENCIAS = ('clasica', 'inmersiva')
EXPERIENCIA_PREDETERMINADA = 'inmersiva'
GALLETA_EXPERIENCIA = 'aeris_experiencia'


def experiencia_elegida():
    pedida = request.args.get('experiencia')
    if pedida in EXPERIENCIAS:
        return pedida, True
    guardada = request.cookies.get(GALLETA_EXPERIENCIA)
    return (guardada if guardada in EXPERIENCIAS else EXPERIENCIA_PREDETERMINADA), False


@blueprint.get('/inicio')
def home():
    experiencia, recordar = experiencia_elegida()
    response = make_response(render_home('v2/home.html', experiencia=experiencia))
    if recordar:
        response.set_cookie(GALLETA_EXPERIENCIA, experiencia, max_age=180 * 86400, path='/inicio',
                            httponly=True, samesite='Lax', secure=request.is_secure)
    return response


@blueprint.get('/inicio/anterior')
def home_previous():
    return render_home('v2/home_v1.html')


@blueprint.get('/inicio/explorar')
def workspace():
    return render_home('v2/workspace.html')


def render_home(template, **extra):
    from .home import read_home
    from datetime import datetime
    from zoneinfo import ZoneInfo
    def local_date(value):
        point = datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(ZoneInfo('America/Mexico_City'))
        offset = point.strftime('%z')
        return point.strftime('%d/%m/%Y '+chr(183)+' %H:%M')+' (UTC'+offset[:3]+':'+offset[3:]+')'
    meses = ('ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic')
    def short_date(value):
        return f'{value.day} {meses[value.month - 1]} {value.year}'
    try:
        overview = read_home(current_app.extensions['aeris_v2_database']())
        try:
            from .estado import read_estado
            estado = read_estado(current_app.extensions['aeris_v2_database']())
        except (sqlite3.Error, RuntimeError, KeyError, ValueError):
            estado = None  # El resumen es complementario: nunca impide mostrar el resto.
        try:
            from .indice import read_indice
            indice = read_indice(current_app.extensions['aeris_v2_database']())
        except (sqlite3.Error, OSError, RuntimeError, KeyError, ValueError):
            indice = None  # Igual: sin capa de contaminantes la portada sigue con PM2.5.
        try:
            from .modelo import read_modelo
            modelo = read_modelo(current_app.extensions['aeris_v2_database']())
        except (sqlite3.Error, OSError, RuntimeError, KeyError, ValueError, ZeroDivisionError):
            modelo = None  # El modelo es contexto opcional.
        return render_template(template, overview=overview, local_date=local_date, unavailable=False,
                               estado=estado, indice=indice, modelo=modelo, short_date=short_date, **extra)
    except (sqlite3.Error, FileNotFoundError, RuntimeError, KeyError, ValueError):
        return render_template(template, overview=None, local_date=local_date, unavailable=True,
                               estado=None, short_date=short_date, **extra), 503


@blueprint.get('/v2')
@blueprint.get('/v2/')
def index(): return render_template('v2/public.html')


@blueprint.get('/v2/datos')
@blueprint.get('/v2/datos/')
def explorer(): return render_template('v2/dashboard.html')


def payload(public=False):
    if set(request.args)-{'source','station','period'}: raise ValueError('Parámetro no válido.')
    return read_dashboard(current_app.extensions['aeris_v2_database'](),
        source=request.args.get('source','OpenAQ'),station=request.args.get('station','all'),
        period=request.args.get('period','7d'),include_history=public)


def respond(stations_only=False,public=False):
    try:
        result=payload(public)
        if public: result=explain(result)
        if stations_only:
            result={k:result[k] for k in ('stations','source','source_label','generated_at_utc')}
        response=jsonify(result); response.headers['Cache-Control']='no-store'; return response
    except TooManyRows as exc: return jsonify(error=str(exc)),413
    except ValueError as exc: return jsonify(error=str(exc)),400
    except (sqlite3.Error,FileNotFoundError,RuntimeError,KeyError):
        return jsonify(error='No se pudieron leer datos compatibles. Los valores anteriores no se consideran actualizados.'),503


@blueprint.get('/api/v2/observations')
def observations(): return respond()


@blueprint.get('/api/v2/stations')
def stations(): return respond(stations_only=True)


@blueprint.get('/api/v2/public')
def public_observations(): return respond(public=True)


@blueprint.get('/api/v2/comparison')
def comparison():
    try:
        if set(request.args)-{'source','station','anchor'}:raise ValueError('Parámetro no válido.')
        result=read_comparison(current_app.extensions['aeris_v2_database'](),
            source=request.args.get('source','OpenAQ'),station=request.args.get('station','all'),
            anchor=request.args.get('anchor','recent'))
        response=jsonify(result);response.headers['Cache-Control']='no-store';return response
    except ValueError as exc:return jsonify(error=str(exc)),400
    except (sqlite3.Error,FileNotFoundError,RuntimeError,KeyError):
        return jsonify(error='No se pudo obtener una comparación compatible. No se interpretan datos anteriores como actuales.'),503
