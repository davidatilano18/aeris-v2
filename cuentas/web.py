"""Registro, verificación, inicio de sesión y recuperación de contraseña.

Local: activas siempre, base data/aeris_usuarios.db, clave de sesión en .secrets/ y correos en la consola.
Beta (Railway): apagadas salvo que AERIS_CUENTAS_DB_PATH lo pida; ese despliegue aún no está habilitado.
"""
import hmac
import re
import secrets
import sqlite3
from datetime import timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from flask import (Blueprint, abort, current_app, g, make_response, redirect, render_template, request,
                   session, url_for)

from . import correo, store

blueprint = Blueprint('cuentas', __name__)
ERROR_ENTRAR = 'Correo o contraseña incorrectos.'
UMBRAL_REFERENCIA = 25.0  # NOM-025-SSA1-2021, referencia de 24 h vigente desde enero de 2026
DEMASIADOS = 'Demasiados intentos. Espera unos minutos y vuelve a probar.'


def configurar(app, root, environ):
    """Registra las cuentas si corresponde. Devuelve la ruta de la base o None si quedan apagadas."""
    if app.config['AERIS_ENV'] == 'beta':
        if not environ.get('AERIS_CUENTAS_DB_PATH'):
            app.context_processor(lambda: {'cuentas_activas': False})
            return None
        raise ValueError('Las cuentas en beta requieren clave de sesión y envío de correos (pendiente)')
    db = Path(environ.get('AERIS_CUENTAS_DB_PATH') or store.DEFAULT_DB)
    store.conectar(db).close()  # crea o valida el esquema al arrancar
    app.secret_key = environ.get('AERIS_SECRET_KEY') or clave_local(root / '.secrets' / 'aeris_session_key')
    app.config.update(SESSION_COOKIE_NAME='aeris_sesion', SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Lax', PERMANENT_SESSION_LIFETIME=timedelta(days=30))
    app.extensions['cuentas_db'] = db
    app.config['AERIS_TELEGRAM_BOT'] = environ.get('AERIS_TELEGRAM_BOT', 'AERIS_QRO_BOT')
    app.extensions.setdefault('cuentas_enviar', correo.consola)
    app.extensions['alertas_db'] = Path(environ.get('AERIS_ALERTAS_DB_PATH') or root / 'data' / 'aeris_alertas.db')
    from . import admin  # noqa: F401  (añade /admin al blueprint antes de registrarlo)
    app.register_blueprint(blueprint)
    app.context_processor(lambda: {'cuentas_activas': True, 'usuario_actual': usuario_actual,
                                   'mis_estaciones': mis_estaciones, 'correo_local': g.get('correo_local')})
    return db


def clave_local(path):
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32), encoding='ascii')
    clave = path.read_text(encoding='ascii').strip()
    if len(clave) < 32:
        raise ValueError('Clave de sesión local demasiado corta')
    return clave


def conexion():
    if 'cuentas_conn' not in g:
        g.cuentas_conn = store.conectar(current_app.extensions['cuentas_db'])
    return g.cuentas_conn


@blueprint.teardown_app_request
def cerrar(_exc):
    conn = g.pop('cuentas_conn', None)
    if conn is not None:
        conn.close()


def usuario_actual():
    """Usuario de la sesión, o None. Una sesión de antes de un cambio de contraseña ya no vale."""
    if 'usuario_actual' not in g:
        g.usuario_actual = None
        uid, version = session.get('uid'), session.get('v')
        if uid is not None:
            u = store.usuario(conexion(), uid)
            if u and u['activo'] and u['verificado_utc'] and u['sesion_version'] == version:
                g.usuario_actual = u
            else:
                session.clear()
    return g.usuario_actual


def requiere_sesion(vista):
    @wraps(vista)
    def envuelta(*args, **kwargs):
        if usuario_actual() is None:
            return redirect(url_for('cuentas.entrar', siguiente=request.path))
        return vista(*args, **kwargs)
    return envuelta


def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']


@blueprint.app_context_processor
def plantillas():
    return {'csrf_token': csrf_token}


@blueprint.before_request
def proteger():
    if request.method == 'POST':
        enviado = request.form.get('csrf', '')
        if not session.get('csrf') or not hmac.compare_digest(enviado, session['csrf']):
            abort(400)


@blueprint.after_request
def sin_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'  # los enlaces llevan tokens en la ruta
    return response


def pagina(plantilla, estado=200, **datos):
    return make_response(render_template(plantilla, **datos), estado)


