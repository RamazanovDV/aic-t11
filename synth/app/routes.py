import json
import re
import uuid
import asyncio
from datetime import datetime

import requests
from flask import Blueprint, jsonify, render_template, request, Response

from app.config import config
from app.handlers import ChatHandler, StreamHandler
from app.llm import ProviderFactory
from app.llm.base import Message
from app.llm.providers import ContextLengthExceededError
from app.llm.client import PromptBuilder, LLMClient, create_llm_client, create_prompt_builder
from app.session import session_manager
from app.request_tracker import RequestTracker
from app import summarizer
from app import status_validator
from app import project_manager
from app import storage
from app import tsm
from app import scheduler
from app.auth import get_auth_provider, require_user, require_admin, get_current_user
from app.mcp import mcp_available, mcp_config
from app.logger import debug, info, warning, error
from app.debug import DebugCollector
from app.context_builder import ContextBuilder
from app.orchestration import OrchestrationController

_mcp_event_loop: asyncio.AbstractEventLoop | None = None

def get_mcp_loop() -> asyncio.AbstractEventLoop:
    global _mcp_event_loop
    if _mcp_event_loop is None or _mcp_event_loop.is_closed():
        _mcp_event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_mcp_event_loop)
    return _mcp_event_loop

def run_mcp_async(coro):
    loop = get_mcp_loop()
    return loop.run_until_complete(coro)


def _cleanup_orphan_tool_results(session) -> int:
    """Удалить сообщения с tool_result без соответствующего tool_use.
    
    Возвращает количество удалённых сообщений.
    """
    tool_use_ids = set()
    messages_to_remove = []
    
    for i, msg in enumerate(session.messages):
        # Собираем все tool_use_id из assistant сообщений
        if msg.role == "assistant" and msg.tool_use:
            for tu in msg.tool_use:
                if tu.get("id"):
                    tool_use_ids.add(tu.get("id"))
        
        # Проверяем tool_result без соответствующего tool_use
        if msg.role == "tool":
            tc_id = msg.tool_call_id
            if tc_id and tc_id not in tool_use_ids:
                messages_to_remove.append(i)
                warning("CLEANUP", f"Found orphan tool_result: {tc_id}")
    
    # Удаляем в обратном порядке (чтобы не сбились индексы)
    for i in reversed(messages_to_remove):
        session.messages.pop(i)
    
    if messages_to_remove:
        info("CLEANUP", f"Removed {len(messages_to_remove)} orphan tool_result messages")
    
    return len(messages_to_remove)


api_bp = Blueprint("api", __name__)
admin_bp = Blueprint("admin", __name__)
auth_bp = Blueprint("auth", __name__)
mcp_bp = Blueprint("mcp", __name__)


def get_interview_prompt() -> str:
    """Получить промт для интервью пользователя"""
    return config.get_context_file("INTERVIEW.md") or ""


def should_show_interview(session, user_id: str | None = None) -> bool:
    """Проверить нужно ли показывать интервью.
    
    Интервью показывается только если:
    1. Это первое сообщение в сессии
    2. Пользователь еще не прошел интервью
    """
    if session.get_active_message_count() != 0:
        return False
    
    user = None
    if session.owner_id:
        from app import storage as app_storage
        user = app_storage.storage.load_user(session.owner_id)
    
    if not user and user_id:
        from app import storage as app_storage
        user = app_storage.storage.load_user(user_id)
    
    if not user:
        try:
            user = get_current_user()
        except:
            pass
    
    if user:
        return not user.interview_completed
    
    return False


@admin_bp.route("/")
def admin_page():
    return render_template("admin.html")


def require_auth(f):
    def wrapper(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")
        if not api_key or api_key != config.api_key:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)

    wrapper.__name__ = f.__name__
    return wrapper


def get_session_id() -> str:
    session_id = request.headers.get("X-Session-Id")
    if not session_id:
        session_id = request.cookies.get("session_id", "default")
    return session_id


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data or "username" not in data or "password" not in data:
        return jsonify({"error": "Missing username or password"}), 400

    auth_provider = get_auth_provider()
    user, error = auth_provider.login(data["username"], data["password"])

    if error:
        return jsonify({"error": error}), 401

    return jsonify({
        "message": "Login successful",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "team_role": user.team_role,
        }
    })


@auth_bp.route("/logout", methods=["POST"])
def logout():
    auth_provider = get_auth_provider()
    auth_provider.logout()
    return jsonify({"message": "Logged out"})


@auth_bp.route("/me", methods=["GET"])
def me():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401

    return jsonify({
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "team_role": user.team_role,
        "preferences": user.preferences,
        "interview_completed": user.interview_completed,
        "is_active": user.is_active,
    })


@api_bp.route("/users", methods=["GET"])
@require_admin
def list_users():
    from app.storage import storage
    users = storage.list_users()
    return jsonify(users)


@api_bp.route("/users", methods=["POST"])
@require_admin
def create_user():
    data = request.get_json()
    if not data or "username" not in data or "email" not in data or "password" not in data:
        return jsonify({"error": "Missing required fields"}), 400

    auth_provider = get_auth_provider()
    user, error = auth_provider.create_user(
        username=data["username"],
        email=data["email"],
        password=data["password"],
        role=data.get("role", "user"),
        team_role=data.get("team_role", "developer"),
        notes=data.get("notes", ""),
        interview_completed=data.get("interview_completed", False),
    )

    if error:
        return jsonify({"error": error}), 400

    return jsonify({
        "message": "User created",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "team_role": user.team_role,
        }
    })


@api_bp.route("/users/<user_id>", methods=["GET"])
@require_admin
def get_user(user_id):
    from app.storage import storage
    user = storage.load_user(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "team_role": user.team_role,
        "preferences": user.preferences,
        "notes": user.notes,
        "interview_completed": user.interview_completed,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat(),
        "last_login": user.last_login.isoformat() if user.last_login else None,
    })


@api_bp.route("/users/<user_id>", methods=["PUT"])
@require_admin
def update_user(user_id):
    from app.storage import storage
    user = storage.load_user(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json()

    if "email" in data:
        user.email = data["email"]
    if "role" in data:
        user.role = data["role"]
    if "team_role" in data:
        user.team_role = data["team_role"]
    if "notes" in data:
        user.notes = data["notes"]
    if "interview_completed" in data:
        user.interview_completed = data["interview_completed"]
    if "is_active" in data:
        user.is_active = data["is_active"]
    if "preferences" in data:
        user.preferences = data["preferences"]

    if "password" in data and data["password"]:
        user.set_password(data["password"])

    storage.save_user(user)

    return jsonify({"message": "User updated"})


@api_bp.route("/users/<user_id>", methods=["DELETE"])
@require_admin
def delete_user(user_id):
    from app.storage import storage
    if not storage.delete_user(user_id):
        return jsonify({"error": "User not found"}), 404

    return jsonify({"message": "User deleted"})


@api_bp.route("/users/<user_id>/reset-password", methods=["POST"])
@require_admin
def reset_password(user_id):
    from app.storage import storage
    from app.models import User
    user = storage.load_user(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    new_password = User.generate_temp_password()
    user.set_password(new_password)
    storage.save_user(user)

    return jsonify({
        "message": "Password reset",
        "new_password": new_password,
    })


@api_bp.route("/profile", methods=["GET"])
@require_user
def get_profile():
    """Получить профиль текущего пользователя"""
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "User not found"}), 404
    
    return jsonify({
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role,
        "team_role": current_user.team_role,
        "preferences": current_user.preferences,
        "notes": current_user.notes,
        "interview_completed": current_user.interview_completed,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at.isoformat(),
        "last_login": current_user.last_login.isoformat() if current_user.last_login else None,
    })


