"""Prepare an exact review manifest; never stage, commit, push or deploy."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_web_release import PATTERNS, git
import re


def release_files(root=ROOT):
    explicit = ['.gitignore', '.dockerignore', 'Dockerfile', 'railway.json',
                'requirements-web.txt', 'requirements-web-linux.lock', 'app.py',
                'wsgi.py', 'gunicorn.conf.py', 'railway_start.py', 'railway_acceptance.py',
                'data/openaq_stations.json', 'static/logo.png',
                'data_ingestion/__init__.py', 'data_ingestion/catalog.py', 'data_ingestion/visibility.py',
                'scripts/prepare_web_snapshot.py', 'scripts/audit_web_release.py',
                'scripts/prepare_railway_release.py', 'scripts/validate_railway_readiness.py',
                'tests/test_web_deployment.py', 'tests/test_railway_readiness.py',
                'tests/test_railway_entry_regression.py',
                'docs/aeris_web_beta_validation.md', 'docs/aeris_railway_deployment_readiness.md',
                'docs/aeris_railway_first_deployment_debug.md']
    selected = {root / name for name in explicit}
    selected.update((root / 'aeris_web').glob('*.py'))
    selected.update((root / 'cuentas').glob('*.py'))
    selected.update({root / 'alertas/__init__.py', root / 'alertas/lecturas.py'})
    for folder in ('templates/v2', 'templates/cuentas', 'static/v2'):
        selected.update(p for p in (root / folder).rglob('*') if p.is_file())
    return sorted(p.relative_to(root).as_posix() for p in selected)


def inspect(root, files):
    findings, records = [], []
    for name in files:
        path = root / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            findings.append(dict(path=name, kind='missing-or-unsafe-path'))
            continue
        content = path.read_bytes()
        if content.startswith(b'SQLite format 3\0') or path.suffix.lower() in {'.db', '.sqlite', '.sqlite3'}:
            findings.append(dict(path=name, kind='database'))
        for label, pattern in PATTERNS.items():
            if re.search(pattern, content):
                findings.append(dict(path=name, kind=label))
        records.append(dict(path=name, sha256=hashlib.sha256(content).hexdigest()))
    return records, findings


def main():
    files = release_files()
    records, findings = inspect(ROOT, files)
    report = dict(branch=git('branch', '--show-current').decode().strip(),
                  base_commit=git('rev-parse', 'HEAD').decode().strip(),
                  prepared_only=True, staged=False, committed=False, pushed=False,
                  files=records, findings=findings)
    (ROOT / 'reports/aeris_railway_release_manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (ROOT / 'reports/aeris_railway_release_files.txt').write_text('\n'.join(files) + '\n', encoding='utf-8')
    print(json.dumps(dict(files=len(files), findings=findings, git_mutations=False), indent=2))
    if findings:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
