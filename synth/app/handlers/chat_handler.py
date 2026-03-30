"""Chat handler for non-streaming requests."""

import re
from typing import Any

from app.handlers.base import BaseHandler
from app.session import Session
from app import tsm
from app.debug import DebugCollector
from app.project_updates import handle_project_updates


TAGS_PATTERN = re.compile(r'@(\w+)')


def parse_agent_tags(message: str) -> tuple[list[str], str, str]:
    """Parse @tags from message and return (tags, clean_message, transformed_message).
    
    - tags: list of tag names found (e.g., ['developer', 'qa'])
    - clean_message: message with @tags removed
    - transformed_message: message with @tag replaced by 'to: tag' for LLM
    """
    tags = TAGS_PATTERN.findall(message)
    clean_message = TAGS_PATTERN.sub('', message).strip()
    transformed_message = TAGS_PATTERN.sub(r'to: \1', message).strip()
    return tags, clean_message, transformed_message


def split_message_by_tags(message: str, tags: list[str]) -> dict[str, str]:
    """Split message by @tags so each agent gets only their relevant portion.
    
    For "to: analyst to: developer hello":
    - 'analyst' gets "to: analyst hello"
    - 'developer' gets "to: developer hello"
    
    Each agent sees only their 'to:' tag and the user's question (content after last tag).
    """
    if not tags:
        return {}
    
    result = {}
    
    trailing_content = message.split(f'to: {tags[-1]}')[-1].strip() if tags else ""
    
    for tag in tags:
        to_pattern = f'to: {tag}'
        pos = message.find(to_pattern)
        if pos == -1:
            continue
        
        if trailing_content:
            result[tag] = f"to: {tag} {trailing_content}"
        else:
            result[tag] = f"to: {tag}"
    
    return result


def _format_mcp_tools_for_prompt(tools: list[dict]) -> str:
    """Format MCP tools list as a readable section for the system prompt.
    
    This helps models understand what tools are available even if they
    don't automatically use the tools parameter.
    """
    if not tools:
        return ""
    
    lines = [
        "",
        "",
        "# Доступные инструменты (MCP Tools)",
        "",
        "У тебя есть доступ к следующим инструментам. Используй их когда это необходимо:",
        ""
    ]
    
    for tool in tools:
        if "function" in tool:
            name = tool["function"].get("name", "unknown")
            desc = tool["function"].get("description", "")
            params = tool["function"].get("parameters", {})
        else:
            # Anthropic format
            name = tool.get("name", "unknown")
            desc = tool.get("description", "")
            params = tool.get("input_schema", {})
        
        lines.append(f"## {name}")
        lines.append(f"{desc}")
        
        # Add parameter info if available
        if params and isinstance(params, dict):
            properties = params.get("properties", {})
            required = params.get("required", [])
            if properties:
                lines.append("Параметры:")
                for param_name, param_info in properties.items():
                    param_type = param_info.get("type", "any")
                    param_desc = param_info.get("description", "")
                    required_marker = " (обязательный)" if param_name in required else ""
                    lines.append(f"  - {param_name}: {param_type}{required_marker} - {param_desc}")
        lines.append("")
    
    lines.extend([
        "",
        "## Инструкция по использованию инструментов",
        "",
        "Когда пользователь просит выполнить действие, которое может быть выполнено с помощью доступных инструментов,",
        "ты ДОЛЖЕН использовать соответствующий инструмент вместо того, чтобы делать это вручную.",
        "",
        "Для вызова инструмента верни ответ с инструментом (function call) в формате API.",
        ""
    ])
    
    return "\n".join(lines)


