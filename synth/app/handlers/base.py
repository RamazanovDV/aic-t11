"""Base handler class."""

from abc import ABC, abstractmethod
from typing import Any

from app.session import Session, SessionManager
from app.llm import ProviderFactory
from app.debug import DebugCollector
from app.context_builder import ContextBuilder
from app.orchestration import OrchestrationController


class BaseHandler(ABC):
    """Base class for request handlers."""
    
    def __init__(self):
        from app.session import session_manager as _session_manager
        self.session_manager = _session_manager
    
    def get_session(self, session_id: str) -> Session:
        """Get session by ID."""
        return self.session_manager.get_session(session_id)
    
    def save_session(self, session_id: str) -> None:
        """Save session."""
        self.session_manager.save_session(session_id)
    
    def create_provider(self, provider_name: str, model: str | None = None, config: dict | None = None):
        """Create LLM provider."""
        from app.config import config as app_config
        
        if config is None:
            config = app_config.get_provider_config(provider_name)
        
        if model:
            config = config.copy()
            config["model"] = model
        
        return ProviderFactory.create(provider_name, config)
    
    def create_context_builder(self, session: Session, user_id: str | None = None, debug_collector=None) -> ContextBuilder:
        """Create ContextBuilder for session."""
        return ContextBuilder(session, user_id, debug_collector)
    
    def create_orchestration_controller(
        self,
        provider,
        session: Session,
        debug_collector: DebugCollector | None = None
    ) -> OrchestrationController:
        """Create OrchestrationController."""
        return OrchestrationController(provider, session, debug_collector)
    
    def create_debug_collector(self, session: Session) -> DebugCollector:
        """Create DebugCollector for session."""
        return DebugCollector.from_session(session)
    
    @abstractmethod
    def handle(self, *args, **kwargs) -> Any:
        """Handle request - must be implemented by subclasses."""
        pass