import os
from pathlib import Path

import requests
import yaml
from flask import Blueprint, Flask, Response, jsonify, make_response, render_template, request

ui_bp = Blueprint("ui", __name__)


class UIConfig:
    _instance = None
    _config: dict = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self) -> None:
        config_path = Path(__file__).parent / "config.yaml"
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, "r") as f:
            self._config = yaml.safe_load(f)

    @property
    def app(self) -> dict:
        return self._config.get("app", {})

    @property
    def host(self) -> str:
        return self.app.get("host", "0.0.0.0")

    @property
    def port(self) -> int:
        return self.app.get("port", 5001)

    @property
    def backend(self) -> dict:
        return self._config.get("backend", {})

    @property
    def backend_url(self) -> str:
        return self.backend.get("url", "http://localhost:5000")

    @property
    def backend_api_key(self) -> str:
        return self.backend.get("api_key", "")

    @property
    def auth(self) -> dict:
        return self._config.get("auth", {})

    @property
    def api_key(self) -> str:
        return self.auth.get("api_key", "")


ui_config = UIConfig()


def get_session_id() -> str:
    session_id = request.headers.get("X-Session-Id")
    if not session_id:
        session_id = request.cookies.get("session_id", "default")
    return session_id


def get_auth_cookies() -> dict:
    cookies = {}
    for name in request.cookies:
        cookies[name] = request.cookies[name]
    return cookies


@ui_bp.route("/")
def index():
    return render_template("chat.html")


@ui_bp.route("/api/note", methods=["POST"])
def add_note():
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "Missing 'content' field"}), 400

    session_id = get_session_id()

    url = f"{ui_config.backend_url}/api/note"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "X-Session-Id": session_id,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing 'message' field"}), 400

    user_message = data["message"]
    provider_name = data.get("provider")
    model = data.get("model")
    session_id = get_session_id()

    url = f"{ui_config.backend_url}/api/chat"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "X-Session-Id": session_id,
        "X-User-Id": request.headers.get("X-User-Id", ""),
        "Content-Type": "application/json",
    }

    payload = {"message": user_message}
    if provider_name:
        payload["provider"] = provider_name
    if model:
        payload["model"] = model
    debug_mode = data.get("debug")
    if debug_mode is not None:
        payload["debug"] = debug_mode
    source = data.get("source")
    if source:
        payload["source"] = source
    agent_role = data.get("agent_role")
    if agent_role:
        payload["agent_role"] = agent_role

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        result["session_id"] = session_id
        return jsonify(result)
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing 'message' field"}), 400

    user_message = data["message"]
    provider_name = data.get("provider")
    model = data.get("model")
    session_id = get_session_id()

    url = f"{ui_config.backend_url}/api/chat/stream"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "X-Session-Id": session_id,
        "X-User-Id": request.headers.get("X-User-Id", ""),
        "Content-Type": "application/json",
    }

    payload = {"message": user_message}
    if provider_name:
        payload["provider"] = provider_name
    if model:
        payload["model"] = model
    tsm_mode = data.get("tsm_mode")
    if tsm_mode:
        payload["tsm_mode"] = tsm_mode
    source = data.get("source")
    if source:
        payload["source"] = source
    agent_role = data.get("agent_role")
    if agent_role:
        payload["agent_role"] = agent_role

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=payload, timeout=120, stream=True)
        response.raise_for_status()

        def generate():
            for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                yield chunk

        return Response(generate(), mimetype="text/event-stream")
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/chat/reset", methods=["POST"])
def reset_chat():
    session_id = get_session_id()

    url = f"{ui_config.backend_url}/api/chat/reset"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "X-Session-Id": session_id,
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), timeout=30)
        response.raise_for_status()
        return jsonify({"status": "reset", "session_id": session_id})
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/health", methods=["GET"])
def health():
    url = f"{ui_config.backend_url}/api/health"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return jsonify({"status": "ok", "backend": "connected"})
        else:
            return jsonify({"status": "ok", "backend": "disconnected"})
    except requests.RequestException:
        return jsonify({"status": "ok", "backend": "disconnected"})


