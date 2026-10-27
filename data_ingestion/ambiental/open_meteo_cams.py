"""Conector Open-Meteo Air Quality (CAMS global) por punto. Producto de modelo, nunca observación local.

Se solicita timezone=GMT: las etiquetas horarias son instantes UTC y se conservan sin desplazar.
Open-Meteo sirve el pronóstico CAMS global (rejilla de 0.4°, salida cada 3 h interpolada a horaria)
encadenando corridas sucesivas; no es el reanálisis CAMS. Las horas futuras (pronóstico) se descartan.
"""
import json
from datetime import datetime, timezone
from urllib.parse import urlencode

URL = 'https://air-quality-api.open-meteo.com/v1/air-quality'
FUENTE = 'open-meteo-cams'
PARAMETROS = {'pm2_5': ('pm25', 'μg/m³'), 'pm10': ('pm10', 'μg/m³')}
# La API devuelve la coordenada del punto de rejilla que usa, no la solicitada.
TOLERANCIA_COORDENADA = 0.11


def url(latitud, longitud, desde, hasta):
    return URL + '?' + urlencode({
        'latitude': latitud, 'longitude': longitud, 'hourly': ','.join(PARAMETROS), 'domains': 'cams_global',
        'start_date': desde.strftime('%Y-%m-%d'), 'end_date': hasta.strftime('%Y-%m-%d'), 'timezone': 'GMT'})


def interpretar(contenido, estacion_id, latitud, longitud, desde=None, hasta=None):
    datos = json.loads(contenido)
    try:
        lat, lon, horas = datos['latitude'], datos['longitude'], datos['hourly']
        unidades, tiempos = datos['hourly_units'], horas['time']
        desfase = datos['utc_offset_seconds']
    except (KeyError, TypeError):
        raise ValueError('Respuesta de Open-Meteo con esquema inesperado') from None
    if desfase != 0:
        raise ValueError('Open-Meteo no devolvió horas en UTC')
    if abs(lat - latitud) > TOLERANCIA_COORDENADA or abs(lon - longitud) > TOLERANCIA_COORDENADA:
        raise ValueError('Open-Meteo devolvió un punto de rejilla lejano al solicitado')
    registros, ausentes = [], 0
    for parametro, (variable, unidad) in PARAMETROS.items():
        if unidades.get(parametro) != unidad or len(horas.get(parametro, ())) != len(tiempos):
            raise ValueError(f'Unidad o longitud inesperada para {parametro}')
        for etiqueta, valor in zip(tiempos, horas[parametro]):
            fecha = datetime.fromisoformat(etiqueta).replace(tzinfo=timezone.utc)
            if (desde and fecha < desde) or (hasta and fecha >= hasta):
                continue
            if valor is None:
                ausentes += 1  # Sin publicación para esa hora: no se imputa.
                continue
            registros.append({
                'estacion_id': estacion_id, 'variable_id': variable, 'fecha': fecha,
                'valor': float(valor), 'valor_original': repr(float(valor)), 'unidad_original': unidad,
                'periodo': 'PT1H', 'tipo_reporte': 'CAMS-global', 'codigo_medicion': '',
                'calidad_origen': '', 'marca_origen': False,
            })
    resumen = {'valores': len(registros), 'sin_valor': ausentes, 'punto_rejilla': [lat, lon],
               'celda_elevacion_m': datos.get('elevation')}
    return registros, resumen
