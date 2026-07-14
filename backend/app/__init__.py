from flask import Flask
from flask_cors import CORS

from .routes import api_bp
from .obstacle.routes_obstacle import obstacle_bp

# Singleton obstacle service, started from run.py (see attach_obstacle_service).
_obstacle_service = None


def attach_obstacle_service(app: Flask, service) -> None:
    """Attach an already-started ObstacleService so routes can reach it."""
    global _obstacle_service
    _obstacle_service = service
    app.config["OBSTACLE_SERVICE"] = service


def get_obstacle_service():
    return _obstacle_service


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(obstacle_bp, url_prefix="/api")
    if _obstacle_service is not None:
        app.config["OBSTACLE_SERVICE"] = _obstacle_service
    return app
