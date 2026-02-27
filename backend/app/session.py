from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from app.llm.base import Message
from app.storage import storage


@dataclass
class Session:
    session_id: str
    messages: list[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    provider: str = ""
    model: str = ""
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    user_settings: dict[str, Any] = field(default_factory=dict)

    def add_user_message(self, content: str, usage: dict[str, int] | None = None) -> None:
        msg = Message(role="user", content=content, usage=usage or {})
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def add_assistant_message(self, content: str, usage: dict[str, int] | None = None, debug: dict | None = None, model: str | None = None) -> None:
        msg = Message(role="assistant", content=content, usage=usage or {}, debug=debug, model=model)
        self.messages.append(msg)
        if usage:
            self.total_tokens += usage.get("total_tokens", 0)
            self.input_tokens += usage.get("input_tokens", 0)
            self.output_tokens += usage.get("output_tokens", 0)
        self.updated_at = datetime.now()

    def add_error_message(self, content: str, debug: dict | None = None, model: str | None = None) -> None:
        msg = Message(role="error", content=content, usage={}, debug=debug, model=model)
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def set_provider_model(self, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model

    def get_current_usage(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }

    def add_note_message(self, content: str, usage: dict[str, int] | None = None) -> None:
        msg = Message(role="note", content=content, usage=usage or self.get_current_usage())
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def add_info_message(self, content: str) -> None:
        msg = Message(role="info", content=content, usage={})
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def add_summary_message(
        self,
        content: str,
        summarized_indices: list[int],
        usage: dict[str, int] | None = None,
        debug: dict | None = None,
        model: str | None = None,
    ) -> None:
        msg = Message(
            role="summary",
            content=content,
            usage=usage or {},
            debug=debug,
            model=model,
            summary_of=summarized_indices,
        )
        self.messages.append(msg)
        if usage:
            self.total_tokens += usage.get("total_tokens", 0)
            self.input_tokens += usage.get("input_tokens", 0)
            self.output_tokens += usage.get("output_tokens", 0)
        self.updated_at = datetime.now()

    def get_messages_for_llm(self) -> list[Message]:
        """Вернуть сообщения для LLM: summary + последний user message (после summary)"""
        if not self.messages:
            return []

        last_summary_idx = None
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].role == "summary":
                last_summary_idx = i
                break

        if last_summary_idx is None:
            return [m for m in self.messages if not m.disabled]

        # summary всегда первым
        result = [self.messages[last_summary_idx]]
        
        # Ищем последний user message ПОСЛЕ summary
        for i in range(len(self.messages) - 1, last_summary_idx, -1):
            if self.messages[i].role == "user" and not self.messages[i].disabled:
                result.append(self.messages[i])
                break

        return result

    def get_active_message_count(self) -> int:
        return sum(1 for m in self.messages if m.role in ("user", "assistant"))

    def get_user_message_count_since_summary(self) -> int:
        """Количество сообщений пользователя после последнего summary"""
        # Ищем последний summary
        last_summary_idx = None
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].role == "summary":
                last_summary_idx = i
                break
        
        if last_summary_idx is None:
            # Нет summary - считаем все сообщения пользователя
            return sum(1 for m in self.messages if m.role == "user")
        
        # Считаем user сообщения после summary
        return sum(1 for m in self.messages[last_summary_idx + 1:] if m.role == "user")

    def get_messages_before_last_user(self) -> list[Message]:
        """Сообщения для суммаризации - предыдущая summary + все user/assistant ПОСЛЕ неё (до последнего user)"""
        # Ищем последний summary
        last_summary_idx = None
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].role == "summary":
                last_summary_idx = i
                break
        
        result = []
        
        # Добавляем предыдущую summary если есть
        if last_summary_idx is not None:
            result.append(self.messages[last_summary_idx])
            msgs = self.messages[last_summary_idx + 1:]
        else:
            msgs = self.messages
        
        # Фильтруем user/assistant
        active_msgs = [m for m in msgs if m.role in ("user", "assistant")]
        # Возвращаем все КРОМЕ последнего user
        result.extend(active_msgs[:-1] if active_msgs else [])
        return result

    def get_summarizable_messages(self) -> list[Message]:
        return [m for m in self.messages if m.role in ("user", "assistant")]

    def get_oldest_message_age_minutes(self) -> int:
        """Возраст самого старого сообщения в минутах (после последнего summary)"""
        last_summary_idx = None
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].role == "summary":
                last_summary_idx = i
                break

        messages_to_check = self.messages[last_summary_idx + 1:] if last_summary_idx else self.messages
        active_msgs = [m for m in messages_to_check if m.role in ("user", "assistant", "summary")]

        if not active_msgs:
            return 0

        oldest = min(active_msgs, key=lambda m: m.created_at)
        now = datetime.now()
        delta = now - oldest.created_at
        return int(delta.total_seconds() / 60)

    def get_context_tokens_estimate(self, model: str | None = None) -> int:
        """Оценка количества токенов в контексте (после последнего summary)"""
        from app.config import config

        last_summary_idx = None
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].role == "summary":
                last_summary_idx = i
                break

        messages_to_check = self.messages[last_summary_idx + 1:] if last_summary_idx else self.messages

        total_chars = sum(len(m.content) for m in messages_to_check if m.role in ("user", "assistant", "system", "summary"))
        chars_per_token = 4
        return total_chars // chars_per_token

    def get_context_usage_percent(self, model: str | None = None) -> float:
        """Процент использования контекстного окна"""
        from app.config import config

        target_model = model or self.model or config.summarizer_model
        context_window = config.get_context_window(target_model)
        tokens = self.get_context_tokens_estimate(target_model)

        if context_window == 0:
            return 0.0

        return (tokens / context_window) * 100

    def delete_message(self, index: int) -> bool:
        """Удалить сообщение по индексу"""
        if 0 <= index < len(self.messages):
            del self.messages[index]
            self.updated_at = datetime.now()
            return True
        return False

    def toggle_message(self, index: int) -> bool:
        """Переключить состояние disabled сообщения"""
        if 0 <= index < len(self.messages):
            self.messages[index].disabled = not self.messages[index].disabled
            self.updated_at = datetime.now()
            return True
        return False

    def to_markdown(self) -> str:
        lines = [f"# Session: {self.session_id}", f"Created: {self.created_at.isoformat()}", ""]
        
        if self.provider or self.model:
            lines.append(f"**Provider:** {self.provider or 'default'}")
            lines.append(f"**Model:** {self.model or 'default'}")
            lines.append(f"**Total tokens:** {self.total_tokens}")
            lines.append("")

        for msg in self.messages:
            role_emoji = "👤" if msg.role == "user" else "🤖"
            lines.append(f"## {role_emoji} {msg.role.capitalize()}")
            lines.append("")
            lines.append(msg.content)
            lines.append("")

        return "\n".join(lines)

    def clear(self) -> None:
        self.messages = []
        self.total_tokens = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.updated_at = datetime.now()

    def clear_debug(self) -> None:
        for msg in self.messages:
            msg.debug = None
        self.updated_at = datetime.now()

    def save(self) -> None:
        storage.save_session(self)


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._load_sessions()

    def _load_sessions(self) -> None:
        sessions = storage.list_sessions()
        for session_info in sessions:
            session_id = session_info["session_id"]
            data = storage.load_session(session_id)
            if data:
                messages = [
                    Message(
                        role=m["role"],
                        content=m["content"],
                        usage=m.get("usage", {}),
                        debug=m.get("debug"),
                        model=m.get("model"),
                        summary_of=m.get("summary_of"),
                        created_at=datetime.fromisoformat(m["created_at"]) if m.get("created_at") else datetime.now(),
                        disabled=m.get("disabled", False),
                    )
                    for m in data.get("messages", [])
                ]
                session = Session(
                    session_id=session_id,
                    messages=messages,
                    created_at=datetime.fromisoformat(data.get("created_at", datetime.now().isoformat())),
                    updated_at=datetime.fromisoformat(data.get("updated_at", datetime.now().isoformat())),
                    provider=data.get("provider", ""),
                    model=data.get("model", ""),
                    total_tokens=data.get("total_tokens", 0),
                    input_tokens=data.get("input_tokens", 0),
                    output_tokens=data.get("output_tokens", 0),
                    user_settings=data.get("user_settings", {}),
                )
                self._sessions[session_id] = session

    def get_session(self, session_id: str) -> Session:
        if session_id not in self._sessions:
            self._sessions[session_id] = Session(session_id=session_id)
        return self._sessions[session_id]

    def reset_session(self, session_id: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id].clear()
            self._sessions[session_id].save()

    def delete_session(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
        return storage.delete_session(session_id)

    def rename_session(self, old_id: str, new_id: str) -> bool:
        if old_id not in self._sessions:
            return False
        
        # Update in-memory session
        session = self._sessions.pop(old_id)
        session.session_id = new_id
        self._sessions[new_id] = session
        
        # Update storage
        return storage.rename_session(old_id, new_id)

    def save_session(self, session_id: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id].save()

    def list_sessions(self) -> list[dict]:
        return storage.list_sessions()

    def get_session_data(self, session_id: str) -> Optional[dict]:
        return storage.load_session(session_id)

    def export_all(self) -> dict:
        return storage.export_all()

    def import_session(self, session_data: dict) -> str:
        session_id = storage.import_session(session_data)
        data = storage.load_session(session_id)
        if data:
            messages = [
                Message(
                    role=m["role"],
                    content=m["content"],
                    usage=m.get("usage", {}),
                    debug=m.get("debug"),
                    model=m.get("model"),
                    summary_of=m.get("summary_of"),
                    created_at=datetime.fromisoformat(m["created_at"]) if m.get("created_at") else datetime.now(),
                )
                for m in data.get("messages", [])
            ]
            session = Session(
                session_id=session_id,
                messages=messages,
                created_at=datetime.fromisoformat(data.get("created_at", datetime.now().isoformat())),
                updated_at=datetime.fromisoformat(data.get("updated_at", datetime.now().isoformat())),
                provider=data.get("provider", ""),
                model=data.get("model", ""),
                total_tokens=data.get("total_tokens", 0),
                input_tokens=data.get("input_tokens", 0),
                output_tokens=data.get("output_tokens", 0),
                user_settings=data.get("user_settings", {}),
            )
            self._sessions[session_id] = session
        return session_id


session_manager = SessionManager()
