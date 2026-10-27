"""Protocol fixtures for local launcher, not demonstration environmental data."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from scripts.run_local_demo import verify_bundle
from scripts.prepare_local_demo import build


class DemoBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=self.root/'source.db'
        conn=sqlite3.connect(self.source);conn.execute('CREATE TABLE mediciones(value REAL)');conn.execute('INSERT INTO mediciones VALUES(1)');conn.commit();conn.close()
        self.bundle=self.root/'bundle'
        build(self.source,None,self.bundle)
        self.manifest=self.bundle/'demo.json'
    def tearDown(self):
        for p in self.root.rglob('*.db'):p.chmod(0o666)
        self.temp.cleanup()
    def test_bundle_is_read_only_and_source_preserved(self):
        before=hashlib.sha256(self.source.read_bytes()).hexdigest()
        data,paths=verify_bundle(self.manifest)
        self.assertEqual(set(paths),{'pm25'})
        conn=sqlite3.connect(paths['pm25'].as_uri()+'?mode=ro',uri=True)
        try:
            with self.assertRaises(sqlite3.OperationalError):conn.execute('DELETE FROM mediciones')
        finally:conn.close()
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),before)
    def test_hash_tamper_is_refused(self):
        data=json.loads(self.manifest.read_text());data['datasets']['pm25']['sha256']='0'*64;self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'hash'):verify_bundle(self.manifest)
    def test_path_escape_is_refused(self):
        data=json.loads(self.manifest.read_text());data['datasets']['pm25']['file']='../source.db';self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'inside'):verify_bundle(self.manifest)
    def test_existing_bundle_cannot_be_overwritten(self):
        with self.assertRaises(ValueError):build(self.source,None,self.bundle)
