"""Create new sanitized read-only derivatives, never change the source databases."""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_web_snapshot import prepare, sha


def build(pm25, ambiental, output):
    output = Path(output).resolve()
    sources = {'pm25': Path(pm25).resolve()}
    if ambiental:
        sources['ambiental'] = Path(ambiental).resolve()
    if output.exists() or any(output == source.parent for source in sources.values()):
        raise ValueError('Use a new external directory, never overwrite a bundle')
    if any(part in ('static', 'templates', '.git') for part in output.parts):
        raise ValueError('Bundle must not be public or in Git internals')
    output.mkdir(parents=True, exist_ok=False)
    result = {'format': 'aeris-demo-bundle-v1', 'created_utc': datetime.now(timezone.utc).isoformat(),
              'purpose': 'local scientific demonstration; not a forensic backup', 'datasets': {}}
    for name, source in sources.items():
        before = sha(source)
        info = prepare(source, output/name)
        copy = output/name/'aeris.db'
        # Meteorological values/revisions must survive sanitization exactly.
        if name == 'ambiental':
            connections = [sqlite3.connect(p.as_uri()+'?mode=ro', uri=True) for p in (source, copy)]
            try:
                for conn in connections:
                    conn.execute('PRAGMA query_only=ON')
                for table in ('amb_observaciones', 'amb_revisiones'):
                    a = connections[0].execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()
                    b = connections[1].execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()
                    if a != b:
                        raise RuntimeError('Environmental values changed during snapshot')
            finally:
                for conn in connections:
                    conn.close()
        if before != sha(source):
            raise RuntimeError('Source changed concurrently; keep evidence and prepare a new bundle later')
        os.chmod(copy, 0o444)
        result['datasets'][name] = {'file': name+'/aeris.db', 'sha256': info['sha256'],
                                    'rows': info['rows'], 'redactions': info['redactions']}
    (output/'demo.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pm25', type=Path, required=True)
    parser.add_argument('--ambiental', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.pm25, args.ambiental, args.output)
    print(json.dumps({'format': result['format'], 'datasets': list(result['datasets'])}))
