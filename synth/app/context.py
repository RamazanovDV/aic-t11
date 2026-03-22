from pathlib import Path
from typing import Any

from app.config import config


SYSTEM_CONTEXT_FILES = [
    "STATUS_REMINDER.md",
    "STATUS_SIMPLE.md",
    "STATUS_ORCHESTRATOR.md",
    "TSM_PLANNING.md",
    "TSM_EXECUTION.md",
    "TSM_VALIDATION.md",
    "TSM_DONE.md",
    "SUMMARIZER.md",
    "INTERVIEW.md",
    "NEW_PROJECT.md",
    "SCHEDULER.md",
    "RAG_UNKNOWN.md",
]

DEFAULT_CONTEXT_FILES = [
    "COMPANY.md",
    "ABOUT.md",
    "SOUL.md",
]


class ContextManager:
    def __init__(self, system_dir: Path | None = None, user_dir: Path | None = None):
        if system_dir is None:
            system_dir = Path(__file__).parent.parent / "context"
        self.system_dir = system_dir
        self.user_dir = user_dir or config.context_dir

    def get_context_file(self, filename: str) -> str | None:
        user_path = self.user_dir / filename
        if user_path.exists():
            return user_path.read_text(encoding="utf-8")

        system_path = self.system_dir / filename
        if system_path.exists():
            return system_path.read_text(encoding="utf-8")

        return None

    def save_context_file(self, filename: str, content: str) -> None:
        self.user_dir.mkdir(parents=True, exist_ok=True)
        (self.user_dir / filename).write_text(content, encoding="utf-8")

    def delete_context_file(self, filename: str) -> None:
        user_path = self.user_dir / filename
        if user_path.exists():
            user_path.unlink()

    def is_system_file(self, filename: str) -> bool:
        return filename in SYSTEM_CONTEXT_FILES

    def is_default_file(self, filename: str) -> bool:
        return filename in DEFAULT_CONTEXT_FILES

    def is_overridden(self, filename: str) -> bool:
        user_path = self.user_dir / filename
        return user_path.exists()

    def get_file_source(self, filename: str) -> str | None:
        user_path = self.user_dir / filename
        if user_path.exists():
            return "user"
        system_path = self.system_dir / filename
        if system_path.exists():
            return "system"
        return None

    def list_system_files(self) -> list[dict[str, Any]]:
        result = []
        for filename in SYSTEM_CONTEXT_FILES:
            system_path = self.system_dir / filename
            user_path = self.user_dir / filename
            info = {
                "filename": filename,
                "is_system": True,
                "is_overridden": user_path.exists(),
                "source": self.get_file_source(filename),
            }
            if user_path.exists():
                info["content"] = user_path.read_text(encoding="utf-8")
            elif system_path.exists():
                info["content"] = system_path.read_text(encoding="utf-8")
            else:
                info["content"] = ""
            result.append(info)
        return result

    def list_user_files(self) -> list[dict[str, Any]]:
        self.user_dir.mkdir(parents=True, exist_ok=True)
        result = []
        
        for filename in DEFAULT_CONTEXT_FILES:
            user_path = self.user_dir / filename
            is_overridden = user_path.exists()
            
            default_filename = f"DEFAULT_{filename}"
            default_path = self.system_dir / default_filename
            
            content = ""
            if user_path.exists():
                content = user_path.read_text(encoding="utf-8")
            elif default_path.exists():
                content = default_path.read_text(encoding="utf-8")
            
            result.append({
                "filename": filename,
                "is_system": False,
                "is_default": True,
                "is_overridden": is_overridden,
                "source": "user",
                "content": content,
            })
        
        for filepath in sorted(self.user_dir.glob("*.md")):
            if self.is_system_file(filepath.name) or self.is_default_file(filepath.name):
                continue
            result.append({
                "filename": filepath.name,
                "is_system": False,
                "is_default": False,
                "is_overridden": False,
                "source": "user",
                "content": filepath.read_text(encoding="utf-8"),
            })
        return result

    def list_default_files(self) -> list[dict[str, Any]]:
        result = []
        for filename in DEFAULT_CONTEXT_FILES:
            user_path = self.user_dir / filename
            default_filename = f"DEFAULT_{filename}"
            default_path = self.system_dir / default_filename
            
            user_content = ""
            default_content = ""
            
            if user_path.exists():
                user_content = user_path.read_text(encoding="utf-8")
            if default_path.exists():
                default_content = default_path.read_text(encoding="utf-8")
            
            result.append({
                "filename": filename,
                "content": user_content or default_content,
                "is_overridden": user_path.exists(),
            })
        return result

    def restore_default_file(self, filename: str) -> bool:
        if not self.is_default_file(filename):
            return False
        
        user_path = self.user_dir / filename
        default_filename = f"DEFAULT_{filename}"
        default_path = self.system_dir / default_filename
        
        if user_path.exists():
            user_path.unlink()
        
        if default_path.exists():
            user_path.write_text(default_path.read_text(encoding="utf-8"), encoding="utf-8")
            return True
        
        return False

    def list_all_files(self) -> list[dict[str, Any]]:
        return self.list_system_files() + self.list_user_files()

    def create_user_file(self, filename: str, content: str = "") -> None:
        if not filename.endswith(".md"):
            filename = filename + ".md"
        if self.is_system_file(filename):
            raise ValueError(f"Cannot create system file: {filename}")
        self.user_dir.mkdir(parents=True, exist_ok=True)
        user_path = self.user_dir / filename
        if user_path.exists():
            raise FileExistsError(f"File already exists: {filename}")
        user_path.write_text(content, encoding="utf-8")

    def rename_user_file(self, old_name: str, new_name: str) -> None:
        if not new_name.endswith(".md"):
            new_name = new_name + ".md"
        if self.is_system_file(new_name):
            raise ValueError(f"Cannot rename to system filename: {new_name}")
        old_path = self.user_dir / old_name
        new_path = self.user_dir / new_name
        if not old_path.exists():
            raise FileNotFoundError(f"File not found: {old_name}")
        if new_path.exists():
            raise FileExistsError(f"File already exists: {new_name}")
        old_path.rename(new_path)


