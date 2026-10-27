"""Migraciones reversibles de la capa ambiental. Solo crea o elimina objetos amb_*.

Nunca altera mediciones, calidad, ingestas ni ninguna tabla existente de AERIS.
Por defecto se niega a escribir en una base que contenga la tabla legada `mediciones`
(producción o copias suyas): esa integración requiere autorización explícita.
"""
import argparse
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .catalogo import ESTACIONES, FUENTES, VARIABLES

AUTORIZACION_ENV = 'AERIS_AMBIENTAL_BASE_PRINCIPAL'
PREFIJO = 'amb_'

MIGRACIONES = {
    1: ('catalogo_y_observaciones', [
        '''CREATE TABLE amb_migraciones (
            version INTEGER PRIMARY KEY, nombre TEXT NOT NULL,
            aplicada_utc TEXT NOT NULL, sql_sha256 TEXT NOT NULL)''',
        '''CREATE TABLE amb_fuentes (
            fuente_id TEXT PRIMARY KEY, nombre TEXT NOT NULL, organizacion TEXT NOT NULL,
            url TEXT NOT NULL, documentacion_url TEXT, licencia TEXT NOT NULL, atribucion TEXT NOT NULL,
            tipo_producto TEXT NOT NULL CHECK(tipo_producto IN
                ('observacion','reanalisis','modelo','estimacion','satelite')),
            metodo_acceso TEXT NOT NULL,
            autorizada INTEGER NOT NULL DEFAULT 0 CHECK(autorizada IN (0,1)), notas TEXT)''',
        '''CREATE TABLE amb_estaciones (
            estacion_id TEXT PRIMARY KEY,
            fuente_id TEXT NOT NULL REFERENCES amb_fuentes(fuente_id),
            id_externo TEXT NOT NULL, nombre TEXT NOT NULL, municipio TEXT, municipio_nota TEXT,
            latitud REAL NOT NULL CHECK(latitud BETWEEN -90 AND 90),
            longitud REAL NOT NULL CHECK(longitud BETWEEN -180 AND 180),
            elevacion_m REAL, tipo_sitio TEXT NOT NULL CHECK(tipo_sitio IN ('estacion','celda_rejilla','punto_modelo')),
            resolucion_espacial TEXT, metadatos_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(fuente_id,id_externo))''',
        '''CREATE TABLE amb_variables (
            variable_id TEXT PRIMARY KEY, nombre TEXT NOT NULL, unidad TEXT NOT NULL,
            dominio TEXT NOT NULL CHECK(dominio IN ('contaminante','meteorologia')),
            minimo_fisico REAL NOT NULL, maximo_fisico REAL NOT NULL)''',
        '''CREATE TABLE amb_ingestas (
            ingesta_id TEXT PRIMARY KEY, fuente_id TEXT NOT NULL REFERENCES amb_fuentes(fuente_id),
            inicio_utc TEXT NOT NULL, fin_utc TEXT,
            estado TEXT NOT NULL CHECK(estado IN ('en_curso','exito','sin_datos_nuevos','sin_publicacion','fallo')),
            ventana_desde_utc TEXT, ventana_hasta_utc TEXT,
            leidas INTEGER NOT NULL DEFAULT 0, insertadas INTEGER NOT NULL DEFAULT 0,
            duplicadas INTEGER NOT NULL DEFAULT 0, revisiones INTEGER NOT NULL DEFAULT 0,
            descartadas INTEGER NOT NULL DEFAULT 0, error_tipo TEXT, reporte_json TEXT)''',
        '''CREATE TABLE amb_archivos (
            sha256 TEXT NOT NULL, url TEXT NOT NULL, consultado_utc TEXT NOT NULL,
            bytes INTEGER NOT NULL, etag TEXT, last_modified TEXT, ruta_local TEXT,
            ingesta_id TEXT NOT NULL REFERENCES amb_ingestas(ingesta_id),
            PRIMARY KEY(sha256,url))''',
        '''CREATE TABLE amb_observaciones (
            id INTEGER PRIMARY KEY,
            estacion_id TEXT NOT NULL REFERENCES amb_estaciones(estacion_id),
            variable_id TEXT NOT NULL REFERENCES amb_variables(variable_id),
            fecha_utc TEXT NOT NULL CHECK(fecha_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
            fecha_local TEXT NOT NULL,
            valor REAL NOT NULL, unidad TEXT NOT NULL,
            valor_original TEXT NOT NULL, unidad_original TEXT NOT NULL,
            periodo TEXT NOT NULL, tipo_reporte TEXT NOT NULL,
            codigo_medicion TEXT NOT NULL DEFAULT '', calidad_origen TEXT NOT NULL DEFAULT '',
            marca_origen INTEGER NOT NULL CHECK(marca_origen IN (0,1)),
            fuera_de_rango INTEGER NOT NULL CHECK(fuera_de_rango IN (0,1)),
            archivo_sha256 TEXT, ingesta_id TEXT NOT NULL REFERENCES amb_ingestas(ingesta_id),
            registrada_utc TEXT NOT NULL,
            UNIQUE(estacion_id,variable_id,fecha_utc,tipo_reporte))''',
        'CREATE INDEX amb_observaciones_serie ON amb_observaciones(estacion_id,variable_id,fecha_utc)',
        '''CREATE TABLE amb_revisiones (
            id INTEGER PRIMARY KEY,
            observacion_id INTEGER NOT NULL REFERENCES amb_observaciones(id),
            tipo TEXT NOT NULL CHECK(tipo IN ('valor','calidad','valor_y_calidad')),
            valor_original_nuevo TEXT NOT NULL, calidad_origen_nueva TEXT NOT NULL,
            ingesta_id TEXT NOT NULL REFERENCES amb_ingestas(ingesta_id),
            archivo_sha256 TEXT, registrada_utc TEXT NOT NULL,
            UNIQUE(observacion_id,valor_original_nuevo,calidad_origen_nueva))''',
        '''CREATE TABLE amb_estado (
            estacion_id TEXT PRIMARY KEY REFERENCES amb_estaciones(estacion_id),
            completo_hasta_utc TEXT, ultima_observacion_utc TEXT,
            ultima_ingesta_id TEXT REFERENCES amb_ingestas(ingesta_id), actualizado_utc TEXT NOT NULL)''',
        *[f'''CREATE TRIGGER amb_{t}_inmutable_{a.lower()} BEFORE {a} ON amb_{t}
            BEGIN SELECT RAISE(ABORT,'Registro ambiental inmutable; registrar una revisión'); END'''
          for t in ('observaciones', 'revisiones') for a in ('UPDATE', 'DELETE')],
    ]),
    # El índice único (estacion_id,variable_id,fecha_utc,tipo_reporte) ya cubre todas las consultas.
    2: ('quitar_indice_redundante', ['DROP INDEX IF EXISTS amb_observaciones_serie']),
}
# Reversa por migración (salvo la 1, cuya reversa es eliminar todos los objetos amb_*).
REVERSAS = {
    2: ['CREATE INDEX IF NOT EXISTS amb_observaciones_serie ON amb_observaciones(estacion_id,variable_id,fecha_utc)'],
}


