"""Derivado de demostración para Railway: instantánea sanitizada + recorte de la capa ambiental.

Producción se lee solo con mode=ro (Backup API, vía prepare_web_snapshot.prepare). La capa
ambiental se copia desde la base de desarrollo, nunca desde ni hacia producción. Solo escribe
en una carpeta nueva excluida de Git. Sin red.
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_web_snapshot import prepare, sha
from data_ingestion.ambiental import esquema
from data_ingestion.production_preflight import snapshot
from railway_start import verify

CATALOGO = {'amb_fuentes': 'fuente_id,nombre,organizacion,url,documentacion_url,licencia,atribucion,'
                           'tipo_producto,metodo_acceso,notas',
            'amb_estaciones': '*', 'amb_variables': '*'}
LEGADO = lambda db: {k: v['sha256'] for k, v in snapshot(db)['tables'].items() if not k.startswith('amb_')}


def copiar_ambiental(destino, desarrollo, desde, estaciones=None):
    """Copia observaciones >= desde y su procedencia; ingestas y rutas quedan sanitizadas."""
    with closing(esquema.conectar(destino)) as conn:
        with patch.dict(os.environ, {esquema.AUTORIZACION_ENV: 'autorizado'}):
            esquema.migrar(conn, permitir_base_principal=True)
    # ATTACH con mode=ro exige una conexión abierta en modo URI.
    with closing(sqlite3.connect(Path(destino).resolve().as_uri(), uri=True)) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('ATTACH DATABASE ? AS dev', (Path(desarrollo).resolve().as_uri() + '?mode=ro',))
        # El catálogo del derivado es el versionado en código; desarrollo debe coincidir (salvo autorizada).
        for tabla, columnas in CATALOGO.items():
            if conn.execute(f'SELECT {columnas} FROM main.{tabla} ORDER BY 1').fetchall() != \
               conn.execute(f'SELECT {columnas} FROM dev.{tabla} ORDER BY 1').fetchall():
                raise RuntimeError(f'Catálogo de desarrollo distinto del versionado: {tabla}')
        filtro = 'o.fecha_utc>=?'
        valores = [desde]
        if estaciones:
            filtro += ' AND o.estacion_id IN (' + ','.join('?' for _ in estaciones) + ')'
            valores += list(estaciones)
        with conn:
            conn.execute(f'''CREATE TEMP TABLE elegidas AS SELECT o.id FROM dev.amb_observaciones o WHERE {filtro}''', valores)
            conn.execute('''INSERT INTO main.amb_ingestas SELECT ingesta_id,fuente_id,inicio_utc,fin_utc,estado,
                ventana_desde_utc,ventana_hasta_utc,leidas,insertadas,duplicadas,revisiones,descartadas,error_tipo,'{}'
                FROM dev.amb_ingestas''')
            conn.execute('''INSERT INTO main.amb_archivos SELECT sha256,url,consultado_utc,bytes,etag,last_modified,
                '[withheld]',ingesta_id FROM dev.amb_archivos''')
            conn.execute('INSERT INTO main.amb_observaciones SELECT * FROM dev.amb_observaciones WHERE id IN (SELECT id FROM elegidas)')
            conn.execute('''INSERT INTO main.amb_revisiones SELECT * FROM dev.amb_revisiones
                WHERE observacion_id IN (SELECT id FROM elegidas)''')
            conn.execute('INSERT INTO main.amb_estado SELECT * FROM dev.amb_estado')
            # La demostración nunca ingiere: ninguna fuente queda autorizada para actualizar.
            conn.execute('UPDATE main.amb_fuentes SET autorizada=0')
        conn.execute('DETACH DATABASE dev')
        conn.execute('ANALYZE')
        conteos = dict(conn.execute('SELECT estacion_id,COUNT(*) FROM amb_observaciones GROUP BY 1').fetchall())
        if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or conn.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('Derivado ambiental inválido')
    with closing(sqlite3.connect(destino)) as conn:
        conn.execute('VACUUM')
    return conteos


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Base principal (solo lectura)')
    parser.add_argument('--dev-db', type=Path, required=True, help='Base ambiental de desarrollo')
    parser.add_argument('--desde', default='2025-06-01T00:00:00Z')
    parser.add_argument('--estacion', action='append', help='Limitar estaciones ambientales (repetible)')
    parser.add_argument('--output-dir', type=Path,
                        default=ROOT / 'reports/beta_snapshots' / ('ambiental-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')))
    args = parser.parse_args(argv)
    destino_relativo = (args.output_dir.resolve() / 'aeris.db').relative_to(ROOT)
    if subprocess.run(['git', 'check-ignore', str(destino_relativo)], cwd=ROOT, capture_output=True).returncode:
        raise RuntimeError('La salida debe estar excluida de Git')
    inicio_fuente = sha(args.source)
    base = prepare(args.source, args.output_dir)
    db = args.output_dir.resolve() / 'aeris.db'
    legado = LEGADO(db)
    conteos = copiar_ambiental(db, args.dev_db, args.desde, args.estacion)
    if LEGADO(db) != legado:
        raise RuntimeError('La capa ambiental alteró tablas existentes del derivado')
    final = sha(db)
    verify(db, final)  # Misma verificación que railway_start.py en el arranque.
    manifiesto = {**base, 'sha256': final, 'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                  'format': 'aeris-web-snapshot-v1', 'bytes': db.stat().st_size,
                  'ambiental': {'migracion': max(esquema.MIGRACIONES), 'desde_utc': args.desde, 'observaciones_por_estacion': conteos,
                                'fuentes_autorizadas_para_ingesta': 0},
                  'legado_sin_cambios_tras_capa_ambiental': True,
                  'fuente_cambio_durante_preparacion': sha(args.source) != inicio_fuente}
    (args.output_dir / 'manifest.json').write_text(json.dumps(manifiesto, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({k: manifiesto[k] for k in ('sha256', 'created_utc', 'bytes', 'ambiental',
                      'fuente_cambio_durante_preparacion')}, indent=2, ensure_ascii=False))
    print('Derivado:', db)


if __name__ == '__main__':
    main()
