import json

import requests
from flask import Blueprint, jsonify, request, Response

from app.config import config
from app.context import get_system_prompt
from app.llm import ProviderFactory
from app.llm.providers import ContextLengthExceededError
from app.session import session_manager

api_bp = Blueprint("api", __name__)
admin_bp = Blueprint("admin", __name__)


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
    provider_name = data.get("provider")
    model = data.get("model")
    debug_mode = data.get("debug", False)
    
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
    session.add_user_message(user_message)
    
    if provider_name and model:
        session.set_provider_model(provider_name, model)
    elif provider_name and not session.provider:
        session.set_provider_model(provider_name, config.get_default_model(provider_name))

    system_prompt = get_system_prompt()

    try:
        response = provider.chat(session.messages, system_prompt, debug=debug_mode)
    except ContextLengthExceededError as e:
        session.add_assistant_message(f"[Ошибка] {str(e)}", None, debug=e.debug_response if debug_mode else None, model=provider.model)
        session_manager.save_session(session_id)
        result = {"error": str(e), "error_type": "context_length_exceeded", "model": provider.model}
        if debug_mode and e.debug_response:
            result["debug"] = {"response": e.debug_response}
        return jsonify(result), 400
    except Exception as e:
        session.add_assistant_message(f"[Ошибка] {str(e)}", None, None, model=provider.model)
        session_manager.save_session(session_id)
        result = {"error": f"LLM error: {str(e)}", "model": provider.model}
        return jsonify(result), 500

    debug_info = None
    if debug_mode:
        debug_info = {
            "request": response.debug_request,
            "response": response.debug_response,
        }

    session.add_assistant_message(response.content, response.usage, debug=debug_info, model=response.model)
    session_manager.save_session(session_id)

    result = {
        "message": response.content,
        "session_id": session_id,
        "model": response.model,
        "usage": response.usage,
        "total_tokens": session.total_tokens,
    }
    
    if debug_info:
        result["debug"] = debug_info
    
    return jsonify(result)


@api_bp.route("/chat/stream", methods=["POST"])
@require_auth
def chat_stream():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing 'message' field"}), 400

    user_message = data["message"]
    provider_name = data.get("provider")
    model = data.get("model")
    debug_mode = data.get("debug", False)

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
    session.add_user_message(user_message)

    if provider_name and model:
        session.set_provider_model(provider_name, model)
    elif provider_name and not session.provider:
        session.set_provider_model(provider_name, config.get_default_model(provider_name))

    system_prompt = get_system_prompt()

    formatted_messages = []
    if system_prompt:
        formatted_messages.append({"role": "system", "content": system_prompt})
    for msg in session.messages:
        formatted_messages.append({"role": msg.role, "content": msg.content})

    def generate():
        full_content = ""
        total_usage = {}
        debug_request = None
        debug_response = None

        if debug_mode:
            debug_request = {
                "url": provider.url,
                "method": "POST",
                "model": provider.model,
                "headers": {"Content-Type": "application/json"},
                "body": {
                    "model": provider.model,
                    "messages": formatted_messages,
                    "temperature": 0.7,
                    "stream": True,
                },
            }

        try:
            for chunk in provider.stream_chat(session.messages, system_prompt, debug=debug_mode):
                if chunk.is_final:
                    total_usage = chunk.usage
                    debug_response = {"usage": total_usage, "model": provider.model, "content_length": len(full_content)}
                    break

                full_content = chunk.content
                yield f"data: {json.dumps({'content': full_content, 'done': False})}\n\n"

            if not full_content:
                raise Exception("Empty response from provider")

            yield f"data: {json.dumps({'content': full_content, 'done': True, 'usage': total_usage, 'debug': {'request': debug_request, 'response': debug_response}})}\n\n"

            debug_info = {"request": debug_request, "response": debug_response} if debug_mode else None
            session.add_assistant_message(full_content, total_usage, debug=debug_info, model=provider.model)
            session_manager.save_session(session_id)

        except ContextLengthExceededError as e:
            session.add_assistant_message(f"[Ошибка] {str(e)}", None, debug=e.debug_response if debug_mode else None, model=provider.model)
            session_manager.save_session(session_id)
            error_data = {"error": str(e), "error_type": "context_length_exceeded", "content_received": full_content}
            if debug_mode and e.debug_response:
                error_data["debug"] = {"request": debug_request, "response": e.debug_response}
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
        except Exception as e:
            session.add_assistant_message(f"[Ошибка] {str(e)}", None, None, model=provider.model)
            session_manager.save_session(session_id)
            error_data = {"error": f"LLM error: {str(e)}", "content_received": full_content}
            if debug_mode:
                error_data["debug"] = {"request": debug_request, "response": {"error": str(e), "content_length": len(full_content)}}
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"

        yield "data: [DONE]\n\n"

    return Response(generate(), mimetype="text/event-stream")


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


