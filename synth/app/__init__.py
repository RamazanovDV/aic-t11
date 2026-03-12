import os
from pathlib import Path

from flask import Flask

from app.routes import api_bp, admin_bp, auth_bp, mcp_bp
from app.config import config
from app.scheduler import scheduler
from app.context import DEFAULT_CONTEXT_FILES, ContextManager

BASE_DIR = Path(__file__).parent


def init_default_context_files() -> None:
    """Копировать дефолтные файлы в data/context/ если их нет."""
    ctx_mgr = ContextManager()
    ctx_mgr.user_dir.mkdir(parents=True, exist_ok=True)
    
    for filename in DEFAULT_CONTEXT_FILES:
        user_path = ctx_mgr.user_dir / filename
        if not user_path.exists():
            default_filename = f"DEFAULT_{filename}"
            default_path = ctx_mgr.system_dir / default_filename
            if default_path.exists():
                user_path.write_text(default_path.read_text(encoding="utf-8"), encoding="utf-8")
                print(f"[INIT] Created default context file: {filename}")
    
    enabled = config.get_enabled_context_files()
    new_enabled = list(enabled)
    for filename in DEFAULT_CONTEXT_FILES:
        if filename not in new_enabled:
            new_enabled.append(filename)
    if new_enabled != enabled:
        config.set_enabled_context_files(new_enabled)
        print(f"[INIT] Enabled default context files: {DEFAULT_CONTEXT_FILES}")


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

    init_default_context_files()
    scheduler.start()

    return app
