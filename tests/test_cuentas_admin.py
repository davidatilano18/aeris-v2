import json
import re
import sqlite3
import unittest

from cuentas import admin, store
from tests.test_cuentas import CLAVE, FavoritosTests, csrf


class AdminTests(FavoritosTests):
    """Fase F. Base: FavoritosTests deja a ana@ejemplo.mx con sesión iniciada y mediciones de prueba."""

    def setUp(self):
        super().setUp()
        self.conn = store.conectar(self.app.extensions['cuentas_db'])
        self.ana = store.por_correo(self.conn, 'ana@ejemplo.mx')
        self.beto_id, _ = store.registrar(self.conn, "beto'x@ejemplo.mx", CLAVE)

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def hacer_admin(self, correo='ana@ejemplo.mx'):
        store.asignar_rol(self.conn, correo, 'admin')

    def accion(self, usuario_id, accion):
        token = csrf(self.client.get('/admin/usuarios').get_data(as_text=True))
        return self.client.post(f'/admin/usuarios/{usuario_id}', data={'csrf': token, 'accion': accion})

    def test_hidden_from_non_admins_and_anonymous(self):
        self.assertEqual(404, self.client.get('/admin').status_code)
        self.assertEqual(404, self.client.get('/admin/usuarios').status_code)
        token = csrf(self.client.get('/cuenta').get_data(as_text=True))
        r = self.client.post(f'/admin/usuarios/{self.beto_id}', data={'csrf': token, 'accion': 'borrar'})
        self.assertEqual(404, r.status_code)
        self.assertIsNotNone(store.usuario(self.conn, self.beto_id))
        anonimo = self.app.test_client().get('/admin')
        self.assertEqual('/cuenta/entrar?siguiente=/admin', anonimo.headers['Location'])
        self.assertNotIn('Panel de administración', self.client.get('/cuenta').get_data(as_text=True))

    def test_dashboard_reads_ingestion_alerts_and_stations(self):
        self.hacer_admin()
        carpeta = self.med.parent / 'sync_runtime' / 'scheduler'
        carpeta.mkdir(parents=True)
        (carpeta / 'last_success.json').write_text(json.dumps({'status': 'success', 'finished_at_utc': '2026-10-27T21:06:12Z'}))
        (carpeta / 'a.json').write_text(json.dumps({'status': 'success', 'finished_at_utc': '2026-10-27T21:06:12Z'}))
        (carpeta / 'b.json').write_text(json.dumps({'status': 'critical_failure', 'finished_at_utc': '2026-10-27T20:06:12Z',
                                                    'error_type': 'TimeoutError'}))
        from alertas import store as alertas
        self.app.extensions['alertas_db'].parent.mkdir(parents=True, exist_ok=True)
        conn = alertas.conectar(self.app.extensions['alertas_db'])
        alertas.alta(conn, 111); conn.close()
        html = self.client.get('/admin').get_data(as_text=True)
        self.assertIn('Panel de', html)
        self.assertIn('27/10/2026 15:06', html)  # hora de Querétaro
        self.assertIn('TimeoutError', html)
        self.assertIn('Josefa Vergara', html)
        self.assertIn('Al día', html)
        self.assertRegex(html, r'<dt>Chats</dt><dd>1</dd>')
        self.assertIn('Panel de administración', self.client.get('/cuenta').get_data(as_text=True))

    def test_user_list_search_and_escaping(self):
        self.hacer_admin()
        html = self.client.get('/admin/usuarios?q=beto').get_data(as_text=True)
        self.assertIn('beto&#39;x@ejemplo.mx', html)
        self.assertNotIn('ana@ejemplo.mx</td>', html)
        self.assertNotIn('scrypt:', html)
        # % y _ se buscan como texto literal, no como comodines de LIKE
        self.assertIn('No hay cuentas que coincidan', self.client.get('/admin/usuarios?q=%25').get_data(as_text=True))
        self.assertIn('No hay cuentas que coincidan', self.client.get('/admin/usuarios?q=_').get_data(as_text=True))
        self.assertIn('ana@ejemplo.mx', self.client.get('/admin/usuarios').get_data(as_text=True))

    def test_actions_are_applied_and_logged(self):
        self.hacer_admin()
        self.assertEqual(302, self.accion(self.beto_id, 'verificar').status_code)
        self.assertIsNotNone(store.usuario(self.conn, self.beto_id)['verificado_utc'])
        self.accion(self.beto_id, 'desactivar')
        self.assertEqual(0, store.usuario(self.conn, self.beto_id)['activo'])
        self.accion(self.beto_id, 'hacer_admin')
        self.assertEqual('admin', store.usuario(self.conn, self.beto_id)['rol'])
        self.accion(self.beto_id, 'borrar')
        self.assertIsNone(store.usuario(self.conn, self.beto_id))
        acciones = [e['accion'] for e in store.eventos_admin(self.conn)]
        self.assertEqual(['borrar', 'hacer_admin', 'desactivar', 'verificar'], acciones)
        self.assertIn('Borró la cuenta', self.client.get('/admin').get_data(as_text=True))

    def test_deactivation_ends_sessions(self):
        self.hacer_admin()
        otro = self.app.test_client()
        store.administrar(self.conn, self.ana, self.beto_id, 'verificar')
        token = csrf(otro.get('/cuenta/entrar').get_data(as_text=True))
        otro.post('/cuenta/entrar', data={'csrf': token, 'correo': "beto'x@ejemplo.mx", 'contrasena': CLAVE})
        self.assertEqual(200, otro.get('/cuenta').status_code)
        self.accion(self.beto_id, 'desactivar')
        self.assertEqual(302, otro.get('/cuenta').status_code)

    def test_cannot_lock_yourself_out_or_remove_last_admin(self):
        self.hacer_admin()
        for accion in ('desactivar', 'quitar_admin', 'borrar'):
            r = self.accion(self.ana['id'], accion)
            self.assertEqual(400, r.status_code)
            self.assertIn('a ti mismo', r.get_data(as_text=True))
        self.hacer_admin("beto'x@ejemplo.mx")
        store.administrar(self.conn, store.usuario(self.conn, self.beto_id), self.ana['id'], 'quitar_admin')
        with self.assertRaises(store.ErrorCuenta) as error:  # beto es ahora el único admin activo
            store.administrar(self.conn, self.ana | {'id': -1}, self.beto_id, 'quitar_admin')
        self.assertIn('al menos una cuenta de administración', str(error.exception))

    def test_requires_csrf(self):
        self.hacer_admin()
        self.assertEqual(400, self.client.post(f'/admin/usuarios/{self.beto_id}', data={'accion': 'borrar'}).status_code)
        self.assertIsNotNone(store.usuario(self.conn, self.beto_id))

    def test_command_line_role(self):
        db = str(self.app.extensions['cuentas_db'])
        self.assertEqual(0, admin.main(['--db', db, 'rol', 'ANA@ejemplo.mx', 'admin']))
        self.assertEqual('admin', store.por_correo(self.conn, 'ana@ejemplo.mx')['rol'])
        self.assertEqual(1, admin.main(['--db', db, 'rol', 'nadie@ejemplo.mx', 'admin']))
        self.assertEqual('consola', store.eventos_admin(self.conn)[0]['admin_correo'])

    def test_v3_database_migrates(self):
        path = self.med.parent / 'v3.db'
        conn = sqlite3.connect(path)
        conn.executescript(store.SCHEMA.split('CREATE TABLE admin_eventos')[0] + 'PRAGMA user_version=3;')
        conn.close()
        conn = store.conectar(path)
        self.assertEqual(store.VERSION, conn.execute('PRAGMA user_version').fetchone()[0])
        conn.close()

    test_lists_active_stations_with_reading = test_save_favorites_and_personal_threshold = None
    test_rejects_unknown_station_and_bad_threshold = test_home_panel = test_migration_from_v1_keeps_users = None


if __name__ == '__main__':
    unittest.main()
