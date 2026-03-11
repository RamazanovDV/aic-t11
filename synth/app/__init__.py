import os
from pathlib import Path

from flask import Flask

from app.routes import api_bp, admin_bp, auth_bp, mcp_bp
from app.config import config
from app.scheduler import scheduler

BASE_DIR = Path(__file__).parent


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.secret_key = config.secret_key
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(mcp_bp, url_prefix="/api")

    scheduler.start()

    return app
