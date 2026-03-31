"""Stream handler for SSE streaming requests."""

import re
from typing import Generator

from app.handlers.base import BaseHandler
from app.session import Session
from app.debug import DebugCollector
from app.llm.base import Message, LLMChunk
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


class StreamHandler(BaseHandler):
    """Handler for /chat/stream endpoint (SSE streaming)."""
    
    def handle(
        self,
        session_id: str,
        message: str,
        provider_name: str | None = None,
        model: str | None = None,
        debug_mode: bool = False,
        user_id: str | None = None,
        source: str | None = None,
        agent_role: str | None = None
    ) -> Generator[str, None, None]:
        """Handle stream request.
        
        Yields:
            SSE formatted strings
        """
        session = self.get_session(session_id)
        
        if provider_name or model:
            session.set_provider_model(provider_name or "", model or "")
        
        tags, clean_message, transformed_message = parse_agent_tags(message)
        
        if agent_role:
            session.set_agent_role(agent_role)
        
        session.add_user_message(message, source=source or "web")
        
        debug_collector = self.create_debug_collector(session)
        
        if tags:
            yield from self._handle_with_tags(
                session, transformed_message, tags, provider_name, model,
                debug_collector, user_id
            )
            return
        
        context_builder = self.create_context_builder(session, user_id, debug_collector)
        effective_role = session.agent_role or None
        system_prompt = context_builder.build_system_prompt(effective_role)
        system_prompt = context_builder.apply_rag_to_prompt(system_prompt, transformed_message)
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
        
        from app.config import config
        if not provider_name:
            provider_name = config.default_provider
        
        provider = self.create_provider(provider_name, model)
        
        from app import tsm
        tsm_mode = tsm.get_tsm_mode(session)
        
        if tsm_mode == "orchestrator":
            yield from self._handle_orchestrator_stream(
                session, messages, system_prompt, provider, debug_collector, transformed_message, provider_name, model, mcp_tools, effective_role
            )
        else:
            yield from self._handle_simple_stream(
                session, messages, system_prompt, provider, debug_collector, mcp_tools, effective_role
            )
    
    def _handle_with_tags(
        self,
        session: Session,
        llm_message: str,
        tags: list[str],
        provider_name: str | None,
        model: str | None,
        debug_collector: DebugCollector | None,
        user_id: str | None
    ) -> Generator[str, None, None]:
        """Handle message with @tags - sequentially call each tagged agent."""
        import json
        from app.config import config
        
        valid_agents = config.agents
        warnings = []
        per_agent_messages = split_message_by_tags(llm_message, tags)
        
        valid_tag_indices = [i for i, tag in enumerate(tags) if tag in valid_agents]
        has_valid_agents = len(valid_tag_indices) > 0
        
        for tag_idx, tag in enumerate(tags):
            if tag not in valid_agents:
                warnings.append(f"Роль @{tag} не найдена, пропускаем.")
                continue
            
            is_last_agent = (tag_idx == valid_tag_indices[-1])
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
            system_prompt = context_builder.apply_rag_to_prompt(system_prompt, agent_message)
            messages = context_builder.build_messages(agent_message, effective_role)
            mcp_tools = context_builder.build_mcp_tools(effective_provider)
            
            # Add MCP tools description to system prompt
            if mcp_tools:
                mcp_tools_description = _format_mcp_tools_for_prompt(mcp_tools)
                if mcp_tools_description:
                    system_prompt += mcp_tools_description
            
            if not effective_provider:
                effective_provider = config.default_provider
            
            provider_config = config.get_provider_config(effective_provider)
            if agent_settings:
                provider_config = provider_config.copy()
                for key, value in agent_settings.items():
                    if value is not None:
                        provider_config[key] = value
            
            provider = self.create_provider(effective_provider, effective_model, provider_config)
            
            from app import tsm
            tsm_mode = tsm.get_tsm_mode(session)
            
            if tsm_mode == "orchestrator":
                yield from self._handle_orchestrator_stream(
                    session, messages, system_prompt, provider, debug_collector, agent_message, effective_provider, effective_model, mcp_tools, effective_role,
                    send_done_marker=is_last_agent
                )
            else:
                yield from self._handle_simple_stream(
                    session, messages, system_prompt, provider, debug_collector, mcp_tools, effective_role,
                    send_done_marker=is_last_agent
                )
        
        if has_valid_agents:
            yield "data: [DONE]\n\n"
        
        if warnings:
            yield f"data: {json.dumps({'type': 'warnings', 'warnings': warnings})}\n\n"
    
    def _handle_simple_stream(
        self,
        session: Session,
        messages: list,
        system_prompt: str,
        provider,
        debug_collector: DebugCollector | None,
        mcp_tools: list,
        agent_role: str | None = None,
        send_done_marker: bool = True
    ) -> Generator[str, None, None]:
        """Handle simple mode with streaming."""
        import json
        
        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})
        
        for msg in messages:
            if msg.role == "summary":
                summary_text = f"До этого вы обсудили следующее:\n{msg.content}"
                if formatted_messages and formatted_messages[0]["role"] == "system":
                    formatted_messages[0]["content"] += f"\n\n{summary_text}"
                else:
                    formatted_messages.insert(0, {"role": "system", "content": summary_text})
            elif msg.role in ("user", "assistant"):
                formatted_messages.append({"role": msg.role, "content": msg.content})
        
        llm_msgs = [Message(role=m["role"], content=m["content"], usage={}) for m in formatted_messages]
        
        tool_calls_handled = False
        full_content = ""
        full_reasoning = ""
        total_usage = {}
        
        try:
            stream_generator = provider.stream_chat(
                llm_msgs, None, debug_collector=debug_collector, tools=mcp_tools
            )
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
            return
        
        tool_group_id = None
        tool_debug_info = None
        
        for chunk in stream_generator:
            if chunk.tool_calls and not tool_calls_handled:
                tool_calls_handled = True
                result = yield from self._handle_tool_calls(
                    session, provider, chunk, debug_collector, mcp_tools, llm_msgs
                )
                if result:
                    final_chunk, tool_group_id, tool_debug_info = result
                    if final_chunk:
                        full_content = final_chunk.content or ""
                        full_reasoning = final_chunk.reasoning or ""
                        total_usage = final_chunk.usage or {}
                continue
            
            if chunk.is_final:
                total_usage = chunk.usage
                continue
            
            if chunk.content:
                full_content += chunk.content
            
            if chunk.reasoning:
                full_reasoning += chunk.reasoning
            
            total_usage = chunk.usage
            
            yield f"data: {json.dumps({'content': full_content, 'reasoning': full_reasoning, 'done': False})}\n\n"
        
        if debug_collector and debug_collector.enabled:
            debug_collector.capture_reasoning(full_reasoning)
            debug_collector.capture_raw_model_response(full_content)
            debug_collector.capture_session_info(
                session.session_id, provider.model, provider.get_provider_name()
            )
            if session.status:
                debug_collector.capture_status(session.status)
        
        debug_info = debug_collector.get_debug_info() if debug_collector else None
        
        if not tool_calls_handled:
            session.add_assistant_message(
                full_content,
                total_usage,
                debug=debug_info,
                model=provider.model,
                reasoning=full_reasoning,
                agent_role=agent_role
            )
        
        from app.status_validator import validate_status_block
        parsed_status, cleaned_content = validate_status_block(full_content)
        if parsed_status:
            session.update_status(parsed_status)
            handle_project_updates(session)
        
        self.save_session(session.session_id)
        
        disabled_indices = [i for i, m in enumerate(session.messages) if m.disabled]
        
        yield f"data: {json.dumps({'content': full_content, 'reasoning': full_reasoning, 'done': True, 'usage': total_usage, 'model': provider.model, 'debug': debug_info, 'disabled_indices': disabled_indices, 'agent_role': agent_role, 'project': session.status.get('project'), 'task_name': session.status.get('task_name', 'conversation'), 'state': session.status.get('state')})}\n\n"
        
        if send_done_marker:
            yield "data: [DONE]\n\n"
    
    def _handle_tool_calls(
        self,
        session: Session,
        provider,
        chunk,
        debug_collector: DebugCollector | None,
        mcp_tools: list,
        llm_msgs: list
    ) -> Generator[str, tuple[LLMChunk | None, str | None, dict | None], None]:
        """Handle tool calls. Yields tool results, returns (final_chunk, group_id, debug_info)."""
        import json
        import uuid
        
        group_id = str(uuid.uuid4())
        
        tool_debug = None
        if debug_collector and debug_collector.enabled:
            tool_debug = debug_collector.get_debug_info()
        if not tool_debug:
            tool_debug = {"usage": chunk.usage or {}, "model": provider.model}
        
        session.add_assistant_message(
            chunk.content or "",
            chunk.usage or {},
            debug=tool_debug,
            model=provider.model,
            reasoning=chunk.reasoning,
            tool_use=chunk.tool_calls,
            group_id=group_id
        )
        
        current_tool_calls = chunk.tool_calls
        max_tool_iterations = 10
        tool_iteration = 0
        
        accumulated_msgs = list(llm_msgs)
        final_response = None
        
        while current_tool_calls and tool_iteration < max_tool_iterations:
            tool_iteration += 1
            
            tool_results = []
            
            for tc in current_tool_calls:
                tool_name = tc.get("function", {}).get("name") or tc.get("name", "")
                tool_args = tc.get("function", {}).get("arguments") or tc.get("arguments", {}) or {}
                tool_call_id = tc.get("id", "")
                
                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except:
                        tool_args = {}
                
                from app.mcp.processor import call_mcp_tool
                from app.routes import run_mcp_async
                
                try:
                    tool_result_content = run_mcp_async(call_mcp_tool(tool_name, tool_args))
                except Exception as e:
                    tool_result_content = f"Error: {str(e)}"
                
                if debug_collector and debug_collector.enabled:
                    debug_collector.capture_mcp_call(
                        tool=tool_name,
                        arguments=tool_args,
                        result=tool_result_content,
                        is_error=tool_result_content.startswith("Error:")
                    )
                
                tool_msg = Message(role="tool", content=tool_result_content, tool_call_id=tool_call_id, group_id=group_id)
                tool_results.append(tool_msg)
                session.messages.append(tool_msg)
                
                yield f"data: {json.dumps({'type': 'tool_result', 'tool': tool_name, 'result': tool_result_content[:500]})}\n\n"
            
            assistant_msg = Message(
                role="assistant",
                content=chunk.content or "",
                tool_use=chunk.tool_calls if hasattr(chunk, 'tool_calls') else None,
                reasoning=chunk.reasoning if hasattr(chunk, 'reasoning') else None,
                usage=chunk.usage if hasattr(chunk, 'usage') else {}
            )
            
            accumulated_msgs.append(assistant_msg)
            accumulated_msgs.extend(tool_results)
            
            response = provider.chat(accumulated_msgs, None, debug_collector=debug_collector, tools=mcp_tools)
            
            final_response = response
            
            if response.tool_calls:
                current_tool_calls = response.tool_calls
                chunk = response
            else:
                break
        
        if final_response:
            reasoning = final_response.reasoning if hasattr(final_response, 'reasoning') and final_response.reasoning else None
            if not reasoning and final_response.content:
                for block in (final_response.content if isinstance(final_response.content, list) else []):
                    if block.get("type") == "thinking":
                        reasoning = block.get("thinking", "")
                        break
            
            raw_content = final_response.content or ""
            if isinstance(raw_content, list):
                text_parts = []
                for block in raw_content:
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "thinking":
                        text_parts.append(f"[THINKING]{block.get('thinking', '')}[/THINKING]")
                raw_content = "\n".join(text_parts)
            
            if debug_collector and debug_collector.enabled:
                debug_collector.capture_reasoning(reasoning)
                debug_collector.capture_raw_model_response(raw_content)
                debug_collector.capture_session_info(
                    session.session_id, provider.model, provider.get_provider_name()
                )
                if session.status:
                    debug_collector.capture_status(session.status)
            
            debug_info = debug_collector.get_debug_info() if debug_collector else None
            
            session.add_assistant_message(
                final_response.content or "",
                final_response.usage or {},
                debug=debug_info,
                model=provider.model,
                reasoning=reasoning,
                group_id=group_id
            )
            
            yield "data: [DONE]\n\n"
            return (
                LLMChunk(
                    content=final_response.content or "",
                    is_final=True,
                    usage=final_response.usage or {},
                    tool_calls=None,
                    reasoning=reasoning
                ),
                group_id,
                debug_info
            )
        
        yield "data: [DONE]\n\n"
        return None, None, None
    
    def _handle_orchestrator_stream(
        self,
        session: Session,
        messages: list,
        system_prompt: str,
        provider,
        debug_collector: DebugCollector | None,
        user_message: str,
        provider_name: str,
        model: str | None,
        mcp_tools: list,
        agent_role: str | None = None,
        send_done_marker: bool = True
    ) -> Generator[str, None, None]:
        """Handle orchestrator mode with streaming events."""
        import json
        import queue
        import threading
        import time
        from app.config import config
        from app import tsm
        
        use_rag = session.session_settings.get("rag_settings", {}).get("enabled", False)
        if use_rag:
            pass  # RAG already applied in handle() method
        
        progress_queue = queue.Queue()
        result_queue = queue.Queue(maxsize=1)
        stop_event = threading.Event()
        
        ORCHESTRATOR_TIMEOUT = config.orchestrator_timeout
        
        model_config = config.get_provider_config(provider_name)
        model_name = model or provider.model
        context_window = config.get_context_window(model_name)
        token_limit = int(context_window * 0.9)
        
        session_manager = self.session_manager
        
        def run_orchestrator():
            try:
                result = tsm.process_orchestrator_response(
                    session=session,
                    llm_messages=messages,
                    provider=provider,
                    system_prompt=system_prompt,
                    debug_collector=debug_collector,
                    debug_prompt=system_prompt,
                    progress_queue=progress_queue,
                    token_limit=token_limit,
                    stop_event=stop_event,
                    mcp_tools=mcp_tools
                )
                
                final_content = result.get("final_content", "")
                if final_content:
                    try:
                        session.add_assistant_message(
                            final_content,
                            result.get("usage", {}),
                            debug=result.get("debug"),
                            model=provider.model,
                            reasoning=result.get("reasoning"),
                            agent_role=agent_role
                        )
                        handle_project_updates(session)
                        session_manager.save_session(session.session_id)
                    except Exception:
                        pass
                
                result_queue.put(("success", result))
            except Exception as e:
                result_queue.put(("error", str(e)))
        
        orchestrator_thread = threading.Thread(target=run_orchestrator)
        orchestrator_thread.start()
        
        timeout_warning_sent = False
        start_time = time.time()
        
        while orchestrator_thread.is_alive():
            elapsed = time.time() - start_time
            
            if elapsed > ORCHESTRATOR_TIMEOUT and not timeout_warning_sent:
                yield f"data: {json.dumps({'type': 'timeout_warning', 'elapsed': round(elapsed)})}\n\n"
                timeout_warning_sent = True
            
            try:
                event = progress_queue.get(timeout=0.3)
                
                if event.get('type') == 'orchestrator_content':
                    content = event.get('content', '')
                    try:
                        yield f"data: {json.dumps({'type': 'orchestrator_content', 'content': content, 'done': False, 'subtasks': event.get('subtasks', [])})}\n\n"
                    except Exception:
                        pass
                
                elif event.get('type') == 'subtask_progress':
                    try:
                        yield f"data: {json.dumps({'type': 'subtask_progress', 'name': event.get('name'), 'status': event.get('status'), 'error': event.get('error')})}\n\n"
                    except Exception:
                        pass
            
            except queue.Empty:
                continue
        
        orchestrator_thread.join(timeout=60)
        
        result_type = None
        result = None
        
        try:
            result_type, result = result_queue.get(timeout=5)
        except queue.Empty:
            pass
        
        if result_type == "error" or result is None:
            yield f"data: {json.dumps({'type': 'error', 'error': 'Orchestrator thread did not complete in time'})}\n\n"
            yield "data: [DONE]\n\n"
            return
        
        final_content = result.get("final_content", "")
        final_reasoning = result.get("reasoning")
        subtask_results = result.get("subtask_results", [])
        debug_info = result.get("debug")
        was_aborted = result.get("aborted", False)
        usage = result.get("usage", {})
        
        try:
            for i in range(0, len(final_content), 50):
                chunk = final_content[i:i+50]
                try:
                    yield f"data: {json.dumps({'content': chunk, 'done': False})}\n\n"
                except Exception:
                    pass
            
            disabled_indices = [i for i, m in enumerate(session.messages) if m.disabled]
            
            try:
                yield f"data: {json.dumps({'content': final_content, 'reasoning': final_reasoning, 'done': True, 'usage': usage, 'model': provider.model, 'subtask_results': subtask_results, 'debug': debug_info, 'disabled_indices': disabled_indices, 'aborted': was_aborted, 'agent_role': agent_role, 'project': session.status.get('project'), 'task_name': session.status.get('task_name', 'conversation'), 'state': session.status.get('state')})}\n\n"
            except Exception:
                pass
            
            try:
                if send_done_marker:
                    yield "data: [DONE]\n\n"
            except Exception:
                pass
        except Exception:
            pass
