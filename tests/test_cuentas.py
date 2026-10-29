import re
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from flask import Flask

from cuentas import store
from cuentas.web import configurar

ROOT = Path(__file__).resolve().parent.parent
CLAVE = 'una frase larga y segura'


def crear_app(folder, correos):
    app = Flask('prueba_cuentas', root_path=str(ROOT))
    app.config.update(AERIS_ENV='local', TESTING=True)
    app.extensions['cuentas_enviar'] = lambda para, asunto, texto: correos.append((para, asunto, texto))
    configurar(app, Path(folder), {'AERIS_CUENTAS_DB_PATH': str(Path(folder) / 'usuarios.db'),
                                   'AERIS_SECRET_KEY': 'k' * 64})
    return app


def csrf(html):
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.conn = store.conectar(Path(self.folder.name) / 'u.db')

    def tearDown(self):
        self.conn.close(); self.folder.cleanup()

    def test_refuses_measurement_and_foreign_databases(self):
        with self.assertRaises(ValueError):
            store.conectar(store.MEDICIONES_DB)
        otra = Path(self.folder.name) / 'otra.db'
        with sqlite3.connect(otra) as c: c.execute('CREATE TABLE x (y)')
        c.close()
        with self.assertRaises(sqlite3.DatabaseError):
            store.conectar(otra)

    def test_password_is_hashed_and_rules_apply(self):
        uid, creado = store.registrar(self.conn, '  Ana@Ejemplo.MX ', CLAVE)
        self.assertTrue(creado)
        u = store.usuario(self.conn, uid)
        self.assertEqual('ana@ejemplo.mx', u['correo'])
        self.assertNotIn(CLAVE, u['contrasena_hash'])
        self.assertTrue(u['contrasena_hash'].startswith('scrypt:'))
        self.assertEqual((uid, False), store.registrar(self.conn, 'ana@ejemplo.mx', 'otra frase distinta'))
        for correo, clave in (('sin-arroba', CLAVE), ('b@x.mx', 'corta'), ('b@x.mx', 'x' * 129),
                              ('largo@ejemplo.mx', 'largo@ejemplo.mx')):
            with self.assertRaises(store.ErrorCuenta):
                store.registrar(self.conn, correo, clave)

    def test_tokens_are_single_use_hashed_and_expire(self):
        uid, _ = store.registrar(self.conn, 'a@b.mx', CLAVE)
        token = store.emitir_token(self.conn, uid, 'verificar')
        self.assertIsNone(self.conn.execute('SELECT 1 FROM tokens WHERE hash=?', (token,)).fetchone())
        nuevo = store.emitir_token(self.conn, uid, 'verificar')
        self.assertIsNone(store.verificar(self.conn, token))  # el anterior quedó invalidado
        self.assertEqual(uid, store.verificar(self.conn, nuevo))
        self.assertIsNone(store.verificar(self.conn, nuevo))
        vencido = store.emitir_token(self.conn, uid, 'recuperar')
        with self.assertRaises(store.ErrorCuenta):
            store.restablecer(self.conn, vencido, 'clave nueva segura', now=store.utc_now() + timedelta(hours=2))

    def test_reset_validates_before_spending_token(self):
        uid, _ = store.registrar(self.conn, 'a@b.mx', CLAVE)
        token = store.emitir_token(self.conn, uid, 'recuperar')
        with self.assertRaises(store.ErrorCuenta):
            store.restablecer(self.conn, token, 'corta')
        store.restablecer(self.conn, token, 'clave nueva segura')
        self.assertIsNotNone(store.autenticar(self.conn, 'a@b.mx', 'clave nueva segura'))
        self.assertEqual(2, store.usuario(self.conn, uid)['sesion_version'])

    def test_rate_limit_window(self):
        ahora = store.utc_now()
        resultados = [store.limitar(self.conn, '1.2.3.4', 'registro_ip', ahora) for _ in range(6)]
        self.assertEqual([True] * 5 + [False], resultados)
        self.assertTrue(store.limitar(self.conn, '1.2.3.4', 'registro_ip', ahora + timedelta(hours=2)))

    def test_delete_cascades(self):
        uid, _ = store.registrar(self.conn, 'a@b.mx', CLAVE)
        store.emitir_token(self.conn, uid, 'verificar')
        self.assertTrue(store.borrar(self.conn, uid))
        self.assertEqual(0, self.conn.execute('SELECT COUNT(*) FROM tokens').fetchone()[0])


class WebTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.correos = []
        self.app = crear_app(self.folder.name, self.correos)
        self.client = self.app.test_client()

    def tearDown(self):
        self.folder.cleanup()

    def post(self, ruta, client=None, **datos):
        client = client or self.client
        token = csrf(client.get('/cuenta/registro' if ruta == '/cuenta/registro' else '/cuenta/entrar').get_data(as_text=True)) \
            if 'csrf' not in datos else datos.pop('csrf')
        return client.post(ruta, data={'csrf': token, **datos})

    def enlace(self):
        return re.search(r'https?://[^/]+(/cuenta/\S+)', self.correos[-1][2]).group(1)

    def registrar(self, correo='ana@ejemplo.mx', clave=CLAVE):
        return self.post('/cuenta/registro', correo=correo, contrasena=clave, confirmar=clave, acepto='si')

    def entrar(self, correo='ana@ejemplo.mx', clave=CLAVE, client=None, **extra):
        return self.post('/cuenta/entrar', client=client, correo=correo, contrasena=clave, **extra)

    def cuenta_verificada(self, correo='ana@ejemplo.mx'):
        self.registrar(correo)
        self.client.get(self.enlace())

    def test_full_registration_verification_and_login(self):
        r = self.registrar()
        self.assertEqual(200, r.status_code)
        self.assertIn('Revisa tu', r.get_data(as_text=True))
        self.assertEqual('Confirma tu correo en AERIS', self.correos[0][1])
        r = self.entrar()
        self.assertEqual(403, r.status_code)
        self.assertIn('confirma tu correo', r.get_data(as_text=True))
        self.assertIn('Correo confirmado', self.client.get(self.enlace()).get_data(as_text=True))
        r = self.entrar()
        self.assertEqual((302, '/cuenta'), (r.status_code, r.headers['Location']))
        perfil = self.client.get('/cuenta')
        self.assertIn('ana@ejemplo.mx', perfil.get_data(as_text=True))
        self.assertIn('Mi cuenta', perfil.get_data(as_text=True))
        self.assertEqual('no-store', perfil.headers['Cache-Control'])
        cookie = next(c for c in r.headers.getlist('Set-Cookie') if c.startswith('aeris_sesion='))
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Lax', cookie)

    def test_post_without_csrf_is_rejected(self):
        self.assertEqual(400, self.client.post('/cuenta/registro', data={'correo': 'a@b.mx'}).status_code)
        self.assertEqual(400, self.post('/cuenta/registro', csrf='falso', correo='a@b.mx').status_code)

    def test_duplicate_registration_does_not_reveal_account(self):
        self.cuenta_verificada()
        primera = self.registrar(clave='otra frase cualquiera').get_data(as_text=True)
        self.assertIn('Revisa tu', primera)
        self.assertEqual('Ya tienes una cuenta en AERIS', self.correos[-1][1])
        self.assertIsNone(self.entrar(clave='otra frase cualquiera').headers.get('Location'))

    def test_form_errors(self):
        r = self.post('/cuenta/registro', correo='a@b.mx', contrasena=CLAVE, confirmar=CLAVE)
        self.assertIn('aviso de privacidad', r.get_data(as_text=True))
        r = self.post('/cuenta/registro', correo='a@b.mx', contrasena=CLAVE, confirmar='otra cosa', acepto='si')
        self.assertIn('no coinciden', r.get_data(as_text=True))
        r = self.post('/cuenta/registro', correo='a@b.mx', contrasena='corta', confirmar='corta', acepto='si')
        self.assertIn('al menos 10', r.get_data(as_text=True))
        self.assertEqual([], self.correos)

    def test_wrong_password_and_unknown_email_look_the_same(self):
        self.cuenta_verificada()
        malo = self.entrar(clave='no es la clave')
        nadie = self.entrar(correo='nadie@ejemplo.mx')
        self.assertEqual((401, 401), (malo.status_code, nadie.status_code))
        self.assertIn('Correo o contraseña incorrectos', malo.get_data(as_text=True))
        self.assertIn('Correo o contraseña incorrectos', nadie.get_data(as_text=True))

    def test_login_attempts_are_limited(self):
        self.cuenta_verificada()
        codigos = [self.entrar(clave='intento fallido').status_code for _ in range(6)]
        self.assertEqual([401] * 5 + [429], codigos)
        self.assertEqual(429, self.entrar().status_code)  # ni con la correcta durante el bloqueo

    def test_next_parameter_only_allows_internal_paths(self):
        self.cuenta_verificada()
        self.assertEqual('/cuenta', self.entrar(siguiente='//malo.example/x').headers['Location'])
        self.client.post('/cuenta/salir', data={'csrf': csrf(self.client.get('/cuenta').get_data(as_text=True))})
        self.assertEqual('/cuenta', self.entrar(siguiente='https://malo.example').headers['Location'])
        self.client.post('/cuenta/salir', data={'csrf': csrf(self.client.get('/cuenta').get_data(as_text=True))})
        self.assertEqual('/inicio/datos', self.entrar(siguiente='/inicio/datos').headers['Location'])

    def test_profile_requires_session_and_logout(self):
        r = self.client.get('/cuenta')
        self.assertEqual('/cuenta/entrar?siguiente=/cuenta', r.headers['Location'])
        self.cuenta_verificada(); self.entrar()
        token = csrf(self.client.get('/cuenta').get_data(as_text=True))
        self.assertEqual(400, self.client.post('/cuenta/salir').status_code)
        self.assertEqual('/inicio', self.client.post('/cuenta/salir', data={'csrf': token}).headers['Location'])
        self.assertEqual(302, self.client.get('/cuenta').status_code)

    def test_recovery_resets_password_and_closes_other_sessions(self):
        self.cuenta_verificada()
        otro = self.app.test_client()
        self.entrar(client=otro)
        self.assertEqual(200, otro.get('/cuenta').status_code)
        n = len(self.correos)
        r = self.post('/cuenta/recuperar', correo='nadie@ejemplo.mx')
        self.assertIn('Si <strong>nadie@ejemplo.mx</strong> tiene una cuenta', r.get_data(as_text=True))
        self.assertEqual(n, len(self.correos))
        self.post('/cuenta/recuperar', correo='ana@ejemplo.mx')
        ruta = self.enlace()
        pagina = self.client.get(ruta).get_data(as_text=True)
        r = self.client.post(ruta, data={'csrf': csrf(pagina), 'contrasena': 'nueva frase segura', 'confirmar': 'nueva frase segura'})
        self.assertIn('Contraseña actualizada', r.get_data(as_text=True))
        self.assertEqual(302, otro.get('/cuenta').status_code)  # la otra sesión quedó cerrada
        self.assertEqual(401, self.entrar().status_code)
        self.assertEqual(302, self.entrar(clave='nueva frase segura').status_code)
        pagina = self.client.get(ruta).get_data(as_text=True)
        r = self.client.post(ruta, data={'csrf': csrf(pagina), 'contrasena': 'tercera frase segura', 'confirmar': 'tercera frase segura'})
        self.assertIn('no es válido o ya venció', r.get_data(as_text=True))

    def test_change_password_keeps_this_session_only(self):
        self.cuenta_verificada()
        otro = self.app.test_client()
        self.entrar(client=otro); self.entrar()
        token = csrf(self.client.get('/cuenta').get_data(as_text=True))
        r = self.client.post('/cuenta/contrasena', data={'csrf': token, 'actual': 'equivocada', 'nueva': 'nueva frase segura', 'confirmar': 'nueva frase segura'})
        self.assertIn('actual no es correcta', r.get_data(as_text=True))
        r = self.client.post('/cuenta/contrasena', data={'csrf': token, 'actual': CLAVE, 'nueva': 'nueva frase segura', 'confirmar': 'nueva frase segura'})
        self.assertEqual('/cuenta?aviso=contrasena', r.headers['Location'])
        self.assertEqual(200, self.client.get('/cuenta').status_code)
        self.assertEqual(302, otro.get('/cuenta').status_code)

    def test_delete_account_requires_password(self):
        self.cuenta_verificada(); self.entrar()
        token = csrf(self.client.get('/cuenta').get_data(as_text=True))
        r = self.client.post('/cuenta/borrar', data={'csrf': token, 'contrasena': 'equivocada'})
        self.assertIn('contraseña correcta', r.get_data(as_text=True))
        r = self.client.post('/cuenta/borrar', data={'csrf': token, 'contrasena': CLAVE})
        self.assertIn('Cuenta borrada', r.get_data(as_text=True))
        self.assertEqual(401, self.entrar().status_code)

    def test_privacy_notice_is_public(self):
        r = self.client.get('/privacidad')
        self.assertEqual(200, r.status_code)
        self.assertIn('ARCO', r.get_data(as_text=True))