@ui_bp.route("/api/profile", methods=["GET"])
def get_profile():
    url = f"{ui_config.backend_url}/api/profile"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }
    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/profile", methods=["PUT"])
def update_profile():
    url = f"{ui_config.backend_url}/api/profile"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }
    data = request.get_json()
    try:
        response = requests.put(url, headers=headers, json=data, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/users/by-username/<username>", methods=["GET"])
def get_user_by_username(username):
    url = f"{ui_config.backend_url}/api/users/by-username/{username}"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }
    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/config", methods=["GET"])
def get_config():
    url = f"{ui_config.backend_url}/api/config"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        if response.status_code == 200:
            return jsonify(response.json())
    except requests.RequestException:
        pass

    return jsonify({
        "default_provider": "openai",
        "providers": ["openai", "anthropic", "ollama"],
    })


@ui_bp.route("/api/agents", methods=["GET"])
def get_agents():
    url = f"{ui_config.backend_url}/api/agents"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions", methods=["GET"])
def list_sessions():
    url = f"{ui_config.backend_url}/api/sessions"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>", methods=["DELETE"])
def delete_session(session_id: str):
    url = f"{ui_config.backend_url}/api/sessions/{session_id}"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.delete(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/rename", methods=["POST"])
def rename_session(session_id: str):
    data = request.get_json()
    if not data or "new_name" not in data:
        return jsonify({"error": "Missing 'new_name' field"}), 400

    url = f"{ui_config.backend_url}/api/sessions/{session_id}/rename"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/copy", methods=["POST"])
def copy_session(session_id: str):
    data = request.get_json()
    if not data or "new_session_id" not in data:
        return jsonify({"error": "Missing 'new_session_id' field"}), 400

    url = f"{ui_config.backend_url}/api/sessions/{session_id}/copy"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>", methods=["GET"])
def get_session(session_id: str):
    url = f"{ui_config.backend_url}/api/sessions/{session_id}"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        if response.status_code == 404:
            return jsonify({"provider": "", "model": "", "messages": []})
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/agent-role", methods=["POST"])
def set_session_agent_role(session_id: str):
    data = request.get_json() or {}
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/agent-role"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "X-User-Id": request.headers.get("X-User-Id", ""),
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/context-settings", methods=["GET"])
def get_context_settings(session_id: str):
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/context-settings"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        if response.status_code == 404:
            return jsonify({
                "context_optimization": "none",
                "summarization_enabled": False,
                "summarize_after_n": 10,
                "summarize_after_minutes": 0,
                "summarize_context_percent": 0,
                "sliding_window_type": "messages",
                "sliding_window_limit": 10,
                "default_interval": 10
            })
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/context-settings", methods=["POST"])
def set_context_settings(session_id: str):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    url = f"{ui_config.backend_url}/api/sessions/{session_id}/context-settings"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/rag-settings", methods=["GET"])
def get_rag_settings(session_id: str):
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/rag-settings"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        if response.status_code == 404:
            return jsonify({
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
                    "model": "cross-encoder/ms-marco-MiniLM-L-6G-v2",
                    "top_k_before": 20,
                }
            })
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/rag-settings", methods=["PUT"])
def set_rag_settings(session_id: str):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    url = f"{ui_config.backend_url}/api/sessions/{session_id}/rag-settings"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.put(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/tsm-settings", methods=["GET"])
def get_tsm_settings(session_id: str):
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/tsm-settings"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        if response.status_code == 404:
            return jsonify({
                "tsm_mode": "simple",
                "mode_name": "Simple Prompt",
                "task_name": "conversation",
                "state": None,
                "allowed_transitions": [],
                "transition_log": [],
                "available_modes": ["simple", "orchestrator", "deterministic"],
                "mode_descriptions": {
                    "simple": "Базовый системный промпт с инструкцией по статусу задачи.",
                    "orchestrator": "Отдельный system prompt-оркестратор с подзадачами.",
                    "deterministic": "Детерминированный переход с жёсткой валидацией.",
                }
            })
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/tsm-settings", methods=["POST"])
def set_tsm_settings(session_id: str):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    url = f"{ui_config.backend_url}/api/sessions/{session_id}/tsm-settings"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/summarize", methods=["POST"])
def manual_summarize(session_id: str):
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/summarize"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), timeout=120)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/clear-debug", methods=["POST"])
def clear_session_debug(session_id: str):
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/clear-debug"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/messages", methods=["GET"])
def get_session_messages(session_id: str):
    url = f"{ui_config.backend_url}/api/sessions/{session_id}"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        if response.status_code == 404:
            return jsonify({"messages": []})
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/messages/<int:index>", methods=["DELETE"])
def delete_session_message(session_id: str, index: int):
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/messages/{index}"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.delete(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/messages/<int:index>/toggle", methods=["POST"])
def toggle_session_message(session_id: str, index: int):
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/messages/{index}/toggle"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/messages/<int:index>/pin", methods=["POST"])
def pin_session_message(session_id: str, index: int):
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/messages/{index}/pin"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/export", methods=["POST"])
def export_sessions():
    url = f"{ui_config.backend_url}/api/sessions/export"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": f"Backend error: {str(e)}"}


