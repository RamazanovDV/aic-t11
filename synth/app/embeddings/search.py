from typing import Any


from app.embeddings.embedder import create_embedder, BaseEmbedder
from app.embeddings.indexer import search_index as index_search
from app.embeddings.storage import embedding_storage
from app.embeddings.config import embeddings_config
from app.embeddings.reranker import apply_reranker


class EmbeddingSearch:
    def __init__(self, embedder: BaseEmbedder | None = None):
        self.embedder = embedder

    def _get_embedder(self, provider: str, model: str, config: dict[str, Any] | None = None) -> BaseEmbedder:
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
        version: int | None = None,
        top_k: int = 5,
        reranker_config: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        if index_id:
            index_data = embedding_storage.load_index(index_id)
        elif index_name:
            index_meta = embedding_storage.get_index_by_name(index_name, version=version)
            if not index_meta:
                raise ValueError(f"Index not found: {index_name}" + (f" v{version}" if version else ""))
            index_data = embedding_storage.load_index(index_meta.id)
        else:
            raise ValueError("Must provide either index_id or index_name")

        if not index_data:
            raise ValueError("Index not found or failed to load")

        index_meta, chunks, faiss_index = index_data

        embedder = self._get_embedder(index_meta.provider, index_meta.model, {"model": index_meta.model})

        query_embedding = embedder.embed(query)

        actual_top_k = top_k
        if reranker_config and reranker_config.get("enabled"):
            actual_top_k = reranker_config.get("top_k_before", top_k * 4)

        results_raw = index_search(faiss_index, chunks, query_embedding, actual_top_k)

        results = [
            {
                "content": chunk.content,
                "metadata": chunk.metadata,
                "distance": distance,
                "similarity": 1 / (1 + distance) if distance is not None else 0,
            }
            for chunk, distance in results_raw
        ]

        meta = None
        if reranker_config and reranker_config.get("enabled"):
            results, meta = apply_reranker(results, reranker_config, top_k, query=query)

        return results, meta

    def search_by_id(
        self,
        query: str,
        index_id: str,
        top_k: int = 5,
        reranker_config: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        return self.search(query, index_id=index_id, top_k=top_k, reranker_config=reranker_config)


def search(
    query: str,
    index_name: str | None = None,
    index_id: str | None = None,
    version: int | None = None,
    top_k: int = 5,
    embedder: BaseEmbedder | None = None,
    reranker_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    search_engine = EmbeddingSearch(embedder)
    results, _ = search_engine.search(query, index_name, index_id, version, top_k, reranker_config)
    return results