@api_bp.route("/sessions/<session_id>/clear-debug", methods=["POST"])
@require_auth
def clear_session_debug(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    
    session.clear_debug()
    session_manager.save_session(session_id)
    
    return jsonify({"status": "cleared", "session_id": session_id})


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


@admin_bp.route("/config", methods=["GET"])
@require_auth
def get_config():
    return jsonify({
        "api_key": config.api_key,
        "default_provider": config.default_provider,
        "providers": config.providers,
        "default_models": config.llm.get("default_models", {}),
    })


@admin_bp.route("/config", methods=["POST"])
@require_auth
def save_config():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    try:
        if "api_key" in data:
            config._config["auth"]["api_key"] = data["api_key"]
        if "default_provider" in data:
            config._config["llm"]["default_provider"] = data["default_provider"]
        if "providers" in data:
            config._config["llm"]["providers"] = data["providers"]
        if "default_models" in data:
            config._config["llm"]["default_models"] = data["default_models"]
        
        config.save()
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/config/validate", methods=["POST"])
@require_auth
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
@require_auth
def list_models(provider_name: str):
    provider_config = config.get_provider_config(provider_name)
    if not provider_config:
        return jsonify({"error": f"Provider '{provider_name}' not found in config", "available": list(config.providers.keys())}), 400

    provider_config = provider_config.copy()
    default_model = config.get_default_model(provider_name)
    if default_model:
        provider_config["model"] = default_model
    elif "model" not in provider_config:
        provider_config["model"] = "gpt-4o-mini"

    try:
        provider = ProviderFactory.create(provider_name, provider_config)
        if hasattr(provider, "list_models"):
            models = provider.list_models()
            return jsonify({"models": sorted(models)})
        return jsonify({"models": sorted([provider.model]) if provider.model else []})
    except ValueError as e:
        return jsonify({"error": f"ValueError: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"error": f"Error: {str(e)}", "type": type(e).__name__}), 500


@admin_bp.route("/context", methods=["GET"])
@require_auth
def list_context_files():
    files = config.get_context_files()
    enabled = config.get_enabled_context_files()
    return jsonify({"files": files, "enabled_files": enabled})


@admin_bp.route("/context", methods=["POST"])
@require_auth
def create_context_file():
    data = request.get_json()
    if not data or "filename" not in data:
        return jsonify({"error": "Missing filename"}), 400

    filename = data["filename"].strip()
    content = data.get("content", "")

    try:
        config.create_context_file(filename, content)
        return jsonify({"status": "created", "filename": filename})
    except FileExistsError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/context/enabled", methods=["GET"])
@require_auth
def get_enabled_context_files():
    enabled = config.get_enabled_context_files()
    return jsonify({"enabled_files": enabled})


@admin_bp.route("/context/enabled", methods=["POST"])
@require_auth
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
@require_auth
def get_context_file(filename: str):
    content = config.get_context_file(filename)
    if content is None:
        return jsonify({"error": "File not found"}), 404
    return jsonify({"filename": filename, "content": content})


@admin_bp.route("/context/<filename>", methods=["POST"])
@require_auth
def save_context_file(filename: str):
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "Missing content"}), 400

    try:
        config.save_context_file(filename, data["content"])
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/context/<filename>", methods=["DELETE"])
@require_auth
def delete_context_file(filename: str):
    try:
        config.delete_context_file(filename)
        return jsonify({"status": "deleted"})
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/context/<filename>/rename", methods=["POST"])
@require_auth
def rename_context_file(filename: str):
    data = request.get_json()
    if not data or "new_name" not in data:
        return jsonify({"error": "Missing new_name"}), 400

    new_name = data["new_name"].strip()
    if not new_name:
        return jsonify({"error": "New name cannot be empty"}), 400

    try:
        config.rename_context_file(filename, new_name)
        return jsonify({"status": "renamed", "old_name": filename, "new_name": new_name})
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except FileExistsError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
