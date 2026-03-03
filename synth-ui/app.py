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
    debug_mode = data.get("debug", False)
    session_id = get_session_id()

    url = f"{ui_config.backend_url}/api/chat"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "X-Session-Id": session_id,
        "X-User-Id": request.headers.get("X-User-Id", ""),
        "Content-Type": "application/json",
    }

    payload = {"message": user_message, "debug": debug_mode}
    if provider_name:
        payload["provider"] = provider_name
    if model:
        payload["model"] = model

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
    debug_mode = data.get("debug", False)
    session_id = get_session_id()

    url = f"{ui_config.backend_url}/api/chat/stream"
    headers = {
        "X-API-Key": ui_config.backend_api_key,
        "X-Session-Id": session_id,
        "X-User-Id": request.headers.get("X-User-Id", ""),
        "Content-Type": "application/json",
    }

    payload = {"message": user_message, "debug": debug_mode}
    if provider_name:
        payload["provider"] = provider_name
    if model:
        payload["model"] = model

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


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(ui_bp)
    return app
