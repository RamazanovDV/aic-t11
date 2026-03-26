"""Context builder for LLM requests - handles prompts, RAG, and MCP."""

from typing import TYPE_CHECKING

from app.session import Session
from app.llm.base import Message

if TYPE_CHECKING:
    from app.debug import DebugCollector


class ContextBuilder:
    """Builds context for LLM requests."""
    
    def __init__(self, session: Session, user_id: str | None = None, debug_collector: "DebugCollector | None" = None):
        self.session = session
        self.user_id = user_id
        self.debug_collector = debug_collector
    
    def build_system_prompt(self, agent_role: str | None = None) -> str:
        """Build full system prompt from components."""
        from app.context import (
            get_system_prompt,
            get_profile_prompt,
            get_project_prompt,
            get_status_prompt,
            should_show_interview,
            get_interview_prompt,
            get_role_prompt
        )
        
        system_prompt = get_system_prompt()
        system_prompt += get_profile_prompt(self.session, self.user_id)
        system_prompt += get_project_prompt(self.session)
        system_prompt += get_status_prompt(self.session)
        
        if should_show_interview(self.session, self.user_id):
            system_prompt += get_interview_prompt()
        
        if agent_role:
            role_prompt = get_role_prompt(agent_role)
            if role_prompt:
                system_prompt += "\n\n" + role_prompt
        
        return system_prompt
    
    def build_messages(self, include_user_message: str | None = None, current_agent_role: str | None = None) -> list[Message]:
        """Build messages for LLM."""
        llm_messages = self.session.get_messages_for_llm()
        
        formatted_messages = []
        for msg in llm_messages:
            if msg.role == "summary":
                summary_text = f"До этого вы обсудили следующее:\n{msg.content}"
                if formatted_messages and formatted_messages[0]["role"] == "system":
                    formatted_messages[0]["content"] += f"\n\n{summary_text}"
                else:
                    formatted_messages.insert(0, {"role": "system", "content": summary_text})
            elif msg.role in ("user", "assistant"):
                content = msg.content
                if msg.role == "assistant" and msg.agent_role and msg.agent_role != current_agent_role:
                    content = f"Ответ ассистента с ролью {msg.agent_role}:\n{content}"
                formatted_messages.append({"role": msg.role, "content": content})
        
        if include_user_message:
            formatted_messages.append({"role": "user", "content": include_user_message})
        
        return [Message(role=m["role"], content=m["content"], usage={}) for m in formatted_messages]
    
    def build_rag_context(self, query: str, use_rag: bool = True) -> str:
        """Build RAG context for query."""
        if not use_rag:
            return ""
        
        from app.config import config
        
        saved_rag = self.session.session_settings.get("rag_settings", {})
        global_rag_config = config.get_rag_config()
        
        rag_enabled = saved_rag.get("enabled", global_rag_config.get("enabled", False))
        if not rag_enabled:
            return ""
        
        rag_index_name = saved_rag.get("index_name") or global_rag_config.get("default_index", "")
        if not rag_index_name:
            return ""
        
        rag_version = saved_rag.get("version") or global_rag_config.get("version")
        rag_top_k = saved_rag.get("top_k", global_rag_config.get("top_k", 5))
        rag_reranker = saved_rag.get("reranker", global_rag_config.get("reranker", {}))
        
        say_unknown_enabled = saved_rag.get("say_unknown_enabled", global_rag_config.get("say_unknown_enabled", False))
        say_unknown_threshold = saved_rag.get("say_unknown_threshold", global_rag_config.get("say_unknown_threshold", 0.3))
        
        reranker_config = None
        if rag_reranker and rag_reranker.get("enabled"):
            reranker_config = rag_reranker
        
        try:
            from app.embeddings.search import EmbeddingSearch
            search_engine = EmbeddingSearch()
            results, reranker_meta = search_engine.search(
                query=query,
                index_name=rag_index_name,
                version=rag_version,
                top_k=rag_top_k,
                reranker_config=reranker_config,
            )
            
            max_similarity = max((r.get("similarity", 0) for r in results), default=0) if results else 0
            
            say_unknown_triggered = False
            if say_unknown_enabled and results and max_similarity < say_unknown_threshold:
                say_unknown_triggered = True
                unknown_context = config.context_manager.get_context_file("RAG_UNKNOWN.md")
                if unknown_context:
                    if self.debug_collector and self.debug_collector.enabled:
                        self.debug_collector.capture_rag_info(
                            query=query,
                            index_name=rag_index_name,
                            version=rag_version,
                            top_k=rag_top_k,
                            results=results or [],
                            context_added=unknown_context,
                            reranker_config=reranker_config,
                            reranker_meta=reranker_meta,
                            say_unknown_triggered=say_unknown_triggered,
                            max_similarity=max_similarity,
                            say_unknown_threshold=say_unknown_threshold,
                        )
                    return unknown_context
                return ""
            elif results:
                rag_context = "\n\n## Relevant Context\n"
                for i, result in enumerate(results, 1):
                    metadata = result.get("metadata", {})
                    source = metadata.get("source", "unknown")
                    section = metadata.get("section", "")
                    content = result.get("content", "")
                    rag_context += f"[{i}] Source: {source}"
                    if section:
                        rag_context += f", Section: {section}"
                    rag_context += f"\n{content}\n\n---\n"
                
                if self.debug_collector and self.debug_collector.enabled:
                    self.debug_collector.capture_rag_info(
                        query=query,
                        index_name=rag_index_name,
                        version=rag_version,
                        top_k=rag_top_k,
                        results=results or [],
                        context_added=rag_context,
                        reranker_config=reranker_config,
                        reranker_meta=reranker_meta,
                        say_unknown_triggered=say_unknown_triggered,
                        max_similarity=max_similarity,
                        say_unknown_threshold=say_unknown_threshold,
                    )
                
                return rag_context
            
            if self.debug_collector and self.debug_collector.enabled:
                self.debug_collector.capture_rag_info(
                    query=query,
                    index_name=rag_index_name,
                    version=rag_version,
                    top_k=rag_top_k,
                    results=[],
                    context_added="",
                    reranker_config=reranker_config,
                    reranker_meta=reranker_meta,
                    say_unknown_triggered=False,
                    max_similarity=0,
                    say_unknown_threshold=say_unknown_threshold,
                )
            
        except Exception as e:
            from app.logger import warning
            warning("RAG", f"RAG search error: {e}")
        
        return ""
    
    def build_mcp_tools(self, provider_name: str) -> list[dict]:
        """Build MCP tools for provider."""
        from app.mcp.processor import get_mcp_tools
        import asyncio
        
        server_names = self.session.get_mcp_servers()
        if not server_names:
            return []
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, get_mcp_tools(server_names, provider_name))
                    return future.result()
            else:
                return asyncio.run(get_mcp_tools(server_names, provider_name))
        except Exception:
            return []
    
    def apply_rag_to_prompt(self, prompt: str, query: str, use_rag: bool = True) -> str:
        """Add RAG context to prompt."""
        rag_context = self.build_rag_context(query, use_rag)
        if rag_context:
            return prompt + rag_context
        return prompt


