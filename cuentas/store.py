"""Base SQLite de cuentas. Contraseñas con scrypt (Werkzeug); tokens guardados solo como SHA-256."""
import hashlib
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / 'data' / 'aeris_usuarios.db'
MEDICIONES_DB = ROOT / 'data' / 'aeris_air_quality.db'
VERSION = 2
MAX_FAVORITOS = 20
ROLES = ('usuario', 'admin')
MIN_CONTRASENA, MAX_CONTRASENA = 10, 128  # el máximo acota el costo de scrypt
VIGENCIA = {'verificar': timedelta(hours=24), 'recuperar': timedelta(hours=1)}
# Ventanas de intentos: (máximo, duración)
LIMITES = {'login_correo': (5, timedelta(minutes=15)), 'login_ip': (20, timedelta(minutes=15)),
           'registro_ip': (5, timedelta(hours=1)), 'correo': (3, timedelta(hours=1))}
CORREO = re.compile(r'[^@\s]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+')
# Se compara contra este hash cuando el correo no existe, para que el tiempo no lo delate.
_HASH_FALSO = generate_password_hash(secrets.token_urlsafe(16))

SCHEMA = '''
CREATE TABLE usuarios (
    id INTEGER PRIMARY KEY,
    correo TEXT NOT NULL UNIQUE,
    contrasena_hash TEXT NOT NULL,
    rol TEXT NOT NULL DEFAULT 'usuario' CHECK(rol IN ('usuario','admin')),
    verificado_utc TEXT,
    activo INTEGER NOT NULL DEFAULT 1 CHECK(activo IN (0,1)),
    sesion_version INTEGER NOT NULL DEFAULT 1,
    creado_utc TEXT NOT NULL,
    ultimo_acceso_utc TEXT,
    umbral REAL CHECK(umbral IS NULL OR (umbral > 0 AND umbral < 1000)));
CREATE TABLE tokens (
    hash TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL CHECK(tipo IN ('verificar','recuperar')),
    vence_utc TEXT NOT NULL,
    usado_utc TEXT);
CREATE INDEX tokens_por_usuario ON tokens(usuario_id, tipo);
CREATE TABLE intentos (
    id INTEGER PRIMARY KEY,
    clave TEXT NOT NULL,
    momento_utc TEXT NOT NULL);
CREATE INDEX intentos_por_clave ON intentos(clave, momento_utc);
CREATE TABLE favoritos (
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    sensor_id INTEGER NOT NULL,
    creado_utc TEXT NOT NULL,
    PRIMARY KEY(usuario_id, sensor_id));
'''
# Migraciones desde cada versión anterior; se aplican en orden dentro de una transacción.
MIGRACIONES = {
    1: '''ALTER TABLE usuarios ADD COLUMN umbral REAL CHECK(umbral IS NULL OR (umbral > 0 AND umbral < 1000));
CREATE TABLE favoritos (
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    sensor_id INTEGER NOT NULL,
    creado_utc TEXT NOT NULL,
    PRIMARY KEY(usuario_id, sensor_id));
''',
}


class ErrorCuenta(ValueError):
    """Error con un mensaje que se puede mostrar al usuario."""


def utc_now(): return datetime.now(timezone.utc)
def stamp(value): return value.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
def digest(token): return hashlib.sha256(token.encode()).hexdigest()