class ChatHandler(BaseHandler):
    """Handler for /chat endpoint (non-streaming)."""
    
    def handle(
        self,
        session_id: str,
        message: str,
        provider_name: str | None = None,
        model: str | None = None,
        debug_mode: bool = False,
        user_id: str | None = None,
        tsm_mode: str | None = None,
        use_rag: bool = False,
        rag_index_name: str | None = None,
        rag_top_k: int = 5,
        source: str | None = None,
        agent_role: str | None = None
    ) -> dict[str, Any]:
        """Handle chat request.
        
        Returns:
            dict with 'message', 'session_id', 'model', 'usage', etc.
        """
        session = self.get_session(session_id)
        
        if provider_name or model:
            session.set_provider_model(provider_name or "", model or "")
        
        if tsm_mode:
            try:
                tsm.set_tsm_mode(session, tsm_mode)
            except ValueError as e:
                return {"error": f"Invalid tsm_mode: {str(e)}"}
        
        tags, clean_message, transformed_message = parse_agent_tags(message)
        
        if agent_role:
            session.set_agent_role(agent_role)
        
        session.add_user_message(message, source=source or "web")
        
        debug_collector = self.create_debug_collector(session)
        
        if tags:
            return self._handle_with_tags(
                session, transformed_message, tags, provider_name, model,
                debug_collector, user_id, use_rag, rag_index_name, rag_top_k
            )
        
        context_builder = self.create_context_builder(session, user_id, debug_collector)
        effective_role = session.agent_role or None
        system_prompt = context_builder.build_system_prompt(effective_role)
        system_prompt = context_builder.apply_rag_to_prompt(system_prompt, transformed_message, use_rag)
        messages = context_builder.build_messages(None, effective_role)
        
        mcp_tools = context_builder.build_mcp_tools(provider_name)
        

        # Debug logging for MCP tools
        from app.logger import debug as dbg
        server_names = session.get_mcp_servers()
        dbg("MCP", f"Session MCP servers: {server_names}")
        dbg("MCP", f"Provider: {provider_name}, MCP tools count: {len(mcp_tools) if mcp_tools else 0}")
        # Add MCP tools description to system prompt
        if mcp_tools:
            mcp_tools_description = _format_mcp_tools_for_prompt(mcp_tools)
            if mcp_tools_description:
                system_prompt += mcp_tools_description

                dbg("MCP", f"Added MCP tools description to system_prompt, length={len(mcp_tools_description)}")
            else:
                dbg("MCP", "mcp_tools_description is empty, not adding to prompt")
        
        tsm_mode = tsm.get_tsm_mode(session)
        
        if tsm_mode == "orchestrator":
            return self._handle_orchestrator(
                session, messages, system_prompt, provider_name, model,
                debug_collector, user_id, mcp_tools, effective_role
            )
        
        return self._handle_simple(
            session, messages, system_prompt, provider_name, model,
            debug_collector, user_id, mcp_tools, effective_role
        )
    
    def _handle_with_tags(
        self,
        session: Session,
        llm_message: str,
        tags: list[str],
        provider_name: str | None,
        model: str | None,
        debug_collector: DebugCollector | None,
        user_id: str | None,
        use_rag: bool,
        rag_index_name: str | None,
        rag_top_k: int
    ) -> dict[str, Any]:
        """Handle message with @tags - sequentially call each tagged agent."""
        from app.config import config
        
        valid_agents = config.agents
        warnings = []
        per_agent_messages = split_message_by_tags(llm_message, tags)
        
        for tag in tags:
            if tag not in valid_agents:
                warnings.append(f"Роль @{tag} не найдена, пропускаем.")
                continue
            
            agent_message = per_agent_messages.get(tag, f"to: {tag}")
            
            agent_config = valid_agents[tag]
            effective_role = tag
            
            effective_provider = agent_config.get('provider') or provider_name
            effective_model = agent_config.get('model') or model
            
            agent_settings = {}
            if agent_config.get('temperature') is not None:
                agent_settings['temperature'] = agent_config['temperature']
            if agent_config.get('top_p') is not None:
                agent_settings['top_p'] = agent_config['top_p']
            if agent_config.get('top_k') is not None:
                agent_settings['top_k'] = agent_config['top_k']
            
            context_builder = self.create_context_builder(session, user_id, debug_collector)
            system_prompt = context_builder.build_system_prompt(effective_role)
            system_prompt = context_builder.apply_rag_to_prompt(system_prompt, agent_message, use_rag)
            messages = context_builder.build_messages(agent_message, effective_role)
            
            mcp_tools = context_builder.build_mcp_tools(effective_provider)
            
            # Add MCP tools description to system prompt
            if mcp_tools:
                mcp_tools_description = _format_mcp_tools_for_prompt(mcp_tools)
                if mcp_tools_description:
                    system_prompt += mcp_tools_description
            
            tsm_mode = tsm.get_tsm_mode(session)
            
            if tsm_mode == "orchestrator":
                result = self._handle_orchestrator(
                    session, messages, system_prompt, effective_provider, effective_model,
                    debug_collector, user_id, mcp_tools, effective_role, agent_settings
                )
            else:
                result = self._handle_simple(
                    session, messages, system_prompt, effective_provider, effective_model,
                    debug_collector, user_id, mcp_tools, effective_role, agent_settings
                )
            
            if warnings:
                result["warnings"] = warnings
        
        final_result = {
            "message": session.messages[-1].content if session.messages else "",
            "session_id": session.session_id,
            "model": session.messages[-1].model if session.messages else model,
            "usage": session.messages[-1].usage if session.messages else {},
            "total_tokens": session.total_tokens,
            "agent_role": session.agent_role,
        }
        
        if warnings:
            final_result["warnings"] = warnings
        
        return final_result
    
    def _handle_simple(
        self,
        session: Session,
        messages: list,
        system_prompt: str,
        provider_name: str | None,
        model: str | None,
        debug_collector: DebugCollector | None,
        user_id: str | None,
        mcp_tools: list,
        agent_role: str | None = None,
        agent_settings: dict | None = None
    ) -> dict:
        """Handle simple mode."""
        from app.config import config
        from app.status_validator import validate_status_block
        
        if not provider_name:
            provider_name = config.default_provider
        
        provider_config = config.get_provider_config(provider_name)
        if agent_settings:
            provider_config = provider_config.copy()
            for key, value in agent_settings.items():
                if value is not None:
                    provider_config[key] = value
        
        provider = self.create_provider(provider_name, model, provider_config)
        
        orchestrator = self.create_orchestration_controller(
            provider, session, debug_collector
        )
        
        status_reminder = config.get_context_file("STATUS_REMINDER.md") or ""
        prompt_with_reminder = system_prompt + "\n\n" + status_reminder

        dbg("MCP", f"Final system_prompt length: {len(prompt_with_reminder)}, has MCP tools: {"Доступные инструменты" in prompt_with_reminder}")
        
        response = orchestrator.run_simple(messages, prompt_with_reminder, mcp_tools)
        
        message_for_user = response.content
        
        raw_original = response.content
        parsed_status, cleaned_content = validate_status_block(response.content)
        if parsed_status:
            session.update_status(parsed_status)
            handle_project_updates(session)
            message_for_user = cleaned_content if cleaned_content else response.content
        
        if debug_collector and debug_collector.enabled:
            debug_collector.capture_reasoning(response.reasoning)
            debug_collector.capture_raw_model_response(raw_original)
            debug_collector.capture_session_info(
                session.session_id, 
                provider.model,
                provider.get_provider_name()
            )
            if parsed_status:
                debug_collector.capture_status(parsed_status)
        
        debug_info = debug_collector.get_debug_info() if debug_collector else None
        
        session.add_assistant_message(
            message_for_user,
            response.usage,
            debug=debug_info,
            model=response.model,
            reasoning=response.reasoning,
            agent_role=agent_role
        )
        
        self.save_session(session.session_id)
        
        disabled_indices = [i for i, m in enumerate(session.messages) if m.disabled]
        
        result = {
            "message": message_for_user,
            "session_id": session.session_id,
            "model": response.model,
            "usage": response.usage,
            "total_tokens": session.total_tokens,
            "disabled_indices": disabled_indices,
            "reasoning": response.reasoning,
            "agent_role": agent_role,
            "project": session.status.get("project"),
            "task_name": session.status.get("task_name", "conversation"),
            "state": session.status.get("state"),
        }
        
        if debug_info:
            result["debug"] = debug_info
        
        return result
    
    def _handle_orchestrator(
        self,
        session: Session,
        messages: list,
        system_prompt: str,
        provider_name: str | None,
        model: str | None,
        debug_collector: DebugCollector | None,
        user_id: str | None,
        mcp_tools: list,
        agent_role: str | None = None,
        agent_settings: dict | None = None
    ) -> dict:
        """Handle orchestrator mode."""
        from app.config import config
        
        if not provider_name:
            provider_name = config.default_provider
        
        provider_config = config.get_provider_config(provider_name)
        if agent_settings:
            provider_config = provider_config.copy()
            for key, value in agent_settings.items():
                if value is not None:
                    provider_config[key] = value
        
        provider = self.create_provider(provider_name, model, provider_config)
        
        result = tsm.process_orchestrator_response(
            session=session,
            llm_messages=messages,
            provider=provider,
            system_prompt=system_prompt,
            debug_collector=debug_collector,
            debug_prompt=system_prompt,
            mcp_tools=mcp_tools
        )
        
        final_content = result.get("final_content", "")
        final_reasoning = result.get("reasoning")
        final_status = result.get("final_status")
        usage = result.get("usage", {})
        debug_info = result.get("debug")
        
        if final_status:
            session.update_status(final_status)
            handle_project_updates(session)
        
        session.add_assistant_message(
            final_content,
            usage,
            debug=debug_info,
            model=provider.model,
            reasoning=final_reasoning,
            agent_role=agent_role
        )
        
        self.save_session(session.session_id)
        
        result = {
            "message": final_content,
            "session_id": session.session_id,
            "model": "orchestrator",
            "usage": usage,
            "total_tokens": session.total_tokens,
            "reasoning": final_reasoning,
            "agent_role": agent_role,
            "project": session.status.get("project"),
            "task_name": session.status.get("task_name", "conversation"),
            "state": session.status.get("state"),
        }
        
        if debug_info:
            result["debug"] = debug_info
        
        return result


def data():
    """Placeholder for request data - should be passed in."""
    pass