class ModoTests(unittest.TestCase):
    def test_beta_stays_off_unless_configured(self):
        app = _beta_app()
        self.assertIsNone(configurar(app, ROOT, {}))
        self.assertNotIn('cuentas', app.blueprints)
        with self.assertRaises(ValueError):
            configurar(_beta_app(), ROOT, {'AERIS_CUENTAS_DB_PATH': '/tmp/u.db'})

    def test_site_header_links_to_login(self):
        import app as aplicacion
        html = aplicacion.app.test_client().get('/inicio/datos').get_data(as_text=True)
        self.assertIn('href="/cuenta/entrar"', html)


def _beta_app():
    app = Flask('beta3', root_path=str(ROOT))
    app.config['AERIS_ENV'] = 'beta'
    return app


if __name__ == '__main__':
    unittest.main()


class FavoritosTests(unittest.TestCase):
    """Fase C: estaciones favoritas y umbral personal."""

    def setUp(self):
        from datetime import datetime, timezone
        from tests.test_alertas_bot import mediciones
        self.folder = tempfile.TemporaryDirectory()
        hora = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
        stamp = hora.isoformat().replace('+00:00', 'Z')
        self.med = Path(self.folder.name) / 'mediciones.db'
        mediciones(self.med, [(10, stamp, 31.4), (20, stamp, 12)])  # 10 Josefa Vergara, 20 Corregidora
        self.correos = []
        self.app = crear_app(self.folder.name, self.correos)
        self.app.extensions['aeris_v2_database'] = lambda: self.med
        self.client = self.app.test_client()
        web = WebTests(); web.client, web.correos, web.app = self.client, self.correos, self.app
        web.cuenta_verificada(); web.entrar()

    def tearDown(self):
        self.folder.cleanup()

    def token(self): return csrf(self.client.get('/cuenta/estaciones').get_data(as_text=True))

    def test_lists_active_stations_with_reading(self):
        html = self.client.get('/cuenta/estaciones').get_data(as_text=True)
        self.assertIn('Corregidora', html)
        self.assertIn('Josefa Vergara', html)
        self.assertNotIn('Histórica', html)
        self.assertEqual(302, self.app.test_client().get('/cuenta/estaciones').status_code)

    def test_save_favorites_and_personal_threshold(self):
        r = self.client.post('/cuenta/estaciones', data={'csrf': self.token(), 'sensor': ['20', '10'],
                                                         'modo_umbral': 'personal', 'umbral': '30,5'})
        self.assertEqual('/cuenta?aviso=estaciones', r.headers['Location'])
        perfil = self.client.get('/cuenta?aviso=estaciones').get_data(as_text=True)
        self.assertIn('Guardamos tus estaciones', perfil)
        self.assertIn('Umbral: 30.5 µg/m³ (personal)', perfil)
        self.assertIn('class="supera">31 µg/m³', perfil)
        r = self.client.post('/cuenta/estaciones', data={'csrf': self.token(), 'sensor': ['20'], 'modo_umbral': 'referencia', 'umbral': '99'})
        perfil = self.client.get('/cuenta').get_data(as_text=True)
        self.assertIn('Umbral: 25 µg/m³ (referencia NOM-025)', perfil)
        self.assertNotIn('Josefa Vergara', perfil)

    def test_rejects_unknown_station_and_bad_threshold(self):
        for datos, mensaje in (({'sensor': ['999']}, 'no existe'),
                               ({'sensor': ['10'], 'modo_umbral': 'personal', 'umbral': 'mucho'}, 'entre 0 y 1000'),
                               ({'sensor': ['10'], 'modo_umbral': 'personal', 'umbral': '0'}, 'entre 0 y 1000')):
            r = self.client.post('/cuenta/estaciones', data={'csrf': self.token(), **datos})
            self.assertEqual(400, r.status_code)
            self.assertIn(mensaje, r.get_data(as_text=True))

    def test_home_panel(self):
        from flask import render_template
        local = lambda v: v[:16]
        self.client.post('/cuenta/estaciones', data={'csrf': self.token(), 'sensor': ['10', '20']})
        with self.client:
            self.client.get('/cuenta')
            html = render_template('cuentas/_mis_estaciones.html', local_date=local)
        self.assertIn('Tus estaciones', html)
        self.assertIn('la referencia de la NOM-025', html)
        self.assertEqual(1, html.count('class="supera"'))
        self.assertEqual(1, html.count('class="debajo"'))
        with self.app.test_request_context():
            self.assertEqual('', render_template('cuentas/_mis_estaciones.html', local_date=local).strip())

    def test_migration_from_v1_keeps_users(self):
        path = Path(self.folder.name) / 'v1.db'
        conn = sqlite3.connect(path)
        v1 = store.SCHEMA.split('CREATE TABLE favoritos')[0].replace(
            ',\n    umbral REAL CHECK(umbral IS NULL OR (umbral > 0 AND umbral < 1000)))', ')')
        conn.executescript(v1 + "PRAGMA user_version=1; INSERT INTO usuarios(correo,contrasena_hash,creado_utc) VALUES ('a@b.mx','x','2026-10-27T00:00:00Z');")
        conn.close()
        conn = store.conectar(path)
        self.assertEqual(store.VERSION, conn.execute('PRAGMA user_version').fetchone()[0])
        self.assertIsNone(store.por_correo(conn, 'a@b.mx')['umbral'])
        store.guardar_preferencias(conn, 1, [5], 40, {5})
        self.assertEqual([5], store.favoritos(conn, 1))
        conn.close()


