from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
import hashlib
import secrets


TEAM_ROLES = [
    "developer",
    "devops",
    "analyst",
    "security",
    "qa",
    "admin_team",
    "manager",
    "other",
]

USER_ROLES = [
    "admin",
    "user",
    "viewer",
]


@dataclass
class User:
    id: str
    username: str
    email: str
    password_hash: str = ""
    role: str = "user"
    team_role: str = "developer"
    preferences: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    interview_completed: bool = False
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    last_login: datetime | None = None

    def set_password(self, password: str) -> None:
        self.password_hash = self._hash_password(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return self.password_hash == self._hash_password(password)

    def _hash_password(self, password: str) -> str:
        salt = self.id[:8]
        return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "password_hash": self.password_hash,
            "role": self.role,
            "team_role": self.team_role,
            "preferences": self.preferences,
            "notes": self.notes,
            "interview_completed": self.interview_completed,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_login": self.last_login.isoformat() if self.last_login else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "User":
        return cls(
            id=data["id"],
            username=data["username"],
            email=data["email"],
            password_hash=data.get("password_hash", ""),
            role=data.get("role", "user"),
            team_role=data.get("team_role", "developer"),
            preferences=data.get("preferences", {}),
            notes=data.get("notes", ""),
            interview_completed=data.get("interview_completed", False),
            is_active=data.get("is_active", True),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
            last_login=datetime.fromisoformat(data["last_login"]) if data.get("last_login") else None,
        )

    @staticmethod
    def generate_id(username: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        safe_name = "".join(c if c.isalnum() else "_" for c in username.lower())
        return f"{safe_name}_{timestamp}"

    @staticmethod
    def generate_temp_password(length: int = 12) -> str:
        return secrets.token_urlsafe(length)[:length]