def ip(): return request.remote_addr or 'desconocida'


def destino_seguro(valor):
    """Solo rutas internas: evita redirecciones abiertas tras iniciar sesión."""
    if not valor or not valor.startswith('/') or valor.startswith('//') or '\\' in valor:
        return url_for('cuentas.perfil')
    partes = urlsplit(valor)
    return url_for('cuentas.perfil') if partes.scheme or partes.netloc else valor


def correo_local():
    """Prototipo local sin envío real: el enlace se muestra en la página."""
    return current_app.config['AERIS_ENV'] == 'local' and current_app.extensions['cuentas_enviar'] is correo.consola


def puede_enviar(conn, direccion):
    """Límite de correos por cuenta. Sin envío real no protege a nadie y solo dejaría al usuario sin enlace."""
    return correo_local() or store.limitar(conn, direccion, 'correo')


def enviar(para, mensaje):
    asunto, texto = mensaje
    if correo_local():
        # Prototipo local: no hay envío real, así que el enlace también se muestra en la página.
        enlace = re.search(r'https?://\S+', texto)
        g.correo_local = {'asunto': asunto, 'enlace': enlace.group(0) if enlace else None}
    try:
        current_app.extensions['cuentas_enviar'](para, asunto, texto)
    except Exception as exc:  # el texto puede incluir el enlace; solo se registra el tipo
        current_app.logger.error('correo_fallido type=%s', type(exc).__name__)


def iniciar_sesion(u):
    session.clear()  # nueva sesión: evita fijación
    session.permanent = True
    session.update(uid=u['id'], v=u['sesion_version'])


@blueprint.route('/cuenta/registro', methods=['GET', 'POST'])
def registro():
    if usuario_actual():
        return redirect(url_for('cuentas.perfil'))
    if request.method == 'GET':
        return pagina('cuentas/registro.html')
    correo_texto = request.form.get('correo', '')
    if request.form.get('acepto') != 'si':
        return pagina('cuentas/registro.html', 400, error='Debes aceptar el aviso de privacidad.', correo=correo_texto)
    if request.form.get('contrasena') != request.form.get('confirmar'):
        return pagina('cuentas/registro.html', 400, error='Las contraseñas no coinciden.', correo=correo_texto)
    conn = conexion()
    if not store.limitar(conn, ip(), 'registro_ip'):
        return pagina('cuentas/registro.html', 429, error=DEMASIADOS, correo=correo_texto)
    try:
        uid, creado = store.registrar(conn, correo_texto, request.form.get('contrasena'))
    except store.ErrorCuenta as exc:
        return pagina('cuentas/registro.html', 400, error=str(exc), correo=correo_texto)
    u = store.usuario(conn, uid)
    if puede_enviar(conn, u['correo']):
        if creado or not u['verificado_utc']:
            token = store.emitir_token(conn, uid, 'verificar')
            enviar(u['correo'], correo.verificacion(url_for('cuentas.verificar', token=token, _external=True)))
        else:  # misma respuesta en pantalla: no se revela si el correo ya existía
            enviar(u['correo'], correo.ya_registrado(url_for('cuentas.entrar', _external=True),
                                                     url_for('cuentas.recuperar', _external=True)))
    return pagina('cuentas/revisa_correo.html', correo=u['correo'])


@blueprint.get('/cuenta/verificar/<token>')
def verificar(token):
    if store.verificar(conexion(), token) is None:
        return pagina('cuentas/mensaje.html', 400, titulo='Enlace no válido',
                      texto='El enlace no es válido o ya venció. Inicia sesión para pedir uno nuevo.')
    return pagina('cuentas/mensaje.html', titulo='Correo confirmado',
                  texto='Tu cuenta está activa. Ya puedes iniciar sesión.', enlace=url_for('cuentas.entrar'),
                  enlace_texto='Iniciar sesión')


