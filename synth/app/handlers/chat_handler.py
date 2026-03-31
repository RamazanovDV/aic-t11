"""Chat handler for non-streaming requests."""

import re
from typing import Any

from app.handlers.base import BaseHandler
from app.session import Session
from app import tsm
from app.debug import DebugCollector
from app.project_updates import handle_project_updates
from app.logger import debug as dbg


TAGS_PATTERN = re.compile(r'@(\w+)')
SLASH_COMMAND_PATTERN = re.compile(r'^/(\w+)(?:\s+(.*))?$', re.DOTALL)


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


def _format_mcp_tools_for_prompt(tools: list) -> str:
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
        if isinstance(tool, dict) and "function" in tool:
            name = tool["function"].get("name", "unknown")
            desc = tool["function"].get("description", "")
            params = tool["function"].get("parameters", {})
        else:
            # Anthropic format
            name = getattr(tool, "name", tool.get("name", "unknown"))
            desc = getattr(tool, "description", tool.get("description", ""))
            params = getattr(tool, "input_schema", tool.get("input_schema", {}))
        
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


def parse_slash_command(message: str) -> tuple[str | None, str | None, str]:
    """Parse slash command from message.
    
    Returns:
        (command, args, clean_message)
        - command: command name (e.g., 'help')
        - args: arguments after command
        - clean_message: original message (unchanged)
    """
    match = SLASH_COMMAND_PATTERN.match(message.strip())
    if match:
        command = match.group(1).lower()
        args = match.group(2) or ""
        return command, args, message
    return None, None, message


