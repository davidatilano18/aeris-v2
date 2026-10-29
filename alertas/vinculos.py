"""Chats vinculados a una cuenta web: sus estaciones y su umbral vienen de la cuenta."""
from alertas import store

UMBRAL_REFERENCIA = 25.0  # NOM-025-SSA1-2021, referencia de 24 h vigente desde enero de 2026
DESVINCULADO = ('Tu chat ya no está vinculado a una cuenta de AERIS, así que quité esas suscripciones. '
                'Puedes suscribirte aquí con /suscribir o volver a conectarlo desde «Mi cuenta».')


def sincronizar(conn_alertas, conn_cuentas):
    """Aplica en la base de alertas lo que dicen las cuentas. Devuelve [(chat_id, mensaje)] por avisar."""
    from cuentas import store as cuentas
    deseado = cuentas.vinculos_activos(conn_cuentas)
    for chat_id, preferencias in deseado.items():
        store.administrar_desde_cuenta(conn_alertas, chat_id, {
            sensor_id: UMBRAL_REFERENCIA if umbral is None else umbral for sensor_id, umbral in preferencias.items()})
    avisos = []
    for chat_id in store.vinculados(conn_alertas) - set(deseado):
        store.liberar(conn_alertas, chat_id)
        avisos.append((chat_id, DESVINCULADO))
    return avisos


def ocultar(correo):
    """d***@gmail.com: suficiente para reconocer la cuenta sin exponer el correo completo."""
    usuario, _, dominio = correo.partition('@')
    return f'{usuario[:1]}***@{dominio}'
