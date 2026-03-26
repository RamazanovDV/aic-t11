import json
from typing import Generator

import requests

from app.llm.base import BaseProvider, LLMChunk, LLMResponse, Message
from app.debug import DebugCollector
from app.logger import debug as dbg, info, warning, error


API_KEY_MASK = "[API_KEY_MASKED]"


def estimate_tokens(text: str) -> dict:
    chars_per_token = 4
    tokens = max(1, len(text) // chars_per_token)
    return {
        "input_tokens": 0,
        "output_tokens": tokens,
        "total_tokens": tokens,
        "estimated": True,
    }


def extract_usage(data: dict) -> dict:
    """Extract usage from API response - supports both Anthropic and OpenAI formats."""
    if "usage" not in data:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    
    u = data["usage"]
    
    if "prompt_tokens" in u or "completion_tokens" in u:
        return {
            "input_tokens": u.get("prompt_tokens", 0),
            "output_tokens": u.get("completion_tokens", 0),
            "total_tokens": u.get("total_tokens", 0),
        }
    elif "input_tokens" in u or "output_tokens" in u:
        return {
            "input_tokens": u.get("input_tokens", 0),
            "output_tokens": u.get("output_tokens", 0),
            "total_tokens": u.get("total_tokens", u.get("input_tokens", 0) + u.get("output_tokens", 0)),
        }
    
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


class ContextLengthExceededError(Exception):
    def __init__(self, message: str = "Context window exceeded", debug_response: dict | None = None):
        self.message = message
        self.debug_response = debug_response
        super().__init__(self.message)


class GenericOpenAIProvider(BaseProvider):
    def chat(self, messages: list[Message], system_prompt: str | None = None, debug_collector: DebugCollector | None = None, tools: list[dict] | None = None) -> LLMResponse:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": [{"type": "text", "text": system_prompt}]})

        for msg in messages:
            if msg.role in ("info", "model"):
                continue
            msg_dict = {"role": msg.role, "content": [{"type": "text", "text": msg.content}]}
            if msg.role == "assistant" and msg.tool_use:
                msg_dict["tool_calls"] = msg.tool_use
            formatted_messages.append(msg_dict)

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": self.temperature,
        }

        if tools:
            payload["tools"] = tools

        if debug_collector:
            debug_collector.capture_api_request(
                url=self.url,
                method="POST",
                headers=headers,
                body=payload,
            )

        response = requests.post(self.url, headers=headers, json=payload, timeout=self.timeout)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            if response.status_code in (400, 422):
                error_data = response.json() if response.content else {}
                error_message = ""
                if isinstance(error_data, dict):
                    error_message = error_data.get("error", {}).get("message", "") or error_data.get("message", "")
                if "context" in error_message.lower() or "length" in error_message.lower() or "token" in error_message.lower():
                    raise ContextLengthExceededError(
                        error_message or "Context window exceeded",
                        debug_response=error_data if debug_collector and debug_collector.enabled else None
                    )
            raise

        data = response.json()
        message_data = data["choices"][0]["message"]
        content = message_data.get("content", "")
        reasoning = message_data.get("reasoning_content", "")
        
        # Also check for thinking field (Ollama format)
        thinking = message_data.get("thinking", "")
        if not reasoning and thinking:
            reasoning = thinking
        
        tool_calls = None
        if "tool_calls" in message_data:
            tool_calls = message_data["tool_calls"]
        
        usage = extract_usage(data)

        if debug_collector:
            debug_collector.capture_api_response(data)

        return LLMResponse(
            content=content,
            model=self.model,
            usage=usage,
            tool_calls=tool_calls,
            reasoning=reasoning if reasoning else None,
        )

    def list_models(self) -> list[str]:
        try:
            base_url = self.url
            if "/chat/completions" in base_url:
                base_url = base_url.split("/chat/completions")[0]
            elif "/messages" in base_url:
                base_url = base_url.split("/messages")[0]
            
            base_url = base_url.rstrip("/")
            models_url = f"{base_url}/models"
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            response = requests.get(models_url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return [m["id"] for m in data.get("data", [])]
            return []
        except Exception as e:
            error("PROVIDERS", f"Error listing models: {e}")
            return []

    def get_provider_name(self) -> str:
        return "generic"

    def embed(self, text: str) -> list[float]:
        base_url = self.url
        if "/chat/completions" in base_url:
            base_url = base_url.split("/chat/completions")[0]
        elif "/v1" in base_url and "/embeddings" not in base_url:
            base_url = base_url.split("/v1")[0] + "/v1"
        
        embed_url = f"{base_url}/embeddings"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        response = requests.post(
            embed_url,
            headers=headers,
            json={"input": text, "model": self.model},
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        base_url = self.url
        if "/chat/completions" in base_url:
            base_url = base_url.split("/chat/completions")[0]
        elif "/v1" in base_url and "/embeddings" not in base_url:
            base_url = base_url.split("/v1")[0] + "/v1"
        
        embed_url = f"{base_url}/embeddings"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        response = requests.post(
            embed_url,
            headers=headers,
            json={"input": texts, "model": self.model},
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()["data"]
        return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]

    def stream_chat(self, messages: list[Message], system_prompt: str | None = None, debug_collector: DebugCollector | None = None, tools: list | None = None) -> Generator[LLMChunk, None, None]:
        from app.llm.base import LLMChunk

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            formatted_messages.append({"role": msg.role, "content": msg.content})

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": self.temperature,
            "stream": True,
        }

        if tools:
            payload["tools"] = tools

        response = requests.post(self.url, headers=headers, json=payload, timeout=self.timeout, stream=True)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            if response.status_code in (400, 422):
                error_data = response.json() if response.content else {}
                error_message = ""
                if isinstance(error_data, dict):
                    error_message = error_data.get("error", {}).get("message", "") or error_data.get("message", "")
                if "context" in error_message.lower() or "length" in error_message.lower() or "token" in error_message.lower():
                    raise ContextLengthExceededError(
                        error_message or "Context window exceeded",
                        debug_response=error_data if debug_collector and debug_collector.enabled else None
                    )
            raise

        full_content = ""
        full_reasoning = ""
        total_usage = {}
        final_data = None

        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data_str = line[6:]
                    if data_str.strip() == '[DONE]':
                        break
                    try:
                        data = json.loads(data_str)
                        final_data = data
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        reasoning = delta.get("reasoning_content", "")
                        if content:
                            full_content += content
                        if reasoning:
                            full_reasoning += reasoning
                        if content or reasoning:
                            yield LLMChunk(
                                content=content,
                                is_final=False,
                                reasoning=reasoning if reasoning else None
                            )

                        if "usage" in data:
                            total_usage = extract_usage(data)
                            if debug_collector:
                                debug_collector.capture_api_response(data)
                    except json.JSONDecodeError:
                        continue

        yield LLMChunk(
            content=full_content,
            is_final=True,
            usage=total_usage,
            reasoning=full_reasoning if full_reasoning else None
        )


class OpenAIProvider(GenericOpenAIProvider):
    def chat(self, messages: list[Message], system_prompt: str | None = None, debug_collector: DebugCollector | None = None, tools: list | None = None) -> LLMResponse:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": [{"type": "text", "text": system_prompt}]})

        for msg in messages:
            formatted_messages.append({"role": msg.role, "content": [{"type": "text", "text": msg.content}]})

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": self.temperature,
        }

        if tools:
            payload["tools"] = tools

        if debug_collector:
            debug_collector.capture_api_request(
                url=self.url,
                method="POST",
                headers=headers,
                body=payload,
            )

        response = requests.post(self.url, headers=headers, json=payload, timeout=self.timeout)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            if response.status_code in (400, 422):
                error_data = response.json() if response.content else {}
                error_message = ""
                if isinstance(error_data, dict):
                    error_message = error_data.get("error", {}).get("message", "") or error_data.get("message", "")
                if "context" in error_message.lower() or "length" in error_message.lower() or "token" in error_message.lower():
                    raise ContextLengthExceededError(
                        error_message or "Context window exceeded",
                        debug_response=error_data if debug_collector and debug_collector.enabled else None
                    )
            raise

        data = response.json()
        message_data = data["choices"][0]["message"]
        content = message_data.get("content", "")
        reasoning = message_data.get("reasoning_content", "")
        
        usage = {}
        if "usage" in data:
            usage = {
                "input_tokens": data["usage"].get("prompt_tokens", 0),
                "output_tokens": data["usage"].get("completion_tokens", 0),
                "total_tokens": data["usage"].get("total_tokens", 0),
            }

        if debug_collector:
            debug_collector.capture_api_response(data)

        return LLMResponse(
            content=content,
            model=self.model,
            usage=usage,
            reasoning=reasoning if reasoning else None,
        )

    def get_provider_name(self) -> str:
        return "openai"


