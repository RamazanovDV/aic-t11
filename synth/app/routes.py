import json
import re
import uuid
import asyncio
from datetime import datetime

import requests
from flask import Blueprint, jsonify, render_template, request, Response

from app.config import config
from app.context import get_system_prompt
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


def get_profile_prompt(session, user_id: str | None = None) -> str:
    """Сформировать промпт с данными профиля пользователя"""
    user = None
    
    if session and session.owner_id:
        from app import storage as app_storage
        user = app_storage.storage.load_user(session.owner_id)
    
    if not user and user_id:
        from app import storage as app_storage
        user = app_storage.storage.load_user(user_id)
    
    if not user:
        try:
            user = get_current_user()
        except Exception:
            user = None
    
    if not user:
        return ""
    
    parts = []
    if user.username:
        parts.append(f"Имя: {user.username}")
    if user.team_role:
        parts.append(f"Роль: {user.team_role}")
    if user.notes:
        notes_without_interview = user.notes.split("[ИНТЕРВЬЮ]")[0].strip()
        if notes_without_interview:
            parts.append(f"Отметки: {notes_without_interview}")
    
    if parts:
        return f"\n\n[ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ]\n" + "\n".join(parts) + "\n"
    
    return ""


def get_project_prompt(session) -> str:
    """Сформировать промпт с данными проекта"""
    project_name = session.status.get("project")
    
    if not project_name:
        projects_list = project_manager.project_manager.get_projects_list()
        projects_text = ", ".join(projects_list) if projects_list else "пока нет проектов"
        
        new_project_prompt = config.get_context_file("NEW_PROJECT.md") or "Если пользователь хочет начать новый проект - уточни название, укажи полученное название в поле project."
        
        return (
            f"\n\n[ПРОЕКТ]\n"
            f"Выясни у пользователя над каким проектом он хочет поработать.\n"
            f"Существующие проекты: {projects_text}\n"
            f"{new_project_prompt}\n"
        )
    
    if not project_manager.project_manager.project_exists(project_name):
        project_manager.project_manager.create_project(project_name)
    
    project_info = project_manager.project_manager.get_project_info(project_name)
    current_task = project_manager.project_manager.get_current_task(project_name)
    invariants = project_manager.project_manager.get_invariants(project_name)
    
    result = f"\n\n[ПРОЕКТ: {project_name}]\n"
    
    if project_info:
        result += f"{project_info}\n"
    else:
        result += "(Описание проекта отсутствует)\n"
    
    if current_task:
        result += f"\n[ТЕКУЩАЯ ЗАДАЧА]\n{current_task}\n"
    
    if invariants:
        result += f"\n[ИНВАРИАНТЫ - ОБЯЗАТЕЛЬНО К СОБЛЮДЕНИЮ]\n"
        for key, value in invariants.items():
            if isinstance(value, list):
                result += f"- {key}: {', '.join(str(v) for v in value)}\n"
            else:
                result += f"- {key}: {value}\n"
    
    schedules = scheduler.scheduler.get_schedules(project_name)
    enabled_schedules = [s for s in schedules if s.enabled]
    if project_name:
        result += f"\n[ЗАДАНИЯ ПО РАСПИСАНИЮ]\n"
        if enabled_schedules:
            result += "В этом проекте настроены автоматические задания:\n"
            for s in enabled_schedules:
                next_run_str = s.next_run.strftime("%Y-%m-%d %H:%M") if s.next_run else "неизвестно"
                result += f"- {s.name}: cron={s.cron}, следующий запуск: {next_run_str}\n"
        result += "Можно создать новое задание, указав его параметры в поле schedule блока статуса.\n"
    
    return result


def get_status_prompt(session) -> str:
    """Сформировать промпт с инструкцией по статусу задачи"""
    return tsm.get_tsm_prompt(session)


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


async def _get_mcp_tools(session, provider_name: str) -> list[dict]:
    """Get MCP tools for the session's configured MCP servers."""
    if not mcp_available():
        return []
    
    mcp_servers = session.get_mcp_servers()
    if not mcp_servers:
        return []
    
    all_tools = []
    failed_servers = []
    
    for server_name in mcp_servers:
        try:
            from app.mcp import MCPManager, tools_to_provider_format
            server_tools = await MCPManager.get_tools([server_name])
            if server_tools:
                all_tools.extend(tools_to_provider_format(server_tools, provider_name))
            else:
                debug("MCP", f"No tools returned from {server_name}")
        except Exception as e:
            error_msg = str(e)
            debug("MCP", f"Failed to get tools from {server_name}: {error_msg}")
    
    return all_tools


