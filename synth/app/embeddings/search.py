from typing import Any


from app.embeddings.embedder import create_embedder, BaseEmbedder
from app.embeddings.indexer import search_index as index_search
from app.embeddings.storage import embedding_storage
from app.embeddings.config import embeddings_config


class EmbeddingSearch:
    def __init__(self, embedder: BaseEmbedder | None = None):
        self.embedder = embedder

    def _get_embedder(self, provider: str, model: str, config: dict[str, Any] = None) -> BaseEmbedder:
        if self.embedder:
            return self.embedder

        provider_config = embeddings_config.get_embedder_config(provider)
        if config:
            provider_config.update(config)
        provider_config.setdefault("model", model)

        return create_embedder(provider, provider_config)

    def search(
        self,
        query: str,
        index_name: str | None = None,
        index_id: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        if index_id:
            index_data = embedding_storage.load_index(index_id)
        elif index_name:
            index_meta = embedding_storage.get_index_by_name(index_name)
            if not index_meta:
                raise ValueError(f"Index not found: {index_name}")
            index_data = embedding_storage.load_index(index_meta.id)
        else:
            raise ValueError("Must provide either index_id or index_name")

        if not index_data:
            raise ValueError("Index not found or failed to load")

        index_meta, chunks, faiss_index = index_data

        embedder = self._get_embedder(index_meta.provider, index_meta.model)

        query_embedding = embedder.embed(query)

        results = index_search(faiss_index, chunks, query_embedding, top_k)

        return [
            {
                "content": chunk.content,
                "metadata": chunk.metadata,
                "distance": distance,
            }
            for chunk, distance in results
        ]

    def search_by_id(
        self,
        query: str,
        index_id: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        return self.search(query, index_id=index_id, top_k=top_k)


def search(
    query: str,
    index_name: str | None = None,
    index_id: str | None = None,
    top_k: int = 5,
    embedder: BaseEmbedder | None = None,
) -> list[dict[str, Any]]:
    search_engine = EmbeddingSearch(embedder)
    return search_engine.search(query, index_name, index_id, top_k)
