from pathlib import Path
from typing import Any

import faiss
import numpy as np

from app.embeddings.chunker import create_chunker
from app.embeddings.embedder import BaseEmbedder
from app.embeddings.models import Chunk, EmbeddingIndex


class EmbeddingIndexer:
    def __init__(self, embedder: BaseEmbedder):
        self.embedder = embedder

    def create_index(
        self,
        source_dir: Path,
        chunking_strategy: str = "structure",
        chunking_params: dict[str, Any] = None,
        extensions: list[str] = None,
    ) -> tuple[EmbeddingIndex, list[Chunk], faiss.Index]:
        if extensions is None:
            extensions = [".md"]

        chunker = create_chunker(chunking_strategy, chunking_params or {})
        chunks = chunker.chunk_directory(source_dir, extensions)

        if not chunks:
            raise ValueError(f"No chunks created from {source_dir}")

        print(f"Created {len(chunks)} chunks from {source_dir}")

        embeddings = []
        for i, chunk in enumerate(chunks):
            if i % 100 == 0:
                print(f"Embedding chunk {i + 1}/{len(chunks)}...")
            emb = self.embedder.embed(chunk.content)
            embeddings.append(emb)

        embeddings_array = np.array(embeddings).astype("float32")

        dimension = embeddings_array.shape[1]
        index = faiss.IndexFlatL2(dimension)
        index.add(embeddings_array)

        file_count = len(list(source_dir.rglob("*.md"))) if source_dir.exists() else 0

        index_meta = EmbeddingIndex(
            source_dir=str(source_dir),
            chunking_strategy=chunking_strategy,
            chunking_params=chunking_params or {},
            file_count=file_count,
            chunk_count=len(chunks),
            dimension=dimension,
        )

        return index_meta, chunks, index

    def update_index(self, index: faiss.Index, chunks: list[Chunk], new_chunks: list[Chunk]) -> faiss.Index:
        if not new_chunks:
            return index

        embeddings = []
        for chunk in new_chunks:
            emb = self.embedder.embed(chunk.content)
            embeddings.append(emb)

        embeddings_array = np.array(embeddings).astype("float32")
        index.add(embeddings_array)

        chunks.extend(new_chunks)

        return index


def search_index(
    index: faiss.Index,
    chunks: list[Chunk],
    query_embedding: list[float],
    top_k: int = 5,
) -> list[tuple[Chunk, float]]:
    query_array = np.array([query_embedding]).astype("float32")
    distances, indices = index.search(query_array, min(top_k, len(chunks)))

    results = []
    for distance, idx in zip(distances[0], indices[0]):
        if idx < len(chunks):
            results.append((chunks[idx], float(distance)))

    return results