@ui_bp.route("/api/sessions/import", methods=["POST"])
def import_session():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    url = f"{ui_config.backend_url}/api/sessions/import"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=30)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/checkpoints", methods=["POST"])
def create_checkpoint(session_id: str):
    data = request.get_json() or {}
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/checkpoints"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/checkpoints/<checkpoint_id>/branch", methods=["POST"])
def create_branch_from_checkpoint(session_id: str, checkpoint_id: str):
    data = request.get_json() or {}
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/checkpoints/{checkpoint_id}/branch"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/branches/<branch_id>/switch", methods=["POST"])
def switch_branch(session_id: str, branch_id: str):
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/branches/{branch_id}/switch"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/branches/<branch_id>/rename", methods=["POST"])
def rename_branch(session_id: str, branch_id: str):
    data = request.get_json() or {}
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/branches/{branch_id}/rename"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/branches/<branch_id>", methods=["DELETE"])
def delete_branch(session_id: str, branch_id: str):
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/branches/{branch_id}"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.delete(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/branches/<branch_id>/reset", methods=["POST"])
def reset_branch(session_id: str, branch_id: str):
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/branches/{branch_id}/reset"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/checkpoints/<checkpoint_id>/rename", methods=["POST"])
def rename_checkpoint(session_id: str, checkpoint_id: str):
    data = request.get_json() or {}
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/checkpoints/{checkpoint_id}/rename"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/checkpoints/<checkpoint_id>", methods=["DELETE"])
def delete_checkpoint(session_id: str, checkpoint_id: str):
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/checkpoints/{checkpoint_id}"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.delete(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/tree", methods=["GET"])
def get_session_tree(session_id: str):
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/tree"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/config", methods=["GET"])
def get_admin_config():
    url = f"{ui_config.backend_url}/admin/config"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/config", methods=["POST"])
def save_admin_config():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    url = f"{ui_config.backend_url}/admin/config"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/config/validate", methods=["POST"])
def validate_provider():
    data = request.get_json()
    if not data or "provider" not in data:
        return jsonify({"error": "Missing provider"}), 400

    url = f"{ui_config.backend_url}/admin/config/validate"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=30)
        if response.status_code == 200:
            return jsonify(response.json())
        return jsonify({"error": response.json().get("error", "Validation failed")}), 400
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/providers/<provider_name>/models", methods=["GET"])
def get_provider_models(provider_name: str):
    url = f"{ui_config.backend_url}/admin/providers/{provider_name}/models"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=30)
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": f"Backend returned {response.status_code}: {response.text}"}), response.status_code
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/context", methods=["GET"])
def list_context_files():
    url = f"{ui_config.backend_url}/admin/context"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/context", methods=["POST"])
