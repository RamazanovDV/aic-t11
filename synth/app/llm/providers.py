import json
from typing import Generator

import requests

from app.llm.base import BaseProvider, LLMChunk, LLMResponse, Message


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


class ContextLengthExceededError(Exception):
    def __init__(self, message: str = "Context window exceeded", debug_response: dict | None = None):
        self.message = message
        self.debug_response = debug_response
        super().__init__(self.message)


class GenericOpenAIProvider(BaseProvider):
    def chat(self, messages: list[Message], system_prompt: str | None = None, debug: bool = False) -> LLMResponse:
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
        }

        debug_request = None
        debug_response = None
        
        if debug:
            debug_request = {
                "url": self.url,
                "method": "POST",
                "headers": {**headers, "Authorization": f"Bearer {API_KEY_MASK}"},
                "body": payload,
            }

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
                        debug_response=error_data if debug else None
                    )
            raise

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        
        usage = {}
        if "usage" in data:
            usage = {
                "input_tokens": data["usage"].get("prompt_tokens", 0),
                "output_tokens": data["usage"].get("completion_tokens", 0),
                "total_tokens": data["usage"].get("total_tokens", 0),
            }

        if debug:
            debug_response = data

        return LLMResponse(
            content=content,
            model=self.model,
            usage=usage,
            debug_request=debug_request,
            debug_response=debug_response,
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
            print(f"Error listing models: {e}")
            return []

    def get_provider_name(self) -> str:
        return "generic"

    def stream_chat(self, messages: list[Message], system_prompt: str | None = None, debug: bool = False) -> Generator[LLMChunk, None, None]:
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
                        debug_response=error_data if debug else None
                    )
            raise

        full_content = ""
        total_usage = {}

        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data_str = line[6:]
                    if data_str.strip() == '[DONE]':
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full_content += content
                            yield LLMChunk(content=full_content, is_final=False)

                        if "usage" in data:
                            total_usage = {
                                "input_tokens": data["usage"].get("prompt_tokens", 0),
                                "output_tokens": data["usage"].get("completion_tokens", 0),
                                "total_tokens": data["usage"].get("total_tokens", 0),
                            }
                    except json.JSONDecodeError:
                        continue

        yield LLMChunk(content=full_content, is_final=True, usage=total_usage)


class OpenAIProvider(GenericOpenAIProvider):
    def chat(self, messages: list[Message], system_prompt: str | None = None, debug: bool = False) -> LLMResponse:
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
        }

        debug_request = None
        debug_response = None
        
        if debug:
            debug_request = {
                "url": self.url,
                "method": "POST",
                "headers": {**headers, "Authorization": f"Bearer {API_KEY_MASK}"},
                "body": payload,
            }

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
                        debug_response=error_data if debug else None
                    )
            raise

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        
        usage = {}
        if "usage" in data:
            usage = {
                "input_tokens": data["usage"].get("prompt_tokens", 0),
                "output_tokens": data["usage"].get("completion_tokens", 0),
                "total_tokens": data["usage"].get("total_tokens", 0),
            }

        if debug:
            debug_response = data

        return LLMResponse(
            content=content,
            model=self.model,
            usage=usage,
            debug_request=debug_request,
            debug_response=debug_response,
        )

    def get_provider_name(self) -> str:
        return "openai"