@blueprint.route('/cuenta/entrar', methods=['GET', 'POST'])
def entrar():
    siguiente = request.values.get('siguiente', '')
    if usuario_actual():
        return redirect(destino_seguro(siguiente))
    if request.method == 'GET':
        return pagina('cuentas/entrar.html', siguiente=siguiente)
    conn, correo_texto = conexion(), request.form.get('correo', '')
    clave_correo = correo_texto.strip().lower()[:254]
    if not store.limitar(conn, ip(), 'login_ip') or not store.limitar(conn, clave_correo, 'login_correo'):
        return pagina('cuentas/entrar.html', 429, error=DEMASIADOS, correo=correo_texto, siguiente=siguiente)
    u = store.autenticar(conn, correo_texto, request.form.get('contrasena'))
    if u is None:
        return pagina('cuentas/entrar.html', 401, error=ERROR_ENTRAR, correo=correo_texto, siguiente=siguiente)
    if not u['activo']:
        return pagina('cuentas/entrar.html', 403, error='Esta cuenta está desactivada.', siguiente=siguiente)
    if not u['verificado_utc']:
        if puede_enviar(conn, u['correo']):
            token = store.emitir_token(conn, u['id'], 'verificar')
            enviar(u['correo'], correo.verificacion(url_for('cuentas.verificar', token=token, _external=True)))
            aviso = 'Primero confirma tu correo. Te enviamos un enlace nuevo.'
        else:  # no se afirma un envío que no ocurrió
            aviso = ('Primero confirma tu correo. Ya te enviamos varios enlaces en la última hora: '
                     'usa el más reciente o espera una hora para pedir otro.')
        return pagina('cuentas/entrar.html', 403, siguiente=siguiente, correo=correo_texto, error=aviso)
    store.olvidar_intentos(conn, clave_correo, 'login_correo')
    iniciar_sesion(u)
    return redirect(destino_seguro(siguiente))


@blueprint.post('/cuenta/salir')
def salir():
    session.clear()
    return redirect('/inicio')


@blueprint.route('/cuenta/recuperar', methods=['GET', 'POST'])
def recuperar():
    if request.method == 'GET':
        return pagina('cuentas/recuperar.html')
    conn = conexion()
    try:
        correo_texto = store.normalizar_correo(request.form.get('correo'))
    except store.ErrorCuenta as exc:
        return pagina('cuentas/recuperar.html', 400, error=str(exc))
    if store.limitar(conn, ip(), 'registro_ip'):
        u = store.por_correo(conn, correo_texto)
        if u and u['activo'] and puede_enviar(conn, u['correo']):
            token = store.emitir_token(conn, u['id'], 'recuperar')
            enviar(u['correo'], correo.recuperacion(url_for('cuentas.restablecer', token=token, _external=True)))
    # Siempre la misma respuesta: no se revela si el correo tiene cuenta.
    return pagina('cuentas/revisa_correo.html', correo=correo_texto, recuperar=True)


@blueprint.route('/cuenta/restablecer/<token>', methods=['GET', 'POST'])
def restablecer(token):
    if request.method == 'GET':
        return pagina('cuentas/restablecer.html', token=token)
    if request.form.get('contrasena') != request.form.get('confirmar'):
        return pagina('cuentas/restablecer.html', 400, token=token, error='Las contraseñas no coinciden.')
    try:
        store.restablecer(conexion(), token, request.form.get('contrasena'))
    except store.ErrorCuenta as exc:
        return pagina('cuentas/restablecer.html', 400, token=token, error=str(exc))
    session.clear()
    return pagina('cuentas/mensaje.html', titulo='Contraseña actualizada',
                  texto='Cerramos las sesiones abiertas. Inicia sesión con tu contraseña nueva.',
                  enlace=url_for('cuentas.entrar'), enlace_texto='Iniciar sesión')


def ver_perfil(estado=200, **datos):
    u = usuario_actual()
    return pagina('cuentas/perfil.html', estado, u=u, telegram=store.vinculo_telegram(conexion(), u['id']), **datos)


@blueprint.get('/cuenta')
@requiere_sesion
def perfil():
    return ver_perfil(aviso=request.args.get('aviso'))


@blueprint.post('/cuenta/telegram')
@requiere_sesion
def conectar_telegram():
    u, conn = usuario_actual(), conexion()
    if not store.limitar(conn, u['id'], 'telegram'):
        return ver_perfil(429, error=DEMASIADOS)
    codigo = store.codigo_telegram(conn, u['id'])
    return ver_perfil(enlace_telegram=f"https://t.me/{current_app.config['AERIS_TELEGRAM_BOT']}?start={codigo}")


@blueprint.post('/cuenta/telegram/desconectar')
@requiere_sesion
def desconectar_telegram():
    store.desvincular_telegram(conexion(), usuario_id=usuario_actual()['id'])
    return redirect(url_for('cuentas.perfil', aviso='telegram'))


