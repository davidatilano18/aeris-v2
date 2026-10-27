"""Start only the local web with a verified, external immutable demo bundle."""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify_bundle(manifest_path):
    manifest_path = Path(manifest_path).resolve(strict=True)
    data = json.loads(manifest_path.read_text(encoding='utf-8'))
    if data.get('format') != 'aeris-demo-bundle-v1':
        raise ValueError('Unsupported demo manifest')
    paths = {}
    for name, item in data['datasets'].items():
        if name not in ('pm25', 'ambiental'):
            raise ValueError('Unknown dataset')
        raw = manifest_path.parent / item['file']
        if raw.is_symlink() or not raw.is_file():
            raise ValueError('Missing regular dataset')
        path = raw.resolve(strict=True)
        if not path.is_relative_to(manifest_path.parent) or path.suffix != '.db':
            raise ValueError('Dataset must stay inside the demo bundle')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != item['sha256']:
            raise ValueError('Dataset hash mismatch')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as conn:
            conn.execute('PRAGMA query_only=ON')
            if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or conn.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Dataset integrity failure')
            table = 'mediciones' if name == 'pm25' else 'amb_observaciones'
            conn.execute('SELECT COUNT(*) FROM '+table).fetchone()
        paths[name] = path
    if 'pm25' not in paths:
        raise ValueError('PM2.5 dataset required')
    return data, paths


def build_app(manifest_path, offline=False):
    data, paths = verify_bundle(manifest_path)
    for key in list(os.environ):
        if key.startswith('AERIS_') or key in ('OPENAQ_API_KEY', 'RAILWAY_ENVIRONMENT_ID'):
            os.environ.pop(key, None)
    os.environ.update(AERIS_ENV='local', AERIS_DB_PATH=str(paths['pm25']),
                      AERIS_TRUSTED_HOSTS='localhost,127.0.0.1', AERIS_PROXY_HOPS='0')
    if 'ambiental' in paths:
        os.environ['AERIS_AMBIENTAL_DB_PATH'] = str(paths['ambiental'])
    sys.path.insert(0, str(ROOT))
    from app import app

    @app.context_processor
    def demo_context():
        return {'demo_bundle': {'created_utc': data['created_utc'], 'offline': offline}}

    if offline:
        @app.after_request
        def offline_policy(response):
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'")
            return response
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--port', type=int, default=5051)
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Use a local port between 1024 and 65535')
    app = build_app(args.manifest, args.offline)
    print('aeris_demo_verified read_only=true ingestion=false predictions=false', flush=True)
    from aeris_web import precalentar
    precalentar(app)
    app.run(host='127.0.0.1', port=args.port, debug=False, use_reloader=False)


if __name__ == '__main__':
    main()
