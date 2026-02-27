import json
from datetime import datetime
from pathlib import Path

from app.config import config


class FileStorage:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or config.data_dir
        self.sessions_dir = self.data_dir / "sessions"
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _session_file(self, session_id: str) -> Path:
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
        return self.sessions_dir / f"{safe_id}.json"

    def save_session(self, session) -> None:
        session_file = self._session_file(session.session_id)
        
        data = {
            "session_id": session.session_id,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "usage": m.usage,
                    "debug": m.debug,
                    "model": m.model,
                    "created_at": m.created_at.isoformat(),
                }
                for m in session.messages
            ],
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "provider": session.provider,
            "model": session.model,
            "total_tokens": session.total_tokens,
            "input_tokens": session.input_tokens,
            "output_tokens": session.output_tokens,
            "user_settings": session.user_settings,
        }

        with open(session_file, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_session(self, session_id: str) -> dict | None:
        session_file = self._session_file(session_id)
        if not session_file.exists():
            return None

        with open(session_file, "r") as f:
            return json.load(f)

    def list_sessions(self) -> list[dict]:
        sessions = []
        
        for session_file in self.sessions_dir.glob("*.json"):
            if session_file.name == "index.json":
                continue
            session_data = self.load_session(session_file.stem)
            if session_data:
                session_id = session_data.get("session_id") or session_file.stem
                sessions.append({
                    "session_id": session_id,
                    "message_count": len(session_data.get("messages", [])),
                    "created_at": session_data.get("created_at"),
                    "updated_at": session_data.get("updated_at"),
                })
        
        return sorted(sessions, key=lambda x: x.get("updated_at") or "", reverse=True)

    def delete_session(self, session_id: str) -> bool:
        session_file = self._session_file(session_id)
        if not session_file.exists():
            return False

        session_file.unlink()

        return True

    def rename_session(self, old_id: str, new_id: str) -> bool:
        old_file = self._session_file(old_id)
        new_file = self._session_file(new_id)
        
        if not old_file.exists():
            return False
        
        if new_file.exists():
            return False

        # Update session data with new ID
        session_data = self.load_session(old_id)
        if not session_data:
            return False
        
        session_data["session_id"] = new_id
        
        # Save to new file
        with open(new_file, "w") as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)
        
        # Delete old file
        old_file.unlink()
        
        return True

    def export_all(self) -> dict:
        return {
            "sessions": {s["session_id"]: self.load_session(s["session_id"]) 
                        for s in self.list_sessions()},
            "exported_at": datetime.now().isoformat(),
        }

    def import_session(self, session_data: dict) -> str:
        session_id = session_data.get("session_id", "imported")
        
        session_file = self._session_file(session_id)
        session_data["session_id"] = session_id
        
        with open(session_file, "w") as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)
        
        return session_id


storage = FileStorage()