def create_context_file():
    data = request.get_json()
    if not data or "filename" not in data:
        return jsonify({"error": "Missing filename"}), 400

    url = f"{ui_config.backend_url}/admin/context"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        if response.status_code == 400:
            return jsonify({"error": response.json().get("error", "File already exists")}), 400
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/context/enabled", methods=["GET"])
def get_enabled_context_files():
    url = f"{ui_config.backend_url}/admin/context/enabled"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/context/enabled", methods=["POST"])
def set_enabled_context_files():
    data = request.get_json()
    if not data or "enabled_files" not in data:
        return jsonify({"error": "Missing enabled_files"}), 400

    url = f"{ui_config.backend_url}/admin/context/enabled"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/context/<filename>", methods=["GET"])
def get_context_file(filename: str):
    url = f"{ui_config.backend_url}/admin/context/{filename}"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        if response.status_code == 404:
            return jsonify({"error": "File not found"}), 404
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/context/<filename>", methods=["POST"])
def save_context_file(filename: str):
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "Missing content"}), 400

    url = f"{ui_config.backend_url}/admin/context/{filename}"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/context/<filename>", methods=["DELETE"])
def delete_context_file(filename: str):
    url = f"{ui_config.backend_url}/admin/context/{filename}"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.delete(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        if response.status_code == 404:
            return jsonify({"error": response.json().get("error", "File not found")}), 404
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/agents", methods=["GET"])
def admin_agents_list():
    url = f"{ui_config.backend_url}/admin/agents"
    headers = {"X-API-Key": ui_config.backend_api_key}
    
    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/agents/<agent_name>/ssh-keys", methods=["GET"])
def admin_agent_ssh_keys(agent_name: str):
    url = f"{ui_config.backend_url}/admin/agents/{agent_name}/ssh-keys"
    headers = {"X-API-Key": ui_config.backend_api_key}
    
    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/agents/<agent_name>/ssh-keys", methods=["POST"])
def admin_agent_ssh_keys_add(agent_name: str):
    url = f"{ui_config.backend_url}/admin/agents/{agent_name}/ssh-keys"
    headers = {"X-API-Key": ui_config.backend_api_key, "Content-Type": "application/json"}
    data = request.get_json()
    
    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/agents/<agent_name>/ssh-keys/<key_id>", methods=["DELETE"])
def admin_agent_ssh_keys_delete(agent_name: str, key_id: str):
    url = f"{ui_config.backend_url}/admin/agents/{agent_name}/ssh-keys/{key_id}"
    headers = {"X-API-Key": ui_config.backend_api_key}
    
    try:
        response = requests.delete(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/embeddings", methods=["GET"])
def admin_embeddings_list():
    url = f"{ui_config.backend_url}/admin/embeddings"
    headers = {"X-API-Key": ui_config.backend_api_key}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/embeddings/<index_id>", methods=["DELETE"])
def admin_embeddings_delete(index_id: str):
    url = f"{ui_config.backend_url}/api/embeddings/{index_id}"
    headers = {"X-API-Key": ui_config.backend_api_key}

    try:
        response = requests.delete(url, headers=headers, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/admin/context/<filename>/rename", methods=["POST"])
def rename_context_file(filename: str):
    data = request.get_json()
    if not data or "new_name" not in data:
        return jsonify({"error": "Missing new_name"}), 400

    url = f"{ui_config.backend_url}/admin/context/{filename}/rename"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        if response.status_code == 400:
            return jsonify({"error": response.json().get("error", "File already exists")}), 400
        if response.status_code == 404:
            return jsonify({"error": response.json().get("error", "File not found")}), 404
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/user/settings", methods=["GET"])
def get_user_settings():
    session_id = get_session_id()
    url = f"{ui_config.backend_url}/api/sessions/{session_id}"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        if response.status_code == 404:
            return jsonify({"provider": "", "model": ""})
        response.raise_for_status()
        data = response.json()
        return jsonify({
            "provider": data.get("provider", ""),
            "model": data.get("model", ""),
        })
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/user/settings", methods=["POST"])
def save_user_settings():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    session_id = get_session_id()
    url = f"{ui_config.backend_url}/api/sessions/{session_id}"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        session_data = {}
        if response.status_code == 200:
            session_data = response.json()
        
        if not session_data.get("session_id"):
            session_data["session_id"] = session_id
        
        session_data["user_settings"] = data
        
        response = requests.post(
            f"{ui_config.backend_url}/api/sessions/import",
            headers={"X-API-Key": ui_config.backend_api_key, "Content-Type": "application/json"},
            json=session_data,
            timeout=10,
        )
        response.raise_for_status()
        return jsonify({"status": "saved"})
    except requests.RequestException as e:
        print(f"[ERROR] save_user_settings: {e}")
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data or "username" not in data or "password" not in data:
        return jsonify({"error": "Missing username or password"}), 400

    try:
        response = requests.post(
            f"{ui_config.backend_url}/api/auth/login",
            json=data,
            timeout=10,
        )
        if response.status_code == 200:
            result = jsonify(response.json()), 200
            resp = make_response(result)
            for name, value in response.cookies.items():
                resp.set_cookie(name, value, httponly=True, path='/')
            return resp
        elif response.status_code == 401:
            return jsonify(response.json().get("error", "Unauthorized")), 401
        return jsonify({"error": f"Backend error: {response.status_code}"}), response.status_code
    except requests.RequestException as e:
        print(f"[ERROR] login: {e}")
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/auth/logout", methods=["POST"])
def logout():
    try:
        response = requests.post(
            f"{ui_config.backend_url}/api/auth/logout",
            cookies=request.cookies,
            timeout=10,
        )
        result = jsonify({"message": "Logged out"})
        resp = make_response(result)
        resp.set_cookie('session', '', expires=0, httponly=True, path='/')
        return resp
    except requests.RequestException as e:
        print(f"[ERROR] logout: {e}")
        result = jsonify({"message": "Logged out"})
        resp = make_response(result)
        resp.set_cookie('session', '', expires=0, httponly=True, path='/')
        return resp


@ui_bp.route("/api/auth/me", methods=["GET"])
def me():
    try:
        response = requests.get(
            f"{ui_config.backend_url}/api/auth/me",
            cookies=request.cookies,
            timeout=10,
        )
        if response.status_code == 200:
            return jsonify(response.json()), 200
        return jsonify({"error": "Not authenticated"}), response.status_code
    except requests.RequestException as e:
        print(f"[ERROR] me: {e}")
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/users", methods=["GET"])
def list_users():
    try:
        response = requests.get(
            f"{ui_config.backend_url}/api/users",
            headers={"X-API-Key": ui_config.backend_api_key},
            timeout=10,
        )
        if response.status_code == 200:
            return jsonify(response.json()), 200
        return jsonify({"error": "Access denied"}), response.status_code
    except requests.RequestException as e:
        print(f"[ERROR] list_users: {e}")
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/users", methods=["POST"])
def create_user():
    data = request.get_json()
    try:
        response = requests.post(
            f"{ui_config.backend_url}/api/users",
            headers={
                "X-API-Key": ui_config.backend_api_key,
                "Content-Type": "application/json"
            },
            json=data,
            timeout=10,
        )
        if response.status_code == 200:
            return jsonify(response.json()), 200
        return jsonify(response.json().get("error", "Error")), response.status_code
    except requests.RequestException as e:
        print(f"[ERROR] create_user: {e}")
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/users/<user_id>", methods=["GET"])
def get_user(user_id):
    try:
        response = requests.get(
            f"{ui_config.backend_url}/api/users/{user_id}",
            headers={"X-API-Key": ui_config.backend_api_key},
            timeout=10,
        )
        if response.status_code == 200:
            return jsonify(response.json()), 200
        return jsonify({"error": "Not found"}), response.status_code
    except requests.RequestException as e:
        print(f"[ERROR] get_user: {e}")
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/users/<user_id>", methods=["PUT"])
def update_user(user_id):
    data = request.get_json()
    try:
        response = requests.put(
            f"{ui_config.backend_url}/api/users/{user_id}",
            headers={
                "X-API-Key": ui_config.backend_api_key,
                "Content-Type": "application/json"
            },
            json=data,
            timeout=10,
        )
        if response.status_code == 200:
            return jsonify(response.json()), 200
        return jsonify(response.json().get("error", "Error")), response.status_code
    except requests.RequestException as e:
        print(f"[ERROR] update_user: {e}")
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/users/<user_id>", methods=["DELETE"])
def delete_user(user_id):
    try:
        response = requests.delete(
            f"{ui_config.backend_url}/api/users/{user_id}",
            headers={"X-API-Key": ui_config.backend_api_key},
            timeout=10,
        )
        if response.status_code == 200:
            return jsonify(response.json()), 200
        return jsonify({"error": "Error"}), response.status_code
    except requests.RequestException as e:
        print(f"[ERROR] delete_user: {e}")
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/users/<user_id>/reset-password", methods=["POST"])
def reset_user_password(user_id):
    try:
        response = requests.post(
            f"{ui_config.backend_url}/api/users/{user_id}/reset-password",
            headers={"X-API-Key": ui_config.backend_api_key},
            timeout=10,
        )
        if response.status_code == 200:
            return jsonify(response.json()), 200
        return jsonify(response.json().get("error", "Error")), response.status_code
    except requests.RequestException as e:
        print(f"[ERROR] reset_user_password: {e}")
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/mcp/servers", methods=["GET"])
def list_mcp_servers():
    url = f"{ui_config.backend_url}/api/mcp/servers"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }
    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/mcp/builtin-tools", methods=["GET"])
def list_builtin_mcp_tools():
    url = f"{ui_config.backend_url}/api/mcp/builtin-tools"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }
    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/session/mcp", methods=["GET"])
def get_session_mcp():
    session_id = get_session_id()
    url = f"{ui_config.backend_url}/api/session/mcp"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "X-Session-Id": session_id,
    }
    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/session/mcp", methods=["PUT"])