class SlashCommandHandler:
    """Handler for slash commands like /help."""
    
    @staticmethod
    def handle_help(
        session: Session,
        args: str,
        provider_name: str | None,
        model: str | None
    ) -> dict[str, Any]:
        """Handle /help command.
        
        Uses Project RAG and MCP to answer questions about the project.
        """
        from app.config import config
        from app.project_rag import ProjectRAGManager
        from app.llm import ProviderFactory
        from app.llm.base import Message
        
        # Get project path from session status
        project_path = session.status.get("project_path")
        git_repo_path = session.status.get("git_repo_path") or project_path
        
        # Initialize Project RAG Manager
        try:
            rag_manager = ProjectRAGManager()
        except Exception as e:
            return {
                "message": f"Project RAG не доступен: {str(e)}",
                "session_id": session.session_id,
                "is_help_response": True
            }
        
        # Extract question from args
        question = args.strip() if args else "project overview"
        
        # Build context from project documentation
        help_context = rag_manager.build_help_context(
            project_path=project_path or "",
            git_repo_path=git_repo_path
        )
        
        # Search for relevant docs if there's a specific question
        if question and question != "project overview":
            help_result = rag_manager.answer_help_question(
                project_path=project_path or "",
                question=question,
                use_mcp=True,
                git_repo_path=git_repo_path
            )
            additional_context = help_result.get("context", "")
        else:
            additional_context = ""
        
        # Build the prompt for LLM
        if not project_path:
            return {
                "message": "Проект не подключён. Используйте команду /project <path> для подключения проекта.",
                "session_id": session.session_id,
                "is_help_response": True
            }
        
        # Build help system prompt
        help_system_prompt = f"""Ты - помощник по проекту. Отвечай на вопросы о проекте на основе предоставленной документации.

## Контекст проекта
{help_context}

## Дополнительная информация
{additional_context}

Отвечай на русском языке. Если информации недостаточно - так и скажи.
"""
        
        # Create LLM request
        if not provider_name:
            provider_name = config.default_provider
        
        provider_config = config.get_provider_config(provider_name)
        provider = ProviderFactory.create(provider_name, provider_config)
        
        user_message = Message(
            role="user",
            content=question
        )
        
        try:
            response = provider.chat(
                messages=[user_message],
                system_prompt=help_system_prompt
            )
            
            return {
                "message": response.content,
                "session_id": session.session_id,
                "model": response.model,
                "usage": response.usage,
                "is_help_response": True,
                "sources": rag_manager.search_project(
                    project_path, question, limit=3
                ) if question != "project overview" else []
            }
        except Exception as e:
            return {
                "message": f"Ошибка при получении ответа: {str(e)}",
                "session_id": session.session_id,
                "is_help_response": True,
                "error": str(e)
            }
    
    @staticmethod
    def get_available_commands() -> list[dict[str, str]]:
        """Get list of available slash commands."""
        return [
            {
                "command": "help",
                "description": "Ответить на вопрос о проекте",
                "usage": "/help <вопрос>"
            },
            {
                "command": "index",
                "description": "Переиндексировать документацию проекта",
                "usage": "/index"
            },
            {
                "command": "project",
                "description": "Подключить проект",
                "usage": "/project <путь>"
            },
        ]


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
        
        # Check for slash commands
        command, args, original_message = parse_slash_command(message)
        
        if command:
            return self._handle_slash_command(
                session, command, args, provider_name, model
            )
        
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
    
    def _handle_slash_command(
        self,
        session: Session,
        command: str,
        args: str,
        provider_name: str | None,
        model: str | None
    ) -> dict[str, Any]:
        """Handle slash commands."""
        from app.project_rag import ProjectRAGManager
        
        if command == "help":
            return SlashCommandHandler.handle_help(session, args, provider_name, model)
        
        elif command == "index":
            # Re-index project documentation
            project_path = session.status.get("project_path")
            if not project_path:
                return {
                    "message": "Проект не подключён. Используйте /project <path>",
                    "session_id": session.session_id,
                    "is_command_response": True
                }
            
            try:
                rag_manager = ProjectRAGManager()
                result = rag_manager.index_project(project_path)
                
                total = sum(result.get("indexed", {}).values())
                return {
                    "message": f"Документация проиндексирована: {total} файлов.\n\n"
                              f"- README: {result['indexed'].get('readme', 0)}\n"
                              f"- docs/: {result['indexed'].get('docs', 0)}\n"
                              f"- schemas: {result['indexed'].get('schemas', 0)}\n"
                              f"- API: {result['indexed'].get('api', 0)}",
                    "session_id": session.session_id,
                    "is_command_response": True,
                    "index_result": result
                }
            except Exception as e:
                return {
                    "message": f"Ошибка индексации: {str(e)}",
                    "session_id": session.session_id,
                    "is_command_response": True,
                    "error": str(e)
                }
        
        elif command == "project":
            # Connect to a project
            if not args:
                return {
                    "message": "Укажите путь к проекту: /project <путь>",
                    "session_id": session.session_id,
                    "is_command_response": True
                }
            
            from pathlib import Path
            project_path = Path(args.strip()).resolve()
            
            if not project_path.exists():
                return {
                    "message": f"Проект не найден: {project_path}",
                    "session_id": session.session_id,
                    "is_command_response": True
                }
            
            # Update session status
            session.status["project_path"] = str(project_path)
            session.status["git_repo_path"] = str(project_path)
            
            # Index the project
            try:
                rag_manager = ProjectRAGManager()
                index_result = rag_manager.index_project(str(project_path))
                total = sum(index_result.get("indexed", {}).values())
                
                return {
                    "message": f"Проект подключён: {project_path}\n\n"
                              f"Проиндексировано файлов: {total}\n\n"
                              f"Используйте /help для вопросов о проекте.",
                    "session_id": session.session_id,
                    "is_command_response": True,
                    "project_path": str(project_path),
                    "index_result": index_result
                }
            except Exception as e:
                return {
                    "message": f"Проект подключён: {project_path}\n"
                              f"Ошибка индексации: {str(e)}\n\n"
                              f"Используйте /index для повторной индексации.",
                    "session_id": session.session_id,
                    "is_command_response": True,
                    "project_path": str(project_path),
                    "index_error": str(e)
                }
        
        elif command == "git":
            # Git operations via MCP
            from app.mcp import MCPManager
            
            project_path = session.status.get("git_repo_path") or session.status.get("project_path")
            
            if not project_path:
                return {
                    "message": "Git репозиторий не подключён.",
                    "session_id": session.session_id,
                    "is_command_response": True
                }
            
            subcommand = args.strip().split()[0] if args.strip() else "status"
            
            try:
                if subcommand == "branch":
                    result = MCPManager.call_tool("git_git_branch", {"repo_path": project_path})
                elif subcommand == "status":
                    result = MCPManager.call_tool("git_git_status", {"repo_path": project_path, "short": True})
                elif subcommand == "diff":
                    result = MCPManager.call_tool("git_git_diff", {"repo_path": project_path})
                elif subcommand == "log":
                    result = MCPManager.call_tool("git_git_log", {"repo_path": project_path, "max_count": 5})
                else:
                    result = MCPManager.call_tool("git_git_status", {"repo_path": project_path})
                
                if result.is_error:
                    return {
                        "message": f"Ошибка: {result.content}",
                        "session_id": session.session_id,
                        "is_command_response": True
                    }
                
                return {
                    "message": result.content,
                    "session_id": session.session_id,
                    "is_command_response": True
                }
            except Exception as e:
                return {
                    "message": f"Git MCP не доступен: {str(e)}\n\n"
                              f"Используйте /help <вопрос о git> для получения справки.",
                    "session_id": session.session_id,
                    "is_command_response": True
                }
        
        elif command == "commands":
            # List available commands
            commands = SlashCommandHandler.get_available_commands()
            msg_parts = ["Доступные команды:"]
            for cmd in commands:
                msg_parts.append(f"\n**{cmd['usage']}** - {cmd['description']}")
            
            return {
                "message": "".join(msg_parts),
                "session_id": session.session_id,
                "is_command_response": True,
                "commands": commands
            }
        
        else:
            return {
                "message": f"Неизвестная команда: /{command}\n\n"
                          f"Используйте /commands для списка доступных команд.",
                "session_id": session.session_id,
                "is_command_response": True
            }
    
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
