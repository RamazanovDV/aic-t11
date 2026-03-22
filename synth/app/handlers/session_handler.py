"""Session handler for session management endpoints."""


from app.handlers.base import BaseHandler


class SessionHandler(BaseHandler):
    """Handler for session management (list, create, delete, etc.)."""
    
    def list(self, user_id: str | None = None, user_role: str = "user") -> list[dict]:
        """List sessions."""
        return self.session_manager.list_sessions(user_id, user_role)
    
    def create(self, session_id: str | None = None, provider: str = "", model: str = "") -> dict:
        """Create new session."""
        import uuid
        
        if not session_id:
            session_id = str(uuid.uuid4())
        
        from app.session import Session
        session = Session(session_id=session_id, provider=provider, model=model)
        session._ensure_main_branch()
        
        self.session_manager._sessions[session_id] = session
        self.save_session(session_id)
        
        return {
            "session_id": session_id,
            "created_at": session.created_at.isoformat()
        }
    
    def get(self, session_id: str) -> dict | None:
        """Get session data."""
        session = self.get_session(session_id)
        if not session:
            return None
        
        return {
            "session_id": session.session_id,
            "messages_count": len(session.messages),
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "provider": session.provider,
            "model": session.model,
            "total_tokens": session.total_tokens,
            "status": session.status,
            "session_settings": session.session_settings,
        }
    
    def delete(self, session_id: str) -> bool:
        """Delete session."""
        return self.session_manager.delete_session(session_id)
    
    def rename(self, old_id: str, new_id: str) -> bool:
        """Rename session."""
        return self.session_manager.rename_session(old_id, new_id)
    
    def reset(self, session_id: str) -> None:
        """Reset session."""
        self.session_manager.reset_session(session_id)
    
    def export_all(self) -> dict:
        """Export all sessions."""
        return self.session_manager.export_all()
    
    def import_session(self, session_data: dict) -> str:
        """Import session."""
        return self.session_manager.import_session(session_data)