class AnthropicProvider(BaseProvider):
    def chat(self, messages, system_prompt=None, debug_collector: DebugCollector | None = None, tools=None) -> LLMResponse:
        dbg("ANTHROPIC", f"STEP1: Entered chat(), messages={len(messages)}, tools={bool(tools)}")
        
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        
        dbg("ANTHROPIC", "STEP2: Starting to format messages")

        # First pass: collect all tool_use_ids from assistant messages
        # This handles cases where tool_result appears before tool_use in message list
        valid_tool_use_ids = set()
        for msg in messages:
            if msg.role == "assistant" and msg.tool_use:
                for tool_use_block in msg.tool_use:
                    tool_use_id = tool_use_block.get("id", "")
                    if tool_use_id:
                        valid_tool_use_ids.add(tool_use_id)
        
        dbg("ANTHROPIC", f"Collected {len(valid_tool_use_ids)} valid tool_use IDs")
        
        formatted_messages = []
        
        if system_prompt:
            formatted_messages.append({"role": "system", "content": [{"type": "text", "text": system_prompt}]})
        
        dbg("ANTHROPIC", f"STEP3: Formatting {len(messages)} messages")
        for msg in messages:
            # Skip info, model and error roles - they are for UI only, not for LLM
            if msg.role in ("info", "model", "error"):
                continue
            
            # Handle tool role: convert to anthropic format
            if msg.role == "tool":
                # Filter out orphan tool_result - skip if tool_use_id not in valid set
                tool_call_id = msg.tool_call_id or ""
                if tool_call_id and tool_call_id not in valid_tool_use_ids:
                    dbg("ANTHROPIC", f"Skipping orphan tool_result: {tool_call_id}")
                    continue
                formatted_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tool_call_id,
                        "content": msg.content
                    }]
                })
            # Handle summary role: convert to user for anthropic
            elif msg.role == "summary":
                formatted_messages.append({"role": "user", "content": [{"type": "text", "text": f"[Summary of previous conversation]\n{msg.content}"}]})
            # Keep system, user, assistant as is
            else:
                content_blocks = [{"type": "text", "text": msg.content}]
                if msg.role == "assistant" and msg.tool_use:
                    for tool_use_block in msg.tool_use:
                        func = tool_use_block.get("function", {})
                        tool_use_id = tool_use_block.get("id", "")
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tool_use_id,
                            "name": func.get("name", ""),
                            "input": func.get("arguments", {}),
                        })
                formatted_messages.append({"role": msg.role, "content": content_blocks})

        dbg("ANTHROPIC", "STEP4: Creating payload")
        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": self.temperature,
        }

        if tools:
            payload["tools"] = tools
            dbg("ANTHROPIC", f"STEP5: Added {len(tools)} tools to payload")

        dbg("ANTHROPIC", f"STEP6: Sending request to {self.url}")
        
        # Debug: show message roles and find tool issues
        roles_summary = []
        has_tool_result_without_tool_use = False
        for i, msg in enumerate(formatted_messages):
            role = msg.get("role", "unknown")
            content = msg.get("content", [])
            # Check for tool_result without tool_use
            has_tool_result = False
            has_tool_use = False
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_result":
                            has_tool_result = True
                        if block.get("type") == "tool_use":
                            has_tool_use = True
            if has_tool_result and not has_tool_use and role == "user":
                has_tool_result_without_tool_use = True
                dbg("ANTHROPIC", f"  Message {i}: {role} - HAS tool_result but NO tool_use!")
            roles_summary.append(f"{i}:{role}")
        
        if has_tool_result_without_tool_use:
            error("ANTHROPIC", "FOUND tool_result without tool_use - this will cause 400 error!")
        
        dbg("ANTHROPIC", f"Message roles: {roles_summary}")
        
        # Print the full payload for debugging
        import json
        dbg("ANTHROPIC", f"FULL REQUEST: {json.dumps(payload, ensure_ascii=False)[:500]}...")
        try:
            payload_str = json.dumps(payload, ensure_ascii=False)
        except Exception as e:
            error("ANTHROPIC", f"JSON ENCODE ERROR: {e}")
            dbg("ANTHROPIC", "Trying to find problematic message...")
            for i, msg in enumerate(formatted_messages):
                try:
                    json.dumps(msg)
                    dbg("ANTHROPIC", f"  Message {i}: OK")
                except Exception as me:
                    dbg("ANTHROPIC", f"  Message {i}: PROBLEM - {me}")
                    dbg("ANTHROPIC", f"    Content: {str(msg.get('content', ''))[:500]}")
        
        dbg("ANTHROPIC", "chat() STEP7: Calling requests.post()...")
        
        if debug_collector:
            debug_collector.capture_api_request(
                url=self.url,
                method="POST",
                headers=headers,
                body=payload,
            )

        response = requests.post(self.url, headers=headers, json=payload, timeout=self.timeout)
        
        dbg("ANTHROPIC", f"chat() STEP8: Got response, status={response.status_code}")
        
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            error("ANTHROPIC", f"ERROR: Status={response.status_code}")
            error("ANTHROPIC", f"ERROR Response body: {response.text[:1000]}")
            if response.status_code in (400, 422):
                error_data = response.json() if response.content else {}
                error_message = ""
                if isinstance(error_data, dict):
                    error_message = error_data.get("error", {}).get("message", "") or error_data.get("message", "")
                error("ANTHROPIC", f"ERROR parsed: {error_message}")
                if "context" in error_message.lower() or "length" in error_message.lower() or "token" in error_message.lower():
                    raise ContextLengthExceededError(
                        error_message or "Context window exceeded",
                        debug_response=error_data if debug_collector and debug_collector.enabled else None
                    )
            raise

        data = response.json()
        content = ""
        reasoning = ""
        tool_calls = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                content = block.get("text", "")
            elif block.get("type") == "thinking":
                reasoning = block.get("thinking", "")
            elif block.get("type") == "tool_use":
                tool_call = {
                    "id": block.get("id"),
                    "type": "function",
                    "function": {
                        "name": block.get("name"),
                        "arguments": block.get("input", {})
                    }
                }
                tool_calls.append(tool_call)
        
        if not content:
            content = data.get("content", [{}])[0].get("text", "") or data.get("content", [{}])[0].get("thinking", "")
        
        usage = extract_usage(data)

        if debug_collector:
            debug_collector.capture_api_response(data)

        return LLMResponse(
            content=content,
            model=self.model,
            usage=usage,
            tool_calls=tool_calls,
            reasoning=reasoning if reasoning else None,
        )

    def list_models(self) -> list[str]:
        try:
            url_lower = self.url.lower()
            if "minimax.io/anthropic" in url_lower:
                return [
                    "MiniMax-M2.5",
                    "MiniMax-M2.5-highspeed",
                    "MiniMax-M2.1",
                    "MiniMax-M2.1-highspeed",
                    "MiniMax-M2",
                ]
            
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            }
            base_url = self.url
            if "/messages" in base_url:
                base_url = base_url.split("/messages")[0]
            elif "/v1" in base_url:
                base_url = base_url.split("/v1")[0]
            models_url = f"{base_url}/v1/models"
            response = requests.get(models_url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return [m["id"] for m in data.get("data", [])]
            return []
        except Exception as e:
            error("ANTHROPIC", f"Error listing models: {e}")
            return []

    def get_provider_name(self) -> str:
        return "anthropic"

    def stream_chat(self, messages, system_prompt=None, debug_collector: DebugCollector | None = None, tools=None):
        from app.llm.base import LLMChunk

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        # First pass: collect all tool_use_ids from assistant messages
        valid_tool_use_ids = set()
        for msg in messages:
            if msg.role == "assistant" and msg.tool_use:
                for tool_use_block in msg.tool_use:
                    tool_use_id = tool_use_block.get("id", "")
                    if tool_use_id:
                        valid_tool_use_ids.add(tool_use_id)
        
        dbg("ANTHROPIC", f"Stream: Collected {len(valid_tool_use_ids)} valid tool_use IDs")
        
        formatted_messages = []
        
        if system_prompt:
            formatted_messages.append({"role": "system", "content": [{"type": "text", "text": system_prompt}]})

        for msg in messages:
            # Skip info and model roles - they are for UI only
            if msg.role in ("info", "model"):
                continue
            
            # Handle tool role: convert to anthropic format
            if msg.role == "tool":
                # Filter out orphan tool_result - skip if tool_use_id not in valid set
                tool_call_id = msg.tool_call_id or ""
                if tool_call_id and tool_call_id not in valid_tool_use_ids:
                    dbg("ANTHROPIC", f"Stream: Skipping orphan tool_result: {tool_call_id}")
                    continue
                formatted_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tool_call_id,
                        "content": msg.content
                    }]
                })
            # Handle summary role: convert to user
            elif msg.role == "summary":
                formatted_messages.append({"role": "user", "content": [{"type": "text", "text": f"[Summary of previous conversation]\n{msg.content}"}]})
            else:
                content_blocks = [{"type": "text", "text": msg.content}]
                if msg.role == "assistant" and msg.tool_use:
                    for tool_use_block in msg.tool_use:
                        func = tool_use_block.get("function", {})
                        tool_use_id = tool_use_block.get("id", "")
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tool_use_id,
                            "name": func.get("name", ""),
                            "input": func.get("arguments", {}),
                        })
                formatted_messages.append({"role": msg.role, "content": content_blocks})

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "max_tokens": 4096,
            "stream": True,
        }

        if tools:
            payload["tools"] = tools

        if debug_collector:
            debug_collector.capture_api_request(
                url=self.url,
                method="POST",
                headers={**headers, "Authorization": f"Bearer {API_KEY_MASK}"},
                body=payload,
            )

        response = requests.post(self.url, headers=headers, json=payload, timeout=self.timeout, stream=True)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            error("ANTHROPIC", f"API Error: {response.status_code}")
            error("ANTHROPIC", f"Response body: {response.text[:500]}")
            if response.status_code in (400, 422):
                error_data = response.json() if response.content else {}
                error_message = ""
                if isinstance(error_data, dict):
                    error_message = error_data.get("error", {}).get("message", "") or error_data.get("message", "")
                error("ANTHROPIC", f"Parsed error: {error_message}")
                if "context" in error_message.lower() or "length" in error_message.lower() or "token" in error_message.lower():
                    raise ContextLengthExceededError(
                        error_message or "Context window exceeded",
                        debug_response=error_data if debug_collector and debug_collector.enabled else None
                    )
            raise

        full_content = ""
        full_reasoning = ""
        total_usage = {}
        tool_calls = []
        current_tool = None
        current_tool_input = ""
        final_data = None

        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data_str = line[6:]
                    try:
                        data = json.loads(data_str)
                        final_data = data
                        
                        if data.get("type") == "content_block_start":
                            block = data.get("content_block", {})
                            if block.get("type") == "tool_use":
                                current_tool = {
                                    "id": block.get("id"),
                                    "type": "function",
                                    "function": {
                                        "name": block.get("name"),
                                        "arguments": {}
                                    }
                                }
                                current_tool_input = ""
                        
                        elif data.get("type") == "content_block_delta":
                            delta = data.get("delta", {})
                            
                            if delta.get("type") == "text_delta":
                                if current_tool is None:
                                    content = delta.get("text", "")
                                    full_content += content
                                    yield LLMChunk(
                                        content=content,
                                        is_final=False,
                                        reasoning=full_reasoning if full_reasoning else None
                                    )
                            
                            elif delta.get("type") == "thinking_delta":
                                thinking = delta.get("thinking", "")
                                full_reasoning += thinking
                                yield LLMChunk(
                                    content="",
                                    is_final=False,
                                    reasoning=thinking if thinking else None
                                )
                            
                            elif delta.get("type") == "input_json_delta":
                                partial_json = delta.get("partial_json", "")
                                current_tool_input += partial_json
                        
                        elif data.get("type") == "content_block_stop":
                            if current_tool:
                                try:
                                    current_tool["function"]["arguments"] = json.loads(current_tool_input) if current_tool_input else {}
                                except json.JSONDecodeError:
                                    current_tool["function"]["arguments"] = {"_raw": current_tool_input}
                                tool_calls.append(current_tool)
                                current_tool = None
                                current_tool_input = ""
                        
                        elif data.get("type") == "message_delta":
                            if "usage" in data:
                                total_usage = extract_usage(data)
                                if debug_collector:
                                    debug_collector.capture_api_response(data)
                    except json.JSONDecodeError:
                        continue

        yield LLMChunk(
            content=full_content,
            is_final=True,
            usage=total_usage,
            tool_calls=tool_calls if tool_calls else None,
            reasoning=full_reasoning if full_reasoning else None
        )


