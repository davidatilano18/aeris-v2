"""Actualización incremental de fuentes ambientales autorizadas. No registra tareas ni borra archivos.

--si-corresponde ejecuta como máximo una vez por día local, a partir de las 08:00 de Querétaro,
para poder invocarse desde un disparador existente sin crear una tarea nueva.
"""
import argparse
import json
import os
import sqlite3
import uuid
from contextlib import closing, ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import operations as ops
from ..production_preflight import sha, snapshot
from . import almacen, ghcnh, nasa_power, open_meteo_cams
from .descargas import FalloFuente, SinPublicacion, descargar
from .esquema import conectar, exigir_base_permitida, tablas, version

SOLAPAMIENTO = timedelta(hours=72)  # Ambas fuentes publican con 1-3 días de latencia y revisan.
HORA_DIARIA = 8
BLOQUE_POWER = timedelta(days=180)
ESTADOS_CORRECTOS = ('exito', 'sin_datos_nuevos', 'sin_publicacion')
DIARIO_ENV = 'AERIS_AMBIENTAL_DIARIO'


def utc(texto):
    return datetime.fromisoformat(texto.replace('Z', '+00:00'))


def guardar_crudo(directorio, fuente_id, respuesta, extension):
    if directorio is None:
        return None
    ruta = Path(directorio) / fuente_id / f'{respuesta.sha256}{extension}'
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if not ruta.exists():
        ruta.write_bytes(respuesta.contenido)
    return ruta


def etag_previo(conn, url):
    fila = conn.execute('SELECT etag FROM amb_archivos WHERE url=? AND etag IS NOT NULL '
                        'ORDER BY consultado_utc DESC LIMIT 1', (url,)).fetchone()
    return fila and fila[0]


def sumar(total, parcial):
    for k in ('leidas', 'insertadas', 'duplicadas', 'revisiones', 'descartadas'):
        total[k] = total.get(k, 0) + parcial.get(k, 0)


def ventana(conn, estacion_id, desde_inicial, rellenar=False):
    completo, _ = almacen.estado(conn, estacion_id)
    if completo and not (rellenar and desde_inicial):
        return utc(completo) - SOLAPAMIENTO
    return desde_inicial


def estacion_ghcnh(conn, ingesta, estacion, desde, ahora, bajar, crudos, total):
    eid, externo = estacion[0], estacion[1]
    detalle = {'anios': {}}
    maximo = None
    for anio in range(desde.year, ahora.year + 1):
        direccion = ghcnh.URL.format(anio=anio, estacion=externo)
        try:
            r = bajar(direccion, etag=etag_previo(conn, direccion))
        except SinPublicacion:
            detalle['anios'][anio] = 'sin_publicacion'
            continue
        if r.sin_cambios:
            detalle['anios'][anio] = 'sin_cambios'
            continue
        ruta = guardar_crudo(crudos, ghcnh.FUENTE, r, '.psv')
        with conn:
            almacen.registrar_archivo(conn, ingesta, r, ruta)
        registros, resumen = ghcnh.interpretar(r.contenido.decode('utf-8'), externo, eid, desde, ahora)
        conteos = almacen.guardar(conn, ingesta, registros, r.sha256, ahora)
        sumar(total, conteos)
        detalle['anios'][anio] = {**resumen, **conteos, 'sha256': r.sha256}
        if registros:
            ultimo = max(x['fecha'] for x in registros)
            maximo = max(maximo, ultimo) if maximo else ultimo
    if all(v == 'sin_publicacion' for v in detalle['anios'].values()):
        raise SinPublicacion('Ningún año de la ventana está publicado')
    almacen.actualizar_estado(conn, eid, maximo, ingesta)
    return detalle


def estacion_power(conn, ingesta, estacion, desde, ahora, bajar, crudos, total, conector=nasa_power):
    eid, _, latitud, longitud = estacion
    detalle = {'bloques': []}
    maximo = None
    inicio = desde.replace(hour=0, minute=0, second=0, microsecond=0)
    while inicio < ahora:
        fin = min(inicio + BLOQUE_POWER, ahora)
        r = bajar(conector.url(latitud, longitud, inicio, fin))
        ruta = guardar_crudo(crudos, conector.FUENTE, r, '.json')
        with conn:
            almacen.registrar_archivo(conn, ingesta, r, ruta)
        registros, resumen = conector.interpretar(r.contenido, eid, latitud, longitud, desde, ahora)
        conteos = almacen.guardar(conn, ingesta, registros, r.sha256, ahora)
        sumar(total, conteos)
        detalle['bloques'].append({'desde': almacen.iso_utc(inicio), 'hasta': almacen.iso_utc(fin),
                                   **resumen, **conteos, 'sha256': r.sha256})
        if registros:
            ultimo = max(x['fecha'] for x in registros) + timedelta(hours=1)
            maximo = max(maximo, ultimo) if maximo else ultimo
        inicio = fin
    almacen.actualizar_estado(conn, eid, maximo, ingesta)
    return detalle


def estacion_cams(*args):
    # Mismo recorrido por bloques que POWER (consulta por punto y rango de fechas).
    return estacion_power(*args, conector=open_meteo_cams)


