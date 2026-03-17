import json
from pathlib import Path
from typing import Any

import faiss

from app.embeddings.models import Chunk, EmbeddingIndex


class EmbeddingStorage:
    def __init__(self, data_dir: Path | None = None):
        if data_dir is None:
            data_dir = Path(__file__).parent.parent.parent.parent / "data" / "embeddings"
        self.data_dir = data_dir
        self.indexes_dir = self.data_dir / "indexes"
        self.index_file = self.data_dir / "index.json"
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.indexes_dir.mkdir(parents=True, exist_ok=True)

    def _load_index_list(self) -> list[dict[str, Any]]:
        if not self.index_file.exists():
            return []
        with open(self.index_file, "r") as f:
            return json.load(f)

    def _save_index_list(self, indexes: list[dict[str, Any]]) -> None:
        with open(self.index_file, "w") as f:
            json.dump(indexes, f, indent=2, ensure_ascii=False)

    def _get_index_dir(self, index_id: str) -> Path:
        return self.indexes_dir / index_id

    def save_index(
        self,
        index_meta: EmbeddingIndex,
        chunks: list[Chunk],
        faiss_index: faiss.Index,
    ) -> EmbeddingIndex:
        index_dir = self._get_index_dir(index_meta.id)
        index_dir.mkdir(parents=True, exist_ok=True)

        config_path = index_dir / "config.json"
        with open(config_path, "w") as f:
            json.dump(index_meta.to_dict(), f, indent=2, ensure_ascii=False)

        metadata_path = index_dir / "metadata.json"
        metadata_data = {
            "chunks": [chunk.to_dict() for chunk in chunks],
        }
        with open(metadata_path, "w") as f:
            json.dump(metadata_data, f, indent=2, ensure_ascii=False)

        faiss_path = index_dir / "index.faiss"
        faiss.write_index(faiss_index, str(faiss_path))

        indexes = self._load_index_list()
        indexes.append(index_meta.to_dict())
        self._save_index_list(indexes)

        return index_meta

    def load_index(self, index_id: str) -> tuple[EmbeddingIndex, list[Chunk], faiss.Index] | None:
        index_dir = self._get_index_dir(index_id)
        if not index_dir.exists():
            return None

        config_path = index_dir / "config.json"
        if not config_path.exists():
            return None

        with open(config_path, "r") as f:
            config_data = json.load(f)
        index_meta = EmbeddingIndex.from_dict(config_data)

        metadata_path = index_dir / "metadata.json"
        with open(metadata_path, "r") as f:
            metadata_data = json.load(f)
        chunks = [Chunk.from_dict(c) for c in metadata_data["chunks"]]

        faiss_path = index_dir / "index.faiss"
        faiss_index = faiss.read_index(str(faiss_path))

        return index_meta, chunks, faiss_index

    def delete_index(self, index_id: str) -> bool:
        index_dir = self._get_index_dir(index_id)
        if not index_dir.exists():
            return False

        import shutil
        shutil.rmtree(index_dir)

        indexes = self._load_index_list()
        indexes = [idx for idx in indexes if idx.get("id") != index_id]
        self._save_index_list(indexes)

        return True

    def list_indexes(self) -> list[EmbeddingIndex]:
        indexes_data = self._load_index_list()
        return [EmbeddingIndex.from_dict(data) for data in indexes_data]

    def get_index_by_id(self, index_id: str) -> EmbeddingIndex | None:
        indexes_data = self._load_index_list()
        for data in indexes_data:
            if data.get("id") == index_id:
                return EmbeddingIndex.from_dict(data)
        return None

    def get_index_by_name(self, name: str, version: int | None = None) -> EmbeddingIndex | None:
        indexes_data = self._load_index_list()
        matching = [EmbeddingIndex.from_dict(data) for data in indexes_data if data.get("name") == name]

        if not matching:
            return None

        if version is not None:
            for idx in matching:
                if idx.version == version:
                    return idx
            return None

        return max(matching, key=lambda idx: idx.version)

    def update_index_metadata(self, index_id: str, updates: dict[str, Any]) -> bool:
        index_dir = self._get_index_dir(index_id)
        if not index_dir.exists():
            return False

        config_path = index_dir / "config.json"
        with open(config_path, "r") as f:
            config_data = json.load(f)

        config_data.update(updates)

        with open(config_path, "w") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)

        indexes = self._load_index_list()
        for idx in indexes:
            if idx.get("id") == index_id:
                idx.update(updates)
        self._save_index_list(indexes)

        return True


embedding_storage = EmbeddingStorage()
