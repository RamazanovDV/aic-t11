import os
from pathlib import Path

from flask import Flask

from app.routes import api_bp, admin_bp

BASE_DIR = Path(__file__).parent


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    return app
