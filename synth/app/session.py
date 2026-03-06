from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from app.llm.base import Message
from app.storage import storage


def _clean_message_content(content: str) -> str:
    """Удалить JSON-блок статуса из содержимого сообщения"""
    if not content:
        return content
    
    try:
        from app import status_validator
        _, cleaned = status_validator.validate_status_block(content)
        return cleaned if cleaned else content
    except Exception:
        return content


@dataclass
class Checkpoint:
    id: str
    name: str
    branch_id: str
    message_count: int
    summary: str | None = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Branch:
    id: str
    name: str
    parent_branch: str | None = None
    parent_checkpoint: str | None = None
    created_at: datetime = field(default_factory=datetime.now)


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
    session_settings: dict[str, Any] = field(default_factory=dict)
    branches: list[Branch] = field(default_factory=list)
    checkpoints: list[Checkpoint] = field(default_factory=list)
    current_branch: str = "main"
    status: dict[str, Any] = field(default_factory=lambda: {
        "task_name": "разговор на свободную тему",
        "state": None,
        "progress": None,
        "project": None,
        "updated_project_info": None,
        "current_task_info": None,
        "approved_plan": None,
        "already_done": None,
        "currently_doing": None,
        "user_info": None,
    })
    owner_id: str | None = None
    access: str = "owner"

    def can_access(self, user_id: str | None, user_role: str = "user") -> bool:
        if user_role == "admin":
            return True
        if self.access == "public":
            return True
        if self.access == "team":
            return True
        if self.access == "owner" and self.owner_id == user_id:
            return True
        return False

    def _ensure_main_branch(self) -> None:
        """Ensure main branch exists"""
        if not any(b.id == "main" for b in self.branches):
            self.branches.append(Branch(id="main", name="main"))
        if self.current_branch not in [b.id for b in self.branches]:
            self.current_branch = "main"

    def add_user_message(self, content: str, usage: dict[str, int] | None = None, source: str | None = None) -> None:
        msg = Message(role="user", content=content, usage=usage or {}, branch_id=self.current_branch, source=source)
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def add_assistant_message(self, content: str, usage: dict[str, int] | None = None, debug: dict | None = None, model: str | None = None) -> None:
        msg = Message(role="assistant", content=content, usage=usage or {}, debug=debug, model=model, branch_id=self.current_branch)
        self.messages.append(msg)
        if usage:
            self.total_tokens += usage.get("total_tokens", 0)
            self.input_tokens += usage.get("input_tokens", 0)
            self.output_tokens += usage.get("output_tokens", 0)
        self.updated_at = datetime.now()

    def update_status(self, status_data: dict[str, Any]) -> None:
        """Обновить статус задачи из данных, полученных от модели"""
        if not status_data:
            return

        valid_states = {"planning", "execution", "validation", "done"}

        self.status = {
            "task_name": status_data.get("task_name", "разговор на свободной теме"),
            "state": status_data.get("state") if status_data.get("state") in valid_states else None,
            "progress": status_data.get("progress"),
            "project": status_data.get("project"),
            "updated_project_info": status_data.get("updated_project_info"),
            "current_task_info": status_data.get("current_task_info"),
            "approved_plan": status_data.get("approved_plan"),
            "already_done": status_data.get("already_done"),
            "currently_doing": status_data.get("currently_doing"),
            "user_info": status_data.get("user_info"),
            "subtasks": status_data.get("subtasks", []),
        }
        self.updated_at = datetime.now()

    def add_error_message(self, content: str, debug: dict | None = None, model: str | None = None) -> None:
        msg = Message(role="error", content=content, usage={}, debug=debug, model=model, branch_id=self.current_branch)
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
        msg = Message(role="note", content=content, usage=usage or self.get_current_usage(), branch_id=self.current_branch)
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def add_info_message(self, content: str) -> None:
        msg = Message(role="info", content=content, usage={}, branch_id=self.current_branch)
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
            branch_id=self.current_branch,
        )
        self.messages.append(msg)
        if usage:
            self.total_tokens += usage.get("total_tokens", 0)
            self.input_tokens += usage.get("input_tokens", 0)
            self.output_tokens += usage.get("output_tokens", 0)
        self.updated_at = datetime.now()

    def get_messages_for_llm(self) -> list[Message]:
        """Вернуть сообщения для LLM с учётом оптимизации контекста"""
        if not self.messages:
            return []

        optimization = self.session_settings.get("context_optimization", "none")

        if optimization == "sliding_window":
            return self._get_messages_sliding_window()

        if optimization == "summarization":
            return self._get_messages_with_summarization()

        if optimization == "sticky_notes":
            return self._get_messages_sticky_notes()

        return [m for m in self.messages if not m.disabled]

    def _get_messages_with_summarization(self) -> list[Message]:
        """Сообщения для LLM с суммаризацией (существующая логика)"""
        last_summary_idx = None
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].role == "summary":
                last_summary_idx = i
                break

        if last_summary_idx is None:
            return [m for m in self.messages if not m.disabled]

        result = [self.messages[last_summary_idx]]

        for i in range(len(self.messages) - 1, last_summary_idx, -1):
            if self.messages[i].role == "user" and not self.messages[i].disabled:
                result.append(self.messages[i])
                break

        return result

    def _get_messages_sticky_notes(self) -> list[Message]:
        """Сообщения для LLM со sticky notes (факты + N последних сообщений)"""
        sticky_limit = self.session_settings.get("sticky_notes_limit", 6)

        active_messages = [m for m in self.messages if not m.disabled and m.role in ("user", "assistant", "system")]

        if not active_messages:
            return []

        last_n_messages = active_messages[-sticky_limit:] if len(active_messages) > sticky_limit else active_messages

        return last_n_messages

    def _get_messages_sliding_window(self) -> list[Message]:
        """Сообщения для LLM со скользящим окном"""
        window_type = self.session_settings.get("sliding_window_type", "messages")
        window_limit = self.session_settings.get("sliding_window_limit", 10)

        active_messages = [m for m in self.messages if not m.disabled and m.role in ("user", "assistant", "system")]

        if not active_messages:
            return []

        if window_type == "messages":
            user_messages = [m for m in self.messages if not m.disabled and m.role == "user"]
            if not user_messages:
                return []
            last_n_users = user_messages[-window_limit:]
            cutoff_index = self.messages.index(last_n_users[0])
            window_messages = [m for i, m in enumerate(self.messages) if i >= cutoff_index]
            
            system_msg = next((m for m in self.messages if m.role == "system"), None)
            if system_msg and system_msg not in window_messages:
                window_messages.insert(0, system_msg)
        else:
            window_messages = self._get_messages_by_token_limit(active_messages, window_limit)

        self._auto_disable_outside_window(window_messages)

        return window_messages

    def _get_messages_by_token_limit(self, messages: list[Message], token_limit: int) -> list[Message]:
        """Выбрать сообщения в пределах лимита токенов"""
        result = []
        total_tokens = 0

        for msg in reversed(messages):
            msg_tokens = msg.usage.get("total_tokens", len(msg.content) // 4)
            if total_tokens + msg_tokens <= token_limit:
                result.insert(0, msg)
                total_tokens += msg_tokens
            else:
                break

        if not result and messages:
            result = [messages[-1]]

        return result

    def _auto_disable_outside_window(self, window_messages: list[Message]) -> None:
        """Автоматически отключить сообщения за пределами окна"""
        disabled_count = 0

        active_messages = [
            m for m in self.messages 
            if not m.disabled 
            and m.role in ("user", "assistant", "system")
            and m.branch_id == self.current_branch
        ]
        window_set = set(id(m) for m in window_messages)

        for msg in active_messages:
            if id(msg) not in window_set:
                msg.disabled = True
                disabled_count += 1

        if disabled_count > 0:
            self.updated_at = datetime.now()

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

    def get_current_branch_messages(self) -> list[Message]:
        """Получить сообщения только текущей ветки"""
        return [m for m in self.messages if m.branch_id == self.current_branch]

    def get_branch_messages(self, branch_id: str) -> list[Message]:
        """Получить сообщения конкретной ветки"""
        return [m for m in self.messages if m.branch_id == branch_id]

    def create_checkpoint(self, name: str | None = None) -> Checkpoint:
        """Создать чекпоинт на текущей ветке с суммаризацией"""
        import uuid
        from app import summarizer

        self._ensure_main_branch()
        branch = self.get_branch(self.current_branch)
        if not branch:
            branch = self.branches[0]

        current_messages = self.get_current_branch_messages()
        
        summary = None
        user_messages = [m for m in current_messages if m.role == "user"]
        if len(user_messages) >= 2:
            try:
                summary, _ = summarizer.summarize_messages(current_messages)
            except Exception as e:
                raise ValueError(f"Failed to create summary: {str(e)}")
        
        checkpoint = Checkpoint(
            id=str(uuid.uuid4())[:8],
            name=name or f"v{len(self.checkpoints) + 1}",
            branch_id=branch.id,
            message_count=len(current_messages),
            summary=summary,
        )
        self.checkpoints.append(checkpoint)
        self.updated_at = datetime.now()
        return checkpoint

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        """Получить чекпоинт по ID"""
        for cp in self.checkpoints:
            if cp.id == checkpoint_id:
                return cp
        return None

    def rename_checkpoint(self, checkpoint_id: str, new_name: str) -> bool:
        """Переименовать чекпоинт"""
        for cp in self.checkpoints:
            if cp.id == checkpoint_id:
                cp.name = new_name
                self.updated_at = datetime.now()
                return True
        return False

    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Удалить чекпоинт и все ответвлённые ветки"""
        checkpoint = self.get_checkpoint(checkpoint_id)
        if not checkpoint:
            return False

        child_branches = [b for b in self.branches if b.parent_checkpoint == checkpoint_id]
        for branch in child_branches:
            self.delete_branch(branch.id)

        self.checkpoints = [cp for cp in self.checkpoints if cp.id != checkpoint_id]
        self.updated_at = datetime.now()
        return True

    def create_branch_from_checkpoint(self, checkpoint_id: str, name: str | None = None) -> Branch | None:
        """Создать ветку от чекпоинта"""
        import uuid

        checkpoint = self.get_checkpoint(checkpoint_id)
        if not checkpoint:
            return None

        self._ensure_main_branch()

        branch_name = name or f"branch-{len(self.branches) + 1}"
        new_branch = Branch(
            id=str(uuid.uuid4())[:8],
            name=branch_name,
            parent_branch=checkpoint.branch_id,
            parent_checkpoint=checkpoint_id,
        )
        self.branches.append(new_branch)

        if checkpoint.summary:
            summary_msg = Message(
                role="system",
                content=checkpoint.summary,
                branch_id=new_branch.id,
                usage={},
            )
            self.messages.append(summary_msg)

        self.updated_at = datetime.now()
        return new_branch

    def get_branch(self, branch_id: str) -> Branch | None:
        """Получить ветку по ID"""
        for b in self.branches:
            if b.id == branch_id:
                return b
        return None

    def switch_branch(self, branch_id: str) -> bool:
        """Переключиться на ветку"""
        self._ensure_main_branch()
        if any(b.id == branch_id for b in self.branches):
            self.current_branch = branch_id
            self.updated_at = datetime.now()
            return True
        return False

    def rename_branch(self, branch_id: str, new_name: str) -> bool:
        """Переименовать ветку"""
        branch = self.get_branch(branch_id)
        if not branch:
            return False
        branch.name = new_name
        self.updated_at = datetime.now()
        return True

    def delete_branch(self, branch_id: str) -> bool:
        """Удалить ветку"""
        if branch_id == "main":
            return False

        branch = self.get_branch(branch_id)
        if not branch:
            return False

        self.messages = [m for m in self.messages if m.branch_id != branch_id]
        self.branches = [b for b in self.branches if b.id != branch_id]

        if self.current_branch == branch_id:
            self.current_branch = "main"

        self.updated_at = datetime.now()
        return True

    def reset_branch_to_checkpoint(self, branch_id: str) -> bool:
        """Сбросить ветку к состоянию чекпоинта"""
        branch = self.get_branch(branch_id)
        if not branch:
            return False

        if branch.parent_checkpoint:
            checkpoint = self.get_checkpoint(branch.parent_checkpoint)
            if checkpoint:
                self.messages = [m for m in self.messages if m.branch_id != branch_id]
                for msg in self.messages:
                    if msg.branch_id == branch.parent_branch:
                        msg_idx = self.messages.index(msg)
                        if msg_idx < checkpoint.message_count:
                            cloned = Message(
                                role=msg.role,
                                content=msg.content,
                                usage=msg.usage.copy(),
                                debug=msg.debug.copy() if msg.debug else None,
                                model=msg.model,
                                summary_of=msg.summary_of,
                                created_at=msg.created_at,
                                disabled=msg.disabled,
                                branch_id=branch_id,
                            )
                            self.messages.append(cloned)
                self.updated_at = datetime.now()
                return True

        return False

    def get_tree(self) -> dict:
        """Получить дерево чекпоинтов и веток"""
        self._ensure_main_branch()

        def get_branch_children(parent_branch_id: str, parent_checkpoint_id: str | None = None) -> list:
            result = []

            branch_checkpoints = [cp for cp in self.checkpoints if cp.branch_id == parent_branch_id]
            for cp in branch_checkpoints:
                child_branches = [b for b in self.branches if b.parent_checkpoint == cp.id]
                result.append({
                    "type": "checkpoint",
                    "id": cp.id,
                    "name": cp.name,
                    "message_count": cp.message_count,
                    "children": [get_branch_children(b.id, b.id) for b in child_branches]
                })

            other_branches = [b for b in self.branches 
                            if b.parent_branch == parent_branch_id 
                            and b.id != "main"]
            for b in other_branches:
                result.append({
                    "type": "branch",
                    "id": b.id,
                    "name": b.name,
                    "children": get_branch_children(b.id)
                })

            return result

        main_branch = self.get_branch("main")
        if not main_branch:
            main_branch = Branch(id="main", name="main")

        main_msgs = self.get_branch_messages("main")
        return {
            "current_branch": self.current_branch,
            "branches": [
                {
                    "id": b.id,
                    "name": b.name,
                    "is_current": b.id == self.current_branch,
                }
                for b in self.branches
            ],
            "tree": {
                "type": "branch",
                "id": main_branch.id,
                "name": main_branch.name,
                "is_current": main_branch.id == self.current_branch,
                "message_count": len(main_msgs),
                "children": get_branch_children("main")
            }
        }

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
        self.facts = {}
        self.status = {}
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
                messages = []
                for m in data.get("messages", []):
                    content = m.get("content", "")
                    if m.get("role") == "assistant":
                        content = _clean_message_content(content)
                    messages.append(Message(
                        role=m["role"],
                        content=content,
                        usage=m.get("usage", {}),
                        debug=m.get("debug"),
                        model=m.get("model"),
                        summary_of=m.get("summary_of"),
                        created_at=datetime.fromisoformat(m["created_at"]) if m.get("created_at") else datetime.now(),
                        disabled=m.get("disabled", False),
                        branch_id=m.get("branch_id", "main"),
                        source=m.get("source"),
                    ))

                branches = [
                    Branch(
                        id=b["id"],
                        name=b["name"],
                        parent_branch=b.get("parent_branch"),
                        parent_checkpoint=b.get("parent_checkpoint"),
                        created_at=datetime.fromisoformat(b["created_at"]) if b.get("created_at") else datetime.now(),
                    )
                    for b in data.get("branches", [])
                ]

                checkpoints = [
                    Checkpoint(
                        id=cp["id"],
                        name=cp["name"],
                        branch_id=cp["branch_id"],
                        message_count=cp["message_count"],
                        summary=cp.get("summary"),
                        created_at=datetime.fromisoformat(cp["created_at"]) if cp.get("created_at") else datetime.now(),
                    )
                    for cp in data.get("checkpoints", [])
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
                    session_settings=data.get("session_settings", data.get("user_settings", {})),
                    branches=branches,
                    checkpoints=checkpoints,
                    current_branch=data.get("current_branch", "main"),
                    status=data.get("status", {
                        "task_name": "разговор на свободную тему",
                        "state": None,
                        "progress": None,
                        "project": None,
                        "updated_project_info": None,
                        "current_task_info": None,
                        "approved_plan": None,
                        "already_done": None,
                        "currently_doing": None
                    }),
                    owner_id=data.get("owner_id"),
                    access=data.get("access", "owner"),
                )
                session._ensure_main_branch()
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

    def list_sessions(self, user_id: str | None = None, user_role: str = "user") -> list[dict]:
        if user_id is None and user_role != "admin":
            return storage.list_sessions()
        return storage.list_sessions_filtered(user_id, user_role)

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
                    disabled=m.get("disabled", False),
                    branch_id=m.get("branch_id", "main"),
                )
                for m in data.get("messages", [])
            ]

            branches = [
                Branch(
                    id=b["id"],
                    name=b["name"],
                    parent_branch=b.get("parent_branch"),
                    parent_checkpoint=b.get("parent_checkpoint"),
                    created_at=datetime.fromisoformat(b["created_at"]) if b.get("created_at") else datetime.now(),
                )
                for b in data.get("branches", [])
            ]

            checkpoints = [
                Checkpoint(
                    id=cp["id"],
                    name=cp["name"],
                    branch_id=cp["branch_id"],
                    message_count=cp["message_count"],
                    summary=cp.get("summary"),
                    created_at=datetime.fromisoformat(cp["created_at"]) if cp.get("created_at") else datetime.now(),
                )
                for cp in data.get("checkpoints", [])
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
                session_settings=data.get("session_settings", data.get("user_settings", {})),
                branches=branches,
                checkpoints=checkpoints,
                current_branch=data.get("current_branch", "main"),
                status=data.get("status", {
                    "task_name": "разговор на свободную тему",
                    "state": None,
                    "progress": None,
                    "project": None,
                    "updated_project_info": None,
                    "current_task_info": None,
                    "approved_plan": None,
                    "already_done": None,
                    "currently_doing": None
                }),
            )
            session._ensure_main_branch()
            self._sessions[session_id] = session
        return session_id


session_manager = SessionManager()