async def _process_status_block(
    provider,
    llm_messages: list,
    system_prompt: str,
    session,
    session_id: str,
    debug_collector,
    user_id: str | None = None,
    max_retries: int = 3,
    mcp_tools: list | None = None,
    mcp_calls: list | None = None,
):
    """Обработать ответ LLM с валидацией статуса.
    
    Returns:
        tuple: (response, message_for_user, status_error, debug_info, group_id)
            - response: LLMResponse или dict с content/usage для orchestrator
            - message_for_user: очищенный контент без JSON блока
            - status_error: строка с ошибкой если все попытки неудачны
            - debug_info: отладочная информация
            - group_id: ID группы сообщений (если были tool calls)
    """
    debug_mode = debug_collector.enabled if debug_collector else False
    
    if mcp_calls is None:
        mcp_calls = []
    
    tsm_mode = tsm.get_tsm_mode(session)
    debug("ROUTES", f"TSM mode: {tsm_mode}, session_id: {session_id}")
    
    if tsm_mode == "orchestrator":
        debug("ROUTES", f"Using orchestrator mode for session {session_id}")
        return _process_orchestrator_mode(
            provider, llm_messages, system_prompt, session, session_id, debug_mode, user_id
        )
    
    status_reminder = config.get_context_file("STATUS_REMINDER.md") or ""
    if status_reminder:
        system_prompt += "\n\n" + status_reminder
    
    tools_called_in_current_attempt = False
    response = None
    group_id = None  # ID группы для связанных сообщений
    
    for attempt in range(max_retries):
        
        while True:
            # If we've already called tools in this attempt and got no more tool calls - don't retry with tools
            use_tools = mcp_tools if not tools_called_in_current_attempt else None
            
            try:
                prompt_with_reminder = system_prompt + status_reminder if attempt > 0 else system_prompt
                if use_tools:
                    debug("MCP", f"Sending {len(use_tools)} tools to model: {[t.get('function', {}).get('name') or t.get('name') for t in use_tools]}")
                
                response = provider.chat(llm_messages, prompt_with_reminder, debug_collector=debug_collector, tools=use_tools)
            except Exception as e:
                import traceback
                error("ROUTES", f"provider.chat() failed: {e}")
                error("ROUTES", traceback.format_exc())
                if attempt == max_retries - 1:
                    break
                break
            
            debug("MCP", f"After response: mcp_tools={bool(mcp_tools)}, response.tool_calls={response.tool_calls}")
            debug("MCP", f"Response content: {response.content[:200] if response.content else 'EMPTY'}")
            
            if not response.tool_calls:
                # No more tool calls, exit the loop
                tools_called_in_current_attempt = False  # Reset after tools completed
                break
            
            tools_called_in_current_attempt = True
            
            # Создаём group_id и сохраняем промежуточное сообщение
            if group_id is None:
                group_id = str(uuid.uuid4())
            
            session.add_assistant_message(
                response.content or "",
                response.usage or {},
                debug={"usage": response.usage or {}, "model": provider.model},
                model=provider.model,
                reasoning=response.reasoning,
                group_id=group_id
            )
            
            # Execute tool calls
            debug("MCP", f"Detected {len(response.tool_calls)} tool call(s)")
            debug("MCP", f"Tool calls: {json.dumps(response.tool_calls, ensure_ascii=False)[:500]}")
            
            # Update last assistant message with tool_use and debug info if tools were called
            if response.tool_calls and debug_mode:
                debug_info = debug_collector.get_debug_info()
                if debug_info is None:
                    debug_info = {}
                debug_info["tool_use"] = response.tool_calls
                # Update the last message
                if session.messages:
                    last_msg = session.messages[-1]
                    last_msg.tool_use = response.tool_calls
                    last_msg.debug = debug_info
            
            try:
                from app.mcp import MCPManager
                tool_call_results = []
                
                for tc in response.tool_calls:
                    tool_name = tc.get("function", {}).get("name") or tc.get("name", "")
                    tool_args = tc.get("function", {}).get("arguments") or tc.get("arguments", {}) or {}
                    
                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except:
                            tool_args = {}
                    
                    debug("MCP", f"Calling tool: {tool_name}")
                    debug("MCP", f"Arguments: {json.dumps(tool_args, ensure_ascii=False)[:500]}")
                    
                    try:
                        result = await MCPManager.call_tool(tool_name, tool_args)
                        tool_result_content = result.content
                        is_error = getattr(result, 'is_error', False)
                        debug("MCP", f"Result: {tool_result_content[:500] if tool_result_content else 'empty'}")
                        debug("MCP", f"Is error: {is_error}")
                    except Exception as e:
                        tool_result_content = f"Error: {str(e)}"
                        is_error = True
                        error("MCP", f"Tool error: {e}")
                    
                    mcp_calls.append({
                        "tool": tool_name,
                        "arguments": tool_args,
                        "result": tool_result_content,
                        "is_error": is_error
                    })
                    
                    tool_call_results.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": tool_result_content,
                    })
                
                # Update last assistant message with mcp_calls after tools execution
                if response.tool_calls and debug_mode and mcp_calls:
                    if session.messages:
                        last_msg = session.messages[-1]
                        if last_msg.debug is None:
                            last_msg.debug = {}
                        last_msg.debug["mcp_calls"] = list(mcp_calls)
                
                # Save session after updating intermediate message
                session_manager.save_session(session_id)
                
                # Build tool messages and call model again
                tool_messages = list(llm_messages)
                tool_messages.append(Message(role="assistant", content=response.content or "", usage={}, tool_use=response.tool_calls))
                for tc_result in tool_call_results:
                    tool_messages.append(Message(
                        role="tool",
                        content=tc_result["content"],
                        tool_call_id=tc_result.get("tool_call_id"),
                        usage={}
                    ))
                
                # Continue in the while loop - will call provider.chat with tools=None
                llm_messages = tool_messages
                debug("MCP", "Continuing with tool results, will call model again")
                
            except Exception as e:
                error("MCP", f"Tool handling error: {e}")
                break
        
        # After while loop, check for status block
        # If tools were called and we're here, it means model didn't provide status - that's an error
        parsed_status = None
        if tools_called_in_current_attempt and response:
            debug("MCP", "Tools were called but no status block - returning error")
            # Return the content anyway, don't retry
            cleaned_content = response.content if response.content else ""
            return response, cleaned_content, "Модель вызвала инструменты, но не предоставила статусный блок", None, group_id
        
        if response:
            parsed_status, cleaned_content = status_validator.validate_status_block(response.content)
        else:
            parsed_status, cleaned_content = None, ""

        # If tools were called but no status - return content without error, keep old status
        if tools_called_in_current_attempt and response:
            debug("MCP", "Tools were called but no status block - returning content without error")
            cleaned_content = response.content if response.content else ""
            return response, cleaned_content, None, None, group_id
        
        # If no status block - just return content without error, keep old status
        if parsed_status is None:
            debug("ROUTES", "No status block in response - returning content without updating status")
            cleaned_content = response.content if response.content else ""
            return response, cleaned_content, None, None, group_id
        
        # Process status transition if status block exists
        parsed_status = tsm.process_state_transition(session, parsed_status)
        
        session.update_status(parsed_status)
        
        _handle_project_updates(session)
        
        _handle_user_info_update(parsed_status, user_id)
        
        return response, cleaned_content, None, None, group_id

        if attempt < max_retries - 1:
            llm_messages = session.get_messages_for_llm()
            status_format = "Пожалуйста, добавь в конце своего ответа JSON-блок со статусом задачи в формате: "
            status_format += '{"status": {"task_name": "название", "state": "состояние", "progress": "прогресс", '
            status_format += '"project": "проект", "updated_project_info": "обновлённое описание проекта", '
            status_format += '"current_task_info": "текущая задача", "approved_plan": "план", '
            status_format += '"already_done": "сделано", "currently_doing": "текущее", '
            status_format += '"invariants": {"язык": "Python", "не использовать": ["материал1"]} или null}}'
            llm_messages.append(Message(role="user", content=status_format, usage={}))

    return response, response.content, "Модель не формирует блок статуса в ответе", None


