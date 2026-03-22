"""Chat handler for non-streaming requests."""

from typing import Any

from app.handlers.base import BaseHandler
from app.session import Session
from app import tsm
from app.debug import DebugCollector


class ChatHandler(BaseHandler):
    """Handler for /chat endpoint (non-streaming)."""
    
    def handle(
        self,
        session_id: str,
        message: str,
        provider_name: str | None = None,
        model: str | None = None,
        debug_mode: bool = False,
        user_id: str | None = None
    ) -> dict[str, Any]:
        """Handle chat request.
        
        Returns:
            dict with 'message', 'session_id', 'model', 'usage', etc.
        """
        session = self.get_session(session_id)
        
        if data.get("tsm_mode"):
            try:
                tsm.set_tsm_mode(session, data["tsm_mode"])
            except ValueError as e:
                return {"error": f"Invalid tsm_mode: {str(e)}"}, 400
        
        session.add_user_message(message, source="web")
        
        debug_collector = self.create_debug_collector(session) if debug_mode else None
        
        context_builder = self.create_context_builder(session, user_id)
        system_prompt = context_builder.build_system_prompt()
        messages = context_builder.build_messages()
        
        mcp_tools = context_builder.build_mcp_tools(provider_name)
        
        tsm_mode = tsm.get_tsm_mode(session)
        
        if tsm_mode == "orchestrator":
            return self._handle_orchestrator(
                session, messages, system_prompt, provider_name, model, 
                debug_collector, user_id
            )
        
        return self._handle_simple(
            session, messages, system_prompt, provider_name, model,
            debug_collector, user_id, mcp_tools
        )
    
    def _handle_simple(
        self,
        session: Session,
        messages: list,
        system_prompt: str,
        provider_name: str | None,
        model: str | None,
        debug_collector: DebugCollector | None,
        user_id: str | None,
        mcp_tools: list
    ) -> dict:
        """Handle simple mode."""
        from app.config import config
        from app.status_validator import validate_status_block
        
        if not provider_name:
            provider_name = config.default_provider
        
        provider = self.create_provider(provider_name, model)
        
        orchestrator = self.create_orchestration_controller(
            provider, session, debug_collector
        )
        
        status_reminder = config.get_context_file("STATUS_REMINDER.md") or ""
        prompt_with_reminder = system_prompt + "\n\n" + status_reminder
        
        response = orchestrator.run_simple(messages, prompt_with_reminder, mcp_tools)
        
        message_for_user = response.content
        
        parsed_status, cleaned_content = validate_status_block(response.content)
        if parsed_status:
            session.update_status(parsed_status)
            message_for_user = cleaned_content if cleaned_content else response.content
        
        if debug_collector and debug_collector.enabled:
            debug_collector.capture_reasoning(response.reasoning)
            debug_collector.capture_session_info(
                session.session_id, 
                provider.model,
                provider.get_provider_name()
            )
        
        debug_info = debug_collector.get_debug_info() if debug_collector else None
        
        session.add_assistant_message(
            message_for_user,
            response.usage,
            debug=debug_info,
            model=response.model,
            reasoning=response.reasoning
        )
        
        self.save_session(session.session_id)
        
        disabled_indices = [i for i, m in enumerate(session.messages) if m.disabled]
        
        return {
            "message": message_for_user,
            "session_id": session.session_id,
            "model": response.model,
            "usage": response.usage,
            "total_tokens": session.total_tokens,
            "disabled_indices": disabled_indices,
            "reasoning": response.reasoning,
        }
    
    def _handle_orchestrator(
        self,
        session: Session,
        messages: list,
        system_prompt: str,
        provider_name: str | None,
        model: str | None,
        debug_collector: DebugCollector | None,
        user_id: str | None
    ) -> dict:
        """Handle orchestrator mode."""
        
        provider = self.create_provider(provider_name, model)
        
        result = tsm.process_orchestrator_response(
            session=session,
            llm_messages=messages,
            provider=provider,
            system_prompt=system_prompt,
            debug_collector=debug_collector,
            debug_prompt=system_prompt
        )
        
        final_content = result.get("final_content", "")
        final_reasoning = result.get("reasoning")
        final_status = result.get("final_status")
        usage = result.get("usage", {})
        debug_info = result.get("debug")
        
        if final_status:
            session.update_status(final_status)
        
        session.add_assistant_message(
            final_content,
            usage,
            debug=debug_info,
            model=provider.model,
            reasoning=final_reasoning
        )
        
        self.save_session(session.session_id)
        
        return {
            "message": final_content,
            "session_id": session.session_id,
            "model": "orchestrator",
            "usage": usage,
            "total_tokens": session.total_tokens,
            "reasoning": final_reasoning,
        }


def data():
    """Placeholder for request data - should be passed in."""
    pass