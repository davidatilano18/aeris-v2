"""Envío de correos de cuentas. En local se imprimen en la consola; el envío real llega con el despliegue."""
import sys


def consola(para, asunto, texto):
    print(f'\n--- correo local (no enviado) ---\nPara: {para}\nAsunto: {asunto}\n\n{texto}\n'
          '--- fin del correo ---\n', file=sys.stderr, flush=True)


def verificacion(enlace):
    return ('Confirma tu correo en AERIS',
            f'Hola:\n\nPara activar tu cuenta de AERIS abre este enlace (vence en 24 horas):\n{enlace}\n\n'
            'Si no creaste una cuenta, ignora este mensaje.')


def ya_registrado(enlace_entrar, enlace_recuperar):
    return ('Ya tienes una cuenta en AERIS',
            'Hola:\n\nAlguien intentó crear una cuenta de AERIS con este correo, pero ya existe una.\n'
            f'Si fuiste tú, inicia sesión: {enlace_entrar}\n'
            f'¿Olvidaste tu contraseña? {enlace_recuperar}\n\nSi no fuiste tú, ignora este mensaje.')


def recuperacion(enlace):
    return ('Restablece tu contraseña de AERIS',
            f'Hola:\n\nPara elegir una contraseña nueva abre este enlace (vence en 1 hora):\n{enlace}\n\n'
            'Si no lo pediste, ignora este mensaje: tu contraseña no cambia.')
