import re
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from alertas import bot, store, vinculos
from cuentas import store as cuentas
from tests.test_alertas_bot import Base
from tests.test_cuentas import CLAVE, FavoritosTests, csrf


class VinculoStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.conn = cuentas.conectar(Path(self.folder.name) / 'u.db')
        self.uid, _ = cuentas.registrar(self.conn, 'ana@ejemplo.mx', CLAVE)
        cuentas.verificar(self.conn, cuentas.emitir_token(self.conn, self.uid, 'verificar'))

    def tearDown(self):
        self.conn.close(); self.folder.cleanup()

    def test_code_is_single_use_hashed_and_expires(self):
        codigo = cuentas.codigo_telegram(self.conn, self.uid)
        self.assertRegex(codigo, r'^[A-Za-z0-9_-]{16,64}$')
        self.assertIsNone(self.conn.execute('SELECT 1 FROM telegram_codigos WHERE hash=?', (codigo,)).fetchone())
        self.assertEqual('ana@ejemplo.mx', cuentas.vincular_telegram(self.conn, codigo, 111)['correo'])
        self.assertIsNone(cuentas.vincular_telegram(self.conn, codigo, 222))
        vencido = cuentas.codigo_telegram(self.conn, self.uid)
        self.assertIsNone(cuentas.vincular_telegram(self.conn, vencido, 222, now=cuentas.utc_now() + timedelta(minutes=16)))
        for malo in ('', 'corto', 'x' * 80, 'con espacios y más'):
            self.assertIsNone(cuentas.vincular_telegram(self.conn, malo, 222))

    def test_one_chat_per_account_and_one_account_per_chat(self):
        otro, _ = cuentas.registrar(self.conn, 'beto@ejemplo.mx', CLAVE)
        cuentas.verificar(self.conn, cuentas.emitir_token(self.conn, otro, 'verificar'))
        cuentas.vincular_telegram(self.conn, cuentas.codigo_telegram(self.conn, self.uid), 111)
        cuentas.vincular_telegram(self.conn, cuentas.codigo_telegram(self.conn, self.uid), 222)
        self.assertEqual(222, cuentas.vinculo_telegram(self.conn, self.uid)['chat_id'])
        cuentas.vincular_telegram(self.conn, cuentas.codigo_telegram(self.conn, otro), 222)
        self.assertIsNone(cuentas.vinculo_telegram(self.conn, self.uid))
        self.assertEqual(222, cuentas.vinculo_telegram(self.conn, otro)['chat_id'])

    def test_unverified_or_inactive_accounts_cannot_link(self):
        nuevo, _ = cuentas.registrar(self.conn, 'sin@verificar.mx', CLAVE)
        self.assertIsNone(cuentas.vincular_telegram(self.conn, cuentas.codigo_telegram(self.conn, nuevo), 333))

    def test_v2_database_migrates(self):
        path = Path(self.folder.name) / 'v2.db'
        conn = sqlite3.connect(path)
        conn.executescript(cuentas.SCHEMA.split('CREATE TABLE telegram_vinculos')[0] + 'PRAGMA user_version=2;')
        conn.close()
        conn = cuentas.conectar(path)
        self.assertEqual(cuentas.VERSION, conn.execute('PRAGMA user_version').fetchone()[0])
        conn.close()


