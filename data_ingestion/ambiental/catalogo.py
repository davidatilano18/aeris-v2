"""Catálogo verificado de fuentes, estaciones y variables (investigación 20/10/2026).

Las coordenadas provienen de la lista oficial de cada proveedor, no de geocodificación.
Una estación nueva o un cambio de coordenadas exige una entrada nueva, nunca reescribir otra.
"""

# tipo_producto separa observaciones reales de productos modelados; la API nunca los combina.
FUENTES = {
    'noaa-ghcnh': {
        'nombre': 'Global Historical Climatology Network-hourly (GHCNh) v1',
        'organizacion': 'NOAA National Centers for Environmental Information',
        'url': 'https://www.ncei.noaa.gov/products/global-historical-climatology-network-hourly',
        'documentacion_url': 'https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh_DOCUMENTATION.pdf',
        'licencia': 'CC0-1.0 (sin protección de derechos de autor en EE. UU.)',
        'atribucion': 'Menne et al. (2023), Global Historical Climatology Network-Hourly (GHCNh), '
                      'NOAA NCEI, doi:10.25921/jp3d-3v19 [subconjunto MMQT, fecha de acceso]',
        'tipo_producto': 'observacion',
        'metodo_acceso': 'HTTPS sin clave; archivo PSV anual por estación',
        'notas': 'Solo reportes METAR FM-15 (rutinario) y FM-16 (especial). Se excluyen SYNOP '
                 'FM-12/FM-94 por inconsistencias verificadas con el METAR de la misma hora.',
    },
    'nasa-power': {
        'nombre': 'NASA POWER, API horaria por punto',
        'organizacion': 'NASA Langley Research Center',
        'url': 'https://power.larc.nasa.gov/api/temporal/hourly/point',
        'documentacion_url': 'https://power.larc.nasa.gov/docs/services/api/temporal/hourly/',
        'licencia': 'Datos públicos de NASA; atribución solicitada por el proveedor',
        'atribucion': 'Datos obtenidos del proyecto NASA Langley Research Center (LaRC) POWER, '
                      'financiado por el programa NASA Earth Science/Applied Science [versión, fecha de acceso]',
        'tipo_producto': 'reanalisis',
        'metodo_acceso': 'HTTPS sin clave; JSON con time-standard=UTC',
        'notas': 'Producto de rejilla (MERRA-2/GEOS-IT). Covariable modelada, no observación local; '
                 'latencia de 1-3 días. Valor de relleno -999 se descarta, nunca se imputa.',
    },
    'openaq-archivo': {
        'nombre': 'OpenAQ Archive (red de monitoreo de Querétaro vía SINAICA)',
        'organizacion': 'OpenAQ; datos de la red estatal publicados en SINAICA',
        'url': 'https://openaq-data-archive.s3.amazonaws.com/',
        'documentacion_url': 'https://docs.openaq.org/aws/about',
        'licencia': 'Términos de SINAICA (licencia de proveedor 36 en OpenAQ: atribución requerida) y de OpenAQ',
        'atribucion': 'Datos de OpenAQ (archivo público), red de monitoreo de Querétaro / SINAICA; procesados por AERIS',
        'tipo_producto': 'observacion',
        'metodo_acceso': 'HTTPS sin clave; CSV diario por ubicación, verificado por SHA-256',
        'notas': 'Contaminantes criterio distintos de PM2.5 (PM10, O3, NO2, SO2, CO), con su unidad original. '
                 'El PM2.5 del mismo archivo se guarda en la tabla de mediciones existente para no duplicarlo. '
                 'La hora se conserva tal como la reporta el archivo, normalizada a UTC.',
    },
    'open-meteo-cams': {
        'nombre': 'Open-Meteo Air Quality API (CAMS global)',
        'organizacion': 'Open-Meteo; modelo del Copernicus Atmosphere Monitoring Service (ECMWF)',
        'url': 'https://air-quality-api.open-meteo.com/v1/air-quality',
        'documentacion_url': 'https://open-meteo.com/en/docs/air-quality-api',
        'licencia': 'CC BY 4.0 (Open-Meteo, uso no comercial de la API gratuita); datos CAMS con atribución a Copernicus',
        'atribucion': 'Generado con información del Copernicus Atmosphere Monitoring Service (CAMS), '
                      'servida por Open-Meteo.com (CC BY 4.0); procesado por AERIS',
        'tipo_producto': 'modelo',
        'metodo_acceso': 'HTTPS sin clave; JSON con timezone=GMT y domains=cams_global',
        'notas': 'Pronóstico del modelo global CAMS (rejilla de 0.4°, salida cada 3 h interpolada a horaria) '
                 'encadenado por Open-Meteo desde agosto de 2022. Estimación de modelo, no medición local. '
                 'Validado por AERIS contra las estaciones de la red: subestima el PM2.5 diario.',
    },
}

