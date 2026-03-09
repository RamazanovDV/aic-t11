"""Unified LLM client and prompt builder for Synth."""

from typing import Generator, Any
from app.llm.base import Message
from app.llm import ProviderFactory
from app.config import config
from app import tsm


class PromptBuilder:
    """Унифицированный построитель промтов для LLM."""
    
    def __init__(self, session, user_id: str | None = None):
        """Инициализировать PromptBuilder.
        
        Args:
            session: объект сессии
            user_id: ID пользователя (опционально)
        """
        self.session = session
        self.user_id = user_id
    
    def build_system_prompt(self) -> str:
        """Собрать базовый system prompt из компонентов.
        
        Returns:
            Полный system prompt для LLM
        """
        from app.context import get_system_prompt
        from app.routes import get_profile_prompt, get_project_prompt, get_status_prompt, should_show_interview
        from app.routes import get_interview_prompt
        
        system_prompt = get_system_prompt()
        system_prompt += get_profile_prompt(self.session, self.user_id)
        system_prompt += get_project_prompt(self.session)
        system_prompt += get_status_prompt(self.session)
        
        if should_show_interview(self.session, self.user_id):
            system_prompt += get_interview_prompt()
        
        return system_prompt
    
    def build_messages(self, include_user_message: str = None) -> list[Message]:
        """Собрать список сообщений для LLM.
        
        Args:
            include_user_message: опциональное сообщение от пользователя для добавления
            
        Returns:
            Список Message объектов для отправки провайдеру
        """
        llm_messages = self.session.get_messages_for_llm()
        
        formatted_messages = []
        for msg in llm_messages:
            if msg.role == "summary":
                summary_text = f"До этого вы обсудили следующее:\n{msg.content}"
                if formatted_messages and formatted_messages[0]["role"] == "system":
                    formatted_messages[0]["content"] += f"\n\n{summary_text}"
                else:
                    formatted_messages.insert(0, {"role": "system", "content": summary_text})
            elif msg.role in ("user", "assistant"):
                formatted_messages.append({"role": msg.role, "content": msg.content})
        
        if include_user_message:
            formatted_messages.append({"role": "user", "content": include_user_message})
        
        return [Message(role=m["role"], content=m["content"], usage={}) for m in formatted_messages]
    
    def build_error_reminder(self, error_msg: str, current_state: str, allowed_transitions: list) -> str:
        """Создать напоминание об ошибке перехода состояния.
        
        Args:
            error_msg: текст ошибки
            current_state: текущее состояние
            allowed_transitions: список допустимых переходов
            
        Returns:
            Текст напоминания для добавления к сообщению
        """
        allowed_str = ", ".join(allowed_transitions) if allowed_transitions else "нет"
        
        return (
            f"\n\n⚠️ ОШИБКА ПЕРЕХОДА СОСТОЯНИЯ! ⚠️\n"
            f"Ты попытался перейти в недопустимое состояние.\n\n"
            f"Ошибка: {error_msg}\n\n"
            f"Текущее состояние: {current_state}\n"
            f"Допустимые переходы из '{current_state}': {allowed_str}\n\n"
            f"ОБЪЯСНИ пользователю почему этот переход невозможен "
            f"и предложи допустимый следующий шаг."
        )


class LLMClient:
    """Унифицированный клиент для отправки к LLM провайдерам."""
    
    def __init__(self, provider_name: str, model: str | None = None):
        """Инициализировать LLMClient.
        
        Args:
            provider_name: имя провайдера (например, 'openai', 'anthropic', 'minimax')
            model: модель для использования (опционально)
        """
        self.provider_name = provider_name
        self.model = model
        provider_config = config.get_provider_config(provider_name)
        if model:
            provider_config["model"] = model
        self.provider = ProviderFactory.create(provider_name, provider_config)
    
    def send(self, 
             messages: list[Message], 
             system_prompt: str,
             debug: bool = False) -> Any:
        """Отправить сообщение провайдеру (non-streaming).
        
        Args:
            messages: список Message объектов
            system_prompt: system prompt
            debug: режим отладки
            
        Returns:
            LLMResponse объект
        """
        return self.provider.chat(messages, system_prompt, debug=debug)
    
    def stream(self, 
               messages: list[Message], 
               system_prompt: str = None,
               debug: bool = False) -> Generator:
        """Отправить сообщение провайдеру (streaming).
        
        Args:
            messages: список Message объектов  
            system_prompt: system prompt (опционально, для некоторых провайдеров)
            debug: режим отладки
            
        Yields:
            Чанки ответа от LLM
        """
        for chunk in self.provider.stream_chat(messages, system_prompt, debug=debug):
            yield chunk


def create_llm_client(session, provider_name: str | None = None, model: str | None = None) -> LLMClient:
    """Создать LLMClient на основе настроек сессии.
    
    Args:
        session: объект сессии
        provider_name: имя провайдера (опционально, берется из сессии)
        model: модель (опционально, берется из сессии)
        
    Returns:
        LLMClient instance
    """
    if not provider_name:
        provider_name = session.provider or config.default_provider
    if not model:
        model = session.model or config.get_default_model(provider_name)
    
    return LLMClient(provider_name, model)


def create_prompt_builder(session, user_id: str | None = None) -> PromptBuilder:
    """Создать PromptBuilder для сессии.
    
    Args:
        session: объект сессии
        user_id: ID пользователя (опционально)
        
    Returns:
        PromptBuilder instance
    """
    return PromptBuilder(session, user_id)