class OllamaProvider(BaseProvider):
    def chat(self, messages, system_prompt=None, debug_collector: DebugCollector | None = None, tools=None):
        headers = {
            "Content-Type": "application/json",
        }

        if self.api_key and self.api_key != "ollama":
            headers["Authorization"] = f"Bearer {self.api_key}"

        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            if msg.role in ("info", "model"):
                continue
            
            if msg.role == "tool":
                formatted_messages.append({
                    "role": "user",
                    "content": f"[Tool result from {msg.tool_call_id or 'unknown'}]: {msg.content}"
                })
            elif msg.role == "summary":
                formatted_messages.append({"role": "user", "content": f"[Summary of previous conversation]\n{msg.content}"})
            elif msg.role == "assistant" and msg.tool_use:
                tool_calls = []
                for tool_use_block in msg.tool_use:
                    func = tool_use_block.get("function", {})
                    tool_calls.append({
                        "id": tool_use_block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": func.get("name", ""),
                            "arguments": json.dumps(func.get("arguments", {}))
                        }
                    })
                formatted_messages.append({"role": msg.role, "content": msg.content, "tool_calls": tool_calls})
            else:
                formatted_messages.append({"role": msg.role, "content": msg.content})

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": self.temperature,
        }

        if tools:
            payload["tools"] = tools
            dbg("DEBUG", f"Sending {len(tools)} tools to API")

        dbg("DEBUG", f"Messages count: {len(formatted_messages)}")
        for i, msg in enumerate(formatted_messages[:5]):
            content = msg.get('content', '')
            content_type = 'text' if isinstance(content, str) else 'array'
            dbg("DEBUG", f"Message {i}: role={msg.get('role')}, content_type={content_type}")
        
        if debug_collector:
            debug_headers = {**headers}
            if "Authorization" in debug_headers:
                debug_headers["Authorization"] = f"Bearer {API_KEY_MASK}"
            debug_collector.capture_api_request(
                url=self.url,
                method="POST",
                headers=debug_headers,
                body=payload,
            )

        response = requests.post(self.url, headers=headers, json=payload, timeout=self.timeout)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            if response.status_code in (400, 422):
                error_data = response.json() if response.content else {}
                error_message = ""
                if isinstance(error_data, dict):
                    error_message = error_data.get("error", {}).get("message", "") or error_data.get("message", "")
                if "context" in error_message.lower() or "length" in error_message.lower() or "token" in error_message.lower():
                    raise ContextLengthExceededError(
                        error_message or "Context window exceeded",
                        debug_response=error_data if debug_collector and debug_collector.enabled else None
                    )
            raise

        response_text = response.text.strip()
        
        if not response_text:
            return LLMResponse(
                content="",
                model=self.model,
                usage={},
                tool_calls=None,
            )
        
        lines = response_text.split('\n')
        full_content = ""
        full_thinking = ""
        final_data = None
        tool_calls = None
        input_tokens = 0
        output_tokens = 0
        
        for line in lines:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                final_data = data
                
                if "message" in data:
                    full_content += data["message"].get("content", "") or ""
                    thinking = data["message"].get("thinking", "")
                    if thinking:
                        full_thinking = thinking
                
                if "message" in data and "tool_calls" in data["message"]:
                    tool_calls = data["message"]["tool_calls"]
                
                if "prompt_eval_count" in data and input_tokens == 0:
                    input_tokens = data.get("prompt_eval_count", 0)
                
                output_tokens = data.get("eval_count", 0)
            except json.JSONDecodeError:
                continue
        
        total_usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        
        if not full_content and final_data:
            if "message" in final_data and "content" in final_data["message"]:
                full_content = final_data["message"]["content"]
            else:
                full_content = final_data.get("content", "") or final_data.get("message", {}).get("content", "")
        
        if total_usage.get("input_tokens", 0) == 0 and total_usage.get("output_tokens", 0) == 0 and full_content:
            total_usage = estimate_tokens(full_content)

        if debug_collector and final_data:
            debug_collector.capture_api_response(final_data)

        return LLMResponse(
            content=full_content,
            model=self.model,
            usage=total_usage,
            tool_calls=tool_calls,
            reasoning=full_thinking if full_thinking else None,
        )

    def stream_chat(self, messages, system_prompt=None, debug_collector: DebugCollector | None = None, tools=None):
        from app.llm.base import LLMChunk

        headers = {
            "Content-Type": "application/json",
        }

        if self.api_key and self.api_key != "ollama":
            headers["Authorization"] = f"Bearer {self.api_key}"

        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            if msg.role in ("info", "model"):
                continue
            
            if msg.role == "tool":
                formatted_messages.append({
                    "role": "user",
                    "content": f"[Tool result from {msg.tool_call_id or 'unknown'}]: {msg.content}"
                })
            elif msg.role == "summary":
                formatted_messages.append({"role": "user", "content": f"[Summary of previous conversation]\n{msg.content}"})
            else:
                msg_dict = {"role": msg.role, "content": msg.content}
                if msg.role == "assistant" and msg.tool_use:
                    msg_dict["tool_calls"] = msg.tool_use
                formatted_messages.append(msg_dict)

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": self.temperature,
            "stream": True,
        }

        if tools:
            payload["tools"] = tools

        if debug_collector:
            debug_collector.capture_api_request(
                url=self.url,
                method="POST",
                headers={**headers, "Authorization": f"Bearer {API_KEY_MASK}"},
                body=payload,
            )

        response = requests.post(self.url, headers=headers, json=payload, timeout=self.timeout, stream=True)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            if response.status_code in (400, 422):
                error_data = response.json() if response.content else {}
                error_message = ""
                if isinstance(error_data, dict):
                    error_message = error_data.get("error", {}).get("message", "") or error_data.get("message", "")
                if "context" in error_message.lower() or "length" in error_message.lower() or "token" in error_message.lower():
                    raise ContextLengthExceededError(
                        error_message or "Context length exceeded",
                        debug_response=error_data if debug_collector and debug_collector.enabled else None
                    )
            raise

        full_content = ""
        full_thinking = ""
        input_tokens = 0
        output_tokens = 0
        tool_calls = None
        final_data = None

        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    final_data = data
                    
                    if "message" in data:
                        message_data = data["message"]
                        content_delta = message_data.get("content", "")
                        thinking_delta = message_data.get("thinking", "")
                        if content_delta:
                            full_content += content_delta
                        if thinking_delta:
                            full_thinking += thinking_delta
                        if content_delta or thinking_delta:
                            yield LLMChunk(
                                content=content_delta,
                                is_final=False,
                                reasoning=thinking_delta if thinking_delta else None
                            )
                    
                    if "message" in data and data["message"].get("tool_calls"):
                        tool_calls = data["message"].get("tool_calls")
                    
                    if "prompt_eval_count" in data and input_tokens == 0:
                        input_tokens = data.get("prompt_eval_count", 0)
                    
                    output_tokens = data.get("eval_count", 0)
                    
                    if debug_collector and "prompt_eval_count" in data:
                        debug_collector.capture_api_response(data)
                    
                    if data.get("done"):
                        break
                except json.JSONDecodeError:
                    continue

        total_usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }

        if input_tokens == 0 and final_data:
            input_tokens = final_data.get("prompt_eval_count", 0)
            output_tokens = final_data.get("eval_count", output_tokens)
            total_usage = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            }

        yield LLMChunk(
            content=full_content,
            is_final=True,
            usage=total_usage,
            tool_calls=tool_calls,
            reasoning=full_thinking if full_thinking else None
        )

    def list_models(self) -> list[str]:
        try:
            base_url = self.url.split("/api/chat")[0] if "/api/chat" in self.url else self.url
            models_url = f"{base_url}/api/tags"
            response = requests.get(models_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return sorted([m["name"] for m in data.get("models", [])])
            return []
        except Exception as e:
            error("PROVIDERS", f"Error listing models: {e}")
            return []

    def get_provider_name(self) -> str:
        return "ollama"

    def embed(self, text: str) -> list[float]:
        base_url = self.url.split("/api/chat")[0] if "/api/chat" in self.url else self.url
        embed_url = f"{base_url}/api/embeddings"
        response = requests.post(
            embed_url,
            json={"model": self.model, "prompt": text},
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()["embedding"]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]