# Estaciones de la red de calidad del aire (ubicaciones OpenAQ verificadas en data/openaq_stations.json).
# sensor_pm25 enlaza con la tabla de mediciones existente; nunca se fusionan series de ubicaciones distintas.
_RED = [
    (235220, 8956473, 'Carrillo Puerto', 'Querétaro', 20.610597222222, -100.43759722222),
    (235221, 1352686, 'El Marqués (histórico)', 'El Marqués', 20.605872222222, -100.33229166667),
    (235224, 1352719, 'Josefa Vergara', 'Querétaro', 20.565863888889, -100.38918611111),
    (235225, 1352676, 'Corregidora', 'Corregidora', 20.552563888889, -100.44580555556),
    (235232, 1352718, 'San Juan del Río (ubicación 235232)', 'San Juan del Río', 20.388888888889, -99.972147222222),
    (235234, 1352681, 'Félix Osores', 'Querétaro', 20.636819444444, -100.46388333333),
    (480392, 2694071, 'Epigmenio González', 'Querétaro', 20.627538888889, -100.40862222222),
    (6498868, 17320548, 'San Juan del Río (ubicación 6498868)', 'San Juan del Río', 20.389961111111, -99.991727777778),
]

ESTACIONES = {
    'ghcnh:MXI0000MMQT': {
        'fuente_id': 'noaa-ghcnh', 'id_externo': 'MXI0000MMQT',
        'nombre': 'Aeropuerto Intercontinental de Querétaro (MMQT)',
        'municipio': 'El Marqués',
        'municipio_nota': 'El aeródromo abarca El Marqués y Colón según su título de concesión (DOF 2009).',
        'latitud': 20.6173, 'longitud': -100.1857, 'elevacion_m': 1919.0,
        'tipo_sitio': 'estacion', 'resolucion_espacial': 'punto',
        'metadatos': {'icao': 'MMQT', 'wmo': '76625', 'isd': '766250-99999',
                      'lista_oficial': 'ghcnh-station-list.txt'},
    },
    'power:mmqt': {
        'fuente_id': 'nasa-power', 'id_externo': '20.6173,-100.1857',
        'nombre': 'NASA POWER, celda del aeropuerto MMQT',
        'municipio': 'El Marqués',
        'municipio_nota': 'Punto solicitado en el aeropuerto; el valor representa una celda de rejilla.',
        'latitud': 20.6173, 'longitud': -100.1857, 'elevacion_m': None,
        'tipo_sitio': 'celda_rejilla', 'resolucion_espacial': 'aprox. 0.5° x 0.625°',
        'metadatos': {'comparar_con': 'ghcnh:MXI0000MMQT'},
    },
    'power:cor': {
        'fuente_id': 'nasa-power', 'id_externo': '20.552563888889,-100.44580555556',
        'nombre': 'NASA POWER, celda de la estación Corregidora',
        'municipio': 'Corregidora',
        'municipio_nota': 'Coordenada de la estación SINAICA 450 (COR); el valor representa una celda.',
        'latitud': 20.552563888889, 'longitud': -100.44580555556, 'elevacion_m': None,
        'tipo_sitio': 'celda_rejilla', 'resolucion_espacial': 'aprox. 0.5° x 0.625°',
        'metadatos': {'comparar_con': 'OpenAQ sensor 1352676'},
    },
}