_context_manager: ContextManager | None = None


def get_context_manager() -> ContextManager:
    global _context_manager
    if _context_manager is None:
        _context_manager = ContextManager()
    return _context_manager


class ContextLoader:
    def __init__(self, context_dir: Path | None = None):
        self.context_dir = context_dir or config.context_dir

    def load(self) -> str:
        if not self.context_dir.exists():
            return ""

        enabled_files = config.get_enabled_context_files()
        if not enabled_files:
            return ""

        context_parts = []
        for filename in enabled_files:
            filepath = self.context_dir / filename
            if filepath.exists() and filepath.suffix == ".md":
                content = filepath.read_text(encoding="utf-8")
                context_parts.append(f"--- File: {filename} ---\n{content}\n")

        if not context_parts:
            return ""

        return "\n".join(context_parts)


def get_system_prompt() -> str:
    loader = ContextLoader()
    context = loader.load()

    base_prompt = "Ты - AI-ассистент. Отвечай на русском языке, если пользователь пишет на русском."

    if context:
        return f"{base_prompt}\n\nДополнительный контекст:\n{context}"

    return base_prompt


def get_profile_prompt(session, user_id: str | None = None) -> str:
    """Сформировать промпт с данными профиля пользователя"""
    from app import storage as app_storage
    
    user = None
    
    if session and session.owner_id:
        user = app_storage.storage.load_user(session.owner_id)
    
    if not user and user_id:
        user = app_storage.storage.load_user(user_id)
    
    if not user:
        try:
            from app.auth import get_current_user
            user = get_current_user()
        except Exception:
            user = None
    
    if not user:
        return ""
    
    parts = []
    if user.username:
        parts.append(f"Имя: {user.username}")
    if user.team_role:
        parts.append(f"Роль: {user.team_role}")
    if user.notes:
        notes_without_interview = user.notes.split("[ИНТЕРВЬЮ]")[0].strip()
        if notes_without_interview:
            parts.append(f"Отметки: {notes_without_interview}")
    
    if parts:
        return f"\n\n[ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ]\n" + "\n".join(parts) + "\n"
    
    return ""


