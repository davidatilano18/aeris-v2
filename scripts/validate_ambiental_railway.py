"""Valida un derivado de demostración como lo serviría Railway, sin red ni Docker.

1. Copia a una carpeta temporal solo lo que las instrucciones COPY del Dockerfile ponen en la imagen.
2. Desde esa copia, importa la app en perfil beta/railway contra el derivado y recorre las rutas
   públicas (v2 y ambiental), midiendo tiempos. Comprueba solo lectura y que el hash no cambie.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SONDA = r'''
import json, os, sys, time, hashlib
db = os.environ['AERIS_DB_PATH']
def h():
    with open(db, 'rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()
antes = h()
from wsgi import application
cliente = application.test_client()
E = 'ghcnh:MXI0000MMQT'
rutas = [
 '/health/live', '/health/ready', '/favicon.ico', '/inicio', '/inicio?experiencia=inmersiva', '/inicio/aprende', '/inicio/datos', '/inicio/datos/pm25-diario.csv', '/inicio/datos/meteorologia-mmqt.csv', '/inicio/explorar', '/inicio/anterior', '/v2', '/v2/datos', '/api/v2/stations', '/api/v2/observations?period=7d',
 '/api/v2/public', '/api/v2/comparison?station=1352676&anchor=latest',
 '/api/ambiental/v1/fuentes', '/api/ambiental/v1/variables', '/api/ambiental/v1/estaciones',
 '/api/ambiental/v1/ingestas',
 f'/api/ambiental/v1/observaciones?estacion={E}&variable=temperatura_aire,humedad_relativa,viento_velocidad,viento_direccion&desde=2026-09-18T00:00:00Z&hasta=2026-10-19T00:00:00Z&resolucion=hora',
 f'/api/ambiental/v1/observaciones?estacion={E}&variable=temperatura_aire&desde=2025-10-19T00:00:00Z&hasta=2026-10-19T00:00:00Z&resolucion=hora',
 '/api/ambiental/v1/observaciones?estacion=power:mmqt&variable=temperatura_aire,precipitacion&desde=2026-07-01T00:00:00Z&hasta=2026-10-19T00:00:00Z',
 f'/api/ambiental/v1/cobertura?estacion={E}&variable=temperatura_aire,visibilidad&desde=2025-10-19T00:00:00Z&hasta=2026-10-19T00:00:00Z',
]
resultado = {'rutas': {}, 'errores': []}
for ruta in rutas:
    tiempos = []
    for _ in range(5):
        t = time.perf_counter(); r = cliente.get(ruta, headers={'Host': 'localhost'}); tiempos.append(time.perf_counter() - t)
    resultado['rutas'][ruta.split('?')[0] + ('?' + ruta.split('?')[1][:60] if '?' in ruta else '')] = {
        'status': r.status_code, 'bytes': len(r.data), 'ms_mediana': round(sorted(tiempos)[2] * 1000, 1),
        'ms_max': round(max(tiempos) * 1000, 1)}
    if r.status_code != 200: resultado['errores'].append(ruta)
resultado['post_rechazado'] = cliente.post('/api/ambiental/v1/fuentes', headers={'Host': 'localhost'}).status_code
resultado['host_no_confiable'] = cliente.get('/api/ambiental/v1/fuentes', headers={'Host': 'evil.example'}).status_code
resultado['modulos_escritores_importados'] = sorted(m for m in sys.modules if m.startswith(('data_ingestion.ambiental', 'data_ingestion.operations', 'forecasting')))
# Escritores, ingesta, modelos y holdout no deben existir dentro de la imagen.
resultado['modulos_escritores_disponibles'] = [p for p in ('data_ingestion/ambiental', 'data_ingestion/operations.py',
    'data_ingestion/scheduled_sync.py', 'forecasting', 'models', '.secrets') if os.path.exists(p)]
resultado['hash_sin_cambios'] = h() == antes
resultado['base_ambiental_servida'] = str(application.extensions['aeris_ambiental_database']())
print(json.dumps(resultado))
'''


def permitidos():
    """Archivos que las instrucciones COPY del Dockerfile llevan a la imagen (sin __pycache__)."""
    archivos = []
    for linea in (ROOT / 'Dockerfile').read_text(encoding='utf-8').splitlines():
        partes = linea.split()
        if not partes or partes[0] != 'COPY' or any(x.startswith('--') for x in partes):
            continue
        for fuente in partes[1:-1]:
            ruta = ROOT / fuente
            candidatos = ruta.rglob('*') if ruta.is_dir() else [ruta]
            archivos += [c.relative_to(ROOT).as_posix() for c in candidatos
                         if c.is_file() and '__pycache__' not in c.parts]
    return sorted(set(archivos))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/aeris_ambiental_railway_validation.json')
    args = parser.parse_args(argv)
    carpeta = args.snapshot_dir.resolve()
    manifiesto = json.loads((carpeta / 'manifest.json').read_text(encoding='utf-8'))
    db = carpeta / 'aeris.db'
    with tempfile.TemporaryDirectory(prefix='aeris-imagen-') as temporal:
        contexto = Path(temporal)
        lista = permitidos()
        for relativa in lista:
            destino = contexto / relativa
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relativa, destino)
        entorno = {k: v for k, v in os.environ.items() if not k.startswith(('AERIS_', 'OPENAQ_'))}
        entorno.update({
            'AERIS_ENV': 'beta', 'AERIS_DB_PATH': str(db), 'AERIS_DEPLOYMENT_PROFILE': 'railway',
            'AERIS_SNAPSHOT_SHA256': manifiesto['sha256'], 'AERIS_SNAPSHOT_CREATED_UTC': manifiesto['created_utc'],
            'AERIS_TRUSTED_HOSTS': 'localhost,127.0.0.1,healthcheck.railway.app', 'AERIS_PROXY_HOPS': '0',
            # Debe ignorarse en beta: la API ambiental solo sirve la instantánea verificada.
            'AERIS_AMBIENTAL_DB_PATH': str(ROOT / 'data/dev/aeris_ambiental_dev.db'),
            'PYTHONDONTWRITEBYTECODE': '1',
        })
        proceso = subprocess.run([sys.executable, '-I', '-c', 'import sys; sys.path.insert(0, ""); exec(sys.stdin.read())'],
                                 input=SONDA, cwd=contexto, env=entorno, capture_output=True, text=True, timeout=600)
        if proceso.returncode:
            raise SystemExit('La sonda falló:\n' + proceso.stderr[-3000:])
        resultado = json.loads(proceso.stdout.strip().splitlines()[-1])
    resultado.update({'snapshot_sha256': manifiesto['sha256'], 'snapshot_bytes': db.stat().st_size,
                      'archivos_en_imagen_simulada': len(lista),
                      'python': sys.version.split()[0], 'plataforma': sys.platform,
                      'nota': 'Contexto Docker simulado en este equipo; no sustituye una ejecución Linux/Gunicorn real.'})
    resultado['correcto'] = (not resultado['errores'] and resultado['hash_sin_cambios']
                             and resultado['post_rechazado'] == 405 and resultado['host_no_confiable'] == 400
                             and not resultado['modulos_escritores_disponibles']
                             and Path(resultado['base_ambiental_servida']).resolve() == db)
    args.output.write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    return 0 if resultado['correcto'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
