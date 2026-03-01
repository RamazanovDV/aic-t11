import json
import re

import requests
from flask import Blueprint, jsonify, render_template, request, Response

from app.config import config
from app.context import get_system_prompt
from app.llm import ProviderFactory
from app.llm.providers import ContextLengthExceededError
from app.session import session_manager
from app import summarizer

api_bp = Blueprint("api", __name__)
admin_bp = Blueprint("admin", __name__)


def get_sticky_notes_prompt(facts: dict[str, str]) -> str:
    """Сформировать промпт с фактами для sticky notes"""
    facts_extraction = config.get_context_file("FACTS_EXTRACTION.md") or ""
    
    result = ""
    
    if facts_extraction:
        result += f"\n\n{facts_extraction}\n"
    
    if facts:
        facts_text = "\nТекущие факты о пользователе и сессии:\n"
        for key, value in facts.items():
            facts_text += f"- {key}: {value}\n"
        result += facts_text
    
    return result


def extract_facts_from_response(content: str) -> tuple[str | None, str]:
    """Извлечь JSON с фактами из ответа модели и очистить контент от JSON блока"""
    cleaned_content = content
    
    json_pattern = r"```json\s*([\s\S]*?)\s*```"
    match = re.search(json_pattern, content)
    if match:
        facts = match.group(1).strip()
        cleaned_content = content[:match.start()] + content[match.end():]
        return facts, cleaned_content.strip()
    
    json_pattern_short = r"\{\s*[\"а-яА-Яa-zA-Z].*\}"
    for line in content.split("\n"):
        stripped = line.strip()
        if re.match(json_pattern_short, stripped) and ":" in stripped:
            facts = stripped
            cleaned_content = content.replace(line, "").strip()
            return facts, cleaned_content

    return None, cleaned_content


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


@api_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@api_bp.route("/note", methods=["POST"])
@require_auth
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

    current_count = session.get_active_message_count()
    session.add_user_message(user_message)

    should_summarize_result, summarize_reason = summarizer.should_summarize(session, current_count)
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

    if session.user_settings.get("context_optimization") == "sticky_notes":
        system_prompt += get_sticky_notes_prompt(session.facts)

    try:
        llm_messages = session.get_messages_for_llm()
        session_manager.save_session(session_id)
        response = provider.chat(llm_messages, system_prompt, debug=debug_mode)
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

    debug_info = None
    if debug_mode:
        debug_info = {
            "request": response.debug_request,
            "response": response.debug_response,
        }

    session.add_assistant_message(response.content, response.usage, debug=debug_info, model=response.model)

    message_for_user = response.content
    
    if session.user_settings.get("context_optimization") == "sticky_notes":
        facts_json, cleaned_content = extract_facts_from_response(response.content)
        if facts_json:
            session.update_facts(facts_json)
        if cleaned_content:
            message_for_user = cleaned_content

    session_manager.save_session(session_id)

    disabled_indices = [i for i, m in enumerate(session.messages) if m.disabled]

    result = {
        "message": message_for_user,
        "session_id": session_id,
        "model": response.model,
        "usage": response.usage,
        "total_tokens": session.total_tokens,
        "disabled_indices": disabled_indices,
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

    needs_summarization, summarize_reason = summarizer.should_summarize(session, 0)

    def generate():
        nonlocal needs_summarization

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
            session.add_user_message(user_message)

        if provider_name and model:
            session.set_provider_model(provider_name, model)
        elif provider_name and not session.provider:
            session.set_provider_model(provider_name, config.get_default_model(provider_name))

        system_prompt = get_system_prompt()

        if session.user_settings.get("context_optimization") == "sticky_notes":
            system_prompt += get_sticky_notes_prompt(session.facts)

        # Используем get_messages_for_llm() для поддержки скользящего окна
        llm_messages = session.get_messages_for_llm()
        session_manager.save_session(session_id)

        # Формируем сообщения для LLM
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
            # Конвертируем в Message объекты
            from app.llm.base import Message
            llm_msgs = [Message(role=m["role"], content=m["content"], usage={}) for m in formatted_messages]
            for chunk in provider.stream_chat(llm_msgs, None, debug=debug_mode):
                if chunk.is_final:
                    total_usage = chunk.usage
                    debug_response = {"usage": total_usage, "model": provider.model, "content_length": len(full_content)}
                    break

                full_content = chunk.content
                yield f"data: {json.dumps({'content': full_content, 'done': False})}\n\n"

            if not full_content:
                raise Exception("Empty response from provider")

            debug_info = {"request": debug_request, "response": debug_response} if debug_mode else None
            
            # Сохраняем сообщения в сессию
            if needs_summarization:
                # При суммаризации user message ещё не был добавлен
                session.add_user_message(user_msg_for_llm)
            session.add_assistant_message(full_content, total_usage, debug=debug_info, model=provider.model)

            content_for_user = full_content
            
            if session.user_settings.get("context_optimization") == "sticky_notes":
                facts_json, cleaned_content = extract_facts_from_response(full_content)
                if facts_json:
                    session.update_facts(facts_json)
                if cleaned_content:
                    content_for_user = cleaned_content

            session_manager.save_session(session_id)

            disabled_indices = [i for i, m in enumerate(session.messages) if m.disabled]
            yield f"data: {json.dumps({'content': content_for_user, 'done': True, 'usage': total_usage, 'debug': {'request': debug_request, 'response': debug_response}, 'disabled_indices': disabled_indices})}\n\n"

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
    session = session_manager.get_session(session_id)
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
        "user_settings": session.user_settings,
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
    })


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