for _loc, _sensor, _nombre, _municipio, _lat, _lon in _RED:
    ESTACIONES[f'openaq:{_loc}'] = {
        'fuente_id': 'openaq-archivo', 'id_externo': str(_loc), 'nombre': _nombre, 'municipio': _municipio,
        'municipio_nota': 'Estación de la red de calidad del aire; representa su entorno, no todo el municipio.',
        'latitud': _lat, 'longitud': _lon, 'elevacion_m': None, 'tipo_sitio': 'estacion', 'resolucion_espacial': 'punto',
        'metadatos': {'location_id': _loc, 'sensor_pm25': _sensor},
    }

# Puntos del modelo CAMS: El Marqués (ubicación de la estación histórica, sin datos desde 2021) y uno por
# estación con PM2.5 para validar el modelo contra la medición en el mismo lugar.
for _loc, _sensor, _nombre, _municipio, _lat, _lon in _RED:
    _clave = 'marques' if _loc == 235221 else str(_loc)
    ESTACIONES[f'cams:{_clave}'] = {
        'fuente_id': 'open-meteo-cams', 'id_externo': f'{_lat:.6f},{_lon:.6f}',
        'nombre': f'Modelo CAMS · {_nombre}', 'municipio': _municipio,
        'municipio_nota': 'Estimación de modelo para el punto de la estación; representa una celda de unos 45 km.',
        'latitud': _lat, 'longitud': _lon, 'elevacion_m': None, 'tipo_sitio': 'punto_modelo',
        'resolucion_espacial': 'rejilla CAMS global de 0.4°',
        'metadatos': {'comparar_con': f'openaq:{_loc}'},
    }

# Rangos físicos amplios para Querétaro (~1,900 m): marcan, nunca corrigen ni eliminan.
VARIABLES = {
    'temperatura_aire': ('Temperatura del aire', '°C', 'meteorologia', -15, 45),
    'punto_rocio': ('Temperatura de punto de rocío', '°C', 'meteorologia', -40, 35),
    'humedad_relativa': ('Humedad relativa', '%', 'meteorologia', 0, 100),
    'viento_velocidad': ('Velocidad del viento', 'm/s', 'meteorologia', 0, 60),
    'viento_direccion': ('Dirección del viento (de donde sopla; 0 = calma)', '°', 'meteorologia', 0, 360),
    'viento_rafaga': ('Ráfaga de viento', 'm/s', 'meteorologia', 0, 80),
    'presion_altimetro': ('Presión de altímetro (QNH)', 'hPa', 'meteorologia', 900, 1100),
    'presion_nivel_mar': ('Presión reducida al nivel del mar', 'hPa', 'meteorologia', 900, 1100),
    'presion_superficie': ('Presión en superficie', 'hPa', 'meteorologia', 700, 900),
    'visibilidad': ('Visibilidad horizontal', 'km', 'meteorologia', 0, 100),
    'precipitacion': ('Precipitación', 'mm', 'meteorologia', 0, 200),
    'pm25': ('Partículas PM2.5', 'µg/m³', 'contaminante', 0, 1000),
    'pm10': ('Partículas PM10', 'µg/m³', 'contaminante', 0, 2000),
    'o3': ('Ozono', 'ppm', 'contaminante', 0, 1),
    'no2': ('Dióxido de nitrógeno', 'ppm', 'contaminante', 0, 2),
    'so2': ('Dióxido de azufre', 'ppm', 'contaminante', 0, 2),
    'co': ('Monóxido de carbono', 'ppm', 'contaminante', 0, 50),
}