@api_bp.route("/profile", methods=["PUT"])
@require_user
def update_profile():
    """Обновить профиль текущего пользователя"""
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "User not found"}), 404
    
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    from app.storage import storage
    
    if "email" in data:
        current_user.email = data["email"]
    if "team_role" in data:
        current_user.team_role = data["team_role"]
    if "notes" in data:
        current_user.notes = data["notes"]
    if "preferences" in data:
        current_user.preferences = data["preferences"]
    
    storage.save_user(current_user)
    
    return jsonify({
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role,
        "team_role": current_user.team_role,
        "preferences": current_user.preferences,
        "notes": current_user.notes,
        "interview_completed": current_user.interview_completed,
        "is_active": current_user.is_active,
    })


@api_bp.route("/users/by-username/<username>", methods=["GET"])
@require_user
def get_user_by_username(username):
    """Получить пользователя по username (для просмотра профилей других пользователей)"""
    from app.storage import storage
    user = storage.get_user_by_username(username)
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    return jsonify({
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "team_role": user.team_role,
        "notes": user.notes,
        "interview_completed": user.interview_completed,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat(),
        "last_login": user.last_login.isoformat() if user.last_login else None,
    })


@api_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@mcp_bp.route("/mcp/servers", methods=["GET"])
@require_user
def list_mcp_servers():
    if not mcp_available():
        return jsonify({"error": "MCP not available. Install: pip install mcp"}), 400
    
    servers = mcp_config.list_servers()
    return jsonify({"servers": servers})


@mcp_bp.route("/mcp/servers/<server_name>/tools", methods=["GET"])
@require_user
def get_mcp_server_tools(server_name):
    import asyncio
    
    if not mcp_available():
        return jsonify({"error": "MCP not available. Install: pip install mcp"}), 400
    
    if not mcp_config.is_server_configured(server_name):
        return jsonify({"error": f"Server '{server_name}' not configured"}), 404
    
    try:
        from app.mcp import MCPManager
        tools = run_mcp_async(MCPManager.get_tools([server_name]))
        return jsonify({
            "server": server_name,
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema
                }
                for t in tools
            ]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@mcp_bp.route("/session/mcp", methods=["GET"])
@require_user
def get_session_mcp_servers():
    session_id = get_session_id()
    session = session_manager.get_session(session_id)
    return jsonify({"mcp_servers": session.get_mcp_servers(), "all_mcp_servers": session.get_all_mcp_servers()})


@mcp_bp.route("/session/mcp", methods=["PUT"])
@require_user
def update_session_mcp_servers():
    data = request.get_json()
    if not data or "mcp_servers" not in data:
        return jsonify({"error": "Missing 'mcp_servers' field"}), 400
    
    mcp_servers = data["mcp_servers"]
    
    for server_name in mcp_servers:
        if not mcp_config.is_server_configured(server_name):
            return jsonify({"error": f"MCP server '{server_name}' not configured"}), 400
    
    session_id = get_session_id()
    session = session_manager.get_session(session_id)
    
    # Preserve inactive servers from before
    existing_inactive = {s.get("name"): s for s in session.get_all_mcp_servers() if s.get("active") == "false"}
    
    session.clear_mcp_servers()
    for server_name in mcp_servers:
        if server_name in existing_inactive:
            return jsonify({"error": f"MCP server '{server_name}' недоступен (ранее был недоступен). Невозможно включить."}), 400
        session.add_mcp_server(server_name)
    session_manager.save_session(session_id)
    
    return jsonify({"message": "MCP servers updated", "mcp_servers": session.get_mcp_servers()})


@mcp_bp.route("/session/mcp", methods=["POST"])
@require_user
def add_session_mcp_server():
    data = request.get_json()
    if not data or "server_name" not in data:
        return jsonify({"error": "Missing 'server_name' field"}), 400
    
    server_name = data["server_name"]
    
    if not mcp_config.is_server_configured(server_name):
        return jsonify({"error": f"MCP server '{server_name}' not configured"}), 400
    
    session_id = get_session_id()
    session = session_manager.get_session(session_id)
    
    # Check if server is already in the list as inactive
    all_servers = session.get_all_mcp_servers()
    for s in all_servers:
        if s.get("name") == server_name:
            if s.get("active") == "false":
                return jsonify({"error": f"MCP server '{server_name}' недоступен (ранее был недоступен). Невозможно включить."}), 400
            # Already active, nothing to do
            return jsonify({"message": "MCP server already active", "mcp_servers": session.get_mcp_servers()})
    
    session.add_mcp_server(server_name)
    session_manager.save_session(session_id)
    
    return jsonify({"message": "MCP server added", "mcp_servers": session.get_mcp_servers()})


@mcp_bp.route("/session/mcp/<server_name>", methods=["DELETE"])
@require_user
def remove_session_mcp_server(server_name):
    session_id = get_session_id()
    session = session_manager.get_session(session_id)
    session.remove_mcp_server(server_name)
    session_manager.save_session(session_id)
    
    return jsonify({"message": "MCP server removed", "mcp_servers": session.get_mcp_servers()})


@mcp_bp.route("/session/mcp", methods=["DELETE"])
@require_user
def clear_session_mcp_servers():
    session_id = get_session_id()
    session = session_manager.get_session(session_id)
    session.clear_mcp_servers()
    session_manager.save_session(session_id)
    
    return jsonify({"message": "MCP servers cleared", "mcp_servers": session.get_mcp_servers()})


@api_bp.route("/note", methods=["POST"])
@require_user
def add_note():
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "Missing 'content' field"}), 400

    content = data["content"]
    session_id = get_session_id()
    session = session_manager.get_session(session_id)

    current_usage = session.get_current_usage()
    session.add_note_message(content, current_usage)
    session_manager.save_session(session_id)

    last_msg = session.messages[-1]
    return jsonify({
        "role": last_msg.role,
        "content": last_msg.content,
        "usage": last_msg.usage,
    })


def _handle_user_info_update(parsed_status: dict, user_id: str | None) -> None:
    """Обработать обновление user_info из статуса и сохранить в профиль пользователя"""
    user_info = parsed_status.get("user_info")
    if not user_info or not user_id:
        return
    
    try:
        from app import storage as app_storage
        user = app_storage.storage.load_user(user_id)
        if not user:
            return
        
        if user.interview_completed:
            return
        
        existing_notes = user.notes or ""
        if existing_notes:
            new_notes = f"{existing_notes}\n\n[ИНТЕРВЬЮ]\n{user_info}"
        else:
            new_notes = f"[ИНТЕРВЬЮ]\n{user_info}"
        
        user.notes = new_notes
        user.interview_completed = True
        app_storage.storage.save_user(user)
    except Exception as e:
        pass