def get_project_prompt(session) -> str:
    """Сформировать промпт с данными проекта"""
    from app import project_manager, scheduler, config
    
    project_name = session.status.get("project")
    
    if not project_name:
        projects_list = project_manager.project_manager.get_projects_list()
        projects_text = ", ".join(projects_list) if projects_list else "пока нет проектов"
        
        new_project_prompt = config.get_context_file("NEW_PROJECT.md") or "Если пользователь хочет начать новый проект - уточни название, укажи полученное название в поле project."
        
        return (
            f"\n\n[ПРОЕКТ]\n"
            f"Выясни у пользователя над каким проектом он хочет поработать.\n"
            f"Существующие проекты: {projects_text}\n"
            f"{new_project_prompt}\n"
        )
    
    if not project_manager.project_manager.project_exists(project_name):
        project_manager.project_manager.create_project(project_name)
    
    project_info = project_manager.project_manager.get_project_info(project_name)
    current_task = project_manager.project_manager.get_current_task(project_name)
    invariants = project_manager.project_manager.get_invariants(project_name)
    
    result = f"\n\n[ПРОЕКТ: {project_name}]\n"
    
    if project_info:
        result += f"{project_info}\n"
    else:
        result += "(Описание проекта отсутствует)\n"
    
    if current_task:
        result += f"\n[ТЕКУЩАЯ ЗАДАЧА]\n{current_task}\n"
    
    if invariants:
        result += f"\n[ИНВАРИАНТЫ - ОБЯЗАТЕЛЬНО К СОБЛЮДЕНИЮ]\n"
        for key, value in invariants.items():
            if isinstance(value, list):
                result += f"- {key}: {', '.join(str(v) for v in value)}\n"
            else:
                result += f"- {key}: {value}\n"
    
    schedules = scheduler.scheduler.get_schedules(project_name)
    enabled_schedules = [s for s in schedules if s.enabled]
    if project_name:
        result += f"\n[ЗАДАНИЯ ПО РАСПИСАНИЮ]\n"
        if enabled_schedules:
            result += "В этом проекте настроены автоматические задания:\n"
            for s in enabled_schedules:
                next_run_str = s.next_run.strftime("%Y-%m-%d %H:%M") if s.next_run else "неизвестно"
                result += f"- {s.name}: cron={s.cron}, следующий запуск: {next_run_str}\n"
        result += "Можно создать новое задание, указав его параметры в поле schedule блока статуса.\n"
    
    return result


def get_status_prompt(session) -> str:
    """Сформировать промпт с инструкцией по статусу задачи"""
    from app import tsm
    return tsm.get_tsm_prompt(session)


def should_show_interview(session, user_id: str | None = None) -> bool:
    """Проверить нужно ли показывать интервью.
    
    Интервью показывается только если:
    1. Это первое сообщение в сессии
    2. Пользователь еще не прошел интервью
    """
    if session.get_active_message_count() != 0:
        return False
    
    from app import storage as app_storage
    
    user = None
    if session.owner_id:
        user = app_storage.storage.load_user(session.owner_id)
    
    if not user and user_id:
        user = app_storage.storage.load_user(user_id)
    
    if not user:
        try:
            from app.auth import get_current_user
            user = get_current_user()
        except Exception:
            pass
    
    if user:
        return not user.interview_completed
    
    return False


def get_interview_prompt() -> str:
    """Получить промпт интервью"""
    return config.get_context_file("INTERVIEW.md") or ""