class CorreoLocalTests(unittest.TestCase):
    """En el prototipo local, sin envío real, el enlace se muestra en la página."""

    def test_local_console_backend_shows_link_on_page(self):
        from cuentas import correo
        with tempfile.TemporaryDirectory() as folder:
            app = Flask('local', root_path=str(ROOT))
            app.config.update(AERIS_ENV='local', TESTING=True)
            app.extensions['cuentas_enviar'] = correo.consola
            configurar(app, Path(folder), {'AERIS_CUENTAS_DB_PATH': str(Path(folder) / 'u.db'), 'AERIS_SECRET_KEY': 'k' * 64})
            c = app.test_client()
            token = csrf(c.get('/cuenta/registro').get_data(as_text=True))
            html = c.post('/cuenta/registro', data={'csrf': token, 'correo': 'a@b.mx', 'contrasena': CLAVE,
                                                     'confirmar': CLAVE, 'acepto': 'si'}).get_data(as_text=True)
            self.assertIn('Prototipo local', html)
            enlace = re.search(r'href="https?://[^/]+(/cuenta/verificar/[^"]+)"', html).group(1)
            self.assertIn('Correo confirmado', c.get(enlace).get_data(as_text=True))

    def test_real_sender_never_shows_link(self):
        with tempfile.TemporaryDirectory() as folder:
            enviados = []
            c = crear_app(folder, enviados).test_client()
            token = csrf(c.get('/cuenta/registro').get_data(as_text=True))
            html = c.post('/cuenta/registro', data={'csrf': token, 'correo': 'a@b.mx', 'contrasena': CLAVE,
                                                     'confirmar': CLAVE, 'acepto': 'si'}).get_data(as_text=True)
            self.assertEqual(1, len(enviados))
            self.assertNotIn('/cuenta/verificar/', html)


