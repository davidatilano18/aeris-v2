"""Conector NASA POWER horario por punto. Producto de reanálisis de rejilla, nunca observación local.

Se solicita time-standard=UTC (el predeterminado es hora solar local). La etiqueta YYYYMMDDHH se
conserva tal cual como instante UTC del valor horario publicado; no se desplaza a inicio o fin.
"""
import json
from datetime import datetime, timezone
from urllib.parse import urlencode

URL = 'https://power.larc.nasa.gov/api/temporal/hourly/point'
FUENTE = 'nasa-power'
PARAMETROS = {
    'T2M': ('temperatura_aire', '°C', 1.0),
    'T2MDEW': ('punto_rocio', '°C', 1.0),
    'RH2M': ('humedad_relativa', '%', 1.0),
    'WS10M': ('viento_velocidad', 'm/s', 1.0),
    'WD10M': ('viento_direccion', '°', 1.0),
    'PS': ('presion_superficie', 'kPa', 10.0),  # kPa -> hPa
    'PRECTOTCORR': ('precipitacion', 'mm/h', 1.0),
}
TOLERANCIA_COORDENADA = 0.01


def url(latitud, longitud, desde, hasta):
    return URL + '?' + urlencode({
        'parameters': ','.join(PARAMETROS), 'community': 'RE', 'latitude': latitud, 'longitude': longitud,
        'start': desde.strftime('%Y%m%d'), 'end': hasta.strftime('%Y%m%d'),
        'format': 'JSON', 'time-standard': 'UTC'})


def interpretar(contenido, estacion_id, latitud, longitud, desde=None, hasta=None):
    datos = json.loads(contenido)
    try:
        lon, lat, elevacion = datos['geometry']['coordinates']
        valores = datos['properties']['parameter']
        relleno = float(datos['header']['fill_value'])
    except (KeyError, TypeError, ValueError):
        raise ValueError('Respuesta NASA POWER con esquema inesperado') from None
    if abs(lat - latitud) > TOLERANCIA_COORDENADA or abs(lon - longitud) > TOLERANCIA_COORDENADA:
        raise ValueError('NASA POWER devolvió un punto distinto del solicitado')
    if set(PARAMETROS) - set(valores):
        raise ValueError('Faltan parámetros solicitados en la respuesta')
    registros, ausentes = [], 0
    for parametro, (variable, unidad, factor) in PARAMETROS.items():
        for etiqueta, valor in valores[parametro].items():
            fecha = datetime.strptime(etiqueta, '%Y%m%d%H').replace(tzinfo=timezone.utc)
            if (desde and fecha < desde) or (hasta and fecha >= hasta):
                continue
            if valor is None or float(valor) == relleno:
                ausentes += 1  # Sin publicación para esa hora: no se imputa.
                continue
            registros.append({
                'estacion_id': estacion_id, 'variable_id': variable, 'fecha': fecha,
                'valor': round(float(valor) * factor, 6), 'valor_original': repr(float(valor)),
                'unidad_original': unidad, 'periodo': 'PT1H', 'tipo_reporte': 'POWER-horario',
                'codigo_medicion': '', 'calidad_origen': '', 'marca_origen': False,
            })
    resumen = {'valores': len(registros), 'relleno_descartado': ausentes,
               'celda_elevacion_m': elevacion, 'version': datos['header'].get('api', {}).get('version')
               if isinstance(datos['header'].get('api'), dict) else None,
               'fuentes_modelo': datos['header'].get('sources')}
    return registros, resumen