def conectar(path=DEFAULT_DB):
    path = Path(path).resolve()
    if path == MEDICIONES_DB.resolve():
        raise ValueError('Las cuentas no pueden escribir en la base de mediciones')
    conn = sqlite3.connect(path, timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version == 0:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                raise sqlite3.DatabaseError('La base no es de cuentas AERIS')
            with conn:
                conn.executescript(SCHEMA + f'PRAGMA user_version={VERSION};')
        elif version in MIGRACIONES:
            with conn:
                for v in range(version, VERSION):
                    conn.executescript('BEGIN;' + MIGRACIONES[v] + f'PRAGMA user_version={v + 1};COMMIT;')
        elif version != VERSION:
            raise sqlite3.DatabaseError(f'Versión de esquema no soportada: {version}')
        return conn
    except BaseException:
        conn.close(); raise


def normalizar_correo(correo):
    correo = (correo or '').strip().lower()
    if len(correo) > 254 or not CORREO.fullmatch(correo):
        raise ErrorCuenta('Escribe un correo válido.')
    return correo


def validar_contrasena(contrasena, correo=''):
    if not isinstance(contrasena, str) or len(contrasena) < MIN_CONTRASENA:
        raise ErrorCuenta(f'La contraseña debe tener al menos {MIN_CONTRASENA} caracteres.')
    if len(contrasena) > MAX_CONTRASENA:
        raise ErrorCuenta(f'La contraseña puede tener como máximo {MAX_CONTRASENA} caracteres.')
    if correo and contrasena.strip().lower() == correo:
        raise ErrorCuenta('La contraseña no puede ser tu correo.')
    return contrasena


def usuario(conn, usuario_id):
    row = conn.execute('SELECT * FROM usuarios WHERE id=?', (int(usuario_id),)).fetchone()
    return dict(row) if row else None


def por_correo(conn, correo):
    row = conn.execute('SELECT * FROM usuarios WHERE correo=?', (correo,)).fetchone()
    return dict(row) if row else None


def registrar(conn, correo, contrasena, now=None):
    """Crea la cuenta sin verificar. Devuelve (usuario_id, creado); si el correo ya existe, creado=False."""
    correo = normalizar_correo(correo)
    validar_contrasena(contrasena, correo)
    existente = por_correo(conn, correo)
    if existente:
        return existente['id'], False
    with conn:
        cur = conn.execute('INSERT INTO usuarios(correo,contrasena_hash,creado_utc) VALUES (?,?,?)',
                           (correo, generate_password_hash(contrasena), stamp(now or utc_now())))
    return cur.lastrowid, True


def autenticar(conn, correo, contrasena, now=None):
    """Devuelve el usuario si correo y contraseña coinciden, o None. Tiempo similar en ambos casos."""
    try:
        correo = normalizar_correo(correo)
    except ErrorCuenta:
        correo = None
    u = por_correo(conn, correo) if correo else None
    ok = check_password_hash(u['contrasena_hash'] if u else _HASH_FALSO, contrasena or '')
    if not (u and ok):
        return None
    with conn:
        conn.execute('UPDATE usuarios SET ultimo_acceso_utc=? WHERE id=?', (stamp(now or utc_now()), u['id']))
    return u


def emitir_token(conn, usuario_id, tipo, now=None):
    """Token de un solo uso; invalida los anteriores del mismo tipo. Solo se guarda su hash."""
    now = now or utc_now()
    token = secrets.token_urlsafe(32)
    with conn:
        conn.execute('DELETE FROM tokens WHERE usuario_id=? AND tipo=?', (int(usuario_id), tipo))
        conn.execute('INSERT INTO tokens(hash,usuario_id,tipo,vence_utc) VALUES (?,?,?,?)',
                     (digest(token), int(usuario_id), tipo, stamp(now + VIGENCIA[tipo])))
    return token


def consumir_token(conn, token, tipo, now=None):
    """Marca el token como usado y devuelve el usuario_id, o None si no es válido o venció."""
    now = now or utc_now()
    if not isinstance(token, str) or not 20 <= len(token) <= 100:
        return None
    with conn:
        row = conn.execute('SELECT usuario_id,vence_utc,usado_utc FROM tokens WHERE hash=? AND tipo=?',
                           (digest(token), tipo)).fetchone()
        if not row or row['usado_utc'] or row['vence_utc'] <= stamp(now):
            return None
        conn.execute('UPDATE tokens SET usado_utc=? WHERE hash=?', (stamp(now), digest(token)))
    return row['usuario_id']


def verificar(conn, token, now=None):
    uid = consumir_token(conn, token, 'verificar', now)
    if uid is not None:
        with conn:
            conn.execute('UPDATE usuarios SET verificado_utc=COALESCE(verificado_utc,?) WHERE id=?',
                         (stamp(now or utc_now()), uid))
    return uid


def cambiar_contrasena(conn, usuario_id, nueva):
    """Cambia la contraseña y cierra todas las sesiones abiertas (sube sesion_version)."""
    u = usuario(conn, usuario_id)
    validar_contrasena(nueva, u['correo'])
    with conn:
        conn.execute('''UPDATE usuarios SET contrasena_hash=?,sesion_version=sesion_version+1 WHERE id=?''',
                     (generate_password_hash(nueva), int(usuario_id)))
        conn.execute("DELETE FROM tokens WHERE usuario_id=? AND tipo='recuperar'", (int(usuario_id),))
    return usuario(conn, usuario_id)['sesion_version']


def restablecer(conn, token, nueva, now=None):
    """Valida la contraseña antes de gastar el token, para que un error no obligue a pedir otro."""
    row = conn.execute("SELECT usuario_id FROM tokens WHERE hash=? AND tipo='recuperar'",
                       (digest(token or ''),)).fetchone()
    if row:
        validar_contrasena(nueva, usuario(conn, row['usuario_id'])['correo'])
    uid = consumir_token(conn, token, 'recuperar', now)
    if uid is None:
        raise ErrorCuenta('El enlace no es válido o ya venció. Pide uno nuevo.')
    cambiar_contrasena(conn, uid, nueva)
    with conn:  # quien recibió el enlace demostró tener el correo
        conn.execute('UPDATE usuarios SET verificado_utc=COALESCE(verificado_utc,?) WHERE id=?',
                     (stamp(now or utc_now()), uid))
    return uid


def borrar(conn, usuario_id):
    with conn:
        return conn.execute('DELETE FROM usuarios WHERE id=?', (int(usuario_id),)).rowcount == 1


def asignar_rol(conn, correo, rol):
    if rol not in ROLES:
        raise ValueError('Rol no válido')
    with conn:
        return conn.execute('UPDATE usuarios SET rol=? WHERE correo=?', (rol, normalizar_correo(correo))).rowcount == 1


def limitar(conn, clave, tipo, now=None):
    """Registra un intento y devuelve False si ya se alcanzó el límite de la ventana."""
    maximo, ventana = LIMITES[tipo]
    now = now or utc_now()
    clave = f'{tipo}:{clave}'
    with conn:
        conn.execute('DELETE FROM intentos WHERE momento_utc<?', (stamp(now - timedelta(days=1)),))
        usados = conn.execute('SELECT COUNT(*) FROM intentos WHERE clave=? AND momento_utc>?',
                              (clave, stamp(now - ventana))).fetchone()[0]
        if usados >= maximo:
            return False
        conn.execute('INSERT INTO intentos(clave,momento_utc) VALUES (?,?)', (clave, stamp(now)))
    return True


def olvidar_intentos(conn, clave, tipo):
    with conn:
        conn.execute('DELETE FROM intentos WHERE clave=?', (f'{tipo}:{clave}',))


def favoritos(conn, usuario_id):
    return [r[0] for r in conn.execute('SELECT sensor_id FROM favoritos WHERE usuario_id=? ORDER BY creado_utc,sensor_id',
                                       (int(usuario_id),))]


def guardar_preferencias(conn, usuario_id, sensores, umbral, validos, now=None):
    """Reemplaza los favoritos (solo estaciones conocidas) y el umbral personal (None = referencia)."""
    sensores = list(dict.fromkeys(int(s) for s in sensores))
    if any(s not in validos for s in sensores):
        raise ErrorCuenta('Elegiste una estación que no existe.')
    if len(sensores) > MAX_FAVORITOS:
        raise ErrorCuenta(f'Puedes guardar hasta {MAX_FAVORITOS} estaciones.')
    if umbral is not None and not 0 < float(umbral) < 1000:
        raise ErrorCuenta('El umbral debe estar entre 0 y 1000 µg/m³.')
    momento = stamp(now or utc_now())
    with conn:
        conn.execute('DELETE FROM favoritos WHERE usuario_id=?', (int(usuario_id),))
        conn.executemany('INSERT INTO favoritos(usuario_id,sensor_id,creado_utc) VALUES (?,?,?)',
                         [(int(usuario_id), s, momento) for s in sensores])
        conn.execute('UPDATE usuarios SET umbral=? WHERE id=?', (None if umbral is None else float(umbral), int(usuario_id)))
