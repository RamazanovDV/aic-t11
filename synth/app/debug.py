from typing import Any


API_KEY_MASK = "***"


class DebugCollector:
    def __init__(self, enabled: bool = False):
        self._enabled = enabled
        self._api_request: dict | None = None
        self._api_response: dict | None = None
        self._raw_model_response: str | None = None
        self._reasoning: str | None = None
        self._status: dict | None = None
        self._session_info: dict | None = None
        self._subagents: list[dict] = []
        self._mcp_calls: list[dict] = []
        self._rag_info: dict | None = None

    @classmethod
    def from_session(cls, session) -> "DebugCollector":
        enabled = session.session_settings.get("debug_enabled", True)  # Default True for new sessions
        return cls(enabled=enabled)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def capture_api_request(
        self,
        url: str,
        method: str,
        headers: dict[str, Any],
        body: dict[str, Any],
    ) -> None:
        if not self._enabled:
            return
        masked_headers = {}
        for k, v in headers.items():
            if k.lower() in ("authorization", "x-api-key", "api-key"):
                masked_headers[k] = API_KEY_MASK
            else:
                masked_headers[k] = v
        self._api_request = {
            "url": url,
            "method": method,
            "headers": masked_headers,
            "body": body,
        }

    def capture_api_response(self, response: dict[str, Any]) -> None:
        if not self._enabled:
            return
        self._api_response = response

    def capture_raw_model_response(self, content: str) -> None:
        if not self._enabled:
            return
        self._raw_model_response = content

    def capture_reasoning(self, reasoning: str | None) -> None:
        if not self._enabled or not reasoning:
            return
        self._reasoning = reasoning

    def capture_status(self, status: dict | None) -> None:
        if not self._enabled or not status:
            return
        self._status = status

    def capture_session_info(self, session_id: str, model: str, provider: str) -> None:
        if not self._enabled:
            return
        self._session_info = {
            "session_id": session_id,
            "model": model,
            "provider": provider,
        }

    def capture_subagent_start(
        self,
        name: str,
        prompt: str,
    ) -> int:
        if not self._enabled:
            return -1
        index = len(self._subagents)
        self._subagents.append({
            "name": name,
            "prompt": prompt,
            "messages": [],
            "response": None,
        })
        return index

    def capture_subagent_message(self, index: int, role: str, content: str) -> None:
        if not self._enabled or index < 0:
            return
        if index < len(self._subagents):
            self._subagents[index]["messages"].append({
                "role": role,
                "content": content,
            })

    def capture_subagent_response(self, index: int, response: str) -> None:
        if not self._enabled or index < 0:
            return
        if index < len(self._subagents):
            self._subagents[index]["response"] = response

    def capture_mcp_call(
        self,
        tool: str,
        arguments: dict[str, Any],
        result: str,
        is_error: bool = False,
    ) -> None:
        if not self._enabled:
            return
        self._mcp_calls.append({
            "tool": tool,
            "arguments": arguments,
            "result": result,
            "is_error": is_error,
        })

    def capture_rag_info(
        self,
        query: str,
        index_name: str,
        version: int | None,
        top_k: int,
        results: list[dict],
        context_added: str,
    ) -> None:
        if not self._enabled:
            return
        self._rag_info = {
            "query": query,
            "index_name": index_name,
            "version": version,
            "top_k": top_k,
            "results_count": len(results),
            "results": [
                {
                    "content": r.get("content", "")[:500],  # Limit content length
                    "source": r.get("metadata", {}).get("source", "unknown"),
                    "section": r.get("metadata", {}).get("section", ""),
                    "distance": r.get("distance"),
                }
                for r in results
            ],
            "context_added": context_added[:2000] if context_added else "",  # Limit length
            "context_length": len(context_added) if context_added else 0,
        }

    def get_debug_info(self) -> dict | None:
        if not self._enabled:
            return None
        result = {}
        if self._api_request:
            result["api_request"] = self._api_request
        if self._api_response:
            result["api_response"] = self._api_response
        if self._raw_model_response:
            result["raw_model_response"] = self._raw_model_response
        if self._reasoning:
            result["reasoning"] = self._reasoning
        if self._status:
            result["status"] = self._status
        if self._session_info:
            result["session"] = self._session_info
        if self._subagents:
            result["subagents"] = self._subagents
        if self._mcp_calls:
            result["mcp_calls"] = self._mcp_calls
        if self._rag_info:
            result["rag_info"] = self._rag_info
        return result if result else None

    def clear(self) -> None:
        self._api_request = None
        self._api_response = None
        self._raw_model_response = None
        self._reasoning = None
        self._status = None
        self._session_info = None
        self._subagents = []
        self._mcp_calls = []


debug_collector = DebugCollector()
