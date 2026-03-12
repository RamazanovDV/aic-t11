from pathlib import Path
from typing import Any

from app.config import config


SYSTEM_CONTEXT_FILES = [
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
        for filepath in sorted(self.user_dir.glob("*.md")):
            if self.is_system_file(filepath.name):
                continue
            result.append({
                "filename": filepath.name,
                "is_system": False,
                "is_overridden": False,
                "source": "user",
                "content": filepath.read_text(encoding="utf-8"),
            })
        return result

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
