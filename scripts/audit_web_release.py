"""Read-only Git release inspection. Reports locations, never secret values.

Heuristic scan of current tracked contents; not a certification of Git history.
"""
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'private-key': rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'github-token': rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b',
    'aws-access-id': rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'credential-literal': rb'''(?i)(?:OPENAQ_API_KEY|RAILWAY_TOKEN|RAILWAY_API_TOKEN|SECRET_KEY)\s*[=:]\s*["']([A-Za-z0-9_+/=.-]{20,})["']''',
    'authenticated-url': rb'https?://[^\s/"<>]+:[^\s/@"<>]+@',
}


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    tracked = git('ls-files', '-z').decode().split('\0')[:-1]
    findings = []
    inventory = []
    for name in tracked:
        path = ROOT / name
        if not path.is_file():
            findings.append(dict(path=name, kind='missing-worktree-file'))
            continue
        data = path.read_bytes()
        inventory.append(dict(path=name, sha256=hashlib.sha256(data).hexdigest()))
        if data.startswith(b'SQLite format 3\0') or path.suffix.lower() in {'.db', '.sqlite', '.sqlite3'}:
            findings.append(dict(path=name, kind='database'))
        if name.startswith(('.secrets/', '.ssh/', '.aws/')) or path.name == '.env':
            findings.append(dict(path=name, kind='sensitive-file'))
        for label, pattern in PATTERNS.items():
            if re.search(pattern, data):
                findings.append(dict(path=name, kind=label))
    # Contents selected for the image, including currently untracked app modules.
    candidates = [ROOT / x for x in ('app.py', 'wsgi.py', 'gunicorn.conf.py', 'railway_start.py',
                  'railway_acceptance.py', 'data/openaq_stations.json',
                  'data_ingestion/__init__.py', 'data_ingestion/catalog.py', 'data_ingestion/visibility.py')]
    candidates += list((ROOT / 'aeris_web').glob('*.py'))
    candidates += list((ROOT / 'cuentas').glob('*.py'))
    candidates += [ROOT / 'alertas/__init__.py', ROOT / 'alertas/lecturas.py']
    candidates += [p for folder in ('templates', 'static/v2') for p in (ROOT / folder).rglob('*') if p.is_file()]
    release_findings = []
    for path in candidates:
        if not path.is_file():
            release_findings.append(dict(path=path.relative_to(ROOT).as_posix(), kind='missing'))
            continue
        for label, pattern in PATTERNS.items():
            if re.search(pattern, path.read_bytes()):
                release_findings.append(dict(path=path.relative_to(ROOT).as_posix(), kind=label))
    probes = ['data/aeris_air_quality.db', 'data/backups/probe.db', 'reports/tmp_aeris_probe/manifest.json',
              'reports/beta_snapshots/probe/aeris.db', '.env', '.env.production', '.secrets/key.clixml',
              'backups/probe.db.bak', 'snapshot.sqlite-wal', '.ssh/id_rsa']
    ignored = subprocess.run(['git', 'check-ignore', '-z', '--stdin'],
                             input=('\0'.join(probes) + '\0').encode(),
                             cwd=ROOT, capture_output=True).stdout.decode().split('\0')
    result = dict(checked_utc=datetime.now(timezone.utc).isoformat(),
                  branch=git('branch', '--show-current').decode().strip(),
                  tracked_count=len(tracked), tracked_findings=findings,
                  release_files_checked=len(candidates), release_findings=release_findings,
                  ignore_probes={p: p in ignored for p in probes},
                  staged_files=git('diff', '--cached', '--name-only').decode().splitlines(),
                  tracked_csv=[p for p in tracked if p.endswith('.csv')],
                  inventory=inventory,
                  limitation='Heuristic worktree scan; Git history and arbitrary secret formats not certified')
    report = ROOT / 'reports' / 'aeris_railway_git_preflight.json'
    report.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'inventory'}, indent=2))
    if findings or release_findings or not all(result['ignore_probes'].values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