class SincronizarTests(Base):
    """El bot con una cuenta vinculada (mediciones de Base: 10 Josefa Vergara 31.4, 20 Corregidora 12)."""

    def setUp(self):
        super().setUp()
        self.cuentas = cuentas.conectar(Path(self.folder.name) / 'usuarios.db')
        self.uid, _ = cuentas.registrar(self.cuentas, 'ana@ejemplo.mx', CLAVE)
        cuentas.verificar(self.cuentas, cuentas.emitir_token(self.cuentas, self.uid, 'verificar'))
        cuentas.guardar_preferencias(self.cuentas, self.uid, [10, 20], None, {10, 20})
        self.bot = bot.Bot(self.conn, self.med, now=lambda: self.bot_now, cuentas=self.cuentas)
        from tests.test_alertas_bot import NOW
        self.bot_now = NOW

    def tearDown(self):
        self.cuentas.close()
        super().tearDown()

    def vincular(self, chat=111):
        return self.say('/start ' + cuentas.codigo_telegram(self.cuentas, self.uid), chat=chat)

    def test_start_with_code_links_and_copies_preferences(self):
        respuesta = self.vincular()
        self.assertIn('a***@ejemplo.mx', respuesta)
        self.assertIn('tus 2 estaciones con umbral de 25', respuesta)
        self.assertEqual({10: 25.0, 20: 25.0}, {s['sensor_id']: s['umbral'] for s in store.suscripciones(self.conn, 111)})
        self.assertIn('no es válido', self.say('/start codigo_que_no_existe_123', chat=222))

    def test_web_changes_reach_the_bot_and_manual_commands_are_redirected(self):
        self.say('/start'); self.say('/suscribir todas 5')
        self.vincular()
        self.assertEqual([10, 20], sorted(s['sensor_id'] for s in store.suscripciones(self.conn, 111)))
        self.assertIn('se eligen en la web', self.say('/suscribir 1'))
        self.assertIn('Se administran desde tu cuenta web', self.say('/mis_alertas'))
        cuentas.guardar_preferencias(self.cuentas, self.uid, [20], 15, {10, 20})
        self.assertEqual([], vinculos.sincronizar(self.conn, self.cuentas))
        self.assertEqual({20: 15.0}, {s['sensor_id']: s['umbral'] for s in store.suscripciones(self.conn, 111)})

    def test_sync_keeps_pause_and_notice_history(self):
        self.vincular()
        sub = store.suscripciones(self.conn, 111)[0]['id']
        store.registrar_aviso(self.conn, sub, 10, '2026-10-27T18:00:00Z', 31, 'supera')
        self.say('/pausa')
        vinculos.sincronizar(self.conn, self.cuentas)
        self.assertEqual(0, store.suscriptor(self.conn, 111)['activo'])
        self.assertEqual('supera', store.ultimo_aviso(self.conn, sub, 10)['tipo'])

    def test_unlink_from_web_or_bot(self):
        self.vincular()
        cuentas.desvincular_telegram(self.cuentas, usuario_id=self.uid)
        self.assertEqual([(111, vinculos.DESVINCULADO)], vinculos.sincronizar(self.conn, self.cuentas))
        self.assertEqual([], store.suscripciones(self.conn, 111))
        self.assertIn('Corregidora supere', self.say('/suscribir 1'))  # el chat vuelve a administrarse aquí
        self.vincular()
        self.assertIn('desconecté', self.say('/desvincular'))
        self.assertIsNone(cuentas.vinculo_telegram(self.cuentas, self.uid))
        self.vincular()
        self.say('/baja')
        self.assertIsNone(cuentas.vinculo_telegram(self.cuentas, self.uid))

    def test_deleting_the_account_unlinks(self):
        self.vincular()
        cuentas.borrar(self.cuentas, self.uid)
        self.assertEqual(1, len(vinculos.sincronizar(self.conn, self.cuentas)))
        self.assertFalse(store.es_vinculado(self.conn, 111))

    def test_alert_store_v1_migrates(self):
        path = Path(self.folder.name) / 'alertas_v1.db'
        conn = sqlite3.connect(path)
        conn.executescript(store.SCHEMA.split('CREATE TABLE chats_vinculados')[0] + 'PRAGMA user_version=1;')
        conn.close()
        conn = store.conectar(path)
        self.assertEqual(store.VERSION, conn.execute('PRAGMA user_version').fetchone()[0])
        conn.close()


class PerfilTelegramTests(FavoritosTests):
    def test_connect_shows_one_time_link_and_disconnect(self):
        perfil = self.client.get('/cuenta').get_data(as_text=True)
        self.assertIn('Conectar Telegram', perfil)
        html = self.client.post('/cuenta/telegram', data={'csrf': csrf(perfil)}).get_data(as_text=True)
        codigo = re.search(r'https://t\.me/AERIS_QRO_BOT\?start=([A-Za-z0-9_-]+)', html).group(1)
        conn = cuentas.conectar(self.app.extensions['cuentas_db'])
        self.assertIsNotNone(cuentas.vincular_telegram(conn, codigo, 555))
        conn.close()
        perfil = self.client.get('/cuenta').get_data(as_text=True)
        self.assertIn('Conectado desde', perfil)
        r = self.client.post('/cuenta/telegram/desconectar', data={'csrf': csrf(perfil)})
        self.assertEqual('/cuenta?aviso=telegram', r.headers['Location'])
        self.assertIn('Conectar Telegram', self.client.get('/cuenta').get_data(as_text=True))

    def test_codes_are_rate_limited(self):
        token = csrf(self.client.get('/cuenta').get_data(as_text=True))
        codigos = [self.client.post('/cuenta/telegram', data={'csrf': token}).status_code for _ in range(6)]
        self.assertEqual([200] * 5 + [429], codigos)

    # Las pruebas heredadas de FavoritosTests ya corren en su propia clase.
    test_lists_active_stations_with_reading = test_save_favorites_and_personal_threshold = None
    test_rejects_unknown_station_and_bad_threshold = test_home_panel = test_migration_from_v1_keeps_users = None


if __name__ == '__main__':
    unittest.main()
