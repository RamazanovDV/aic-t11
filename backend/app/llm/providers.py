import json

import requests

from backend.app.llm.base import BaseProvider, LLMResponse, Message


class GenericOpenAIProvider(BaseProvider):
    def chat(self, messages: list[Message], system_prompt: str | None = None) -> LLMResponse:
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
            "temperature": 0.7,
        }

        response = requests.post(self.url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        data = response.json()
        content = data["choices"][0]["message"]["content"]

        return LLMResponse(content=content, model=self.model)

    def get_provider_name(self) -> str:
        return "generic"


class OpenAIProvider(GenericOpenAIProvider):
    def chat(self, messages: list[Message], system_prompt: str | None = None) -> LLMResponse:
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
            "temperature": 0.7,
        }

        response = requests.post(self.url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        data = response.json()
        content = data["choices"][0]["message"]["content"]

        return LLMResponse(content=content, model=self.model)

    def get_provider_name(self) -> str:
        return "openai"


class AnthropicProvider(BaseProvider):
    def chat(self, messages: list[Message], system_prompt: str | None = None) -> LLMResponse:
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
        }

        response = requests.post(self.url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        data = response.json()
        content = data["content"][0]["text"]

        return LLMResponse(content=content, model=self.model)

    def get_provider_name(self) -> str:
        return "anthropic"


class OllamaProvider(BaseProvider):
    def chat(self, messages: list[Message], system_prompt: str | None = None) -> LLMResponse:
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

        response = requests.post(self.url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()

        data = response.json()
        content = data["message"]["content"]

        return LLMResponse(content=content, model=self.model)

    def get_provider_name(self) -> str:
        return "ollama"