class RAGProcessor:
    """Standalone RAG processing."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def search(self, query: str, **kwargs):
        """Search RAG index."""
        from app.embeddings.search import EmbeddingSearch
        from app.config import config
        
        saved_rag = self.session.session_settings.get("rag_settings", {})
        global_rag_config = config.get_rag_config()
        
        index_name = saved_rag.get("index_name") or global_rag_config.get("default_index", "")
        version = saved_rag.get("version") or global_rag_config.get("version")
        top_k = saved_rag.get("top_k", global_rag_config.get("top_k", 5))
        reranker = saved_rag.get("reranker", global_rag_config.get("reranker", {}))
        
        reranker_config = reranker if reranker.get("enabled") else None
        
        search_engine = EmbeddingSearch()
        return search_engine.search(
            query=query,
            index_name=index_name,
            version=version,
            top_k=top_k,
            reranker_config=reranker_config,
            **kwargs
        )
    
    def should_use_unknown_context(self, results: list[dict]) -> bool:
        """Check if should use RAG_UNKNOWN.md context."""
        from app.config import config
        
        saved_rag = self.session.session_settings.get("rag_settings", {})
        global_rag_config = config.get_rag_config()
        
        say_unknown_enabled = saved_rag.get("say_unknown_enabled", global_rag_config.get("say_unknown_enabled", False))
        say_unknown_threshold = saved_rag.get("say_unknown_threshold", global_rag_config.get("say_unknown_threshold", 0.3))
        
        if not say_unknown_enabled or not results:
            return False
        
        max_similarity = max((r.get("similarity", 0) for r in results), default=0)
        return max_similarity < say_unknown_threshold


class MCPToolLoader:
    """Standalone MCP tool loading."""
    
    @staticmethod
    async def get_tools(session: Session, provider_name: str) -> list[dict]:
        """Get MCP tools for session and provider."""
        from app.mcp.processor import get_mcp_tools
        
        server_names = session.get_mcp_servers()
        if not server_names:
            return []
        
        return await get_mcp_tools(server_names, provider_name)
    
    @staticmethod
    def get_tools_sync(session: Session, provider_name: str) -> list[dict]:
        """Get MCP tools synchronously."""
        import asyncio
        try:
            return asyncio.run(MCPToolLoader.get_tools(session, provider_name))
        except RuntimeError:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, MCPToolLoader.get_tools(session, provider_name))
                return future.result()