import json
from datetime import datetime
from pathlib import Path

from app.config import config
from app.models import User
from app.logger import debug


class FileStorage:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or config.data_dir
        self.sessions_dir = self.data_dir / "sessions"
        self.users_dir = self.data_dir / "users"
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.users_dir.mkdir(parents=True, exist_ok=True)

    def _session_file(self, session_id: str) -> Path:
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
        return self.sessions_dir / f"{safe_id}.json"

    def save_session(self, session) -> None:
        session_file = self._session_file(session.session_id)
        
        debug("STORAGE", f"Saving session {session.session_id}, messages count: {len(session.messages)}")
        
        data = {
            "schema_version": "1.0.0",
            "session_id": session.session_id,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "usage": m.usage,
                    "debug": m.debug,
                    "model": m.model,
                    "created_at": m.created_at.isoformat(),
                    "disabled": m.disabled,
                    "branch_id": m.branch_id,
                    "source": m.source,
                    "status": m.status,
                    "reasoning": m.reasoning,
                    "tool_call_id": m.tool_call_id,
                    "tool_use": m.tool_use,
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
            "session_settings": session.session_settings,
            "branches": [
                {
                    "id": b.id,
                    "name": b.name,
                    "parent_branch": b.parent_branch,
                    "parent_checkpoint": b.parent_checkpoint,
                    "created_at": b.created_at.isoformat(),
                }
                for b in session.branches
            ],
            "checkpoints": [
                {
                    "id": cp.id,
                    "name": cp.name,
                    "branch_id": cp.branch_id,
                    "message_count": cp.message_count,
                    "summary": cp.summary,
                    "created_at": cp.created_at.isoformat(),
                }
                for cp in session.checkpoints
            ],
            "current_branch": session.current_branch,
            "status": session.status,
            "owner_id": session.owner_id,
            "access": session.access,
            "mcp_servers": session.mcp_servers,
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

    def list_sessions_filtered(self, user_id: str | None = None, user_role: str = "user") -> list[dict]:
        sessions = []
        
        for session_file in self.sessions_dir.glob("*.json"):
            if session_file.name == "index.json":
                continue
            session_data = self.load_session(session_file.stem)
            if not session_data:
                continue
            
            access = session_data.get("access", "owner")
            owner_id = session_data.get("owner_id")
            
            if user_role == "admin":
                pass
            elif access == "public":
                pass
            elif access == "team":
                pass
            elif access == "owner" and owner_id != user_id:
                continue
            
            session_id = session_data.get("session_id") or session_file.stem
            sessions.append({
                "session_id": session_id,
                "message_count": len(session_data.get("messages", [])),
                "created_at": session_data.get("created_at"),
                "updated_at": session_data.get("updated_at"),
                "owner_id": owner_id,
                "access": access,
            })
        
        return sorted(sessions, key=lambda x: x.get("updated_at") or "", reverse=True)

    def update_session_access(self, session_id: str, owner_id: str | None, access: str) -> bool:
        session_data = self.load_session(session_id)
        if not session_data:
            return False
        
        session_data["owner_id"] = owner_id
        session_data["access"] = access
        
        session_file = self._session_file(session_id)
        with open(session_file, "w") as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)
        
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

    def _user_file(self, user_id: str) -> Path:
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in user_id)
        return self.users_dir / f"{safe_id}.json"

    def save_user(self, user: User) -> None:
        user_file = self._user_file(user.id)
        with open(user_file, "w") as f:
            json.dump(user.to_dict(), f, indent=2, ensure_ascii=False)

    def load_user(self, user_id: str) -> User | None:
        user_file = self._user_file(user_id)
        if not user_file.exists():
            return None

        with open(user_file, "r") as f:
            data = json.load(f)
        return User.from_dict(data)

    def get_user_by_username(self, username: str) -> User | None:
        for user_file in self.users_dir.glob("*.json"):
            with open(user_file, "r") as f:
                data = json.load(f)
            if data.get("username", "").lower() == username.lower():
                return User.from_dict(data)
        return None

    def get_user_by_email(self, email: str) -> User | None:
        for user_file in self.users_dir.glob("*.json"):
            with open(user_file, "r") as f:
                data = json.load(f)
            if data.get("email", "").lower() == email.lower():
                return User.from_dict(data)
        return None

    def list_users(self) -> list[dict]:
        users = []
        for user_file in self.users_dir.glob("*.json"):
            with open(user_file, "r") as f:
                data = json.load(f)
            users.append({
                "id": data.get("id"),
                "username": data.get("username"),
                "email": data.get("email"),
                "role": data.get("role"),
                "team_role": data.get("team_role"),
                "interview_completed": data.get("interview_completed", False),
                "is_active": data.get("is_active", True),
                "created_at": data.get("created_at"),
                "last_login": data.get("last_login"),
            })

        return sorted(users, key=lambda x: x.get("created_at") or "", reverse=True)

    def delete_user(self, user_id: str) -> bool:
        user_file = self._user_file(user_id)
        if not user_file.exists():
            return False

        user_file.unlink()
        return True

    def user_exists(self, username: str | None = None, email: str | None = None) -> bool:
        if username:
            if self.get_user_by_username(username):
                return True
        if email:
            if self.get_user_by_email(email):
                return True
        return False


storage = FileStorage()