CONECTORES = {ghcnh.FUENTE: estacion_ghcnh, nasa_power.FUENTE: estacion_power, open_meteo_cams.FUENTE: estacion_cams}


def sincronizar_fuente(conn, fuente_id, ahora, desde_inicial=None, bajar=descargar, crudos=None, rellenar=False):
    """Cada estación se procesa por separado; un fallo de red no borra ni bloquea las demás."""
    estaciones = conn.execute('SELECT estacion_id,id_externo,latitud,longitud FROM amb_estaciones '
                              'WHERE fuente_id=? ORDER BY estacion_id', (fuente_id,)).fetchall()
    ingesta = almacen.iniciar(conn, fuente_id, desde_inicial, ahora, inicio=ahora)
    total, reporte, fallos = {}, {}, 0
    for estacion in estaciones:
        desde = ventana(conn, estacion[0], desde_inicial, rellenar)
        if desde is None:
            reporte[estacion[0]] = {'estado': 'requiere_desde_inicial'}
            continue
        try:
            reporte[estacion[0]] = {'desde': almacen.iso_utc(desde), 'estado': 'procesada',
                                    **CONECTORES[fuente_id](conn, ingesta, estacion, desde, ahora, bajar, crudos, total)}
        except SinPublicacion:
            reporte[estacion[0]] = {'estado': 'sin_publicacion'}
        except (FalloFuente, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            fallos += 1
            reporte[estacion[0]] = {'estado': 'fallo', 'error_tipo': type(exc).__name__, 'detalle': str(exc)[:200]}
    if fallos:
        estado = 'fallo'
    elif total.get('insertadas') or total.get('revisiones'):
        estado = 'exito'
    elif any(v.get('estado') == 'procesada' for v in reporte.values()):
        estado = 'sin_datos_nuevos'
    else:
        estado = 'sin_publicacion'
    almacen.cerrar(conn, ingesta, estado, total, 'fallo_estacion' if fallos else None, reporte)
    return {'fuente_id': fuente_id, 'ingesta_id': ingesta, 'estado': estado, **total, 'estaciones': reporte}


def corresponde(conn, fuentes, ahora):
    local = ahora.astimezone(almacen.ZONA)
    if local.hour < HORA_DIARIA:
        return False
    inicio_dia = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    marcas = ','.join('?' for _ in fuentes)
    hechas = {r[0] for r in conn.execute(
        f'''SELECT DISTINCT fuente_id FROM amb_ingestas WHERE fuente_id IN ({marcas})
            AND estado IN ('exito','sin_datos_nuevos','sin_publicacion') AND inicio_utc>=?''',
        (*fuentes, almacen.iso_utc(inicio_dia)))}
    return bool(set(fuentes) - hechas)


def huella_legada(db):
    """Huella lógica de todas las tablas que no son amb_* (las de la tarea horaria y la calidad)."""
    tablas_snapshot = snapshot(db)['tables']
    return {k: v['sha256'] for k, v in tablas_snapshot.items() if not k.startswith('amb_')}


def respaldar(db, ahora):
    """Copia consistente y verificada antes de escribir en la base principal. Nunca borra respaldos."""
    destino = db.parent / 'backups' / (
        'aeris_before_ambiental_' + ahora.strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8] + '.db')
    destino.parent.mkdir(parents=True, exist_ok=True)
    ops.copy_database(db, destino)
    original, copia = snapshot(db), snapshot(destino)
    if original != copia or original['integrity_check'] != ['ok']:
        raise RuntimeError('El respaldo previo no coincide con la base; no se escribe nada')
    return {'ruta': str(destino), 'sha256': sha(destino), 'verificado': True,
            'huella_legada': {k: v['sha256'] for k, v in original['tables'].items() if not k.startswith('amb_')}}


def ejecutar(db, fuentes=None, si_corresponde=False, desde_inicial=None, permitir_base_principal=False,
             ahora=None, bajar=descargar, crudos=None, rellenar=False):
    """rellenar=True usa desde_inicial aunque haya estado: recarga histórica, igualmente idempotente."""
    db = Path(db).resolve()
    ahora = ahora or datetime.now(timezone.utc)
    reporte = {'iniciado_utc': almacen.iso_utc(ahora), 'base': str(db), 'resultados': []}
    with closing(conectar(db)) as conn:
        exigir_base_permitida(conn, permitir_base_principal)
        if version(conn) < 1:
            raise RuntimeError('Capa ambiental sin migrar')
        autorizadas = {r[0] for r in conn.execute('SELECT fuente_id FROM amb_fuentes WHERE autorizada=1')}
        pedidas = list(fuentes or sorted(autorizadas))
        reporte['no_autorizadas'] = sorted(set(pedidas) - autorizadas)
        pedidas = [f for f in pedidas if f in autorizadas]
        if si_corresponde and not corresponde(conn, pedidas, ahora):
            reporte['estado'] = 'no_corresponde'
            return reporte
        principal = 'mediciones' in tablas(conn)
        with ExitStack() as pila:
            pila.enter_context(ops.exclusive_lock(Path(str(db) + '.ambiental.lock')))
            if principal:
                # Misma base que la tarea horaria: nunca escribir a la vez que ella.
                pila.enter_context(ops.exclusive_lock(Path(str(db) + '.sync.lock')))
                reporte['respaldo'] = respaldar(db, ahora)
            for fuente in pedidas:
                reporte['resultados'].append(sincronizar_fuente(conn, fuente, ahora, desde_inicial, bajar, crudos, rellenar))
            if principal:
                if huella_legada(db) != reporte['respaldo']['huella_legada']:
                    raise RuntimeError('Las tablas existentes cambiaron durante la actualización ambiental')
                reporte['legado_intacto'] = True
        integridad = conn.execute('PRAGMA integrity_check').fetchone()[0]
        claves = len(conn.execute('PRAGMA foreign_key_check').fetchall())
    reporte['integridad'] = {'integrity_check': integridad, 'foreign_key_violations': claves}
    correcto = integridad == 'ok' and not claves and all(
        r['estado'] in ESTADOS_CORRECTOS for r in reporte['resultados'])
    reporte['estado'] = 'correcto' if correcto else 'con_fallos'
    return reporte