@blueprint.post('/cuenta/contrasena')
@requiere_sesion
def contrasena():
    u, conn = usuario_actual(), conexion()
    if not store.limitar(conn, u['correo'], 'login_correo'):
        return ver_perfil(429, error=DEMASIADOS)
    if not store.autenticar(conn, u['correo'], request.form.get('actual')):
        return ver_perfil(400, error='Tu contraseña actual no es correcta.')
    if request.form.get('nueva') != request.form.get('confirmar'):
        return ver_perfil(400, error='Las contraseñas nuevas no coinciden.')
    try:
        version = store.cambiar_contrasena(conn, u['id'], request.form.get('nueva'))
    except store.ErrorCuenta as exc:
        return ver_perfil(400, error=str(exc))
    session['v'] = version  # esta sesión sigue; las demás se cierran
    return redirect(url_for('cuentas.perfil', aviso='contrasena'))


@blueprint.post('/cuenta/borrar')
@requiere_sesion
def borrar():
    u, conn = usuario_actual(), conexion()
    if not store.limitar(conn, u['correo'], 'login_correo'):
        return ver_perfil(429, error=DEMASIADOS)
    if not store.autenticar(conn, u['correo'], request.form.get('contrasena')):
        return ver_perfil(400, error='Para borrar tu cuenta escribe tu contraseña correcta.')
    store.borrar(conn, u['id'])
    session.clear()
    return pagina('cuentas/mensaje.html', titulo='Cuenta borrada',
                  texto='Borramos tu cuenta y todos sus datos.', enlace='/inicio', enlace_texto='Volver al inicio')


def lecturas_actuales():
    """Estaciones activas con su última lectura (solo lectura), o None si no se pueden leer."""
    from alertas import lecturas
    try:
        return lecturas.estaciones(current_app.extensions['aeris_v2_database']())
    except (sqlite3.Error, OSError, RuntimeError, ValueError, KeyError):
        current_app.logger.warning('cuentas_lecturas_no_disponibles')
        return None


def umbral_de(u): return u['umbral'] if u['umbral'] is not None else UMBRAL_REFERENCIA


def mis_estaciones():
    """Panel de la portada: None sin sesión; si no, favoritas con lectura y comparación con el umbral."""
    u = usuario_actual()
    if u is None:
        return None
    ids = store.favoritos(conexion(), u['id'])
    lista = lecturas_actuales() if ids else []
    por_id = {e['sensor_id']: e for e in lista or []}
    umbral = umbral_de(u)
    filas = [{**por_id[s], 'supera': por_id[s]['valor'] > umbral} for s in ids if s in por_id]
    return {'umbral': umbral, 'personal': u['umbral'] is not None, 'filas': filas, 'elegidas': len(ids),
            'sin_datos': len(ids) - len(filas), 'disponible': lista is not None}


@blueprint.route('/cuenta/estaciones', methods=['GET', 'POST'])
@requiere_sesion
def estaciones():
    u, conn = usuario_actual(), conexion()
    lista = lecturas_actuales()
    if lista is None:
        return pagina('cuentas/mensaje.html', 503, titulo='Estaciones no disponibles',
                      texto='No pudimos leer las estaciones en este momento. Intenta más tarde.')
    elegidas = set(store.favoritos(conn, u['id']))
    if request.method == 'POST':
        texto = request.form.get('umbral', '').strip().replace(',', '.')
        try:
            umbral = None if request.form.get('modo_umbral') != 'personal' or not texto else float(texto)
        except ValueError:
            umbral = -1  # lo rechaza la validación con un mensaje claro
        try:
            seleccion = [int(x) for x in request.form.getlist('sensor') if x.isdigit()]
            store.guardar_preferencias(conn, u['id'], seleccion, umbral, {e['sensor_id'] for e in lista})
        except store.ErrorCuenta as exc:
            return pagina('cuentas/estaciones.html', 400, u=u, lista=lista, elegidas=set(seleccion),
                          referencia=UMBRAL_REFERENCIA, error=str(exc))
        return redirect(url_for('cuentas.perfil', aviso='estaciones'))
    return pagina('cuentas/estaciones.html', u=u, lista=lista, elegidas=elegidas, referencia=UMBRAL_REFERENCIA)


@blueprint.get('/privacidad')
def privacidad():
    return pagina('cuentas/privacidad.html')


@blueprint.errorhandler(sqlite3.Error)
def base_no_disponible(_exc):
    current_app.logger.error('cuentas_db_error')
    return pagina('cuentas/mensaje.html', 503, titulo='Servicio no disponible',
                  texto='No pudimos acceder a las cuentas en este momento. Intenta más tarde.')
