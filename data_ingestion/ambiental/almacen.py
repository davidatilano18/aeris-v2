"""Escritura idempotente: inserta solo claves nuevas; las diferencias se registran como revisiones."""
import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .esquema import ahora

ZONA = ZoneInfo('America/Mexico_City')  # Querétaro; incluye el horario de verano vigente hasta 2022.


def iso_utc(fecha):
    if fecha.tzinfo is None:
        raise ValueError('Fecha sin zona horaria: no se asume ninguna')
    return fecha.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def iso_local(fecha):
    return fecha.astimezone(ZONA).isoformat(timespec='seconds')


def iniciar(conn, fuente_id, desde=None, hasta=None, inicio=None):
    ingesta_id = uuid.uuid4().hex
    with conn:
        conn.execute('''INSERT INTO amb_ingestas(ingesta_id,fuente_id,inicio_utc,estado,ventana_desde_utc,ventana_hasta_utc)
            VALUES (?,?,?,'en_curso',?,?)''', (ingesta_id, fuente_id, iso_utc(inicio) if inicio else ahora(),
            desde and iso_utc(desde), hasta and iso_utc(hasta)))
    return ingesta_id


def cerrar(conn, ingesta_id, estado, conteos=None, error_tipo=None, reporte=None):
    c = conteos or {}
    with conn:
        conn.execute('''UPDATE amb_ingestas SET fin_utc=?,estado=?,leidas=?,insertadas=?,duplicadas=?,
            revisiones=?,descartadas=?,error_tipo=?,reporte_json=? WHERE ingesta_id=?''',
            (ahora(), estado, c.get('leidas', 0), c.get('insertadas', 0), c.get('duplicadas', 0),
             c.get('revisiones', 0), c.get('descartadas', 0), error_tipo,
             json.dumps(reporte or {}, ensure_ascii=False, sort_keys=True), ingesta_id))


def registrar_archivo(conn, ingesta_id, respuesta, ruta_local=None):
    conn.execute('INSERT OR IGNORE INTO amb_archivos VALUES (?,?,?,?,?,?,?,?)',
                 (respuesta.sha256, respuesta.url, ahora(), len(respuesta.contenido), respuesta.etag,
                  respuesta.last_modified, ruta_local and str(ruta_local), ingesta_id))


def guardar(conn, ingesta_id, registros, archivo_sha256=None, ahora_utc=None):
    """Una transacción por lote. Nunca actualiza ni borra observaciones existentes."""
    limite_futuro = (ahora_utc or datetime.now(timezone.utc)) + timedelta(hours=1)
    rangos = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
        'SELECT variable_id,unidad,minimo_fisico,maximo_fisico FROM amb_variables')}
    conteos = {'leidas': 0, 'insertadas': 0, 'duplicadas': 0, 'revisiones': 0, 'descartadas': 0}
    motivos = {}
    registrada = ahora()
    with conn:
        for r in registros:
            conteos['leidas'] += 1
            unidad, minimo, maximo = rangos[r['variable_id']]
            motivo = None
            if not math.isfinite(r['valor']):
                motivo = 'no_finito'
            elif r['fecha'] > limite_futuro:
                motivo = 'fecha_futura'
            if motivo:
                conteos['descartadas'] += 1
                motivos[motivo] = motivos.get(motivo, 0) + 1
                continue
            fecha = iso_utc(r['fecha'])
            clave = (r['estacion_id'], r['variable_id'], fecha, r['tipo_reporte'])
            previo = conn.execute('''SELECT id,valor_original,calidad_origen FROM amb_observaciones
                WHERE estacion_id=? AND variable_id=? AND fecha_utc=? AND tipo_reporte=?''', clave).fetchone()
            if previo is None:
                conn.execute('''INSERT INTO amb_observaciones(estacion_id,variable_id,fecha_utc,fecha_local,valor,
                    unidad,valor_original,unidad_original,periodo,tipo_reporte,codigo_medicion,calidad_origen,
                    marca_origen,fuera_de_rango,archivo_sha256,ingesta_id,registrada_utc)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (*clave[:3], iso_local(r['fecha']), r['valor'], unidad, r['valor_original'],
                     r['unidad_original'], r['periodo'], r['tipo_reporte'], r.get('codigo_medicion', ''),
                     r.get('calidad_origen', ''), int(bool(r.get('marca_origen'))),
                     int(not minimo <= r['valor'] <= maximo), archivo_sha256, ingesta_id, registrada))
                conteos['insertadas'] += 1
                continue
            cambia_valor = previo[1] != r['valor_original']
            cambia_calidad = previo[2] != r.get('calidad_origen', '')
            if not (cambia_valor or cambia_calidad):
                conteos['duplicadas'] += 1
                continue
            tipo = 'valor_y_calidad' if cambia_valor and cambia_calidad else 'valor' if cambia_valor else 'calidad'
            nueva = conn.execute('''INSERT OR IGNORE INTO amb_revisiones(observacion_id,tipo,valor_original_nuevo,
                calidad_origen_nueva,ingesta_id,archivo_sha256,registrada_utc) VALUES (?,?,?,?,?,?,?)''',
                (previo[0], tipo, r['valor_original'], r.get('calidad_origen', ''), ingesta_id,
                 archivo_sha256, registrada)).rowcount
            conteos['revisiones' if nueva else 'duplicadas'] += 1
    conteos['motivos_descarte'] = motivos
    return conteos


def actualizar_estado(conn, estacion_id, completo_hasta, ingesta_id):
    ultima = conn.execute('SELECT MAX(fecha_utc) FROM amb_observaciones WHERE estacion_id=?',
                          (estacion_id,)).fetchone()[0]
    with conn:
        conn.execute('''INSERT INTO amb_estado VALUES (?,?,?,?,?) ON CONFLICT(estacion_id) DO UPDATE SET
            completo_hasta_utc=NULLIF(MAX(COALESCE(amb_estado.completo_hasta_utc,''),
                COALESCE(excluded.completo_hasta_utc,'')),''),
            ultima_observacion_utc=excluded.ultima_observacion_utc,
            ultima_ingesta_id=excluded.ultima_ingesta_id,actualizado_utc=excluded.actualizado_utc''',
            (estacion_id, completo_hasta and iso_utc(completo_hasta), ultima, ingesta_id, ahora()))


def estado(conn, estacion_id):
    fila = conn.execute('SELECT completo_hasta_utc,ultima_observacion_utc FROM amb_estado WHERE estacion_id=?',
                        (estacion_id,)).fetchone()
    return fila or (None, None)