def escribir_reporte(db, reporte):
    directorio = Path(db).resolve().parent / 'sync_runtime' / 'ambiental'
    directorio.mkdir(parents=True, exist_ok=True)
    ruta = directorio / (uuid.uuid4().hex + '.json')
    texto = json.dumps(reporte, ensure_ascii=False, indent=2, default=str)
    ruta.write_text(texto, encoding='utf8')
    if reporte.get('estado') == 'correcto':
        temporal = directorio / ('ultimo_correcto.' + uuid.uuid4().hex + '.tmp')
        temporal.write_text(texto, encoding='utf8')
        temporal.replace(directorio / 'ultimo_correcto.json')
    return ruta


def diario(db, bajar=descargar, ahora=None):
    """Paso opcional de la tarea horaria existente. Inactivo salvo AERIS_AMBIENTAL_DIARIO=apply.

    Nunca lanza: un fallo ambiental queda en su propio reporte y no altera el resultado de OpenAQ.
    """
    if os.environ.get(DIARIO_ENV) != 'apply':
        return {'estado': 'desactivado'}
    db = Path(db).resolve()
    try:
        reporte = ejecutar(db, si_corresponde=True, permitir_base_principal=True, ahora=ahora, bajar=bajar,
                           crudos=db.parent / 'raw' / 'ambiental')
    except Exception as exc:
        reporte = {'estado': 'fallo_entrada', 'error_tipo': type(exc).__name__, 'detalle': str(exc)[:200]}
    if reporte['estado'] != 'no_corresponde':
        reporte['finalizado_utc'] = almacen.iso_utc(datetime.now(timezone.utc))
        reporte['reporte'] = str(escribir_reporte(db, reporte))
    return reporte


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--fuente', action='append')
    parser.add_argument('--desde', help='Inicio UTC explícito para estaciones sin estado, p. ej. 2026-10-01T00:00:00Z')
    parser.add_argument('--si-corresponde', action='store_true')
    parser.add_argument('--crudos', type=Path, help='Carpeta para conservar las respuestas originales')
    parser.add_argument('--rellenar', action='store_true', help='Con --desde, recarga desde esa fecha aunque haya estado')
    parser.add_argument('--permitir-base-principal', action='store_true')
    args = parser.parse_args(argv)
    if args.rellenar and not args.desde:
        parser.error('--rellenar requiere --desde')
    if not args.db.is_file():
        parser.error('La base no existe; ejecutar primero la migración')
    desde = utc(args.desde) if args.desde else None
    if desde is not None and desde.tzinfo is None:
        parser.error('--desde requiere zona horaria explícita')
    try:
        reporte = ejecutar(args.db, args.fuente, args.si_corresponde, desde, args.permitir_base_principal,
                           crudos=args.crudos, rellenar=args.rellenar,
                           bajar=descargar)  # se resuelve al llamar: las pruebas pueden sustituirlo
    except (OSError, sqlite3.Error, PermissionError, RuntimeError) as exc:
        reporte = {'estado': 'fallo_entrada', 'error_tipo': type(exc).__name__, 'detalle': str(exc)[:200],
                   'finalizado_utc': almacen.iso_utc(datetime.now(timezone.utc))}
    else:
        reporte['finalizado_utc'] = almacen.iso_utc(datetime.now(timezone.utc))
    ruta = escribir_reporte(args.db, reporte)
    resumen = {k: reporte.get(k) for k in ('estado', 'no_autorizadas')}
    resumen['resultados'] = [{k: r.get(k) for k in ('fuente_id', 'estado', 'leidas', 'insertadas', 'duplicadas',
                              'revisiones', 'descartadas')} for r in reporte.get('resultados', [])]
    print(json.dumps({**resumen, 'reporte': str(ruta)}, ensure_ascii=False))
    return 0 if reporte['estado'] in ('correcto', 'no_corresponde') else 1


if __name__ == '__main__':
    raise SystemExit(main())
