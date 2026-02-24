import json

from flask import Blueprint, jsonify, request, Response

from backend.app.config import config
from backend.app.context import get_system_prompt
from backend.app.llm import ProviderFactory
from backend.app.session import session_manager

api_bp = Blueprint("api", __name__)


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


@api_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@api_bp.route("/chat", methods=["POST"])
@require_auth
def chat():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing 'message' field"}), 400

    user_message = data["message"]
    provider_name = data.get("provider", config.default_provider)

    provider_config = config.get_provider_config(provider_name)
    if not provider_config:
        return jsonify({"error": f"Unknown provider: {provider_name}"}), 400

    try:
        provider = ProviderFactory.create(provider_name, provider_config)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    session_id = get_session_id()
    session = session_manager.get_session(session_id)
    session.add_user_message(user_message)

    system_prompt = get_system_prompt()

    try:
        response = provider.chat(session.messages, system_prompt)
    except Exception as e:
        return jsonify({"error": f"LLM error: {str(e)}"}), 500

    session.add_assistant_message(response.content)
    session_manager.save_session(session_id)

    return jsonify({
        "message": response.content,
        "session_id": session_id,
        "model": response.model,
    })


@api_bp.route("/chat/reset", methods=["POST"])
@require_auth
def reset_chat():
    session_id = get_session_id()
    session_manager.reset_session(session_id)

    return jsonify({
        "status": "reset",
        "session_id": session_id,
    })


@api_bp.route("/sessions", methods=["GET"])
@require_auth
def list_sessions():
    sessions = session_manager.list_sessions()
    return jsonify({"sessions": sessions})


@api_bp.route("/sessions/<session_id>", methods=["GET"])
@require_auth
def get_session(session_id: str):
    session_data = session_manager.get_session_data(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(session_data)


@api_bp.route("/sessions/<session_id>", methods=["DELETE"])
@require_auth
def delete_session(session_id: str):
    if session_id == "default":
        return jsonify({"error": "Cannot delete default session"}), 400
    
    success = session_manager.delete_session(session_id)
    if not success:
        return jsonify({"error": "Session not found"}), 404
    
    return jsonify({"status": "deleted", "session_id": session_id})


@api_bp.route("/sessions/<session_id>/rename", methods=["POST"])
@require_auth
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


@api_bp.route("/sessions/export", methods=["POST"])
@require_auth
def export_sessions():
    data = session_manager.export_all()
    return Response(
        json.dumps(data, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment;filename=t6-sessions.json"},
    )


@api_bp.route("/sessions/import", methods=["POST"])
@require_auth
def import_session():
    data = request.get_json()
    if not data or "session_id" not in data:
        return jsonify({"error": "Invalid session data"}), 400

    try:
        session_id = session_manager.import_session(data)
        return jsonify({"status": "imported", "session_id": session_id})
    except Exception as e:
        return jsonify({"error": f"Import failed: {str(e)}"}), 500