def update_session_mcp():
    session_id = get_session_id()
    data = request.get_json()
    if not data or "mcp_servers" not in data:
        return jsonify({"error": "Missing 'mcp_servers' field"}), 400
    
    url = f"{ui_config.backend_url}/api/session/mcp"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "X-Session-Id": session_id,
        "Content-Type": "application/json",
    }
    try:
        response = requests.put(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(ui_bp)
    return app


@ui_bp.route("/api/projects/<project_name>/schedules", methods=["GET"])
def list_project_schedules(project_name):
    url = f"{ui_config.backend_url}/api/projects/{project_name}/schedules"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }
    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/projects/<project_name>/schedules", methods=["POST"])
def create_project_schedule(project_name):
    data = request.get_json()
    if not data or "name" not in data or "prompt" not in data or "cron" not in data:
        return jsonify({"error": "Missing required fields: name, prompt, cron"}), 400

    url = f"{ui_config.backend_url}/api/projects/{project_name}/schedules"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json()), 201
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/projects/<project_name>/schedules/<schedule_id>", methods=["PUT"])
def update_project_schedule(project_name, schedule_id):
    data = request.get_json()
    url = f"{ui_config.backend_url}/api/projects/{project_name}/schedules/{schedule_id}"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }
    try:
        response = requests.put(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/projects/<project_name>/schedules/<schedule_id>", methods=["DELETE"])
def delete_project_schedule(project_name, schedule_id):
    url = f"{ui_config.backend_url}/api/projects/{project_name}/schedules/{schedule_id}"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }
    try:
        response = requests.delete(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/projects/<project_name>/schedules/<schedule_id>/run", methods=["POST"])
def run_project_schedule(project_name, schedule_id):
    url = f"{ui_config.backend_url}/api/projects/{project_name}/schedules/{schedule_id}/run"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }
    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), timeout=120)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/projects/<project_name>/embeddings", methods=["GET"])
