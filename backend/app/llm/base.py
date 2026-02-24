from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class Message:
    role: str
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str


class BaseProvider(ABC):
    def __init__(self, url: str, api_key: str, model: str):
        self.url = url
        self.api_key = api_key
        self.model = model

    @abstractmethod
    def chat(self, messages: list[Message], system_prompt: str | None = None) -> LLMResponse:
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        pass


class ProviderFactory:
    _providers: dict[str, type[BaseProvider]] = {}

    @classmethod
    def register(cls, name: str, provider_class: type[BaseProvider]) -> None:
        cls._providers[name] = provider_class

    @classmethod
    def create(cls, name: str, config: dict[str, Any]) -> BaseProvider:
        from backend.app.llm.providers import GenericOpenAIProvider

        if name in cls._providers:
            provider_class = cls._providers[name]
        elif config.get("url") and config.get("api_key") and config.get("model"):
            provider_class = GenericOpenAIProvider
        else:
            raise ValueError(f"Unknown provider: {name}. Available: {list(cls._providers.keys())}")

        return provider_class(
            url=config.get("url", ""),
            api_key=config.get("api_key", ""),
            model=config.get("model", ""),
        )

    @classmethod
    def available_providers(cls) -> list[str]:
        return list(cls._providers.keys())
