"""Panel de administración (/admin) y comando para asignar el rol.

Comparte el blueprint de cuentas: misma sesión, CSRF y Cache-Control. Quien no es admin recibe 404.
Uso del comando: python -m cuentas.admin rol <correo> admin|usuario [--db data/aeris_usuarios.db]
"""
import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import abort, current_app, redirect, request, url_for

from . import store
from .web import blueprint, conexion, lecturas_actuales, pagina, usuario_actual

LOCAL = ZoneInfo('America/Mexico_City')
EDAD_MAXIMA_HORAS = 4  # misma tolerancia que las alertas


def requiere_admin(vista):
    @wraps(vista)
    def envuelta(*args, **kwargs):
        u = usuario_actual()
        if u is None:
            return redirect(url_for('cuentas.entrar', siguiente=request.path))
        if u['rol'] != 'admin':
            abort(404)  # no se revela que el panel existe
        return vista(*args, **kwargs)
    return envuelta


def hora_local(valor):
    if not valor:
        return '—'
    if isinstance(valor, str):
        valor = datetime.fromisoformat(valor.replace('Z', '+00:00'))
    return valor.astimezone(LOCAL).strftime('%d/%m/%Y %H:%M')


def estado_ingesta(mediciones, now=None):
    """Lee los reportes que ya escribe la sincronización programada; no la ejecuta ni la modifica."""
    now = now or datetime.now(timezone.utc)
    carpeta = Path(mediciones).resolve().parent / 'sync_runtime' / 'scheduler'
    if not carpeta.is_dir():
        return None
    ultima, recientes = None, []
    try:
        ultima = json.loads((carpeta / 'last_success.json').read_text(encoding='utf8'))
    except (OSError, ValueError):
        pass
    for archivo in carpeta.glob('*.json'):
        if archivo.name == 'last_success.json':
            continue
        try:
            if datetime.fromtimestamp(archivo.stat().st_mtime, timezone.utc) < now - timedelta(hours=24):
                continue
            datos = json.loads(archivo.read_text(encoding='utf8'))
        except (OSError, ValueError):
            continue
        recientes.append({'estado': datos.get('status', 'desconocido'), 'fin': datos.get('finished_at_utc'),
                          'error': datos.get('error_type')})
    recientes.sort(key=lambda r: r['fin'] or '', reverse=True)
    fin = ultima.get('finished_at_utc') if ultima else None
    edad = (now - datetime.fromisoformat(fin.replace('Z', '+00:00'))).total_seconds() / 3600 if fin else None
    return {'ultima_exitosa': fin, 'edad_horas': edad, 'corridas_24h': len(recientes),
            'fallas_24h': [r for r in recientes if r['estado'] != 'success'][:5],
            'exitosas_24h': sum(r['estado'] == 'success' for r in recientes)}


def estado_alertas(path):
    """Resumen de la base del bot, en solo lectura. None si todavía no existe."""
    path = Path(path)
    if not path.is_file():
        return None
    hace24 = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec='seconds').replace('+00:00', 'Z')
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            uno = lambda sql, *p: conn.execute(sql, p).fetchone()[0]
            return {'chats': uno('SELECT COUNT(*) FROM suscriptores'),
                    'pausados': uno('SELECT COUNT(*) FROM suscriptores WHERE activo=0'),
                    'vinculados': uno("SELECT COUNT(*) FROM sqlite_master WHERE name='chats_vinculados'") and
                                  uno('SELECT COUNT(*) FROM chats_vinculados'),
                    'suscripciones': uno('SELECT COUNT(*) FROM suscripciones'),
                    'avisos_24h': uno('SELECT COUNT(*) FROM alertas_enviadas WHERE enviada_utc>=?', hace24),
                    'ultimo_aviso': uno('SELECT MAX(enviada_utc) FROM alertas_enviadas')}
        finally:
            conn.close()
    except sqlite3.Error:
        return None


@blueprint.get('/admin')
@requiere_admin
def admin_inicio():
    mediciones = current_app.extensions['aeris_v2_database']()
    estaciones = lecturas_actuales()
    return pagina('cuentas/admin/inicio.html', usuarios=store.resumen_usuarios(conexion()),
                  ingesta=estado_ingesta(mediciones), alertas=estado_alertas(current_app.extensions['alertas_db']),
                  estaciones=estaciones, edad_maxima=EDAD_MAXIMA_HORAS, eventos=store.eventos_admin(conexion(), 10),
                  acciones=store.ACCIONES, hora_local=hora_local)


@blueprint.get('/admin/usuarios')
@requiere_admin
def admin_usuarios():
    buscar = request.args.get('q', '')
    return pagina('cuentas/admin/usuarios.html', usuarios=store.listar_usuarios(conexion(), buscar), buscar=buscar,
                  yo=usuario_actual(), hora_local=hora_local, aviso=request.args.get('aviso'))


@blueprint.post('/admin/usuarios/<int:usuario_id>')
@requiere_admin
def admin_accion(usuario_id):
    accion, buscar = request.form.get('accion', ''), request.form.get('q', '')
    try:
        u = store.administrar(conexion(), usuario_actual(), usuario_id, accion)
    except store.ErrorCuenta as exc:
        return pagina('cuentas/admin/usuarios.html', 400, usuarios=store.listar_usuarios(conexion(), buscar),
                      buscar=buscar, yo=usuario_actual(), hora_local=hora_local, error=str(exc))
    return redirect(url_for('cuentas.admin_usuarios', q=buscar or None,
                            aviso=f'{store.ACCIONES[accion]}: {u["correo"]}'))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Administración de cuentas AERIS desde la consola')
    parser.add_argument('--db', type=Path, default=store.DEFAULT_DB)
    sub = parser.add_subparsers(dest='orden', required=True)
    rol = sub.add_parser('rol', help='Asigna el rol de una cuenta')
    rol.add_argument('correo')
    rol.add_argument('rol', choices=store.ROLES)
    sub.add_parser('listar', help='Lista las cuentas (sin contraseñas)')
    args = parser.parse_args(argv)
    conn = store.conectar(args.db)
    try:
        if args.orden == 'listar':
            for u in store.listar_usuarios(conn):
                print(f"{u['id']:>4}  {u['rol']:<8} {'verificada' if u['verificado_utc'] else 'sin verificar':<13} "
                      f"{'activa' if u['activo'] else 'inactiva':<8} {u['correo']}")
            return 0
        if not store.asignar_rol(conn, args.correo, args.rol):
            print('No existe una cuenta con ese correo.'); return 1
        with conn:
            conn.execute('INSERT INTO admin_eventos(admin_correo,accion,usuario_correo,momento_utc) VALUES (?,?,?,?)',
                         ('consola', 'hacer_admin' if args.rol == 'admin' else 'quitar_admin',
                          store.normalizar_correo(args.correo), store.stamp(store.utc_now())))
        print(f'Listo: {args.correo} ahora tiene rol {args.rol}.')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