def get_project_embeddings(project_name):
    """Get embeddings indexes for a project - proxy to backend."""
    url = f"{ui_config.backend_url}/api/projects/{project_name}/embeddings"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }
    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/projects/<project_name>/embeddings/<index_name>", methods=["DELETE"])
def delete_project_embeddings(project_name, index_name):
    """Delete an embeddings index from project - proxy to backend."""
    url = f"{ui_config.backend_url}/api/projects/{project_name}/embeddings/{index_name}"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }
    try:
        response = requests.delete(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/projects/<project_name>/embeddings/<index_name>/enable", methods=["POST"])
def enable_project_embeddings(project_name, index_name):
    """Enable or disable an embeddings index - proxy to backend."""
    data = request.get_json() or {}
    url = f"{ui_config.backend_url}/api/projects/{project_name}/embeddings/{index_name}/enable"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/projects/<project_name>/embeddings/add", methods=["POST"])
def add_project_embeddings(project_name):
    """Add an existing embeddings index to a project - proxy to backend."""
    data = request.get_json() or {}
    url = f"{ui_config.backend_url}/api/projects/{project_name}/embeddings/add"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/sessions/<session_id>/events", methods=["GET"])
def session_events(session_id: str):
    """SSE endpoint for session updates - proxy to backend."""
    url = f"{ui_config.backend_url}/api/sessions/{session_id}/events"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
    }

    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), stream=True, timeout=30)
        response.raise_for_status()

        def generate():
            for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                yield chunk

        return Response(generate(), mimetype="text/event-stream")
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/embeddings/list", methods=["GET"])
def embeddings_list():
    """Get list of embeddings indexes for UI dropdown."""
    url = f"{ui_config.backend_url}/api/embeddings/list"
    headers = {"X-API-Key": ui_config.backend_api_key}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/embeddings/by-name/<name>", methods=["GET"])