def _process_orchestrator_mode(
    provider,
    llm_messages: list,
    system_prompt: str,
    session,
    session_id: str,
    debug_collector,
    user_id: str | None = None,
):
    """Обработать ответ в режиме оркестратора с поддержкой сабагентов."""
    debug_mode = debug_collector.enabled if debug_collector else False
    debug("ORCHESTRATOR", f"Starting orchestrator mode, debug_mode: {debug_mode}")
    try:
        result = tsm.process_orchestrator_response(
            session=session,
            llm_messages=llm_messages,
            provider=provider,
            system_prompt=system_prompt,
            debug_prompt=system_prompt,
            debug_collector=debug_collector
        )
        debug("ORCHESTRATOR", f"Result keys: {result.keys() if result else 'None'}")
    except Exception as e:
        return None, f"Ошибка при обработке оркестратора: {str(e)}", str(e), None
    
    final_content = result.get("final_content", "")
    final_status = result.get("final_status", {})
    debug_info = result.get("debug")
    usage = result.get("usage", {})
    
    if final_status:
        session.update_status(final_status)
        _handle_project_updates(session)
        _handle_user_info_update(final_status, user_id)
    
    cleaned_content, _ = status_validator.validate_status_block(final_content)
    if cleaned_content:
        final_content = cleaned_content
    
    class MockResponse:
        def __init__(self, content, usage, debug_info, model):
            self.content = content
            self.usage = usage
            self.debug_request = debug_info.get("orchestrator_request", {}) if debug_info else {}
            self.debug_response = debug_info
            self.model = model
    
    mock_response = MockResponse(final_content, usage, debug_info, provider.model)
    
    return mock_response, final_content, None, debug_info


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
@require_user
def chat():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing 'message' field"}), 400

    user_message = data["message"]
    provider_name = data.get("provider")
    model = data.get("model")
    debug_mode = data.get("debug", False)  # Deprecated - for backward compat
    source_type = data.get("source", "web")
    mcp_servers = data.get("mcp_servers", [])
    mcp_calls = []
    
    current_user = get_current_user()
    if current_user:
        username = current_user.username
    else:
        username = data.get("username", "unknown")
    source = f"{username} | {source_type}"
    
    if not provider_name:
        provider_name = config.default_provider
    
    provider_config = config.get_provider_config(provider_name)
    if not provider_config:
        return jsonify({"error": f"Unknown provider: {provider_name}"}), 400
    
    provider_config = provider_config.copy()
    
    if model:
        provider_config["model"] = model
    else:
        default_model = config.get_default_model(provider_name)
        if default_model:
            provider_config["model"] = default_model
        else:
            return jsonify({"error": f"No model specified and no default model for provider: {provider_name}"}), 400
    
    if "timeout" not in provider_config:
        provider_config["timeout"] = config.timeout

    try:
        provider = ProviderFactory.create(provider_name, provider_config)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    session_id = get_session_id()
    session = session_manager.get_session(session_id)

    debug_collector = DebugCollector.from_session(session)

    request_id = RequestTracker.create_request()

    if data.get("tsm_mode"):
        try:
            tsm.set_tsm_mode(session, data["tsm_mode"])
        except ValueError as e:
            RequestTracker.error(request_id, str(e))
            return jsonify({"error": f"Invalid tsm_mode: {str(e)}"}), 400
    
    is_first_message = session.get_active_message_count() == 0
    session.add_user_message(user_message, source=source)

    should_summarize_result, summarize_reason = summarizer.should_summarize(session, session.get_active_message_count())
    if should_summarize_result:
        messages_to_summarize = session.get_messages_before_last_user()
        if messages_to_summarize:
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

    if provider_name and model:
        session.set_provider_model(provider_name, model)
    elif provider_name and not session.provider:
        session.set_provider_model(provider_name, config.get_default_model(provider_name))

    system_prompt = get_system_prompt()
    system_prompt += get_profile_prompt(session, request.headers.get("X-User-Id"))
    system_prompt += get_project_prompt(session)
    system_prompt += get_status_prompt(session)
    if should_show_interview(session, request.headers.get("X-User-Id")):
        system_prompt += get_interview_prompt()

    try:
        llm_messages = session.get_messages_for_llm()
        session_manager.save_session(session_id)
    except ContextLengthExceededError as e:
        session.add_error_message(f"[Ошибка] {str(e)}", debug=e.debug_response if debug_mode else None, model=provider.model)
        session_manager.save_session(session_id)
        result = {"error": str(e), "error_type": "context_length_exceeded", "model": provider.model}
        if debug_mode and e.debug_response:
            result["debug"] = {"response": e.debug_response}
        return jsonify(result), 400
    except Exception as e:
        session.add_error_message(f"[Ошибка] {str(e)}", None, model=provider.model)
        session_manager.save_session(session_id)
        result = {"error": f"LLM error: {str(e)}", "model": provider.model}
        return jsonify(result), 500

    import asyncio
    actual_provider_type = provider.get_provider_name()
    mcp_tools = run_mcp_async(_get_mcp_tools(session, actual_provider_type))

    try:
        response, message_for_user, status_error, orchestrator_debug, group_id = run_mcp_async(_process_status_block(
            provider, llm_messages, system_prompt, session, session_id, debug_collector, 
            request.headers.get("X-User-Id"), mcp_tools=mcp_tools, mcp_calls=mcp_calls
        ))
        if status_error:
            # Save assistant message first
            if message_for_user:
                session.add_assistant_message(message_for_user, response.usage if response else {}, debug=orchestrator_debug if debug_mode else None, model=response.model if response else provider.model, group_id=group_id)
            session.add_error_message(f"[Ошибка статуса] {status_error}", debug=orchestrator_debug if debug_mode else None, model=provider.model)
            session_manager.save_session(session_id)
            RequestTracker.error(request_id, status_error)
            result = {
                "error": status_error,
                "model_error": status_error,
                "model": provider.model,
            }
            if debug_mode:
                result["debug"] = {"status_error": status_error}
            return jsonify(result), 500
    except ContextLengthExceededError as e:
        session.add_error_message(f"[Ошибка] {str(e)}", debug=e.debug_response if debug_mode else None, model=provider.model)
        session_manager.save_session(session_id)
        RequestTracker.error(request_id, str(e))
        result = {"error": str(e), "error_type": "context_length_exceeded", "model": provider.model}
        if debug_mode and e.debug_response:
            result["debug"] = {"response": e.debug_response}
        return jsonify(result), 400
    except Exception as e:
        session.add_error_message(f"[Ошибка] {str(e)}", None, model=provider.model)
        session_manager.save_session(session_id)
        RequestTracker.error(request_id, str(e))
        result = {"error": f"LLM error: {str(e)}", "model": provider.model}
        return jsonify(result), 500

    if debug_collector.enabled:
        debug_collector.capture_reasoning(response.reasoning)
        debug_collector.capture_session_info(session.session_id, provider.model, provider.get_provider_name())
        if session.status:
            debug_collector.capture_status(session.status)
        for mcp in mcp_calls:
            debug_collector.capture_mcp_call(
                tool=mcp.get("tool", ""),
                arguments=mcp.get("arguments", {}),
                result=mcp.get("result", ""),
                is_error=mcp.get("is_error", False)
            )

    debug_info = debug_collector.get_debug_info()

    message_index = len(session.messages)
    session.add_assistant_message(message_for_user, response.usage, debug=debug_info, model=response.model, reasoning=response.reasoning, group_id=group_id)
    
    debug("STORAGE", f"Saving session after assistant message, messages count: {len(session.messages)}")
    session_manager.save_session(session_id)

    disabled_indices = [i for i, m in enumerate(session.messages) if m.disabled]

    message_id = session.messages[message_index].id if message_index < len(session.messages) else None
    RequestTracker.complete(request_id, message_id)

    result = {
        "message": message_for_user,
        "session_id": session_id,
        "model": response.model,
        "usage": response.usage,
        "total_tokens": session.total_tokens,
        "disabled_indices": disabled_indices,
        "request_id": request_id,
        "message_id": message_id,
        "reasoning": response.reasoning,
    }
    
    if debug_info:
        result["debug"] = debug_info
    
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
@require_user
def chat_stream():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing 'message' field"}), 400

    user_message = data["message"]
    provider_name = data.get("provider")
    model = data.get("model")
    debug_mode = data.get("debug", False)  # Deprecated - for backward compat
    source_type = data.get("source", "web")
    mcp_servers = data.get("mcp_servers", [])
    mcp_calls = []
    
    current_user = get_current_user()
    if current_user:
        username = current_user.username
    else:
        username = data.get("username", "unknown")
    source = f"{username} | {source_type}"

    if not provider_name:
        provider_name = config.default_provider

    provider_config = config.get_provider_config(provider_name)
    if not provider_config:
        return jsonify({"error": f"Unknown provider: {provider_name}"}), 400

    provider_config = provider_config.copy()

    if model:
        provider_config["model"] = model
    else:
        default_model = config.get_default_model(provider_name)
        if default_model:
            provider_config["model"] = default_model
        else:
            return jsonify({"error": f"No model specified and no default model for provider: {provider_name}"}), 400

    if "timeout" not in provider_config:
        provider_config["timeout"] = config.timeout

    try:
        provider = ProviderFactory.create(provider_name, provider_config)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    session_id = get_session_id()
    session = session_manager.get_session(session_id)

    debug_collector = DebugCollector.from_session(session)

    if data.get("tsm_mode"):
        try:
            tsm.set_tsm_mode(session, data["tsm_mode"])
        except ValueError as e:
            return jsonify({"error": f"Invalid tsm_mode: {str(e)}"}), 400
    
    user_id = request.headers.get("X-User-Id")
    is_first_message = session.get_active_message_count() == 0

    needs_summarization, summarize_reason = summarizer.should_summarize(session, 0)

    def generate():
        nonlocal needs_summarization, mcp_calls

        previous_status = {
            "project": session.status.get("project") if session.status else None,
            "task_name": session.status.get("task_name") if session.status else None,
            "state": session.status.get("state") if session.status else None,
        }

        user_msg_for_llm = user_message
        summary_content = None

        if needs_summarization:
            yield f"data: {json.dumps({'type': 'summarizing'})}\n\n"

            messages_to_summarize = session.get_messages_before_last_user()
            if messages_to_summarize:
                try:
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
                    last_summary = None
                    for i in range(len(session.messages) - 1, -1, -1):
                        if session.messages[i].role == "summary" and session.messages[i] != session.messages[-1]:
                            last_summary = session.messages[i]
                            break
                    debug_for_ui = debug_info if debug_mode else (last_summary.debug if last_summary else None)
                    summary_event = {"type": "summary", "content": summary_content, "debug": debug_for_ui}
                    yield f"data: {json.dumps(summary_event)}\n\n"
                except Exception as e:
                    error_msg = f"Ошибка суммаризации: {str(e)}"
                    yield f"data: {json.dumps({'type': 'error', 'error': error_msg})}\n\n"
                    yield "data: [DONE]\n\n"
                    return
        else:
            # Без суммаризации - добавляем user message в сессию сейчас
            session.add_user_message(user_message, source=source)

        if provider_name and model:
            session.set_provider_model(provider_name, model)
        elif provider_name and not session.provider:
            session.set_provider_model(provider_name, config.get_default_model(provider_name))

        system_prompt = get_system_prompt()
        system_prompt += get_profile_prompt(session, user_id)
        system_prompt += get_project_prompt(session)
        system_prompt += get_status_prompt(session)
        if should_show_interview(session, user_id):
            system_prompt += get_interview_prompt()

        # Используем get_messages_for_llm() для поддержки скользящего окна
        llm_messages = session.get_messages_for_llm()
        session_manager.save_session(session_id)

        # Получаем MCP инструменты
        import asyncio
        actual_provider_type = provider.get_provider_name()
        mcp_tools = run_mcp_async(_get_mcp_tools(session, actual_provider_type))

        # Формируем сообщения для LLM (до проверки tsm_mode)
        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})

        for msg in llm_messages:
            if msg.role == "summary":
                summary_text = f"До этого вы обсудили следующее:\n{msg.content}"
                if formatted_messages and formatted_messages[0]["role"] == "system":
                    formatted_messages[0]["content"] = f"{formatted_messages[0]['content']}\n\n{summary_text}"
                else:
                    formatted_messages.insert(0, {"role": "system", "content": summary_text})
            elif msg.role in ("user", "assistant"):
                formatted_messages.append({"role": msg.role, "content": msg.content})

        # Проверяем режим TSM для orchestrator
        tsm_mode = tsm.get_tsm_mode(session)
        debug("CHAT_STREAM", f"TSM mode: {tsm_mode}")
        
        if tsm_mode == "orchestrator":
            debug("CHAT_STREAM", "Using orchestrator mode, will process with subagents")
            # Для orchestrator используем non-streaming режим
            from app.llm.base import Message
            llm_msgs = [Message(role=m["role"], content=m["content"], usage={}) for m in formatted_messages]
            
            # Проверим есть ли system message в списке
            has_system = any(m.role == "system" for m in llm_msgs)
            
            # Если system уже в сообщениях - передаем None в provider
            import queue
            import threading
            import time
            
            orchestrator_system = None if has_system else system_prompt
            
            debug("ROUTES", f"Calling orchestrator with {len(llm_msgs)} messages")
            
            ORCHESTRATOR_TIMEOUT = config.orchestrator_timeout
            TOKEN_WARNING_PERCENT = config.token_warning_percent
            TOKEN_ABORT_PERCENT = config.token_abort_percent
            
            model_config = config.get_provider_config(provider_name)
            model_name = model or provider.model
            context_window = config.get_context_window(model_name)
            token_limit = int(context_window * 0.9)
            
            progress_queue = queue.Queue()
            result_queue = queue.Queue()
            stop_event = threading.Event()
            
            def run_orchestrator():
                try:
                    result = tsm.process_orchestrator_response(
                        session=session,
                        llm_messages=llm_msgs,
                        provider=provider,
                        system_prompt=orchestrator_system,
                        debug_prompt=system_prompt,
                        debug_mode=debug_mode,
                        progress_queue=progress_queue,
                        token_limit=token_limit,
                        stop_event=stop_event
                    )
                    result_queue.put(("success", result))
                except Exception as e:
                    result_queue.put(("error", str(e)))
            
            orchestrator_thread = threading.Thread(target=run_orchestrator)
            orchestrator_thread.start()
            
            timeout_warning_sent = False
            start_time = time.time()
            
            while orchestrator_thread.is_alive():
                elapsed = time.time() - start_time
                
                if elapsed > ORCHESTRATOR_TIMEOUT and not timeout_warning_sent:
                    yield f"data: {json.dumps({'type': 'timeout_warning', 'elapsed': round(elapsed)})}\n\n"
                    timeout_warning_sent = True
                
                try:
                    event = progress_queue.get(timeout=0.3)
                    
                    if event.get('type') == 'orchestrator_content':
                        content = event.get('content', '')
                        debug("ROUTES", f"orchestrator_content event: content_len={len(content)}, subtasks={len(event.get('subtasks', []))}")
                        event_data = {
                            'type': 'orchestrator_content',
                            'content': content,
                            'done': False,
                            'subtasks': event.get('subtasks', [])
                        }
                        # Отправляем статус если он изменился
                        status_info = event.get('status')
                        if status_info and status_info.get('state'):
                            event_data['status'] = status_info
                        yield f"data: {json.dumps(event_data)}\n\n"
                    
                    if event.get('type') == 'token_usage':
                        percent = event.get('percent', 0)
                        if percent >= TOKEN_ABORT_PERCENT:
                            yield f"data: {json.dumps({'type': 'token_limit_abort', 'percent': percent})}\n\n"
                            stop_event.set()
                        elif percent >= TOKEN_WARNING_PERCENT:
                            yield f"data: {json.dumps({'type': 'token_warning', 'percent': percent})}\n\n"
                    
                    if event.get('type') != 'orchestrator_content':
                        yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    continue
                except Exception as e:
                    error("ROUTES", f"Error processing progress event: {e}")
                    continue
            
            orchestrator_thread.join(timeout=10)
            
            try:
                status, result = result_queue.get_nowait()
            except queue.Empty:
                result = {"error": "Orchestrator timeout", "aborted": True}
                status = "error"
            
            if status == "error":
                if isinstance(result, str):
                    yield f"data: {json.dumps({'type': 'error', 'error': f'Orchestrator error: {result}'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'error', 'error': result.get('error', 'Unknown error')})}\n\n"
                yield "data: [DONE]\n\n"
                return
            
            final_content = result.get("final_content", "")
            subtask_results = result.get("subtask_results", [])
            debug_info = result.get("debug") if debug_mode else None
            was_aborted = result.get("aborted", False)
            
            raw_original_content = result.get("raw_response", final_content)
            usage = result.get("usage", {})
            
            info("ORCHESTRATOR", f"Usage: {usage}")
            info("ORCHESTRATOR", "Model: orchestrator")
            
            if was_aborted:
                yield f"data: {json.dumps({'type': 'aborted', 'reason': 'user_stop'})}\n\n"
            
            # Очищаем JSON-блок из ответа
            if final_content and isinstance(final_content, str):
                from app.status_validator import validate_status_block
                _, cleaned_content = validate_status_block(final_content)
                if cleaned_content and isinstance(cleaned_content, str) and cleaned_content != final_content:
                    final_content = cleaned_content
            else:
                final_content = str(final_content) if final_content else ""
            
            # Сохраняем оригинальный контент для debug если debug_mode включен
            if debug_mode and raw_original_content:
                if debug_info is None:
                    debug_info = {}
                debug_info['raw_model_response'] = raw_original_content
            
            # Отправляем контент частями для имитации streaming
            for i in range(0, len(final_content), 50):
                chunk = final_content[i:i+50]
                yield f"data: {json.dumps({'content': chunk, 'done': False})}\n\n"
            
            # Сохраняем в сессию (user_message уже добавлен в get_messages_for_llm)
            if session.status:
                if debug_info is None:
                    debug_info = {}
                debug_info['status'] = session.status
                debug_info['subtasks'] = session.status.get('subtasks', [])
            
            if mcp_calls:
                if debug_info is None:
                    debug_info = {}
                debug_info['mcp_calls'] = mcp_calls
                
            session.add_assistant_message(final_content, usage, debug=debug_info, model=provider.model)
            
            session_manager.save_session(session_id)
            
            disabled_indices = [i for i, m in enumerate(session.messages) if m.disabled]
            
            yield f"data: {json.dumps({'content': final_content, 'done': True, 'usage': usage, 'model': provider.model, 'subtask_results': subtask_results, 'debug': debug_info, 'disabled_indices': disabled_indices, 'aborted': was_aborted})}\n\n"
            
            status_event = _emit_project_status(session, previous_status)
            if status_event:
                yield f"data: {json.dumps(status_event, ensure_ascii=False)}\n\n"
            
            yield "data: [DONE]\n\n"
            return

        full_content = ""
        full_reasoning = ""
        total_usage = {}

        if debug_collector and debug_collector.enabled:
            debug_collector.capture_api_request(
                url=provider.url,
                method="POST",
                headers={"Content-Type": "application/json"},
                body={
                    "model": provider.model,
                    "messages": formatted_messages,
                    "temperature": 0.7,
                    "stream": True,
                },
            )

        try:
            # Конвертируем в Message объекты
            from app.llm.base import Message
            llm_msgs = [Message(role=m["role"], content=m["content"], usage={}) for m in formatted_messages]
            
            tool_calls_handled = False
            tool_use_for_message = None  # Track tool_use for saving to session
            preliminary_saved = False  # Track if we've already saved to avoid duplicate messages
            preliminary_message_id = None  # ID сообщения для последующего обновления
            group_id = None  # ID группы для связанных сообщений
            
            if mcp_tools:
                debug("MCP", f"Stream: Sending {len(mcp_tools)} tools to model: {[t.get('function', {}).get('name') or t.get('name') for t in mcp_tools]}")
            for chunk in provider.stream_chat(llm_msgs, None, debug_collector=debug_collector, tools=mcp_tools):
                if chunk.tool_calls and not tool_calls_handled:
                    tool_calls_handled = True
                    tool_use_for_message = chunk.tool_calls  # Save for later
                    group_id = str(uuid.uuid4())  # Новый group_id для группы сообщений
                    debug("MCP", f"Stream: Detected {len(chunk.tool_calls)} tool call(s)")
                    debug("MCP", f"Stream: Tool calls: {json.dumps(chunk.tool_calls, ensure_ascii=False)[:500]}")
                    
                    # Сохраняем промежуточное сообщение с group_id
                    session.add_assistant_message(
                        chunk.content or "",
                        chunk.usage or {},
                        debug={"usage": chunk.usage or {}, "model": provider.model},
                        model=provider.model,
                        reasoning=chunk.reasoning,
                        group_id=group_id
                    )
                    preliminary_message_id = session.messages[-1].id
                    preliminary_saved = True
                    
                    try:
                        from app.mcp import MCPManager
                        import asyncio
                        
                        current_tool_calls = chunk.tool_calls
                        max_tool_iterations = 10
                        tool_iteration = 0
                        
                        # Update last assistant message with tool_use and debug info if tools were called
                        if current_tool_calls and session.session_settings.get("debug_enabled", True):
                            debug_info = debug_collector.get_debug_info()
                            if debug_info is None:
                                debug_info = {}
                            debug_info["tool_use"] = current_tool_calls
                            if session.messages:
                                last_msg = session.messages[-1]
                                last_msg.tool_use = current_tool_calls
                                last_msg.debug = debug_info
                        
                        while current_tool_calls and tool_iteration < max_tool_iterations:
                            tool_iteration += 1
                            debug("MCP", f"Tool iteration {tool_iteration}: processing {len(current_tool_calls)} tool call(s)")
                            
                            tool_call_results = []
                            
                            for tc in current_tool_calls:
                                tool_name = tc.get("function", {}).get("name") or tc.get("name", "")
                                tool_args = tc.get("function", {}).get("arguments") or tc.get("arguments", {}) or {}
                                
                                if isinstance(tool_args, str):
                                    try:
                                        tool_args = json.loads(tool_args)
                                    except:
                                        tool_args = {}
                                
                                debug("MCP", f"Calling tool: {tool_name}")
                                debug("MCP", f"Arguments: {json.dumps(tool_args, ensure_ascii=False)[:500]}")
                                
                                try:
                                    result = run_mcp_async(MCPManager.call_tool(tool_name, tool_args))
                                    tool_result_content = result.content
                                    is_error = getattr(result, 'is_error', False)
                                    debug("MCP", f"Result: {tool_result_content[:500] if tool_result_content else 'empty'}")
                                    debug("MCP", f"Is error: {is_error}")
                                except Exception as e:
                                    tool_result_content = f"Error: {str(e)}"
                                    is_error = True
                                    error("MCP", f"Tool error: {e}")
                                
                                mcp_calls.append({
                                    "tool": tool_name,
                                    "arguments": tool_args,
                                    "result": tool_result_content,
                                    "is_error": is_error
                                })
                                
                                tool_call_results.append({
                                    "role": "tool",
                                    "tool_call_id": tc.get("id"),
                                    "content": tool_result_content,
                                })
                            
                            # Update last assistant message with mcp_calls after tools execution
                            if current_tool_calls and session.session_settings.get("debug_enabled", True) and mcp_calls:
                                if session.messages:
                                    last_msg = session.messages[-1]
                                    if last_msg.debug is None:
                                        last_msg.debug = {}
                                    last_msg.debug["mcp_calls"] = list(mcp_calls)
                            
                            # Save session after updating intermediate message
                            session_manager.save_session(session_id)
                            
                            assistant_msg = Message(role="assistant", content=chunk.content or "", usage=chunk.usage, tool_use=current_tool_calls)
                            tool_messages = list(llm_msgs)
                            tool_messages.append(assistant_msg)
                            for tc_result in tool_call_results:
                                tool_messages.append(Message(
                                    role="tool",
                                    content=tc_result["content"],
                                    tool_call_id=tc_result.get("tool_call_id"),
                                    usage={}
                                ))
                            
                            debug("MCP", f"Executing {len(tool_call_results)} tool(s), continuing stream...")
                            
                            current_tool_calls = None
                            for new_chunk in provider.stream_chat(tool_messages, None, debug_collector=debug_collector, tools=mcp_tools):
                                full_content = new_chunk.content
                                full_reasoning = new_chunk.reasoning if new_chunk.reasoning else full_reasoning
                                debug("MCP", f"Stream after tool: content='{full_content[:100] if full_content else 'EMPTY'}', is_final={new_chunk.is_final}, tool_calls={new_chunk.tool_calls}")
                                
                                if new_chunk.tool_calls:
                                    current_tool_calls = new_chunk.tool_calls
                                    debug("MCP", f"Detected {len(current_tool_calls)} new tool call(s) in response")
                                
                                if new_chunk.is_final:
                                    total_usage = new_chunk.usage
                                    debug_response = {"usage": total_usage, "model": provider.model, "content_length": len(full_content)}
                                    session.add_assistant_message(full_content, total_usage, debug={"usage": total_usage, "model": provider.model}, model=provider.model, reasoning=full_reasoning, group_id=group_id)
                                    preliminary_message_id = session.messages[-1].id
                                    session_manager.save_session(session_id)
                                    preliminary_saved = True
                                yield f"data: {json.dumps({'content': full_content, 'reasoning': full_reasoning, 'done': new_chunk.is_final and not current_tool_calls})}\n\n"
                                
                                if new_chunk.is_final:
                                    break
                            
                            if current_tool_calls:
                                chunk = type('obj', (object,), {
                                    'content': full_content,
                                    'usage': new_chunk.usage,
                                    'tool_calls': current_tool_calls,
                                    'is_final': True
                                })()
                        
                        if tool_iteration >= max_tool_iterations:
                            warning("MCP", f"Reached max tool iterations ({max_tool_iterations})")
                        
                        break
                        
                    except Exception as e:
                        error("MCP", f"Tool handling error: {e}")
                
                if chunk.is_final and not preliminary_saved:
                    total_usage = chunk.usage
                    full_reasoning = chunk.reasoning if chunk.reasoning else full_reasoning
                    info("STREAM", f"Usage: {total_usage}")
                    info("STREAM", f"Model: {provider.model}")
                    debug_response = {"usage": total_usage, "model": provider.model, "content_length": len(full_content)}
                    # Save to session immediately to avoid race condition with UI
                    session.add_assistant_message(full_content, total_usage, debug={"usage": total_usage, "model": provider.model}, model=provider.model, reasoning=full_reasoning, group_id=group_id)
                    preliminary_message_id = session.messages[-1].id
                    session_manager.save_session(session_id)
                    preliminary_saved = True
                    break

                full_content = chunk.content
                full_reasoning = chunk.reasoning if chunk.reasoning else full_reasoning
                yield f"data: {json.dumps({'content': full_content, 'reasoning': full_reasoning, 'done': False})}\n\n"

            if not full_content:
                raise Exception("Empty response from provider")

            if debug_collector.enabled:
                debug_collector.capture_raw_model_response(full_content)
                debug_collector.capture_reasoning(full_reasoning)
                debug_collector.capture_session_info(session.session_id, provider.model, provider.get_provider_name())

            debug_info = debug_collector.get_debug_info()
            
            content_for_user = full_content
            status_error = None

            # Сохраняем предыдущее состояние для восстановления при ошибке
            previous_state = session.status.get("state") if session.status else None

            parsed_status, cleaned_content = status_validator.validate_status_block(full_content)
            
            if parsed_status:
                parsed_status = tsm.process_state_transition(session, parsed_status)
                
                transition_error = parsed_status.get("_transition_error")
                proposed_state = parsed_status.get("state")
                proposed_state_raw = parsed_status.get("_proposed_state")
                
                debug("CHAT_STREAM", f"state={proposed_state}, _proposed_state={proposed_state_raw}, _transition_error={transition_error}")
                
                if transition_error or (proposed_state is None and proposed_state_raw is not None):
                    if transition_error:
                        error_msg = transition_error
                    else:
                        invalid_state = parsed_status.get("_proposed_state")
                        error_msg = f"Недопустимое состояние: '{invalid_state}'. Допустимые: {tsm.VALID_STATES}"
                    
                    transition_info = parsed_status.get("_transition_info", {})
                    current_state = previous_state or transition_info.get("from") or session.status.get("state")
                    allowed = tsm.get_allowed_transitions(current_state)
                    
                    debug("CHAT_STREAM", f"Invalid state (retry): {error_msg}")
                    
                    try:
                        prompt_builder = create_prompt_builder(session, user_id)
                        error_reminder = prompt_builder.build_error_reminder(error_msg, current_state, allowed)
                        retry_messages = prompt_builder.build_messages(error_reminder)
                        
                        # Добавляем строгое предупреждение в system prompt
                        retry_system = system_prompt + "\n\n⚠️ ВНИМАНИЕ! Ты должен ОБЪЯСНИТЬ пользователю если он просит невозможное. Не делай вид что всё в порядке. Если переход невозможен - скажи об этом явно и предложи допустимый следующий шаг."
                        
                        debug("CHAT_STREAM", f"Retry: {len(retry_messages)} messages, provider={session.provider}")
                        llm_client = create_llm_client(session)
                        retry_response = llm_client.send(retry_messages, retry_system, debug=debug_mode)
                        retry_status, retry_cleaned = status_validator.validate_status_block(retry_response.content)
                        
                        if retry_status:
                            retry_status = tsm.process_state_transition(session, retry_status)
                            if retry_status.get("_transition_error"):
                                debug("CHAT_STREAM", "Retry failed - model still reports invalid state")
                                # Восстанавливаем предыдущее состояние
                                if previous_state and session.status:
                                    session.status["state"] = previous_state
                            else:
                                session.update_status(retry_status)
                                _handle_project_updates(session)
                                _handle_user_info_update(retry_status, user_id)
                            content_for_user = retry_cleaned
                            
                            status_event = _emit_project_status(session, previous_status)
                            if status_event:
                                yield f"data: {json.dumps(status_event, ensure_ascii=False)}\n\n"
                        else:
                            # Retry не вернул статус - восстанавливаем предыдущее состояние
                            if previous_state and session.status:
                                session.status["state"] = previous_state
                            content_for_user = cleaned_content
                    except Exception as e:
                        error("CHAT_STREAM", f"Error during retry: {e}")
                        import traceback
                        traceback.print_exc()
                        # При ошибке retry - восстанавливаем предыдущее состояние
                        if previous_state and session.status:
                            session.status["state"] = previous_state
                        content_for_user = cleaned_content
                else:
                    session.update_status(parsed_status)
                    _handle_project_updates(session)
                    _handle_user_info_update(parsed_status, user_id)
                    content_for_user = cleaned_content
                    
                    status_event = _emit_project_status(session, previous_status)
                    if status_event:
                        yield f"data: {json.dumps(status_event, ensure_ascii=False)}\n\n"
            else:
                for retryAttempt in range(3):
                        retry_msgs = session.get_messages_for_llm()
                        retry_status_format = '{"status": {"task_name": "название", "state": "состояние", "progress": "прогресс", '
                        retry_status_format += '"project": "проект", "updated_project_info": "обновлённое описание", '
                        retry_status_format += '"current_task_info": "текущая задача", "approved_plan": "план", '
                        retry_status_format += '"already_done": "сделано", "currently_doing": "текущее", '
                        retry_status_format += '"invariants": {"язык": "Python", "не использовать": ["материал1"]} или null}}'
                        retry_msgs.append(Message(role="user", content="Пожалуйста, добавь в конце своего ответа JSON-блок со статусом задачи в формате: " + retry_status_format, usage={}))
                        retry_system = system_prompt + "\n\nВАЖНО: Ты ОБЯЗАН добавить JSON-блок со статусом задачи в конце ответа!"
                        
                        try:
                            retry_response = provider.chat(retry_msgs, retry_system, debug=debug_mode, tools=mcp_tools)
                            retry_status, retry_cleaned = status_validator.validate_status_block(retry_response.content)
                            
                            if retry_status:
                                session.update_status(retry_status)
                                _handle_project_updates(session)
                                _handle_user_info_update(retry_status, user_id)
                                content_for_user = retry_cleaned
                                
                                status_event = _emit_project_status(session, previous_status)
                                if status_event:
                                    yield f"data: {json.dumps(status_event, ensure_ascii=False)}\n\n"
                                if debug_mode and retry_response.content:
                                    if debug_info is None:
                                        debug_info = {}
                                    debug_info['raw_model_response'] = retry_response.content
                                break
                        except Exception:
                            if retryAttempt == 2:
                                status_error = "Модель не формирует блок статуса в ответе"
            
            # Сохраняем сообщения в сессию
            if needs_summarization:
                # При суммаризации user message ещё не был добавлен
                session.add_user_message(user_msg_for_llm, source=source)
            
            if session.status:
                if debug_info is None:
                    debug_info = {}
                debug_info['status'] = session.status
                debug_info['subtasks'] = session.status.get('subtasks', [])
            if status_error:
                if debug_info is None:
                    debug_info = {}
                debug_info['status_error'] = status_error
            if mcp_calls:
                if debug_info is None:
                    debug_info = {}
                debug_info['mcp_calls'] = mcp_calls
            
            # Update or add assistant message
            if debug_collector.enabled:
                if session.status:
                    debug_collector.capture_status(session.status)
                for mcp in mcp_calls:
                    debug_collector.capture_mcp_call(
                        tool=mcp.get("tool", ""),
                        arguments=mcp.get("arguments", {}),
                        result=mcp.get("result", ""),
                        is_error=mcp.get("is_error", False)
                    )
            debug_info = debug_collector.get_debug_info()
            
            if preliminary_saved and preliminary_message_id:
                # Find assistant message by ID (search from end to handle info messages added after)
                target_msg = None
                for msg in reversed(session.messages):
                    if msg.id == preliminary_message_id:
                        target_msg = msg
                        break
                if target_msg:
                    target_msg.content = content_for_user
                    target_msg.usage = total_usage
                    target_msg.debug = debug_info
                    target_msg.tool_use = tool_use_for_message
                    target_msg.group_id = group_id
            elif preliminary_saved:
                # Fallback: update last message if no ID stored
                last_msg = session.messages[-1]
                last_msg.content = content_for_user
                last_msg.usage = total_usage
                last_msg.debug = debug_info
                last_msg.tool_use = tool_use_for_message
                last_msg.group_id = group_id
            else:
                session.add_assistant_message(content_for_user, total_usage, debug=debug_info, model=provider.model, group_id=group_id)

            session_manager.save_session(session_id)

            disabled_indices = [i for i, m in enumerate(session.messages) if m.disabled]
                
            yield f"data: {json.dumps({'content': content_for_user, 'done': True, 'usage': total_usage, 'model': provider.model, 'debug': debug_info, 'disabled_indices': disabled_indices})}\n\n"

        except ContextLengthExceededError as e:
            session.add_error_message(f"[Ошибка] {str(e)}", debug=e.debug_response if debug_mode else None, model=provider.model)
            session_manager.save_session(session_id)
            error_data = {"error": str(e), "error_type": "context_length_exceeded", "content_received": full_content}
            if debug_mode and e.debug_response:
                error_data["debug"] = {"request": debug_request, "response": e.debug_response}
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
        except Exception as e:
            session.add_error_message(f"[Ошибка] {str(e)}", None, model=provider.model)
            session_manager.save_session(session_id)
            error_data = {"error": f"LLM error: {str(e)}", "content_received": full_content}
            if debug_mode:
                error_data["debug"] = {"request": debug_request, "response": {"error": str(e), "content_length": len(full_content)}}
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"

        yield "data: [DONE]\n\n"

    from flask import stream_with_context
    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@api_bp.route("/chat/reset", methods=["POST"])
@require_user
def reset_chat():
    session_id = get_session_id()
    session_manager.reset_session(session_id)

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
