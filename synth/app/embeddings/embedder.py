from typing import Any

from app.llm.base import BaseProvider


class EmbedderWrapper:
    def __init__(self, provider: BaseProvider):
        self.provider = provider
        self._dimension: int | None = None

    def embed(self, text: str) -> list[float]:
        return self.provider.embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self.provider.embed_batch(texts)

    def get_dimension(self) -> int:
        if self._dimension is not None:
            return self._dimension
        test_emb = self.embed("test")
        self._dimension = len(test_emb)
        return self._dimension


def create_embedder(provider: str, config: dict[str, Any] | None = None) -> EmbedderWrapper:
    from app.llm import ProviderFactory
    
    if config is None:
        config = {}

    provider_config = {
        "url": config.get("url", ""),
        "api_key": config.get("api_key", ""),
        "model": config.get("model", "nomic-embed-text-v2-moe:latest"),
    }

    llm_provider = ProviderFactory.create(provider, provider_config)
    return EmbedderWrapper(llm_provider)


class BaseEmbedder:
    @staticmethod
    def create(provider: str, config: dict[str, Any] | None = None) -> EmbedderWrapper:
        return create_embedder(provider, config)
