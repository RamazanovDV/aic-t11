import time
from typing import Any

from app.llm.base import BaseProvider


class EmbedderWrapper:
    def __init__(self, provider: BaseProvider, max_retries: int = 3, retry_delay: float = 1.0, timeout: float = 30.0):
        self.provider = provider
        self._dimension: int | None = None
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout

    def embed(self, text: str) -> list[float]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return self.provider.embed(text)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
        if last_error:
            raise last_error
        raise Exception("Unknown error during embedding")

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            embedding = self.embed(text)
            results.append(embedding)
        return results

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
    return EmbedderWrapper(
        llm_provider,
        max_retries=config.get("max_retries", 3),
        retry_delay=config.get("retry_delay", 1.0),
        timeout=config.get("timeout", 30.0),
    )


class BaseEmbedder:
    @staticmethod
    def create(provider: str, config: dict[str, Any] | None = None) -> EmbedderWrapper:
        return create_embedder(provider, config)