def embeddings_by_name(name: str):
    """Get all versions of an embedding index."""
    url = f"{ui_config.backend_url}/api/embeddings/by-name/{name}"
    headers = {"X-API-Key": ui_config.backend_api_key}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/projects/<project_name>/git-repos", methods=["GET"])
def list_git_repos(project_name: str):
    """List git repositories for a project - proxy to backend."""
    url = f"{ui_config.backend_url}/api/projects/{project_name}/git-repos"
    headers = {"X-API-Key": ui_config.backend_api_key}
    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/projects/<project_name>/git-repos", methods=["POST"])
def add_git_repo(project_name: str):
    """Add a git repository to a project - proxy to backend."""
    data = request.get_json() or {}
    url = f"{ui_config.backend_url}/api/projects/{project_name}/git-repos"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=30)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/projects/<project_name>/git-repos/<repo_name>", methods=["DELETE"])
def delete_git_repo(project_name: str, repo_name: str):
    """Delete a git repository from a project - proxy to backend."""
    data = request.get_json() or {}
    url = f"{ui_config.backend_url}/api/projects/{project_name}/git-repos/{repo_name}"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }
    try:
        response = requests.delete(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/projects/<project_name>/git-repos/<repo_name>/fetch", methods=["POST"])
def fetch_git_repo(project_name: str, repo_name: str):
    """Fetch updates from a git repository - proxy to backend."""
    data = request.get_json() or {}
    url = f"{ui_config.backend_url}/api/projects/{project_name}/git-repos/{repo_name}/fetch"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, headers=headers, cookies=get_auth_cookies(), json=data, timeout=30)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500


@ui_bp.route("/api/projects/<project_name>/git-repos/<repo_name>/info", methods=["GET"])
def git_repo_info(project_name: str, repo_name: str):
    """Get info about a git repository - proxy to backend."""
    url = f"{ui_config.backend_url}/api/projects/{project_name}/git-repos/{repo_name}/info"
    headers = {"X-API-Key": ui_config.backend_api_key}
    try:
        response = requests.get(url, headers=headers, cookies=get_auth_cookies(), timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": f"Backend error: {str(e)}"}), 500
