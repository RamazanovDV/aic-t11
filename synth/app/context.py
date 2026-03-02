from pathlib import Path

from app.config import config


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
