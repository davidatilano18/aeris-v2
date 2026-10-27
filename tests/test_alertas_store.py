import sqlite3
import tempfile
import unittest
from pathlib import Path

from alertas import store

NOW = '2026-10-27T12:00:00Z'


class AlertasStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'alertas.db'
        self.conn = store.conectar(self.path)

    def tearDown(self):
        self.conn.close()
        self.folder.cleanup()

    def test_schema_is_created_once_and_reopens(self):
        self.conn.close()
        self.conn = store.conectar(self.path)
        self.assertEqual(store.VERSION, self.conn.execute('PRAGMA user_version').fetchone()[0])

    def test_refuses_measurement_database_and_foreign_sqlite(self):
        with self.assertRaises(ValueError):
            store.conectar(store.MEDICIONES_DB)
        other = Path(self.folder.name) / 'otra.db'
        with sqlite3.connect(other) as conn:
            conn.execute('CREATE TABLE mediciones (x)')
        conn.close()
        with self.assertRaises(sqlite3.DatabaseError):
            store.conectar(other)

    def test_alta_is_idempotent_and_reactivates(self):
        self.assertTrue(store.alta(self.conn, 111, NOW))
        store.pausar(self.conn, 111)
        self.assertFalse(store.alta(self.conn, 111, NOW))
        self.assertEqual(1, self.conn.execute('SELECT activo FROM suscriptores').fetchone()[0])

    def test_subscribe_requires_alta_and_valid_threshold(self):
        with self.assertRaises(ValueError):
            store.suscribir(self.conn, 111, 5, 25)
        store.alta(self.conn, 111, NOW)
        for umbral in (0, -3, 1000):
            with self.assertRaises(ValueError):
                store.suscribir(self.conn, 111, 5, umbral)

    def test_subscribe_updates_same_station_including_all(self):
        store.alta(self.conn, 111, NOW)
        a = store.suscribir(self.conn, 111, 5, 25, now=NOW)
        self.assertEqual(a, store.suscribir(self.conn, 111, 5, 41))
        b = store.suscribir(self.conn, 111, store.TODAS, 25)
        self.assertEqual(b, store.suscribir(self.conn, 111, store.TODAS, 33))
        rows = store.suscripciones(self.conn, 111)
        self.assertEqual([(None, 33.0), (5, 41.0)], [(r['sensor_id'], r['umbral']) for r in rows])

    def test_subscription_limit_per_chat(self):
        store.alta(self.conn, 111, NOW)
        for sid in range(store.MAX_SUSCRIPCIONES):
            store.suscribir(self.conn, 111, sid, 25)
        with self.assertRaises(ValueError):
            store.suscribir(self.conn, 111, 999, 25)

    def test_quiet_hours_per_chat(self):
        store.alta(self.conn, 111, NOW)
        store.suscribir(self.conn, 111, 5, 25)
        self.assertTrue(store.silenciar(self.conn, 111, 23, 7))
        self.assertEqual((23, 7), (store.activas(self.conn)[0]['silencio_desde'], store.activas(self.conn)[0]['silencio_hasta']))
        for bad in ((23, None), (24, 7), (5, 5)):
            with self.assertRaises(ValueError):
                store.silenciar(self.conn, 111, *bad)
        store.silenciar(self.conn, 111)
        self.assertIsNone(store.suscriptor(self.conn, 111)['silencio_desde'])

    def test_paused_chats_are_not_active(self):
        for chat in (111, 222):
            store.alta(self.conn, chat, NOW)
            store.suscribir(self.conn, chat, 5, 25)
        store.pausar(self.conn, 222)
        self.assertEqual([111], [r['chat_id'] for r in store.activas(self.conn)])

    def test_last_notice_per_station(self):
        store.alta(self.conn, 111, NOW)
        sub = store.suscribir(self.conn, 111, store.TODAS, 25)
        self.assertIsNone(store.ultimo_aviso(self.conn, sub, 5))
        store.registrar_aviso(self.conn, sub, 5, '2026-10-27T10:00:00Z', 40, 'supera', NOW)
        store.registrar_aviso(self.conn, sub, 6, '2026-10-27T10:00:00Z', 50, 'supera', NOW)
        store.registrar_aviso(self.conn, sub, 5, '2026-10-27T11:00:00Z', 12, 'normaliza', NOW)
        self.assertEqual('normaliza', store.ultimo_aviso(self.conn, sub, 5)['tipo'])
        self.assertEqual('supera', store.ultimo_aviso(self.conn, sub, 6)['tipo'])
        with self.assertRaises(sqlite3.IntegrityError):
            store.registrar_aviso(self.conn, sub, 5, NOW, 1, 'otro')

    def test_baja_deletes_everything_for_that_chat(self):
        for chat in (111, 222):
            store.alta(self.conn, chat, NOW)
            sub = store.suscribir(self.conn, chat, 5, 25)
            store.registrar_aviso(self.conn, sub, 5, NOW, 40, 'supera', NOW)
        self.assertTrue(store.baja(self.conn, 111))
        self.assertFalse(store.baja(self.conn, 111))
        for table in ('suscriptores', 'suscripciones', 'alertas_enviadas'):
            self.assertEqual(1, self.conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], table)
        self.assertEqual([], store.suscripciones(self.conn, 111))


if __name__ == '__main__':
    unittest.main()
