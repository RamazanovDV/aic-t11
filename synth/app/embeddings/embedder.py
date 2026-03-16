from abc import ABC, abstractmethod
from typing import Any

import requests


class BaseEmbedder(ABC):
    @abstractmethod
    def embed(self, text: str) -> list[float]:
        pass

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        pass

    @abstractmethod
    def get_dimension(self) -> int:
        pass


class OllamaEmbedder(BaseEmbedder):
    def __init__(self, url: str = "http://localhost:11434", model: str = "nomic-embed-text-v2-moe:latest"):
        self.url = url.rstrip("/")
        self.model = model

    def embed(self, text: str) -> list[float]:
        response = requests.post(
            f"{self.url}/api/embeddings",
            json={"model": self.model, "prompt": text},
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["embedding"]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for text in texts:
            emb = self.embed(text)
            embeddings.append(emb)
        return embeddings

    def get_dimension(self) -> int:
        test_emb = self.embed("test")
        return len(test_emb)


class OpenAIEmbedder(BaseEmbedder):
    def __init__(self, api_key: str, model: str = "text-embedding-3-small", base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    def embed(self, text: str) -> list[float]:
        response = requests.post(
            f"{self.base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "input": text,
                "model": self.model,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = requests.post(
            f"{self.base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "input": texts,
                "model": self.model,
            },
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()["data"]
        return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]

    def get_dimension(self) -> int:
        dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }
        return dimensions.get(self.model, 1536)


def create_embedder(provider: str, config: dict[str, Any] = None) -> BaseEmbedder:
    if config is None:
        config = {}

    if provider == "ollama":
        return OllamaEmbedder(
            url=config.get("url", "http://localhost:11434"),
            model=config.get("model", "nomic-embed-text-v2-moe:latest"),
        )
    elif provider == "openai":
        return OpenAIEmbedder(
            api_key=config.get("api_key", ""),
            model=config.get("model", "text-embedding-3-small"),
            base_url=config.get("base_url", "https://api.openai.com/v1"),
        )
    else:
        raise ValueError(f"Unknown embedder provider: {provider}")
