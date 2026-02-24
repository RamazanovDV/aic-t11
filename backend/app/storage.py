import json
from datetime import datetime
from pathlib import Path

from backend.app.config import config
from backend.app.llm.base import Message


class FileStorage:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or config.data_dir
        self.sessions_dir = self.data_dir / "sessions"
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._init_index()

    def _init_index(self) -> None:
        index_file = self.sessions_dir / "index.json"
        if not index_file.exists():
            self._save_index({"sessions": [], "last_modified": datetime.now().isoformat()})

    def _get_index(self) -> dict:
        index_file = self.sessions_dir / "index.json"
        with open(index_file, "r") as f:
            return json.load(f)

    def _save_index(self, index: dict) -> None:
        index["last_modified"] = datetime.now().isoformat()
        index_file = self.sessions_dir / "index.json"
        with open(index_file, "w") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

    def _session_file(self, session_id: str) -> Path:
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
        return self.sessions_dir / f"{safe_id}.json"

    def save_session(self, session_id: str, messages: list[Message], created_at: datetime, updated_at: datetime) -> None:
        session_file = self._session_file(session_id)
        
        data = {
            "session_id": session_id,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "created_at": created_at.isoformat(),
            "updated_at": updated_at.isoformat(),
        }

        with open(session_file, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        index = self._get_index()
        if session_id not in index["sessions"]:
            index["sessions"].append(session_id)
        self._save_index(index)

    def load_session(self, session_id: str) -> dict | None:
        session_file = self._session_file(session_id)
        if not session_file.exists():
            return None

        with open(session_file, "r") as f:
            return json.load(f)

    def list_sessions(self) -> list[dict]:
        index = self._get_index()
        sessions = []
        
        for session_id in index["sessions"]:
            session_data = self.load_session(session_id)
            if session_data:
                sessions.append({
                    "session_id": session_data["session_id"],
                    "message_count": len(session_data.get("messages", [])),
                    "created_at": session_data.get("created_at"),
                    "updated_at": session_data.get("updated_at"),
                })
        
        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)

    def delete_session(self, session_id: str) -> bool:
        session_file = self._session_file(session_id)
        if not session_file.exists():
            return False

        session_file.unlink()

        index = self._get_index()
        if session_id in index["sessions"]:
            index["sessions"].remove(session_id)
        self._save_index(index)

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
        
        # Update index
        index = self._get_index()
        if old_id in index["sessions"]:
            index["sessions"].remove(old_id)
            if new_id not in index["sessions"]:
                index["sessions"].append(new_id)
        self._save_index(index)
        
        return True

    def export_all(self) -> dict:
        return {
            "index": self._get_index(),
            "sessions": {s["session_id"]: self.load_session(s["session_id"]) 
                        for s in self.list_sessions()},
            "exported_at": datetime.now().isoformat(),
        }

    def import_session(self, session_data: dict) -> str:
        session_id = session_data.get("session_id", "imported")
        messages = [Message(role=m["role"], content=m["content"]) for m in session_data.get("messages", [])]
        created_at = datetime.fromisoformat(session_data.get("created_at", datetime.now().isoformat()))
        updated_at = datetime.fromisoformat(session_data.get("updated_at", datetime.now().isoformat()))
        
        self.save_session(session_id, messages, created_at, updated_at)
        return session_id


storage = FileStorage()