def _emit_project_status(session, previous_status: dict) -> dict:
    """Определить тип изменения статуса и сформировать данные для отправки"""
    current = session.status or {}
    prev = previous_status
    
    project = current.get("project")
    task_name = current.get("task_name", "conversation")
    state = current.get("state")
    
    prev_project = prev.get("project")
    prev_task_name = prev.get("task_name")
    prev_state = prev.get("state")
    
    # Определяем тип события
    if project and project != prev_project:
        event_type = "project_open"
    elif task_name == "conversation" and prev_task_name and prev_task_name != "conversation":
        event_type = "free_conversation"
    elif state and state != prev_state:
        event_type = "state_change"
    elif project and (not prev_project or prev_project != project):
        event_type = "project_update"
    else:
        event_type = None
    
    if not event_type:
        return None
    
    return {
        "type": "project_status",
        "event_type": event_type,
        "project": project,
        "task_name": task_name,
        "state": state,
        "previous_state": prev_state,
    }


def _handle_project_updates(session) -> None:
    """Обработать обновления проекта из статуса"""
    status = session.status
    
    project_name = status.get("project")
    if not project_name:
        return
    
    if not project_manager.project_manager.project_exists(project_name):
        project_manager.project_manager.create_project(project_name)
    
    updated_info = status.get("updated_project_info")
    if updated_info:
        project_manager.project_manager.update_project_info(project_name, updated_info)
    
    current_task = status.get("current_task_info")
    if current_task:
        project_manager.project_manager.save_current_task(project_name, current_task)

    invariants = status.get("invariants")
    if invariants:
        project_manager.project_manager.save_invariants(project_name, invariants)

    schedule_data = status.get("schedule")
    if schedule_data and project_name:
        try:
            model = schedule_data.get("model") or session.model
            schedule_type = schedule_data.get("type", "cron")
            
            run_at = None
            if schedule_type == "once" and schedule_data.get("run_at"):
                run_at = datetime.fromisoformat(schedule_data.get("run_at"))
            
            scheduler.scheduler.create_schedule(
                project_name=project_name,
                name=schedule_data.get("name", "Scheduled task"),
                prompt=schedule_data.get("prompt", ""),
                cron=schedule_data.get("cron", "0 0 * * *"),
                type=schedule_type,
                run_at=run_at,
                model=model,
                session_id=session.session_id,
                enabled=True,
            )
        except Exception as e:
            error("ROUTES", f"Failed to create schedule from status block: {e}")