class LimiteCorreoTests(unittest.TestCase):
    """Regresión: tras el límite de correos la página decía «te enviamos un enlace» sin enviarlo."""

    def registrar_y_entrar(self, app, veces):
        c = app.test_client()
        token = csrf(c.get('/cuenta/registro').get_data(as_text=True))
        c.post('/cuenta/registro', data={'csrf': token, 'correo': 'a@b.mx', 'contrasena': CLAVE, 'confirmar': CLAVE, 'acepto': 'si'})
        respuestas = []
        for _ in range(veces):
            token = csrf(c.get('/cuenta/entrar').get_data(as_text=True))
            respuestas.append(c.post('/cuenta/entrar', data={'csrf': token, 'correo': 'a@b.mx', 'contrasena': CLAVE}).get_data(as_text=True))
        return respuestas

    def test_real_sender_is_limited_and_says_so(self):
        with tempfile.TemporaryDirectory() as folder:
            enviados = []
            ultima = self.registrar_y_entrar(crear_app(folder, enviados), 4)[-1]
            self.assertEqual(3, len(enviados))
            self.assertIn('Ya te enviamos varios enlaces', ultima)
            self.assertNotIn('Te enviamos un enlace nuevo', ultima)

    def test_local_prototype_always_shows_a_fresh_link(self):
        from cuentas import correo
        with tempfile.TemporaryDirectory() as folder:
            app = Flask('local2', root_path=str(ROOT))
            app.config.update(AERIS_ENV='local', TESTING=True)
            app.extensions['cuentas_enviar'] = correo.consola
            configurar(app, Path(folder), {'AERIS_CUENTAS_DB_PATH': str(Path(folder) / 'u.db'), 'AERIS_SECRET_KEY': 'k' * 64})
            ultima = self.registrar_y_entrar(app, 4)[-1]
            self.assertIn('Prototipo local', ultima)
            self.assertRegex(ultima, r'href="https?://[^"]+/cuenta/verificar/')
