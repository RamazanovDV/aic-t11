from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional
from functools import wraps

from flask import request, jsonify, session, g
from app.models import User
from app.storage import storage


class AuthProvider(ABC):
    @abstractmethod
    def login(self, username: str, password: str) -> tuple[User | None, str]:
        pass

    @abstractmethod
    def logout(self) -> None:
        pass

    @abstractmethod
    def get_current_user(self) -> Optional[User]:
        pass

    @abstractmethod
    def create_user(self, username: str, email: str, password: str, **kwargs) -> tuple[User | None, str]:
        pass


class SessionAuthProvider(AuthProvider):
    def login(self, username: str, password: str) -> tuple[User | None, str]:
        user = storage.get_user_by_username(username)
        if not user:
            return None, "User not found"
        
        if not user.is_active:
            return None, "User is inactive"
        
        if not user.check_password(password):
            return None, "Invalid password"
        
        user.last_login = datetime.now()
        storage.save_user(user)
        
        self._set_session(user)
        
        return user, ""

    def logout(self) -> None:
        session.pop("user_id", None)
        session.pop("user_role", None)
        session.clear()

    def get_current_user(self) -> Optional[User]:
        user_id = session.get("user_id")
        if not user_id:
            return None
        
        return storage.load_user(user_id)

    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        role: str = "user",
        team_role: str = "developer",
        **kwargs
    ) -> tuple[User | None, str]:
        if storage.user_exists(username=username):
            return None, "Username already exists"
        
        if storage.user_exists(email=email):
            return None, "Email already exists"
        
        user = User(
            id=User.generate_id(username),
            username=username,
            email=email,
            role=role,
            team_role=team_role,
            **kwargs
        )
        user.set_password(password)
        
        storage.save_user(user)
        
        return user, ""

    def _set_session(self, user: User) -> None:
        session["user_id"] = user.id
        session["user_role"] = user.role
        session.permanent = True


class JWTAuthProvider(AuthProvider):
    pass


class OIDCAuthProvider(AuthProvider):
    pass


auth_provider: AuthProvider = SessionAuthProvider()


def get_auth_provider() -> AuthProvider:
    return auth_provider


def set_auth_provider(provider: AuthProvider) -> None:
    global auth_provider
    auth_provider = provider


def require_user(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = auth_provider.get_current_user()
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        
        g.current_user = user
        return f(*args, **kwargs)
    
    wrapper.__name__ = f.__name__
    return wrapper


def require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        from flask import request
        from app.config import config
        
        api_key = request.headers.get("X-API-Key")
        if api_key and api_key == config.api_key:
            g.current_user = None
            return f(*args, **kwargs)
        
        user = auth_provider.get_current_user()
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        
        if user.role != "admin":
            return jsonify({"error": "Admin access required"}), 403
        
        g.current_user = user
        return f(*args, **kwargs)
    
    wrapper.__name__ = f.__name__
    return wrapper


def get_current_user() -> Optional[User]:
    return auth_provider.get_current_user()
