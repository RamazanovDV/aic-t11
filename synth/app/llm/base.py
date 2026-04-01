from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generator
import uuid


@dataclass
class Message:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    role: str = ""
    content: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    debug: dict | None = None
    model: str | None = None
    summary_of: list[int] | None = None
    created_at: datetime = field(default_factory=datetime.now)
    disabled: bool = False
    pinned: bool = False
    branch_id: str = "main"
    source: str | None = None
    status: dict | None = None
    tool_call_id: str | None = None
    tool_use: list[dict] | None = None
    reasoning: str | None = None
    group_id: str | None = None
    agent_role: str | None = None


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list[dict] | None = None
    reasoning: str | None = None


@dataclass
class LLMChunk:
    content: str
    is_final: bool
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list[dict] | None = None
    reasoning: str | None = None


class BaseProvider(ABC):
    def __init__(self, url: str, api_key: str, model: str, timeout: int = 120, temperature: float = 0.7):
        self.url = url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature

    @abstractmethod
    def chat(self, messages, system_prompt=None, debug_collector=None, tools=None):
        pass

    @abstractmethod
    def stream_chat(self, messages, system_prompt=None, debug_collector=None, tools=None):
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        pass

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError(f"Provider {self.get_provider_name()} does not support embeddings")

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class ProviderFactory:
    _providers: dict[str, type[BaseProvider]] = {}

    @classmethod
    def register(cls, name: str, provider_class: type[BaseProvider]) -> None:
        cls._providers[name] = provider_class

    @classmethod
    def create(cls, name: str, config: dict[str, Any]) -> BaseProvider:
        from app.llm.providers import GenericOpenAIProvider

        provider_type = config.get("type", name).lower()
        
        if provider_type not in cls._providers:
            url = config.get("url", "").lower()
            if "anthropic" in url or "minimax.io/anthropic" in url:
                provider_type = "anthropic"
            elif "ollama" in url:
                provider_type = "ollama"
            elif "minimax" in url or "minimaxi" in url:
                provider_type = "minimax"
            else:
                provider_type = "openai"
        
        if provider_type in cls._providers:
            provider_class = cls._providers[provider_type]
        elif provider_type in ("minimax", "minimaxi"):
            url_lower = config.get("url", "").lower()
            if "minimaxi" in url_lower and "/chatcompletion" in url_lower:
                provider_class = GenericOpenAIProvider
            else:
                provider_type = "anthropic"
                provider_class = cls._providers["anthropic"]
        elif config.get("url") and config.get("api_key") and config.get("model"):
            provider_class = GenericOpenAIProvider
        else:
            raise ValueError(f"Unknown provider: {name}. Available: {list(cls._providers.keys())}")

        url = config.get("url", "").strip()
        
        default_urls = {
            "openai": "https://api.openai.com/v1/chat/completions",
            "anthropic": "https://api.anthropic.com/v1/messages",
            "ollama": "http://localhost:11434",
            "minimax": "https://api.minimaxi.com/v1/text/chatcompletion_v2",
            "minimaxi": "https://api.minimaxi.com/v1/text/chatcompletion_v2",
        }
        
        if not url:
            url = default_urls.get(provider_type, "")
        
        if provider_type == "ollama":
            if "/api/chat" not in url:
                url = url.rstrip("/") + "/api/chat"
        elif provider_type == "anthropic":
            url_lower = url.lower()
            if "/anthropic" in url_lower and "/v1/messages" not in url_lower:
                if url_lower.endswith("/anthropic"):
                    url = url + "/v1/messages"
                elif "/anthropic/" in url_lower:
                    url = url.rstrip("/") + "/v1/messages"
            elif "/messages" not in url:
                url = url.rstrip("/") + "/messages"
        elif provider_type in ("minimax", "minimaxi"):
            if "/chatcompletion" not in url:
                url = url.rstrip("/") + "/text/chatcompletion_v2"
        elif "/chat/completions" not in url:
            url = url.rstrip("/") + "/chat/completions"

        return provider_class(
            url=url,
            api_key=config.get("api_key", ""),
            model=config.get("model", ""),
            timeout=config.get("timeout", 120),
            temperature=config.get("temperature", 0.7),
        )

    @classmethod
    def available_providers(cls) -> list[str]:
        return list(cls._providers.keys())