def ahora():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def tablas(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def version(conn):
    if 'amb_migraciones' not in tablas(conn):
        return 0
    return conn.execute('SELECT COALESCE(MAX(version),0) FROM amb_migraciones').fetchone()[0]


def exigir_base_permitida(conn, permitir_base_principal=False):
    """La base principal solo se acepta con argumento explícito y variable de entorno."""
    if 'mediciones' in tablas(conn):
        if not (permitir_base_principal and os.environ.get(AUTORIZACION_ENV) == 'autorizado'):
            raise PermissionError('Base con mediciones legadas: la capa ambiental requiere autorización explícita')


def sql_sha(sentencias):
    return hashlib.sha256('\n;\n'.join(sentencias).encode('utf8')).hexdigest()


def migrar(conn, objetivo=max(MIGRACIONES), permitir_base_principal=False):
    """Aplica en una transacción; los objetos legados quedan intactos byte a byte."""
    exigir_base_permitida(conn, permitir_base_principal)
    actual = version(conn)
    with conn:
        for numero in range(actual + 1, objetivo + 1):
            nombre, sentencias = MIGRACIONES[numero]
            for sentencia in sentencias:
                conn.execute(sentencia)
            conn.execute('INSERT INTO amb_migraciones VALUES (?,?,?,?)', (numero, nombre, ahora(), sql_sha(sentencias)))
        sembrar(conn)
    return version(conn)


def revertir(conn, descartar_datos=False, permitir_base_principal=False, objetivo=0):
    """Vuelve a la versión objetivo. Objetivo 0 elimina únicamente objetos amb_*; con datos exige confirmación."""
    exigir_base_permitida(conn, permitir_base_principal)
    if objetivo:
        with conn:
            for numero in range(version(conn), objetivo, -1):
                for sentencia in REVERSAS[numero]:
                    conn.execute(sentencia)
                conn.execute('DELETE FROM amb_migraciones WHERE version=?', (numero,))
        return version(conn)
    if 'amb_observaciones' in tablas(conn) and not descartar_datos:
        if conn.execute('SELECT 1 FROM amb_observaciones LIMIT 1').fetchone():
            raise PermissionError('Hay observaciones ambientales; usar descartar_datos=True solo en desarrollo')
    objetos = conn.execute("SELECT type,name FROM sqlite_master WHERE name LIKE 'amb\\_%' ESCAPE '\\' "
                           "AND type IN ('trigger','index','table')").fetchall()
    orden = {'trigger': 0, 'index': 1, 'table': 2}
    dependientes = ['amb_revisiones', 'amb_estado', 'amb_observaciones', 'amb_archivos', 'amb_ingestas',
                    'amb_estaciones', 'amb_variables', 'amb_fuentes', 'amb_migraciones']
    objetos.sort(key=lambda o: (orden[o[0]], dependientes.index(o[1]) if o[1] in dependientes else -1))
    with conn:
        for tipo, nombre in objetos:
            if not nombre.startswith(PREFIJO):
                raise RuntimeError('Objeto fuera del espacio amb_')
            conn.execute(f'DROP {tipo.upper()} IF EXISTS "{nombre}"')
    return version(conn)


def sembrar(conn):
    """Catálogo idempotente. Fuentes nuevas quedan no autorizadas hasta decisión explícita."""
    for fid, f in FUENTES.items():
        conn.execute('''INSERT INTO amb_fuentes(fuente_id,nombre,organizacion,url,documentacion_url,licencia,
            atribucion,tipo_producto,metodo_acceso,notas) VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(fuente_id) DO UPDATE SET nombre=excluded.nombre,organizacion=excluded.organizacion,
            url=excluded.url,documentacion_url=excluded.documentacion_url,licencia=excluded.licencia,
            atribucion=excluded.atribucion,metodo_acceso=excluded.metodo_acceso,notas=excluded.notas''',
            (fid, f['nombre'], f['organizacion'], f['url'], f['documentacion_url'], f['licencia'],
             f['atribucion'], f['tipo_producto'], f['metodo_acceso'], f['notas']))
        tipo = conn.execute('SELECT tipo_producto FROM amb_fuentes WHERE fuente_id=?', (fid,)).fetchone()[0]
        if tipo != f['tipo_producto']:
            raise ValueError(f'No se reclasifica el tipo de producto de {fid}')
    for vid, (nombre, unidad, dominio, minimo, maximo) in VARIABLES.items():
        previo = conn.execute('SELECT unidad FROM amb_variables WHERE variable_id=?', (vid,)).fetchone()
        if previo and previo[0] != unidad:
            raise ValueError(f'Cambio de unidad canónica no permitido: {vid}')
        conn.execute('''INSERT INTO amb_variables VALUES (?,?,?,?,?,?) ON CONFLICT(variable_id) DO UPDATE SET
            nombre=excluded.nombre,minimo_fisico=excluded.minimo_fisico,maximo_fisico=excluded.maximo_fisico''',
            (vid, nombre, unidad, dominio, minimo, maximo))
    for eid, e in ESTACIONES.items():
        previo = conn.execute('SELECT fuente_id,id_externo,latitud,longitud FROM amb_estaciones WHERE estacion_id=?',
                              (eid,)).fetchone()
        if previo and tuple(previo) != (e['fuente_id'], e['id_externo'], e['latitud'], e['longitud']):
            raise ValueError(f'Identidad o coordenadas de {eid} cambiaron; registrar una estación nueva')
        conn.execute('''INSERT INTO amb_estaciones VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(estacion_id) DO UPDATE SET nombre=excluded.nombre,municipio=excluded.municipio,
            municipio_nota=excluded.municipio_nota,resolucion_espacial=excluded.resolucion_espacial''',
            (eid, e['fuente_id'], e['id_externo'], e['nombre'], e['municipio'], e['municipio_nota'],
             e['latitud'], e['longitud'], e['elevacion_m'], e['tipo_sitio'], e['resolucion_espacial'],
             json.dumps(e['metadatos'], ensure_ascii=False, sort_keys=True)))


def autorizar(conn, fuente_id, autorizada=True):
    with conn:
        if not conn.execute('UPDATE amb_fuentes SET autorizada=? WHERE fuente_id=?',
                            (int(autorizada), fuente_id)).rowcount:
            raise KeyError(fuente_id)


def conectar(path):
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('accion', choices=['migrar', 'revertir', 'estado', 'autorizar', 'desautorizar'])
    parser.add_argument('--fuente', action='append', default=[])
    parser.add_argument('--descartar-datos', action='store_true')
    parser.add_argument('--hasta-version', type=int, default=0, help='revertir: versión a conservar (0 = todo)')
    parser.add_argument('--permitir-base-principal', action='store_true')
    args = parser.parse_args(argv)
    if args.accion != 'migrar' and not args.db.is_file():
        parser.error('La base no existe')
    args.db.parent.mkdir(parents=True, exist_ok=True)
    with closing(conectar(args.db)) as conn:
        if args.accion == 'migrar':
            migrar(conn, permitir_base_principal=args.permitir_base_principal)
        elif args.accion == 'revertir':
            revertir(conn, args.descartar_datos, args.permitir_base_principal, args.hasta_version)
        elif args.accion in ('autorizar', 'desautorizar'):
            exigir_base_permitida(conn, args.permitir_base_principal)
            for fuente in args.fuente:
                autorizar(conn, fuente, args.accion == 'autorizar')
        fuentes = conn.execute('SELECT fuente_id,autorizada FROM amb_fuentes').fetchall() if version(conn) else []
        print(json.dumps({'base': str(args.db), 'version': version(conn), 'fuentes_autorizadas': dict(fuentes)},
                         ensure_ascii=False))


if __name__ == '__main__':
    main()