@api_bp.route("/projects/<project_name>/schedules", methods=["GET"])
@require_user
def list_schedules(project_name):
    """Получить список расписаний проекта"""
    schedules = scheduler.scheduler.get_schedules(project_name)
    return jsonify([
        {
            "id": s.id,
            "name": s.name,
            "prompt": s.prompt,
            "model": s.model,
            "session_id": s.session_id,
            "cron": s.cron,
            "type": s.type,
            "run_at": s.run_at.isoformat() if s.run_at else None,
            "enabled": s.enabled,
            "last_run": s.last_run.isoformat() if s.last_run else None,
            "next_run": s.next_run.isoformat() if s.next_run else None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in schedules
    ])


@api_bp.route("/projects/<project_name>/schedules", methods=["POST"])
@require_user
def create_schedule(project_name):
    """Создать новое расписание"""
    data = request.get_json()
    if not data or "name" not in data or "prompt" not in data:
        return jsonify({"error": "Missing required fields: name, prompt"}), 400

    schedule_type = data.get("type", "cron")
    
    if schedule_type == "once" and not data.get("run_at"):
        return jsonify({"error": "Missing required field for one-time schedule: run_at"}), 400
    
    if schedule_type == "cron" and not data.get("cron"):
        return jsonify({"error": "Missing required field for cron schedule: cron"}), 400

    try:
        run_at = None
        if data.get("run_at"):
            run_at = datetime.fromisoformat(data["run_at"])
        
        schedule = scheduler.scheduler.create_schedule(
            project_name=project_name,
            name=data["name"],
            prompt=data["prompt"],
            cron=data.get("cron"),
            type=schedule_type,
            run_at=run_at,
            model=data.get("model"),
            session_id=data.get("session_id"),
            enabled=data.get("enabled", True),
        )
        return jsonify({
            "id": schedule.id,
            "name": schedule.name,
            "prompt": schedule.prompt,
            "model": schedule.model,
            "session_id": schedule.session_id,
            "cron": schedule.cron,
            "type": schedule.type,
            "run_at": schedule.run_at.isoformat() if schedule.run_at else None,
            "enabled": schedule.enabled,
            "last_run": schedule.last_run.isoformat() if schedule.last_run else None,
            "next_run": schedule.next_run.isoformat() if schedule.next_run else None,
            "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/projects/<project_name>/schedules/<schedule_id>", methods=["PUT"])
@require_user
def update_schedule(project_name, schedule_id):
    """Обновить расписание"""
    data = request.get_json()

    try:
        run_at = None
        if data.get("run_at"):
            run_at = datetime.fromisoformat(data["run_at"])
        
        schedule = scheduler.scheduler.update_schedule(
            project_name=project_name,
            schedule_id=schedule_id,
            name=data.get("name"),
            prompt=data.get("prompt"),
            cron=data.get("cron"),
            type=data.get("type"),
            run_at=run_at,
            model=data.get("model"),
            session_id=data.get("session_id"),
            enabled=data.get("enabled"),
        )
        if not schedule:
            return jsonify({"error": "Schedule not found"}), 404

        return jsonify({
            "id": schedule.id,
            "name": schedule.name,
            "prompt": schedule.prompt,
            "model": schedule.model,
            "session_id": schedule.session_id,
            "cron": schedule.cron,
            "type": schedule.type,
            "run_at": schedule.run_at.isoformat() if schedule.run_at else None,
            "enabled": schedule.enabled,
            "last_run": schedule.last_run.isoformat() if schedule.last_run else None,
            "next_run": schedule.next_run.isoformat() if schedule.next_run else None,
            "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/projects/<project_name>/schedules/<schedule_id>", methods=["DELETE"])
@require_user
def delete_schedule(project_name, schedule_id):
    """Удалить расписание"""
    success = scheduler.scheduler.delete_schedule(project_name, schedule_id)
    if not success:
        return jsonify({"error": "Schedule not found"}), 404
    return jsonify({"message": "Schedule deleted"})


@api_bp.route("/projects/<project_name>/schedules/<schedule_id>/run", methods=["POST"])
@require_user
def run_schedule(project_name, schedule_id):
    """Запустить расписание вручную"""
    success = scheduler.scheduler.run_job(project_name, schedule_id)
    if not success:
        return jsonify({"error": "Schedule not found or execution failed"}), 404
    return jsonify({"message": "Job executed"})


@api_bp.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing 'message' field"}), 400

    user_message = data["message"]
    provider_name = data.get("provider")
    model = data.get("model")
    debug_mode = data.get("debug", False)
    tsm_mode = data.get("tsm_mode")
    use_rag = data.get("use_rag", False)
    rag_index_name = data.get("rag_index_name")
    rag_top_k = data.get("rag_top_k", 5)
    
    session_id = get_session_id()
    user_id = request.headers.get("X-User-Id")
    
    handler = ChatHandler()
    result = handler.handle(
        session_id=session_id,
        message=user_message,
        provider_name=provider_name,
        model=model,
        debug_mode=debug_mode,
        user_id=user_id,
        tsm_mode=tsm_mode,
        use_rag=use_rag,
        rag_index_name=rag_index_name,
        rag_top_k=rag_top_k
    )
    
    if "error" in result:
        return jsonify(result), 400
    
    return jsonify(result)


@api_bp.route("/chat/status/<request_id>", methods=["GET"])
@require_user
def chat_status(request_id: str):
    status = RequestTracker.get_status(request_id)
    if not status:
        return jsonify({"error": "Request not found"}), 404
    
    return jsonify({
        "status": status.status,
        "message_id": status.message_id,
        "error": status.error,
    })


@api_bp.route("/chat/message/<message_id>", methods=["GET"])
@require_user
def get_message(message_id: str):
    session_id = get_session_id()
    session = session_manager.get_session(session_id)
    
    for msg in session.messages:
        if msg.id == message_id:
            return jsonify({
                "role": msg.role,
                "content": msg.content,
                "reasoning": msg.reasoning,
                "usage": msg.usage,
                "model": msg.model,
                "status": msg.status,
                "id": msg.id,
            })
    
    return jsonify({"error": "Message not found"}), 404


@api_bp.route("/chat/stream", methods=["POST"])
def chat_stream():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing 'message' field"}), 400

    user_message = data["message"]
    provider_name = data.get("provider")
    model = data.get("model")
    debug_mode = data.get("debug", False)
    source_type = data.get("source", "web")
    
    session_id = get_session_id()
    user_id = request.headers.get("X-User-Id")
    
    handler = StreamHandler()
    
    return Response(
        handler.handle(
            session_id=session_id,
            message=user_message,
            provider_name=provider_name,
            model=model,
            debug_mode=debug_mode,
            user_id=user_id
        ),
        mimetype='text/event-stream'
    )


def _old_chat_stream_placeholder():
    """Placeholder - old code removed."""
    pass


@api_bp.route("/chat/reset", methods=["POST"])
def reset_chat():
    from app.logger import info
    session_id = get_session_id()
    info("RESET", f"Resetting session: {session_id}")
    session_manager.reset_session(session_id)
    info("RESET", f"Session reset complete: {session_id}")

    return jsonify({
        "status": "reset",
        "session_id": session_id,
    })


@api_bp.route("/sessions", methods=["GET"])
@require_user
def list_sessions():
    sessions = session_manager.list_sessions()
    return jsonify({"sessions": sessions})


@api_bp.route("/sessions/<session_id>", methods=["GET"])
@require_user
def get_session(session_id: str):
    session = session_manager.get_session(session_id, reload=True)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    
    current_branch_messages = session.get_current_branch_messages()
    
    messages = [
        {
            "role": m.role,
            "content": m.content,
            "usage": m.usage,
            "debug": m.debug,
            "model": m.model,
            "summary_of": m.summary_of,
            "created_at": m.created_at.isoformat(),
            "disabled": m.disabled,
            "source": m.source,
            "status": m.status,
            "reasoning": m.reasoning,
            "id": m.id,
            "group_id": m.group_id,
            "tool_use": m.tool_use,
        }
        for m in current_branch_messages
    ]

    return jsonify({
        "session_id": session.session_id,
        "messages": messages,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "provider": session.provider,
        "model": session.model,
        "total_tokens": session.total_tokens,
        "input_tokens": session.input_tokens,
        "output_tokens": session.output_tokens,
        "session_settings": session.session_settings,
        "tsm_mode": session.session_settings.get("tsm_mode"),
        "branches": [
            {
                "id": b.id,
                "name": b.name,
            }
            for b in session.branches
        ],
        "checkpoints": [
            {
                "id": cp.id,
                "name": cp.name,
                "branch_id": cp.branch_id,
                "message_count": cp.message_count,
            }
            for cp in session.checkpoints
        ],
        "current_branch": session.current_branch,
        "project": session.status.get("project") if session.status else None,
        "task_name": session.status.get("task_name") if session.status else None,
        "state": session.status.get("state") if session.status else None,
    })


@api_bp.route("/sessions/<session_id>", methods=["DELETE"])
@require_user
def delete_session(session_id: str):
    if session_id == "default":
        return jsonify({"error": "Cannot delete default session"}), 400
    
    success = session_manager.delete_session(session_id)
    if not success:
        return jsonify({"error": "Session not found"}), 404
    
    return jsonify({"status": "deleted", "session_id": session_id})


@api_bp.route("/sessions/<session_id>/rename", methods=["POST"])
@require_user
def rename_session(session_id: str):
    if session_id == "default":
        return jsonify({"error": "Cannot rename default session"}), 400
    
    data = request.get_json()
    if not data or "new_name" not in data:
        return jsonify({"error": "Missing 'new_name' field"}), 400
    
    new_name = data["new_name"].strip()
    if not new_name:
        return jsonify({"error": "New name cannot be empty"}), 400
    
    success = session_manager.rename_session(session_id, new_name)
    if not success:
        return jsonify({"error": "Failed to rename session (may already exist)"}), 400
    
    return jsonify({"status": "renamed", "old_id": session_id, "new_id": new_name})


@api_bp.route("/sessions/<session_id>/copy", methods=["POST"])
@require_user
def copy_session(session_id: str):
    session_data = session_manager.get_session_data(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404
    
    data = request.get_json()
    if not data or "new_session_id" not in data:
        return jsonify({"error": "Missing 'new_session_id' field"}), 400
    
    new_session_id = data["new_session_id"].strip()
    if not new_session_id:
        return jsonify({"error": "New session_id cannot be empty"}), 400
    
    if session_manager.get_session_data(new_session_id):
        return jsonify({"error": "Session already exists"}), 400
    
    session_data["session_id"] = new_session_id
    session_manager.import_session(session_data)
    
    return jsonify({"status": "copied", "session_id": new_session_id})


@api_bp.route("/sessions/<session_id>/access", methods=["GET"])
@require_user
def get_session_access(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    
    return jsonify({
        "owner_id": session.owner_id,
        "access": session.access,
    })


@api_bp.route("/sessions/<session_id>/access", methods=["POST"])
@require_user
def update_session_access(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing data"}), 400
    
    from app.auth import get_current_user
    user = get_current_user()
    
    if session.owner_id and session.owner_id != (user.id if user else None):
        if not user or user.role != "admin":
            return jsonify({"error": "Not authorized to change access"}), 403
    
    access = data.get("access", "owner")
    if access not in ["owner", "team", "public"]:
        return jsonify({"error": "Invalid access value"}), 400
    
    session.access = access
    if user:
        session.owner_id = user.id
    
    session_manager.save_session(session_id)
    
    return jsonify({"status": "updated", "access": access})


@api_bp.route("/sessions/<session_id>/clear-debug", methods=["POST"])
@require_user
def clear_session_debug(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    
    session.clear_debug()
    session_manager.save_session(session_id)
    
    return jsonify({"status": "cleared", "session_id": session_id})


@api_bp.route("/sessions/<session_id>/messages/<int:index>", methods=["DELETE"])
@require_user
def delete_message(session_id: str, index: int):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    
    if session.delete_message(index):
        session_manager.save_session(session_id)
        return jsonify({"status": "deleted", "index": index})
    
    return jsonify({"error": "Invalid message index"}), 400


@api_bp.route("/sessions/<session_id>/messages/<int:index>/toggle", methods=["POST"])
@require_user
def toggle_message(session_id: str, index: int):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    
    if session.toggle_message(index):
        session_manager.save_session(session_id)
        msg = session.messages[index]
        return jsonify({"status": "toggled", "index": index, "disabled": msg.disabled})
    
    return jsonify({"error": "Invalid message index"}), 400



@api_bp.route("/sessions/<session_id>/context-settings", methods=["GET"])
@require_user
def get_context_settings(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    optimization = session.session_settings.get("context_optimization", "none")
    
    summarization_enabled = session.session_settings.get("summarization_enabled", False)
    summarize_after_n = session.session_settings.get("summarize_after_n", config.default_messages_interval)
    summarize_after_minutes = session.session_settings.get("summarize_after_minutes", 0)
    summarize_context_percent = session.session_settings.get("summarize_context_percent", 0)

    sliding_window_type = session.session_settings.get("sliding_window_type", "messages")
    sliding_window_limit = session.session_settings.get("sliding_window_limit", 10)

    return jsonify({
        "context_optimization": optimization,
        "summarization_enabled": summarization_enabled,
        "summarize_after_n": summarize_after_n,
        "summarize_after_minutes": summarize_after_minutes,
        "summarize_context_percent": summarize_context_percent,
        "sliding_window_type": sliding_window_type,
        "sliding_window_limit": sliding_window_limit,
        "default_interval": config.default_messages_interval,
    })


@api_bp.route("/sessions/<session_id>/context-settings", methods=["POST"])
@require_user
def set_context_settings(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    if "context_optimization" in data:
        opt = data["context_optimization"]
        if opt in ("none", "summarization", "sliding_window"):
            session.session_settings["context_optimization"] = opt

    if "summarization_enabled" in data:
        session.session_settings["summarization_enabled"] = bool(data["summarization_enabled"])

    if "summarize_after_n" in data:
        interval = int(data["summarize_after_n"])
        if interval < 5:
            interval = 5
        if interval > 100:
            interval = 100
        session.session_settings["summarize_after_n"] = interval

    if "summarize_after_minutes" in data:
        minutes = int(data["summarize_after_minutes"])
        if minutes < 0:
            minutes = 0
        if minutes > 10080:
            minutes = 10080
        session.session_settings["summarize_after_minutes"] = minutes

    if "summarize_context_percent" in data:
        percent = int(data["summarize_context_percent"])
        if percent < 0:
            percent = 0
        if percent > 100:
            percent = 100
        session.session_settings["summarize_context_percent"] = percent

    if "sliding_window_type" in data:
        wtype = data["sliding_window_type"]
        if wtype in ("messages", "tokens"):
            session.session_settings["sliding_window_type"] = wtype

    if "sliding_window_limit" in data:
        limit = int(data["sliding_window_limit"])
        if limit < 1:
            limit = 1
        if limit > 1000:
            limit = 1000
        session.session_settings["sliding_window_limit"] = limit

    if "debug_enabled" in data:
        session.session_settings["debug_enabled"] = bool(data["debug_enabled"])

    if "stream_enabled" in data:
        session.session_settings["stream_enabled"] = bool(data["stream_enabled"])

    session_manager.save_session(session_id)

    return jsonify({"status": "saved"})


@api_bp.route("/sessions/<session_id>/rag-settings", methods=["GET"])
@require_user
def get_rag_settings(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    rag_settings = session.session_settings.get("rag_settings", {
        "enabled": False,
        "index_name": "",
        "version": None,
        "top_k": 5,
        "reranker": {
            "enabled": False,
            "type": "relative",
            "threshold": 0.3,
            "multiplier": 1.5,
            "std_multiplier": 2.0,
            "top_k_before": 20,
        },
        "say_unknown_enabled": False,
        "say_unknown_threshold": 0.3,
    })

    reranker = rag_settings.get("reranker", {})
    if not reranker:
        reranker = {
            "enabled": False,
            "type": "relative",
            "threshold": 0.3,
            "multiplier": 1.5,
            "std_multiplier": 2.0,
            "top_k_before": 20,
        }

    return jsonify({
        "enabled": rag_settings.get("enabled", False),
        "index_name": rag_settings.get("index_name", ""),
        "version": rag_settings.get("version"),
        "top_k": rag_settings.get("top_k", 5),
        "reranker": reranker,
        "say_unknown_enabled": rag_settings.get("say_unknown_enabled", False),
        "say_unknown_threshold": rag_settings.get("say_unknown_threshold", 0.3),
    })


@api_bp.route("/sessions/<session_id>/rag-settings", methods=["PUT"])
@require_user
def set_rag_settings(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    if "rag_settings" not in session.session_settings:
        session.session_settings["rag_settings"] = {
            "enabled": False,
            "index_name": "",
            "version": None,
            "top_k": 5,
            "reranker": {
                "enabled": False,
                "type": "relative",
                "threshold": 0.3,
                "multiplier": 1.5,
                "std_multiplier": 2.0,
                "top_k_before": 20,
            },
            "say_unknown_enabled": False,
            "say_unknown_threshold": 0.3,
        }

    if "enabled" in data:
        session.session_settings["rag_settings"]["enabled"] = bool(data["enabled"])
    if "index_name" in data:
        session.session_settings["rag_settings"]["index_name"] = str(data["index_name"] or "")
    if "version" in data:
        session.session_settings["rag_settings"]["version"] = data["version"]
    if "top_k" in data:
        top_k = int(data["top_k"])
        if top_k < 1:
            top_k = 1
        if top_k > 20:
            top_k = 20
        session.session_settings["rag_settings"]["top_k"] = top_k

    reranker_data = data.get("reranker", {})
    if reranker_data:
        if "reranker" not in session.session_settings["rag_settings"]:
            session.session_settings["rag_settings"]["reranker"] = {
                "enabled": False,
                "type": "relative",
                "threshold": 0.3,
                "multiplier": 1.5,
                "std_multiplier": 2.0,
                "top_k_before": 20,
            }
        
        r = session.session_settings["rag_settings"]["reranker"]
        if "enabled" in reranker_data:
            r["enabled"] = bool(reranker_data["enabled"])
        if "type" in reranker_data:
            r["type"] = reranker_data["type"]
        if "threshold" in reranker_data:
            r["threshold"] = float(reranker_data["threshold"])
        if "multiplier" in reranker_data:
            r["multiplier"] = float(reranker_data["multiplier"])
        if "std_multiplier" in reranker_data:
            r["std_multiplier"] = float(reranker_data["std_multiplier"])
        if "top_k_before" in reranker_data:
            r["top_k_before"] = int(reranker_data["top_k_before"])

    if "say_unknown_enabled" in data:
        if "say_unknown_enabled" not in session.session_settings["rag_settings"]:
            session.session_settings["rag_settings"]["say_unknown_enabled"] = False
        session.session_settings["rag_settings"]["say_unknown_enabled"] = bool(data["say_unknown_enabled"])
    if "say_unknown_threshold" in data:
        if "say_unknown_threshold" not in session.session_settings["rag_settings"]:
            session.session_settings["rag_settings"]["say_unknown_threshold"] = 0.3
        session.session_settings["rag_settings"]["say_unknown_threshold"] = float(data["say_unknown_threshold"])
    else:
        # Ensure default value exists
        if "say_unknown_threshold" not in session.session_settings["rag_settings"]:
            session.session_settings["rag_settings"]["say_unknown_threshold"] = 0.3

    session_manager.save_session(session_id)

    return jsonify({
        "status": "saved",
        "debug": {
            "say_unknown_enabled": session.session_settings["rag_settings"].get("say_unknown_enabled"),
            "say_unknown_threshold": session.session_settings["rag_settings"].get("say_unknown_threshold"),
        }
    })


@api_bp.route("/sessions/<session_id>/tsm-settings", methods=["GET"])
def get_tsm_settings(session_id: str):
    session_manager.save_session(session_id)  # Save any pending changes first
    session = session_manager.get_session(session_id, reload=True)  # Reload to get fresh data
    if not session:
        return jsonify({"error": "Session not found"}), 404

    tsm_mode = tsm.get_tsm_mode(session)
    state_info = tsm.get_current_state_info(session)

    return jsonify({
        "tsm_mode": tsm_mode,
        "mode_name": state_info["mode_name"],
        "task_name": state_info["task_name"],
        "state": state_info["state"],
        "allowed_transitions": state_info["allowed_transitions"],
        "transition_log": state_info.get("transition_log", []),
        "available_modes": tsm.TSM_MODES,
        "mode_descriptions": tsm.TSM_MODE_DESCRIPTIONS,
    })


@api_bp.route("/sessions/<session_id>/tsm-settings", methods=["POST"])
def set_tsm_settings(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    if "tsm_mode" in data:
        mode = data["tsm_mode"]
        try:
            tsm.set_tsm_mode(session, mode)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    session_manager.save_session(session_id)

    return jsonify({"status": "saved"})


@api_bp.route("/sessions/<session_id>/summarize", methods=["POST"])
@require_user
def manual_summarize(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    messages_to_summarize = session.get_messages_before_last_user()
    if not messages_to_summarize:
        return jsonify({"error": "No messages to summarize", "has_summary": len([m for m in session.messages if m.role == "summary"]) > 0}), 400

    debug_mode = request.args.get("debug", "false").lower() == "true"
    summary_content, debug_info = summarizer.summarize_messages(
        messages_to_summarize,
        debug=debug_mode,
    )

    summarized_indices = list(range(len(messages_to_summarize)))
    session.add_summary_message(
        content=summary_content,
        summarized_indices=summarized_indices,
        usage={},
        debug=debug_info if debug_mode else None,
        model=config.summarizer_model,
    )

    session_manager.save_session(session_id)

    return jsonify({
        "status": "summarized",
        "summary": summary_content,
        "summarized_count": len(messages_to_summarize),
        "debug": debug_info if debug_mode else None,
    })


@api_bp.route("/sessions/<session_id>/checkpoints", methods=["GET"])
@require_user
def list_checkpoints(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    checkpoints = [
        {
            "id": cp.id,
            "name": cp.name,
            "branch_id": cp.branch_id,
            "message_count": cp.message_count,
            "created_at": cp.created_at.isoformat(),
        }
        for cp in session.checkpoints
    ]

    return jsonify({"checkpoints": checkpoints})


@api_bp.route("/sessions/<session_id>/checkpoints", methods=["POST"])
@require_user
def create_checkpoint(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    data = request.get_json() or {}
    name = data.get("name")

    try:
        checkpoint = session.create_checkpoint(name)
    except ValueError as e:
        return jsonify({"error": str(e)}), 500
    session_manager.save_session(session_id)

    return jsonify({
        "id": checkpoint.id,
        "name": checkpoint.name,
        "branch_id": checkpoint.branch_id,
        "message_count": checkpoint.message_count,
        "created_at": checkpoint.created_at.isoformat(),
    })


@api_bp.route("/sessions/<session_id>/checkpoints/<checkpoint_id>/rename", methods=["POST"])
@require_user
def rename_checkpoint(session_id: str, checkpoint_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    data = request.get_json()
    if not data or "name" not in data:
        return jsonify({"error": "Missing 'name' field"}), 400

    if session.rename_checkpoint(checkpoint_id, data["name"]):
        session_manager.save_session(session_id)
        return jsonify({"status": "renamed", "checkpoint_id": checkpoint_id, "name": data["name"]})

    return jsonify({"error": "Checkpoint not found"}), 404


@api_bp.route("/sessions/<session_id>/checkpoints/<checkpoint_id>", methods=["DELETE"])
@require_user
def delete_checkpoint(session_id: str, checkpoint_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    if session.delete_checkpoint(checkpoint_id):
        session_manager.save_session(session_id)
        return jsonify({"status": "deleted", "checkpoint_id": checkpoint_id})

    return jsonify({"error": "Checkpoint not found"}), 404


@api_bp.route("/sessions/<session_id>/checkpoints/<checkpoint_id>/branch", methods=["POST"])
@require_user
def create_branch_from_checkpoint(session_id: str, checkpoint_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    data = request.get_json() or {}
    name = data.get("name")

    branch = session.create_branch_from_checkpoint(checkpoint_id, name)
    if not branch:
        return jsonify({"error": "Checkpoint not found"}), 404

    session_manager.save_session(session_id)

    return jsonify({
        "id": branch.id,
        "name": branch.name,
        "parent_branch": branch.parent_branch,
        "parent_checkpoint": branch.parent_checkpoint,
        "created_at": branch.created_at.isoformat(),
    })


@api_bp.route("/sessions/<session_id>/branches", methods=["GET"])
@require_user
def list_branches(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    branches = [
        {
            "id": b.id,
            "name": b.name,
            "parent_branch": b.parent_branch,
            "parent_checkpoint": b.parent_checkpoint,
            "created_at": b.created_at.isoformat(),
            "is_current": b.id == session.current_branch,
        }
        for b in session.branches
    ]

    return jsonify({"branches": branches, "current_branch": session.current_branch})


@api_bp.route("/sessions/<session_id>/branches/<branch_id>/switch", methods=["POST"])
@require_user
def switch_branch(session_id: str, branch_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    if session.switch_branch(branch_id):
        session_manager.save_session(session_id)
        return jsonify({"status": "switched", "current_branch": session.current_branch})

    return jsonify({"error": "Branch not found"}), 404


@api_bp.route("/sessions/<session_id>/branches/<branch_id>/rename", methods=["POST"])
@require_user
def rename_branch(session_id: str, branch_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    data = request.get_json()
    if not data or "name" not in data:
        return jsonify({"error": "Missing 'name' field"}), 400

    if session.rename_branch(branch_id, data["name"]):
        session_manager.save_session(session_id)
        return jsonify({"status": "renamed", "branch_id": branch_id, "name": data["name"]})

    return jsonify({"error": "Branch not found"}), 404


@api_bp.route("/sessions/<session_id>/branches/<branch_id>", methods=["DELETE"])
@require_user
def delete_branch(session_id: str, branch_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    if session.delete_branch(branch_id):
        session_manager.save_session(session_id)
        return jsonify({"status": "deleted", "branch_id": branch_id})

    return jsonify({"error": "Branch not found or cannot be deleted"}), 404


@api_bp.route("/sessions/<session_id>/branches/<branch_id>/reset", methods=["POST"])
@require_user
def reset_branch(session_id: str, branch_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    if session.reset_branch_to_checkpoint(branch_id):
        session_manager.save_session(session_id)
        return jsonify({"status": "reset", "branch_id": branch_id})

    return jsonify({"error": "Branch not found or has no parent checkpoint"}), 404


@api_bp.route("/sessions/<session_id>/tree", methods=["GET"])
@require_user
def get_session_tree(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    return jsonify(session.get_tree())


@api_bp.route("/sessions/export", methods=["POST"])
@require_user
def export_sessions():
    data = session_manager.export_all()
    return Response(
        json.dumps(data, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment;filename=t6-sessions.json"},
    )


@api_bp.route("/sessions/import", methods=["POST"])
@require_user
def import_session():
    data = request.get_json()
    if not data or "session_id" not in data:
        return jsonify({"error": "Invalid session data"}), 400

    try:
        session_id = session_manager.import_session(data)
        return jsonify({"status": "imported", "session_id": session_id})
    except Exception as e:
        return jsonify({"error": f"Import failed: {str(e)}"}), 500


@admin_bp.route("/config", methods=["GET"])
@require_user
def get_config():
    default_models = {}
    for name, cfg in config.providers.items():
        if "default_model" in cfg:
            default_models[name] = cfg["default_model"]
    
    return jsonify({
        "api_key": config.api_key,
        "default_provider": config.default_provider,
        "providers": config.providers,
        "default_models": default_models,
        "summarizer": config.summarizer_config,
        "summarization": config.summarization_config,
        "mcp": config._config.get("mcp", {}),
        "embeddings": config._config.get("embeddings", {}),
        "rag": config.get_rag_config(),
    })


@admin_bp.route("/config", methods=["POST"])
@require_user
def save_config():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    try:
        if "api_key" in data:
            config._config["auth"]["api_key"] = data["api_key"]
        if "default_provider" in data:
            config._config["default_provider"] = data["default_provider"]
        if "providers" in data:
            config._config["providers"] = data["providers"]
        if "summarizer" in data:
            config._config["summarizer"] = data["summarizer"]
        if "summarization" in data:
            if "summarization" not in config._config:
                config._config["summarization"] = {}
            config._config["summarization"].update(data["summarization"])
        if "mcp" in data:
            if "mcp" not in config._config:
                config._config["mcp"] = {}
            config._config["mcp"] = data["mcp"]
        if "embeddings" in data:
            if "embeddings" not in config._config:
                config._config["embeddings"] = {}
            config._config["embeddings"].update(data["embeddings"])
        
        if "rag" in data:
            config.save_rag_config(data["rag"])
        
        # Add new models from provider API to model catalog
        if "new_models" in data:
            new_models = data["new_models"]
            
            if "models" not in config._config:
                config._config["models"] = {}
            
            for provider_type, model_list in new_models.items():
                for model_name in model_list:
                    existing = config._config["models"].get(model_name)
                    
                    if existing:
                        if existing.get("provider") == provider_type:
                            continue
                        else:
                            existing["provider"] = provider_type
                            config._config["models"][model_name] = existing
                            continue
                    
                    config._config["models"][model_name] = {
                        "provider": provider_type,
                        "context_window": 128000,
                        "input_price": 0,
                        "output_price": 0,
                        "cache_read_price": 0,
                        "cache_write_price": 0,
                    }
        
        config.save()
        config.reload()
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/debug", methods=["GET"])
@require_user
def get_debug_config():
    from app.logger import get_all_groups, LEVEL_NAMES
    groups = get_all_groups()
    return jsonify({
        "groups": groups,
        "available_levels": list(LEVEL_NAMES.values()),
    })


@admin_bp.route("/debug", methods=["POST"])
@require_user
def save_debug_config():
    data = request.get_json()
    if not data or "groups" not in data:
        return jsonify({"error": "No groups provided"}), 400

    try:
        from app.logger import set_level_for_group
        for group, level in data["groups"].items():
            set_level_for_group(group, level)
        config.reload()
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/config/validate", methods=["POST"])
@require_user
def validate_provider():
    data = request.get_json()
    if not data or "provider" not in data:
        return jsonify({"error": "Missing provider"}), 400

    provider_name = data["provider"]
    provider_config = data.get("config", {})

    try:
        from app.llm.base import Message
        provider = ProviderFactory.create(provider_name, provider_config)
        test_messages = [
            Message(role="user", content="Hi")
        ]
        response = provider.chat(test_messages, "Reply with 'OK' only")
        return jsonify({
            "status": "valid",
            "response": response.content[:100],
            "model": response.model,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@admin_bp.route("/providers/<provider_name>/models", methods=["GET"])
@require_user
def list_provider_models_from_catalog(provider_name: str):
    """Список доступных моделей для конкретного провайдера из справочника"""
    models = config.models
    provider_models = {
        name: info for name, info in models.items() 
        if info.get("enabled", True) and (info.get("provider") == provider_name or info.get("provider") == "*")
    }
    return jsonify({"models": sorted(provider_models.keys())})


@admin_bp.route("/models/fetch", methods=["POST"])
@require_user
def fetch_models_from_providers():
    """Загрузить модели от всех настроенных провайдеров"""
    results = {}
    providers = config.providers
    
    for provider_name, provider_cfg in providers.items():
        try:
            provider_cfg = provider_cfg.copy()
            if "default_model" not in provider_cfg:
                provider_cfg["default_model"] = config.get_default_model(provider_name)
            
            provider = ProviderFactory.create(provider_name, provider_cfg)
            if hasattr(provider, "list_models"):
                models = provider.list_models()
                results[provider_name] = {
                    "status": "ok",
                    "count": len(models),
                    "models": models,
                }
                
                for model_name in models:
                    existing = config.get_model_info(model_name)
                    
                    if existing:
                        if existing.get("provider") == provider_name:
                            continue
                        else:
                            existing["provider"] = provider_name
                            config._config["models"][model_name] = existing
                            continue
                    
                    config.set_model_info(model_name, {
                        "provider": provider_name,
                        "context_window": 128000,
                        "input_price": 0,
                        "output_price": 0,
                        "cache_read_price": 0,
                        "cache_write_price": 0,
                        "enabled": True,
                    })
            else:
                results[provider_name] = {"status": "not_supported", "count": 0}
        except Exception as e:
            results[provider_name] = {"status": "error", "error": str(e)}
    
    config.save()
    config.reload()
    
    return jsonify({
        "status": "completed",
        "results": results,
        "models": config.models,
    })


@admin_bp.route("/providers/fetch-models", methods=["POST"])
@require_user
def fetch_models_for_provider():
    """Загрузить модели от конкретного провайдера"""
    data = request.get_json()
    if not data or "provider" not in data or "config" not in data:
        return jsonify({"error": "Missing provider or config"}), 400

    provider_name = data["provider"]
    provider_config = data["config"]

    try:
        provider = ProviderFactory.create(provider_name, provider_config)
        if hasattr(provider, "list_models"):
            models = provider.list_models()
            return jsonify({"models": models})
        else:
            return jsonify({"error": "Provider does not support listing models"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@admin_bp.route("/context", methods=["GET"])
@require_user
def list_context_files():
    ctx_mgr = config.context_manager
    system_files = ctx_mgr.list_system_files()
    user_files = ctx_mgr.list_user_files()
    enabled = config.get_enabled_context_files()
    return jsonify({
        "system_files": system_files,
        "user_files": user_files,
        "enabled_files": enabled,
    })


@admin_bp.route("/context", methods=["POST"])
@require_user
def create_context_file():
    data = request.get_json()
    if not data or "filename" not in data:
        return jsonify({"error": "Missing filename"}), 400

    filename = data["filename"].strip()
    content = data.get("content", "")

    try:
        config.context_manager.create_user_file(filename, content)
        return jsonify({"status": "created", "filename": filename})
    except FileExistsError as e:
        return jsonify({"error": str(e)}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/context/enabled", methods=["GET"])
@require_user
def get_enabled_context_files():
    enabled = config.get_enabled_context_files()
    return jsonify({"enabled_files": enabled})


@admin_bp.route("/context/enabled", methods=["POST"])
@require_user
def set_enabled_context_files():
    data = request.get_json()
    if not data or "enabled_files" not in data:
        return jsonify({"error": "Missing enabled_files"}), 400

    try:
        config.set_enabled_context_files(data["enabled_files"])
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/context/<filename>", methods=["GET"])
@require_user
def get_context_file(filename: str):
    content = config.context_manager.get_context_file(filename)
    if content is None:
        return jsonify({"error": "File not found"}), 404
    return jsonify({"filename": filename, "content": content})


@admin_bp.route("/context/<filename>", methods=["POST"])
@require_user
def save_context_file(filename: str):
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "Missing content"}), 400

    try:
        config.context_manager.save_context_file(filename, data["content"])
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/context/<filename>", methods=["DELETE"])
@require_user
def delete_context_file(filename: str):
    ctx_mgr = config.context_manager
    if ctx_mgr.is_system_file(filename):
        if ctx_mgr.is_overridden(filename):
            ctx_mgr.delete_context_file(filename)
            return jsonify({"status": "reset"})
        return jsonify({"error": "System file not overridden"}), 400
    else:
        ctx_mgr.delete_context_file(filename)
        return jsonify({"status": "deleted"})


@admin_bp.route("/context/<filename>/restore", methods=["POST"])
@require_user
def restore_default_context_file(filename: str):
    ctx_mgr = config.context_manager
    if not ctx_mgr.is_default_file(filename):
        return jsonify({"error": "Not a default file"}), 400
    
    try:
        success = ctx_mgr.restore_default_file(filename)
        if success:
            return jsonify({"status": "restored"})
        return jsonify({"error": "Failed to restore"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/context/<filename>/rename", methods=["POST"])
@require_user
def rename_context_file(filename: str):
    data = request.get_json()
    if not data or "new_name" not in data:
        return jsonify({"error": "Missing new_name"}), 400

    new_name = data["new_name"].strip()
    if not new_name:
        return jsonify({"error": "New name cannot be empty"}), 400

    try:
        config.context_manager.rename_user_file(filename, new_name)
        return jsonify({"status": "renamed", "old_name": filename, "new_name": new_name})
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except FileExistsError as e:
        return jsonify({"error": str(e)}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/context/system", methods=["GET"])
@require_user
def list_system_context_files():
    files = config.context_manager.list_system_files()
    return jsonify({"system_files": files})


@admin_bp.route("/context/system/<filename>", methods=["GET"])
@require_user
def get_system_context_file(filename: str):
    ctx_mgr = config.context_manager
    content = ctx_mgr.get_context_file(filename)
    if content is None:
        return jsonify({"error": "System file not found"}), 404
    is_overridden = ctx_mgr.is_overridden(filename)
    return jsonify({
        "filename": filename,
        "content": content,
        "is_overridden": is_overridden,
    })


@admin_bp.route("/context/system/<filename>", methods=["POST"])
@require_user
def save_system_context_file(filename: str):
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "Missing content"}), 400

    ctx_mgr = config.context_manager
    if not ctx_mgr.is_system_file(filename):
        return jsonify({"error": "Not a system file"}), 400

    try:
        ctx_mgr.save_context_file(filename, data["content"])
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/context/system/<filename>", methods=["DELETE"])
@require_user
def reset_system_context_file(filename: str):
    ctx_mgr = config.context_manager
    if not ctx_mgr.is_system_file(filename):
        return jsonify({"error": "Not a system file"}), 400

    if not ctx_mgr.is_overridden(filename):
        return jsonify({"error": "File is not overridden"}), 400

    try:
        ctx_mgr.delete_context_file(filename)
        return jsonify({"status": "reset"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@admin_bp.route("/models", methods=["GET"])
@require_user
def list_model_catalog():
    models = config.models
    return jsonify({"models": models})


@admin_bp.route("/models/available", methods=["GET"])
@require_user
def list_available_models():
    """Список доступных (включённых) моделей для выбора"""
    models = config.models
    available = {name: info for name, info in models.items() if info.get("enabled", True)}
    return jsonify({"models": available})

@admin_bp.route("/models", methods=["POST"])
@require_user
def add_or_update_model():
    data = request.get_json()
    if not data or "name" not in data:
        return jsonify({"error": "Missing model name"}), 400

    model_name = data["name"].strip()
    if not model_name:
        return jsonify({"error": "Model name cannot be empty"}), 400

    info = {
        "provider": data.get("provider", "*"),
        "context_window": data.get("context_window", 128000),
        "input_price": data.get("input_price", 0.0),
        "output_price": data.get("output_price", 0.0),
        "cache_read_price": data.get("cache_read_price", 0.0),
        "cache_write_price": data.get("cache_write_price", 0.0),
        "enabled": data.get("enabled", True),
    }

    config.set_model_info(model_name, info)
    return jsonify({"status": "saved", "model": model_name, "info": info})


@admin_bp.route("/models/<model_name>", methods=["DELETE"])
@require_user
def delete_model(model_name: str):
    if config.delete_model(model_name):
        return jsonify({"status": "deleted", "model": model_name})
    return jsonify({"error": "Cannot delete default model or model not found"}), 400


@admin_bp.route("/embeddings", methods=["GET"])
@require_user
def admin_embeddings_list():
    from app.embeddings.storage import embedding_storage
    indexes = embedding_storage.list_indexes()
    return jsonify([idx.to_dict() for idx in indexes])


@api_bp.route("/embeddings/list", methods=["GET"])
def api_embeddings_list():
    from app.embeddings.storage import embedding_storage
    indexes = embedding_storage.list_indexes()
    return jsonify([{"id": idx.id, "name": idx.name} for idx in indexes])


@api_bp.route("/sessions/<session_id>/events", methods=["GET"])
def session_events(session_id: str):
    """SSE endpoint for session updates."""
    import time
    from flask import stream_with_context
    
    @stream_with_context
    def generate():
        from flask import request
        from app import events
        
        response = request._get_current_object()
        
        # Send initial comment to establish connection
        yield ":\n\n"
        
        events.subscribe(session_id, response)
        
        try:
            while True:
                time.sleep(1)
                yield ":\n\n"  # Keep-alive
        except GeneratorExit:
            events.unsubscribe(session_id, response)
    
    return Response(generate(), mimetype='text/event-stream')