@api_bp.route("/sessions/<session_id>/copy", methods=["POST"])
@require_auth
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


@api_bp.route("/sessions/<session_id>/clear-debug", methods=["POST"])
@require_auth
def clear_session_debug(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    
    session.clear_debug()
    session_manager.save_session(session_id)
    
    return jsonify({"status": "cleared", "session_id": session_id})


@api_bp.route("/sessions/<session_id>/messages/<int:index>", methods=["DELETE"])
@require_auth
def delete_message(session_id: str, index: int):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    
    if session.delete_message(index):
        session_manager.save_session(session_id)
        return jsonify({"status": "deleted", "index": index})
    
    return jsonify({"error": "Invalid message index"}), 400


@api_bp.route("/sessions/<session_id>/messages/<int:index>/toggle", methods=["POST"])
@require_auth
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
@require_auth
def get_context_settings(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    optimization = session.user_settings.get("context_optimization", "none")
    
    summarization_enabled = session.user_settings.get("summarization_enabled", False)
    summarize_after_n = session.user_settings.get("summarize_after_n", config.default_messages_interval)
    summarize_after_minutes = session.user_settings.get("summarize_after_minutes", 0)
    summarize_context_percent = session.user_settings.get("summarize_context_percent", 0)

    sliding_window_type = session.user_settings.get("sliding_window_type", "messages")
    sliding_window_limit = session.user_settings.get("sliding_window_limit", 10)

    sticky_notes_limit = session.user_settings.get("sticky_notes_limit", 6)

    return jsonify({
        "context_optimization": optimization,
        "summarization_enabled": summarization_enabled,
        "summarize_after_n": summarize_after_n,
        "summarize_after_minutes": summarize_after_minutes,
        "summarize_context_percent": summarize_context_percent,
        "sliding_window_type": sliding_window_type,
        "sliding_window_limit": sliding_window_limit,
        "sticky_notes_limit": sticky_notes_limit,
        "default_interval": config.default_messages_interval,
    })


@api_bp.route("/sessions/<session_id>/context-settings", methods=["POST"])
@require_auth
def set_context_settings(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    if "context_optimization" in data:
        opt = data["context_optimization"]
        if opt in ("none", "summarization", "sliding_window", "sticky_notes"):
            if opt != "sticky_notes":
                session.facts = {}
            session.user_settings["context_optimization"] = opt

    if "summarization_enabled" in data:
        session.user_settings["summarization_enabled"] = bool(data["summarization_enabled"])

    if "summarize_after_n" in data:
        interval = int(data["summarize_after_n"])
        if interval < 5:
            interval = 5
        if interval > 100:
            interval = 100
        session.user_settings["summarize_after_n"] = interval

    if "summarize_after_minutes" in data:
        minutes = int(data["summarize_after_minutes"])
        if minutes < 0:
            minutes = 0
        if minutes > 10080:
            minutes = 10080
        session.user_settings["summarize_after_minutes"] = minutes

    if "summarize_context_percent" in data:
        percent = int(data["summarize_context_percent"])
        if percent < 0:
            percent = 0
        if percent > 100:
            percent = 100
        session.user_settings["summarize_context_percent"] = percent

    if "sliding_window_type" in data:
        wtype = data["sliding_window_type"]
        if wtype in ("messages", "tokens"):
            session.user_settings["sliding_window_type"] = wtype

    if "sliding_window_limit" in data:
        limit = int(data["sliding_window_limit"])
        if limit < 1:
            limit = 1
        if limit > 1000:
            limit = 1000
        session.user_settings["sliding_window_limit"] = limit

    if "sticky_notes_limit" in data:
        limit = int(data["sticky_notes_limit"])
        if limit < 1:
            limit = 1
        if limit > 50:
            limit = 50
        session.user_settings["sticky_notes_limit"] = limit

    session_manager.save_session(session_id)

    return jsonify({"status": "saved"})


@api_bp.route("/sessions/<session_id>/summarize", methods=["POST"])
@require_auth
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
@require_auth
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
@require_auth
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
@require_auth
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
@require_auth
def delete_checkpoint(session_id: str, checkpoint_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    if session.delete_checkpoint(checkpoint_id):
        session_manager.save_session(session_id)
        return jsonify({"status": "deleted", "checkpoint_id": checkpoint_id})

    return jsonify({"error": "Checkpoint not found"}), 404


@api_bp.route("/sessions/<session_id>/checkpoints/<checkpoint_id>/branch", methods=["POST"])
@require_auth
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
@require_auth
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
@require_auth
def switch_branch(session_id: str, branch_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    if session.switch_branch(branch_id):
        session_manager.save_session(session_id)
        return jsonify({"status": "switched", "current_branch": session.current_branch})

    return jsonify({"error": "Branch not found"}), 404


@api_bp.route("/sessions/<session_id>/branches/<branch_id>/rename", methods=["POST"])
@require_auth
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
@require_auth
def delete_branch(session_id: str, branch_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    if session.delete_branch(branch_id):
        session_manager.save_session(session_id)
        return jsonify({"status": "deleted", "branch_id": branch_id})

    return jsonify({"error": "Branch not found or cannot be deleted"}), 404


@api_bp.route("/sessions/<session_id>/branches/<branch_id>/reset", methods=["POST"])
@require_auth
def reset_branch(session_id: str, branch_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    if session.reset_branch_to_checkpoint(branch_id):
        session_manager.save_session(session_id)
        return jsonify({"status": "reset", "branch_id": branch_id})

    return jsonify({"error": "Branch not found or has no parent checkpoint"}), 404


@api_bp.route("/sessions/<session_id>/tree", methods=["GET"])
@require_auth
def get_session_tree(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    return jsonify(session.get_tree())


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
            config._config["default_provider"] = data["default_provider"]
        if "providers" in data:
            config._config["providers"] = data["providers"]
        if "summarizer" in data:
            config._config["summarizer"] = data["summarizer"]
        if "summarization" in data:
            if "summarization" not in config._config:
                config._config["summarization"] = {}
            config._config["summarization"].update(data["summarization"])
        
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
def list_provider_models_from_catalog(provider_name: str):
    """Список доступных моделей для конкретного провайдера из справочника"""
    models = config.models
    provider_models = {
        name: info for name, info in models.items() 
        if info.get("enabled", True) and (info.get("provider") == provider_name or info.get("provider") == "*")
    }
    return jsonify({"models": sorted(provider_models.keys())})


@admin_bp.route("/models/fetch", methods=["POST"])
@require_auth
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
                    if not existing:
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
    
    return jsonify({
        "status": "completed",
        "results": results,
        "models": config.models,
    })


@admin_bp.route("/providers/fetch-models", methods=["POST"])
@require_auth
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



@admin_bp.route("/models", methods=["GET"])
@require_auth
def list_model_catalog():
    models = config.models
    return jsonify({"models": models})


@admin_bp.route("/models/available", methods=["GET"])
@require_auth
def list_available_models():
    """Список доступных (включённых) моделей для выбора"""
    models = config.models
    available = {name: info for name, info in models.items() if info.get("enabled", True)}
    return jsonify({"models": available})


@admin_bp.route("/models", methods=["POST"])
@require_auth
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
@require_auth
def delete_model(model_name: str):
    if config.delete_model(model_name):
        return jsonify({"status": "deleted", "model": model_name})
    return jsonify({"error": "Cannot delete default model or model not found"}), 400
