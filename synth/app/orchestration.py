"""Orchestration controller for LLM interactions."""

import json
from typing import Generator
from dataclasses import dataclass
from enum import Enum

from app.llm.base import BaseProvider, Message, LLMResponse
from app.session import Session
from app.debug import DebugCollector
from app.async_utils import run_mcp_async


class OrchestratorMode(Enum):
    SIMPLE = "simple"
    ORCHESTRATOR = "orchestrator"
    DETERMINISTIC = "deterministic"


@dataclass
class OrchestratorEvent:
    """Base event from orchestrator."""
    pass


@dataclass
class ContentEvent(OrchestratorEvent):
    """Partial content from orchestrator."""
    content: str
    done: bool = False


@dataclass
class SubtaskStartedEvent(OrchestratorEvent):
    """Subtask started."""
    name: str
    subtask_id: str


@dataclass
class SubtaskCompletedEvent(OrchestratorEvent):
    """Subtask completed."""
    name: str
    subtask_id: str
    result: str


@dataclass
class SubtaskFailedEvent(OrchestratorEvent):
    """Subtask failed."""
    name: str
    subtask_id: str
    error: str


@dataclass
class FinalEvent(OrchestratorEvent):
    """Final response from orchestrator."""
    content: str
    reasoning: str | None = None
    usage: dict | None = None
    debug_info: dict | None = None


class OrchestrationController:
    """Controller for LLM orchestration modes."""
    
    def __init__(
        self,
        provider: BaseProvider,
        session: Session,
        debug_collector: DebugCollector | None = None
    ):
        self.provider = provider
        self.session = session
        self.debug_collector = debug_collector
    
    def run_simple(
        self,
        messages: list[Message],
        system_prompt: str,
        tools: list | None = None
    ) -> LLMResponse:
        """Run simple mode - single LLM call."""
        if self.debug_collector and self.debug_collector.enabled:
            self.debug_collector.capture_api_request(
                url=self.provider.url,
                method="POST",
                headers={"Content-Type": "application/json"},
                body={
                    "model": self.provider.model,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                    "tools": tools
                }
            )
        
        response = self.provider.chat(
            messages,
            system_prompt,
            debug_collector=self.debug_collector,
            tools=tools
        )
        
        if self.debug_collector and self.debug_collector.enabled:
            self.debug_collector.capture_api_response({
                "type": "message",
                "usage": response.usage if response.usage else {}
            })
            self.debug_collector.capture_reasoning(response.reasoning)
            self.debug_collector.capture_session_info(
                self.session.session_id,
                response.model,
                self.provider.get_provider_name()
            )
            if self.session.status:
                self.debug_collector.capture_status(self.session.status)
        
        return response
    
    def run_simple_stream(
        self,
        messages: list[Message],
        system_prompt: str,
        tools: list | None = None
    ) -> Generator:
        """Run simple mode with streaming."""
        if self.debug_collector and self.debug_collector.enabled:
            self.debug_collector.capture_api_request(
                url=self.provider.url,
                method="POST",
                headers={"Content-Type": "application/json"},
                body={
                    "model": self.provider.model,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                    "tools": tools,
                    "stream": True
                }
            )
        
        full_content = ""
        
        for chunk in self.provider.stream_chat(
            messages,
            system_prompt,
            debug_collector=self.debug_collector,
            tools=tools
        ):
            if chunk.content:
                full_content += chunk.content
            
            if self.debug_collector and chunk.reasoning:
                self.debug_collector.capture_reasoning(chunk.reasoning)
            yield chunk
        
        if self.debug_collector and self.debug_collector.enabled:
            self.debug_collector.capture_api_response({
                "type": "stream_delta",
                "usage": chunk.usage if chunk and chunk.usage else {}
            })
            self.debug_collector.capture_raw_model_response(full_content)
            self.debug_collector.capture_session_info(
                self.session.session_id,
                self.provider.model,
                self.provider.get_provider_name()
            )
            if self.session.status:
                self.debug_collector.capture_status(self.session.status)
    
    def run_orchestrator(
        self,
        messages: list[Message],
        system_prompt: str,
        progress_queue=None,
        token_limit: int | None = None,
        stop_event=None
    ) -> dict:
        """Run orchestrator mode with subagents.
        
        This is a sync version that returns a dict with all results.
        For streaming events, use run_orchestrator_stream().
        """
        from app import tsm
        
        result = tsm.process_orchestrator_response(
            session=self.session,
            llm_messages=messages,
            provider=self.provider,
            system_prompt=system_prompt,
            debug_collector=self.debug_collector,
            debug_prompt=system_prompt,
            progress_queue=progress_queue,
            token_limit=token_limit,
            stop_event=stop_event
        )
        
        return result
    
    def save_response(
        self,
        response: LLMResponse,
        group_id: str | None = None
    ) -> None:
        """Save LLM response to session."""
        debug_info = None
        if self.debug_collector:
            debug_info = self.debug_collector.get_debug_info()
        
        self.session.add_assistant_message(
            content=response.content,
            usage=response.usage,
            debug=debug_info,
            model=response.model,
            reasoning=response.reasoning,
            group_id=group_id
        )
    
    def handle_tools(
        self,
        response: LLMResponse,
        messages: list[Message],
        system_prompt: str,
        tools: list,
        max_iterations: int = 10
    ) -> tuple[list[Message], list[dict]]:
        """Handle tool calls in response.
        
        Returns:
            Tuple of (new_messages, tool_results)
        """
        tool_results = []
        
        if not response.tool_calls:
            return [], tool_results
        
        current_tool_calls = response.tool_calls
        tool_iteration = 0
        
        while current_tool_calls and tool_iteration < max_iterations:
            tool_iteration += 1
            
            for tc in current_tool_calls:
                tool_name = tc.get("function", {}).get("name") or tc.get("name", "")
                tool_args = tc.get("function", {}).get("arguments") or tc.get("arguments", {}) or {}
                
                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except Exception:
                        tool_args = {}
                
                try:
                    from app.mcp.processor import call_mcp_tool
                    tool_result_content = run_mcp_async(call_mcp_tool(tool_name, tool_args))
                    is_error = tool_result_content.startswith("Error:")
                except Exception as e:
                    tool_result_content = f"Error: {str(e)}"
                    is_error = True
                
                tool_results.append({
                    "tool": tool_name,
                    "arguments": tool_args,
                    "result": tool_result_content,
                    "is_error": is_error
                })
            
            tool_messages = [
                Message(
                    role="tool",
                    content=tr["result"],
                    tool_call_id=tr.get("id")
                )
                for tr in tool_results
            ]
            
            continuation_messages = messages + [response] + tool_messages
            response = self.provider.chat(
                continuation_messages,
                system_prompt,
                debug_collector=self.debug_collector,
                tools=tools
            )
            
            if not response.tool_calls:
                break
            
            current_tool_calls = response.tool_calls
        
        return tool_messages, tool_results