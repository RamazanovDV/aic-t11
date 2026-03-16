from pathlib import Path
from typing import Any

from app.config import config as main_config


class EmbeddingsConfig:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._config = main_config._config.get("embeddings", {})
        return cls._instance

    @property
    def enabled(self) -> bool:
        return self._config.get("enabled", True)

    @property
    def data_dir(self) -> Path:
        dir_name = self._config.get("data_dir", "./data/embeddings")
        return Path(__file__).parent.parent.parent.parent / dir_name

    @property
    def default_provider(self) -> str:
        return self._config.get("default_provider", "ollama")

    @property
    def default_model(self) -> str:
        return self._config.get("default_model", "nomic-embed-text-v2-moe:latest")

    @property
    def supported_providers(self) -> dict[str, list[str]]:
        return self._config.get("supported_providers", {
            "ollama": [
                "nomic-embed-text-v2-moe:latest",
                "nomic-embed-text",
                "mxbai-embed-large",
            ],
            "openai": [
                "text-embedding-3-small",
                "text-embedding-ada-002",
            ],
        })

    def get_provider_config(self, provider: str) -> dict[str, Any]:
        providers = main_config.providers
        if provider in providers:
            return providers[provider]
        return {}

    def get_embedder_config(self, provider: str) -> dict[str, Any]:
        if provider == "ollama":
            provider = "ollama-embed"
        
        providers = main_config.providers
        if provider in providers:
            pc = providers[provider]
            return {
                "url": pc.get("url", ""),
                "api_key": pc.get("api_key", ""),
                "model": pc.get("default_model", self.default_model),
            }
        return {
            "url": "",
            "api_key": "",
            "model": self.default_model,
        }


embeddings_config = EmbeddingsConfig()
