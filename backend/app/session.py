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
        self.updated_at = datetime.now()

    def add_error_message(self, content: str, debug: dict | None = None, model: str | None = None) -> None:
        msg = Message(role="error", content=content, usage={}, debug=debug, model=model)
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def set_provider_model(self, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model

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
                user_settings=data.get("user_settings", {}),
            )
            self._sessions[session_id] = session
        return session_id


session_manager = SessionManager()
