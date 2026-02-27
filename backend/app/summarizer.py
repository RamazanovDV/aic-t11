from app.config import config
from app.llm.base import Message
from app.llm import ProviderFactory


def get_summarizer_prompt() -> str:
    prompt_file = config.summarizer_prompt_source
    return config.get_context_file(prompt_file) or ""


def summarize_messages(messages: list[Message], debug: bool = False) -> tuple[str, dict]:
    if not messages:
        return "", {}

    formatted = []
    for i, msg in enumerate(messages):
        role_label = "Пользователь" if msg.role == "user" else "AI"
        formatted.append(f"[{i+1}] {role_label}: {msg.content}")

    dialog_text = "\n\n".join(formatted)
    summarizer_prompt = get_summarizer_prompt()

    if not summarizer_prompt:
        summarizer_prompt = "Создай краткое резюме следующего диалога:"

    full_prompt = f"{summarizer_prompt}\n\n## Диалог\n{dialog_text}"

    provider_config = config.get_provider_config(config.summarizer_provider)
    provider_config["model"] = config.summarizer_model
    provider_config["temperature"] = config.summarizer_temperature
    if "timeout" not in provider_config:
        provider_config["timeout"] = config.timeout

    provider = ProviderFactory.create(config.summarizer_provider, provider_config)

    summary_messages = [Message(role="user", content=full_prompt, usage={})]
    response = provider.chat(summary_messages, "", debug=debug)

    debug_info = {}
    if debug:
        debug_info = {
            "summarized_count": len(messages),
            "summarized_messages": formatted,
            "model": config.summarizer_model,
            "provider": config.summarizer_provider,
            "request": response.debug_request if hasattr(response, 'debug_request') else {},
            "response": response.debug_response if hasattr(response, 'debug_response') else {},
        }

    return response.content, debug_info


def should_summarize(session, current_message_count: int) -> bool:
    enabled = session.user_settings.get("summarization_enabled", False)
    if not enabled:
        return False

    interval = session.user_settings.get("summarize_after_n", config.default_messages_interval)
    count_since_summary = session.get_user_message_count_since_summary()
    print(f"[DEBUG summarizer] enabled={enabled}, interval={interval}, count_since_summary={count_since_summary}")
    return count_since_summary >= interval