class AnthropicProvider(BaseProvider):
    def chat(self, messages: list[Message], system_prompt: str | None = None, debug: bool = False) -> LLMResponse:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
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

        debug_request = None
        debug_response = None
        
        if debug:
            debug_request = {
                "url": self.url,
                "method": "POST",
                "headers": {**headers, "Authorization": f"Bearer {API_KEY_MASK}"},
                "body": payload,
            }

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
                        debug_response=error_data if debug else None
                    )
            raise

        data = response.json()
        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content = block.get("text", "")
                break
        if not content:
            content = data.get("content", [{}])[0].get("text", "") or data.get("content", [{}])[0].get("thinking", "")
        
        usage = {}
        if "usage" in data:
            usage = {
                "input_tokens": data["usage"].get("prompt_tokens", 0),
                "output_tokens": data["usage"].get("completion_tokens", 0),
                "total_tokens": data["usage"].get("total_tokens", 0),
            }

        if debug:
            debug_response = data

        return LLMResponse(
            content=content,
            model=self.model,
            usage=usage,
            debug_request=debug_request,
            debug_response=debug_response,
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
            print(f"Error listing models: {e}")
            return []

    def get_provider_name(self) -> str:
        return "anthropic"

    def stream_chat(self, messages: list[Message], system_prompt: str | None = None, debug: bool = False) -> Generator[LLMChunk, None, None]:
        from app.llm.base import LLMChunk

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
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
            "max_tokens": 4096,
            "stream": True,
        }

        debug_request = None
        if debug:
            debug_request = {
                "url": self.url,
                "method": "POST",
                "headers": {**headers, "x-api-key": API_KEY_MASK},
                "body": payload,
            }

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
                        debug_response=error_data if debug else None
                    )
            raise

        full_content = ""
        total_usage = {}

        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data_str = line[6:]
                    try:
                        data = json.loads(data_str)
                        if data.get("type") == "content_block_delta":
                            delta = data.get("delta", {})
                            if delta.get("type") == "text_delta":
                                content = delta.get("text", "")
                                full_content += content
                                yield LLMChunk(content=full_content, is_final=False)
                        elif data.get("type") == "message_delta":
                            if "usage" in data:
                                total_usage = {
                                    "input_tokens": data["usage"].get("input_tokens", 0),
                                    "output_tokens": data["usage"].get("output_tokens", 0),
                                    "total_tokens": data["usage"].get("input_tokens", 0) + data["usage"].get("output_tokens", 0),
                                }
                    except json.JSONDecodeError:
                        continue

        yield LLMChunk(content=full_content, is_final=True, usage=total_usage)


class OllamaProvider(BaseProvider):
    def chat(self, messages: list[Message], system_prompt: str | None = None, debug: bool = False) -> LLMResponse:
        headers = {
            "Content-Type": "application/json",
        }

        if self.api_key and self.api_key != "ollama":
            headers["Authorization"] = f"Bearer {self.api_key}"

        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            formatted_messages.append({"role": msg.role, "content": msg.content})

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "stream": False,
        }

        debug_request = None
        debug_response = None
        
        if debug:
            debug_headers = {**headers}
            if "Authorization" in debug_headers:
                debug_headers["Authorization"] = f"Bearer {API_KEY_MASK}"
            debug_request = {
                "url": self.url,
                "method": "POST",
                "headers": debug_headers,
                "body": payload,
            }

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
                        debug_response=error_data if debug else None
                    )
            raise

        data = response.json()
        
        if "message" in data and "content" in data["message"]:
            content = data["message"]["content"]
        else:
            content = data.get("content", "") or data.get("message", {}).get("content", "")
        
        usage = {}
        if "usage" in data:
            usage = {
                "input_tokens": data["usage"].get("prompt_tokens", 0),
                "output_tokens": data["usage"].get("completion_tokens", 0),
                "total_tokens": data["usage"].get("total_tokens", 0),
            }
        elif "prompt_eval_count" in data:
            usage = {
                "input_tokens": data.get("prompt_eval_count", 0),
                "output_tokens": data.get("eval_count", 0),
                "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            }
        elif content:
            usage = estimate_tokens(content)

        if debug:
            debug_response = data

        return LLMResponse(
            content=content,
            model=self.model,
            usage=usage,
            debug_request=debug_request,
            debug_response=debug_response,
        )

    def stream_chat(self, messages: list[Message], system_prompt: str | None = None, debug: bool = False) -> Generator[LLMChunk, None, None]:
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

        debug_request = None
        if debug:
            debug_request = {
                "url": self.url,
                "method": "POST",
                "headers": {**headers, "Authorization": f"Bearer {API_KEY_MASK}"},
                "body": payload,
            }

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
                        debug_response=error_data if debug else None
                    )
            raise

        full_content = ""
        total_usage = {}

        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data_str = line[6:]
                    if data_str.strip() == '[DONE]':
                        break
                    try:
                        data = json.loads(data_str)
                        
                        if "message" in data and "content" in data["message"]:
                            delta = data["message"].get("content", "")
                            if delta:
                                full_content += delta
                                yield LLMChunk(content=full_content, is_final=False)
                        elif "choices" in data:
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                full_content += content
                                yield LLMChunk(content=full_content, is_final=False)

                        if "eval_count" in data:
                            total_usage = {
                                "input_tokens": data.get("prompt_eval_count", 0),
                                "output_tokens": data.get("eval_count", 0),
                                "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                            }
                    except json.JSONDecodeError:
                        continue

        if not total_usage and full_content:
            total_usage = estimate_tokens(full_content)

        yield LLMChunk(content=full_content, is_final=True, usage=total_usage)

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
            print(f"Error listing models: {e}")
            return []

    def get_provider_name(self) -> str:
        return "ollama"
