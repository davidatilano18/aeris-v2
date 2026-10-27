"""Descargas acotadas con reintentos. Sin credenciales: solo fuentes públicas sin clave."""
import hashlib
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

AGENTE = 'AERIS-Ambiental/1.0 (investigación ambiental Querétaro)'
LIMITE = 64 * 1024 * 1024
REINTENTABLES = {408, 429, 500, 502, 503, 504}


class SinPublicacion(Exception):
    """La fuente respondió que el recurso no existe (p. ej. 404): no se inventan registros."""


class FalloFuente(Exception):
    """La fuente no respondió de forma utilizable tras los reintentos permitidos."""


@dataclass
class Respuesta:
    url: str
    estado: int
    contenido: bytes
    sha256: str
    etag: str = None
    last_modified: str = None

    @property
    def sin_cambios(self):
        return self.estado == 304


def espera_retry_after(valor, maximo):
    if not valor:
        return None
    try:
        segundos = float(valor)
    except ValueError:
        try:
            segundos = (parsedate_to_datetime(valor).timestamp() - time.time())
        except (TypeError, ValueError):
            return None
    return max(0.0, min(segundos, maximo))


def descargar(url, etag=None, intentos=4, espera_base=2.0, espera_maxima=60.0, timeout=60,
              limite=LIMITE, abrir=urlopen, dormir=time.sleep):
    """GET con backoff exponencial; respeta Retry-After y falla cerrado si se excede el límite."""
    cabeceras = {'User-Agent': AGENTE, 'Accept': '*/*'}
    if etag:
        cabeceras['If-None-Match'] = etag
    ultimo = None
    for intento in range(intentos):
        espera = espera_base * 2 ** intento
        try:
            with abrir(Request(url, headers=cabeceras), timeout=timeout) as r:
                contenido = r.read(limite + 1)
                if len(contenido) > limite:
                    raise FalloFuente('Respuesta mayor que el límite permitido')
                return Respuesta(url, r.status, contenido, hashlib.sha256(contenido).hexdigest(),
                                 r.headers.get('ETag'), r.headers.get('Last-Modified'))
        except HTTPError as exc:
            if exc.code == 304:
                return Respuesta(url, 304, b'', '', etag)
            if exc.code in (404, 410):
                raise SinPublicacion(f'HTTP {exc.code}') from None
            if exc.code not in REINTENTABLES:
                raise FalloFuente(f'HTTP {exc.code}') from None
            ultimo = f'HTTP {exc.code}'
            espera = espera_retry_after(exc.headers.get('Retry-After') if exc.headers else None,
                                        espera_maxima) or espera
        except (URLError, TimeoutError, ConnectionError) as exc:
            ultimo = type(exc).__name__
        if intento + 1 < intentos:
            dormir(min(espera, espera_maxima))
    raise FalloFuente(f'Sin respuesta utilizable tras {intentos} intentos ({ultimo})')
