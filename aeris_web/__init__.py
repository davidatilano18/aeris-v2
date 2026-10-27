"""Independent, read-only AERIS 2.0 presentation layer."""
import threading

from .routes import blueprint
from .datos_abiertos import blueprint as datos_blueprint
from .aprende import blueprint as aprende_blueprint


def register_v2(app, database_getter):
    app.extensions['aeris_v2_database'] = database_getter
    app.register_blueprint(blueprint)
    app.register_blueprint(datos_blueprint)
    app.register_blueprint(aprende_blueprint)


def precalentar(app):
    """Calcula en segundo plano los resúmenes de la portada (índice y modelo) para que la primera visita no espere."""
    def calcular():
        from .indice import read_indice
        from .modelo import read_modelo
        try:
            ruta = app.extensions['aeris_v2_database']()
            read_indice(ruta)
            read_modelo(ruta)
        except Exception:  # La portada los calcula igual al pedirse; esto solo adelanta el trabajo.
            app.logger.warning('precalentar_resumenes_fallo', exc_info=True)
    threading.Thread(target=calcular, name='aeris-precalentar', daemon=True).start()
