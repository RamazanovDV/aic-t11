import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Chunk:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Chunk":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            content=data.get("content", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class EmbeddingIndex:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    version: int = 1
    user_id: str = ""

    provider: str = "ollama"
    model: str = "nomic-embed-text-v2-moe:latest"
    chunking_strategy: str = "structure"
    chunking_params: dict[str, Any] = field(default_factory=dict)

    created_at: datetime = field(default_factory=datetime.now)
    source_dir: str = ""

    file_count: int = 0
    chunk_count: int = 0
    dimension: int = 768

    ratings: dict[str, int] = field(default_factory=lambda: {
        "thumbs_up": 0,
        "thumbs_down": 0,
    })

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "user_id": self.user_id,
            "provider": self.provider,
            "model": self.model,
            "chunking_strategy": self.chunking_strategy,
            "chunking_params": self.chunking_params,
            "created_at": self.created_at.isoformat(),
            "source_dir": self.source_dir,
            "file_count": self.file_count,
            "chunk_count": self.chunk_count,
            "dimension": self.dimension,
            "ratings": self.ratings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EmbeddingIndex":
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now()

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            description=data.get("description", ""),
            version=data.get("version", 1),
            user_id=data.get("user_id", ""),
            provider=data.get("provider", "ollama"),
            model=data.get("model", "nomic-embed-text-v2-moe:latest"),
            chunking_strategy=data.get("chunking_strategy", "structure"),
            chunking_params=data.get("chunking_params", {}),
            created_at=created_at,
            source_dir=data.get("source_dir", ""),
            file_count=data.get("file_count", 0),
            chunk_count=data.get("chunk_count", 0),
            dimension=data.get("dimension", 768),
            ratings=data.get("ratings", {"thumbs_up": 0, "thumbs_down": 0}),
        )
