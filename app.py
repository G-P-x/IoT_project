from http import server
from flask import Flask
from flask_cors import CORS

from config.config import Config

from cloud_platform.application.operator_api import register_operator_routes

class FlaskServer:
    """
    This class encapsulates the Flask app and its setup. 
    It creates:
    - the Flask app and configures it to handle HTTP requests from researchers and operators 
    
    """
    def __init__(self, cfg: Config):
        self.app = Flask(__name__, template_folder=cfg.TEMPLATES_DIR, static_folder=cfg.STATIC_DIR)
        CORS(self.app)  # Enable CORS for all routes
        self._register_blueprints()
        

    def _register_blueprints(self):
        register_operator_routes(self.app)

    def run(self, host: str, port: int, debug: bool):
        """Start the Flask server."""
        self.app.run(host=host, port=port, debug=debug)

# def create_app() -> Flask:
#     # Expose needed config to Flask
#     app.config.update(
#         DEFAULT_TWIN_ID=cfg.DEFAULT_TWIN_ID,
#         TOPIC_COMMANDS_DOWNLINK=cfg.TOPIC_COMMANDS_DOWNLINK,
#     )

#     # DB + Services
#     mongo = MongoDB(cfg.MONGO_URI, cfg.MONGO_DB_NAME)
#     dt = DTService(
#         twins=mongo.collections.twins,
#         telemetry=mongo.collections.telemetry,
#         health=mongo.collections.health,
#         commands=mongo.collections.commands,
#         anomalies=mongo.collections.anomalies,
#     )

#     # MQTT client (subscriber)
#     mqttc = MQTTClient(cfg, dt)

#     # Attach as Flask extensions so routes can access
#     app.extensions["mongo"] = mongo
#     app.extensions["dt_service"] = dt
#     app.extensions["mqtt_client"] = mqttc

#     # Register routes using Blueprints, this creates modular route groups in separate files
#     app.register_blueprint(bp_public)
#     app.register_blueprint(bp_operator)
#     app.register_blueprint(bp_commands)
#     app.register_blueprint(bp_frontend)

#     # Start MQTT once
#     # IMPORTANT: when Flask debug reloader is on, it runs twice. Avoid double-start.
#     if not cfg.FLASK_DEBUG:
#         mqttc.start()
#     else:
#         # In debug, only start MQTT in the reloader child process
#         # Werkzeug sets WERKZEUG_RUN_MAIN='true' in the child.
#         if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
#             mqttc.start()

#     return app


if __name__ == "__main__":
    cfg = Config()
    server = FlaskServer(cfg)
    server.run(host=cfg.FLASK_HOST, port=cfg.FLASK_PORT, debug=cfg.FLASK_DEBUG)
