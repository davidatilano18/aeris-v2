"""Conector del archivo público de OpenAQ para contaminantes distintos de PM2.5 (capa ambiental).

Lee los archivos diarios ya descargados y verificados por `data_ingestion.openaq_archive.download`
(manifiesto aeris-openaq-archive-v1, SHA-256 por archivo). No descarga ni modifica la tabla
`mediciones`: el PM2.5 de los mismos archivos lo importa la herramienta existente.

- Unidad: se exige la canónica (µg/m³ para PM10; ppm para gases). Otra unidad se rechaza, no se convierte.
- Hora: el `datetime` del archivo trae desfase explícito; se normaliza a UTC sin desplazarlo.
- El valor textual original y el sensor de origen se conservan.
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from . import almacen
from .esquema import conectar, exigir_base_permitida, version

FUENTE = 'openaq-archivo'
PREFIJO = 'https://openaq-data-archive.s3.amazonaws.com/records/csv.gz/locationid='
VARIABLES = {'pm10': ('pm10', 'µg/m³'), 'o3': ('o3', 'ppm'), 'no2': ('no2', 'ppm'), 'so2': ('so2', 'ppm'), 'co': ('co', 'ppm')}


def interpretar(texto, estaciones, sha=None):
    """Registros de la capa ambiental a partir de un CSV diario. `estaciones`: location_id -> estacion_id."""
    lector = csv.DictReader(io.StringIO(texto))
    requeridas = {'location_id', 'sensors_id', 'datetime', 'parameter', 'units', 'value'}
    if not requeridas <= set(lector.fieldnames or ()):
        raise ValueError('Columnas de archivo incompatibles')
    registros, descartes = [], {}
    for fila in lector:
        parametro = fila['parameter']
        if parametro not in VARIABLES:
            continue  # PM2.5 va a mediciones; NO y NOx no son contaminantes criterio del índice.
        estacion = estaciones.get(int(fila['location_id']))
        variable, unidad = VARIABLES[parametro]
        motivo = None
        if estacion is None:
            motivo = 'ubicacion_fuera_de_catalogo'
        elif fila['units'] != unidad:
            motivo = 'unidad_no_canonica'
        else:
            try:
                fecha = datetime.fromisoformat(fila['datetime'])
                valor = float(fila['value'])
            except ValueError:
                motivo = 'valor_o_fecha_invalidos'
            else:
                if fecha.tzinfo is None:
                    motivo = 'fecha_sin_zona'
                elif not math.isfinite(valor):
                    motivo = 'no_finito'
        if motivo:
            descartes[motivo] = descartes.get(motivo, 0) + 1
            continue
        registros.append({
            'estacion_id': estacion, 'variable_id': variable, 'fecha': fecha.astimezone(timezone.utc),
            'valor': valor, 'valor_original': fila['value'], 'unidad_original': fila['units'],
            'periodo': 'PT1H', 'tipo_reporte': 'OpenAQ-Archive', 'codigo_medicion': 'sensor ' + fila['sensors_id'],
            'calidad_origen': '', 'marca_origen': False,
        })
    return registros, descartes


def importar(db, manifiesto, raiz, permitir_base_principal=False):
    """Importa todos los archivos del manifiesto en una sola ingesta, idempotente."""
    db, manifiesto, raiz = Path(db).resolve(), Path(manifiesto).resolve(), Path(raiz).resolve()
    datos = json.loads(manifiesto.read_text(encoding='utf-8'))
    if datos.get('format') != 'aeris-openaq-archive-v1':
        raise ValueError('Manifiesto con formato inesperado')
    if any('error' in f for f in datos['files']):
        raise ValueError('El manifiesto tiene descargas fallidas; no se importa')
    with closing(conectar(db)) as conn:
        exigir_base_permitida(conn, permitir_base_principal)
        if version(conn) < 1:
            raise RuntimeError('Capa ambiental sin migrar')
        estaciones = {json.loads(m)['location_id']: e for e, m in conn.execute(
            'SELECT estacion_id,metadatos_json FROM amb_estaciones WHERE fuente_id=?', (FUENTE,))}
        ingesta = almacen.iniciar(conn, FUENTE)
        total, descartes, archivos = {}, {}, 0
        cache = (raiz / 'data' / 'raw' / 'openaq_archive').resolve()
        try:
            for item in datos['files']:
                if not item['url'].startswith(PREFIJO):
                    raise ValueError('URL de origen incompatible')
                ruta = (raiz / item['path']).resolve()
                if not ruta.is_relative_to(cache):
                    raise ValueError('Archivo fuera del caché permitido')
                crudo = ruta.read_bytes()
                if hashlib.sha256(crudo).hexdigest() != item['sha256']:
                    raise ValueError('SHA-256 no coincide')
                registros, d = interpretar(gzip.decompress(crudo).decode('utf-8-sig'), estaciones)
                for k, v in d.items():
                    descartes[k] = descartes.get(k, 0) + v
                with conn:
                    conn.execute('INSERT OR IGNORE INTO amb_archivos VALUES (?,?,?,?,?,?,?,?)',
                                 (item['sha256'], item['url'], almacen.ahora(), item['bytes'], None, None,
                                  item['path'], ingesta))
                conteos = almacen.guardar(conn, ingesta, registros, item['sha256'])
                for k in ('leidas', 'insertadas', 'duplicadas', 'revisiones', 'descartadas'):
                    total[k] = total.get(k, 0) + conteos[k]
                archivos += 1
            for estacion in set(estaciones.values()):
                ultima = conn.execute('SELECT MAX(fecha_utc) FROM amb_observaciones WHERE estacion_id=?', (estacion,)).fetchone()[0]
                if ultima:
                    almacen.actualizar_estado(conn, estacion, datetime.fromisoformat(ultima.replace('Z', '+00:00')), ingesta)
            estado = 'exito' if total.get('insertadas') or total.get('revisiones') else 'sin_datos_nuevos'
            reporte = {'manifiesto': manifiesto.name, 'archivos': archivos, 'descartes': descartes}
            almacen.cerrar(conn, ingesta, estado, total, None, reporte)
        except BaseException as exc:
            almacen.cerrar(conn, ingesta, 'fallo', total, type(exc).__name__, {'archivos': archivos})
            raise
    return {'ingesta': ingesta, 'estado': estado, 'archivos': archivos, **total, 'descartes': descartes}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--manifiesto', type=Path, required=True)
    parser.add_argument('--raiz', type=Path, default=Path('.'), help='Raíz donde está data/raw/openaq_archive')
    parser.add_argument('--permitir-base-principal', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(importar(args.db, args.manifiesto, args.raiz, args.permitir_base_principal), ensure_ascii=False))


if __name__ == '__main__':
    main()
