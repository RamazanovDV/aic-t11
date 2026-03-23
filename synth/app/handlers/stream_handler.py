"""Stream handler for SSE streaming requests."""

from typing import Generator

from app.handlers.base import BaseHandler
from app.session import Session
from app.debug import DebugCollector


class StreamHandler(BaseHandler):
    """Handler for /chat/stream endpoint (SSE streaming)."""
    
    def handle(
        self,
        session_id: str,
        message: str,
        provider_name: str | None = None,
        model: str | None = None,
        debug_mode: bool = False,
        user_id: str | None = None
    ) -> Generator[str, None, None]:
        """Handle stream request.
        
        Yields:
            SSE formatted strings
        """
        session = self.get_session(session_id)
        
        session.add_user_message(message, source="web")
        
        debug_collector = self.create_debug_collector(session)
        
        context_builder = self.create_context_builder(session, user_id)
        system_prompt = context_builder.build_system_prompt()
        
        system_prompt = context_builder.apply_rag_to_prompt(system_prompt, message)
        
        messages = context_builder.build_messages(message)
        mcp_tools = context_builder.build_mcp_tools(provider_name)
        
        # Set default provider if not specified
        from app.config import config
        if not provider_name:
            provider_name = config.default_provider
        
        provider = self.create_provider(provider_name, model)
        
        from app import tsm
        tsm_mode = tsm.get_tsm_mode(session)
        
        if tsm_mode == "orchestrator":
            yield from self._handle_orchestrator_stream(
                session, messages, system_prompt, provider, debug_collector, message, provider_name, model
            )
        else:
            yield from self._handle_simple_stream(
                session, messages, system_prompt, provider, debug_collector, mcp_tools
            )
    
    def _handle_simple_stream(
        self,
        session: Session,
        messages: list,
        system_prompt: str,
        provider,
        debug_collector: DebugCollector | None,
        mcp_tools: list
    ) -> Generator[str, None, None]:
        """Handle simple mode with streaming."""
        import json
        from app.llm.base import Message
        
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
        preliminary_saved = False
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
        
        for chunk in stream_generator:
            if chunk.tool_calls and not tool_calls_handled:
                tool_calls_handled = True
                yield from self._handle_tool_calls(
                    session, provider, chunk, debug_collector, mcp_tools, llm_msgs
                )
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
        
        session.add_assistant_message(
            full_content,
            total_usage,
            debug=debug_info,
            model=provider.model,
            reasoning=full_reasoning
        )
        
        self.save_session(session.session_id)
        
        disabled_indices = [i for i, m in enumerate(session.messages) if m.disabled]
        
        yield f"data: {json.dumps({'content': full_content, 'reasoning': full_reasoning, 'done': True, 'usage': total_usage, 'model': provider.model, 'debug': debug_info, 'disabled_indices': disabled_indices})}\n\n"
        
        yield "data: [DONE]\n\n"
    
    def _handle_tool_calls(
        self,
        session: Session,
        provider,
        chunk,
        debug_collector: DebugCollector | None,
        mcp_tools: list,
        llm_msgs: list
    ) -> Generator[str, None, None]:
        """Handle tool calls."""
        import json
        import uuid
        
        tool_use = chunk.tool_calls
        group_id = str(uuid.uuid4())
        
        session.add_assistant_message(
            chunk.content or "",
            chunk.usage or {},
            debug={"usage": chunk.usage or {}, "model": provider.model},
            model=provider.model,
            reasoning=chunk.reasoning,
            group_id=group_id
        )
        preliminary_saved = True
        
        current_tool_calls = chunk.tool_calls
        max_tool_iterations = 10
        tool_iteration = 0
        
        while current_tool_calls and tool_iteration < max_tool_iterations:
            tool_iteration += 1
            
            for tc in current_tool_calls:
                tool_name = tc.get("function", {}).get("name") or tc.get("name", "")
                tool_args = tc.get("function", {}).get("arguments") or tc.get("arguments", {}) or {}
                
                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except:
                        tool_args = {}
                
                from app.mcp import MCPManager
                import asyncio
                
                try:
                    result = asyncio.run(MCPManager.call_tool(tool_name, tool_args))
                    tool_result_content = result.content
                except Exception as e:
                    tool_result_content = f"Error: {str(e)}"
                
                tool_result_msg = {
                    "role": "tool",
                    "content": tool_result_content
                }
                
                yield f"data: {json.dumps({'type': 'tool_result', 'tool': tool_name, 'result': tool_result_content[:500]})}\n\n"
            
            tool_messages = [
                {"role": "tool", "content": tr.get("content", "")}
                for tr in [tool_result_msg]
            ]
            
            continuation = llm_msgs + [chunk] + [Message(role="tool", content=tool_result_msg["content"])]
            
            response = provider.chat(continuation, None, debug_collector=debug_collector, tools=mcp_tools)
            
            if response.tool_calls:
                current_tool_calls = response.tool_calls
            else:
                break
        
        yield "data: [DONE]\n\n"
    
    def _handle_orchestrator_stream(
        self,
        session: Session,
        messages: list,
        system_prompt: str,
        provider,
        debug_collector: DebugCollector | None,
        user_message: str,
        provider_name: str,
        model: str | None
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
            # context_builder was in handle() method, need to recreate or pass it
            pass  # RAG already applied in handle() method
        
        progress_queue = queue.Queue()
        result_queue = queue.Queue()
        stop_event = threading.Event()
        
        ORCHESTRATOR_TIMEOUT = config.orchestrator_timeout
        
        model_config = config.get_provider_config(provider_name)
        model_name = model or provider.model
        context_window = config.get_context_window(model_name)
        token_limit = int(context_window * 0.9)
        
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
                    stop_event=stop_event
                )
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
                    yield f"data: {json.dumps({'type': 'orchestrator_content', 'content': content, 'done': False, 'subtasks': event.get('subtasks', [])})}\n\n"
                
                elif event.get('type') == 'subtask_progress':
                    yield f"data: {json.dumps({'type': 'subtask_progress', 'name': event.get('name'), 'status': event.get('status'), 'error': event.get('error')})}\n\n"
            
            except queue.Empty:
                continue
        
        orchestrator_thread.join(timeout=10)
        
        result_type, result = result_queue.get()
        
        if result_type == "error":
            yield f"data: {json.dumps({'type': 'error', 'error': str(result)})}\n\n"
            yield "data: [DONE]\n\n"
            return
        
        final_content = result.get("final_content", "")
        final_reasoning = result.get("reasoning")
        subtask_results = result.get("subtask_results", [])
        debug_info = result.get("debug")  # Get from result regardless of enabled check
        was_aborted = result.get("aborted", False)
        usage = result.get("usage", {})
        
        for i in range(0, len(final_content), 50):
            chunk = final_content[i:i+50]
            yield f"data: {json.dumps({'content': chunk, 'done': False})}\n\n"
        
        session.add_assistant_message(
            final_content,
            usage,
            debug=debug_info,
            model=provider.model,
            reasoning=final_reasoning
        )
        
        self.save_session(session.session_id)
        
        disabled_indices = [i for i, m in enumerate(session.messages) if m.disabled]
        
        yield f"data: {json.dumps({'content': final_content, 'reasoning': final_reasoning, 'done': True, 'usage': usage, 'model': provider.model, 'subtask_results': subtask_results, 'debug': debug_info, 'disabled_indices': disabled_indices, 'aborted': was_aborted})}\n\n"
        
        yield "data: [DONE]\n\n"