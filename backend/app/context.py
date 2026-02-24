from pathlib import Path

from backend.app.config import config


class ContextLoader:
    def __init__(self, context_dir: Path | None = None):
        self.context_dir = context_dir or config.context_dir

    def load(self) -> str:
        if not self.context_dir.exists():
            return ""

        context_parts = []
        md_files = sorted(self.context_dir.glob("*.md"))

        for md_file in md_files:
            content = md_file.read_text(encoding="utf-8")
            context_parts.append(f"--- File: {md_file.name} ---\n{content}\n")

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
