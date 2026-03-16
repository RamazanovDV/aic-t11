# Embeddings Pipeline Specification

## 1. Module Structure

```
synth/app/embeddings/
├── __init__.py
├── config.py          # Configuration providers/models
├── chunker.py        # FixedChunker + StructureChunker
├── embedder.py       # OpenAI + Ollama providers
├── indexer.py        # FAISS indexing
├── storage.py        # Save/load
├── search.py         # Semantic search
├── models.py         # EmbeddingIndex, Chunk
└── routes.py         # REST API

synth-cli/main.py     # Add embeddings group
```

## 2. Data Models

```python
@dataclass
class EmbeddingIndex:
    id: str                    # UUID v4
    name: str                  # Name
    description: str          # Description  
    version: int              # 1, 2, 3...
    user_id: str              # Creator (for future)
    
    provider: str              # "ollama" | "openai"
    model: str                 # model name
    chunking_strategy: str     # "fixed" | "structure"
    chunking_params: dict      # {chunk_size, overlap} or {min/max_chunk_size}
    
    created_at: datetime
    source_dir: str            # Source path
    
    file_count: int
    chunk_count: int
    dimension: int
    
    ratings: dict = field(default_factory=lambda: {
        "thumbs_up": 0,
        "thumbs_down": 0,
    })

@dataclass
class Chunk:
    id: str
    content: str
    metadata: dict  # source, title, section, chunk_index, total_chunks
```

## 3. Storage Structure

```
data/embeddings/
├── index.json           # List of all indexes
└── {index_id}/           # UUID
    ├── config.json       # Parameters (provider, model, chunking)
    ├── metadata.json     # Chunks with metadata
    └── index.faiss       # FAISS index
```

## 4. CLI Commands

```bash
# Create (interactive or with flags)
python main.py embeddings create \
    --name "Company Context" \
    --description "Main documents" \
    --source ./data/context \
    --provider ollama \
    --model "nomic-embed-text-v2-moe:latest" \
    --strategy structure \
    --chunk-size 512 \
    --overlap 50

# Search
python main.py embeddings search "query" --name "Company Context"

# List
python main.py embeddings list

# Info
python main.py embeddings info {index_id}

# Delete
python main.py embeddings delete {index_id}

# Rate
python main.py embeddings rate {index_id} --thumbs-up
python main.py embeddings rate {index_id} --thumbs-down
```

**Authentication:** CLI makes POST to `/api/auth/login`, gets cookies, uses them for all requests.

## 5. REST API

```
POST /api/embeddings          # Create (auth required)
GET  /api/embeddings         # List (all, no user filter)
GET  /api/embeddings/{id}    # Info
DELETE /api/embeddings/{id}   # Delete

POST /api/embeddings/search   # Semantic search
POST /api/embeddings/{id}/rate # Rate (thumbs_up / thumbs_down)
```

**Create request body:**
```json
{
  "name": "Name",
  "description": "Description",
  "source_dir": "./data/context",
  "provider": "ollama",
  "model": "nomic-embed-text-v2-moe:latest",
  "chunking_strategy": "structure",
  "chunking_params": {"min_chunk_size": 100, "max_chunk_size": 1000}
}
```

**Search request body:**
```json
{
  "query": "question",
  "index_name": "Company Context",  -- search by name (latest version)
  "top_k": 5
}
```

## 6. Chat Integration (RAG)

In `/api/chat` add:
```json
{
  "message": "question",
  "use_rag": true,
  "rag_index_name": "Company Context",
  "rag_top_k": 5
}
```

Logic:
1. Find index by name (latest version)
2. Get query embedding
3. FAISS search → top-K chunks
4. Add to prompt:
```
## Relevant Context
[chunk 1: source: file.md, section: Header]
Content...

---
[chunk 2: ...]
...
```

## 7. Chunking Strategies

**FixedChunker:**
- `chunk_size` - size in tokens
- `overlap` - overlap in tokens

**StructureChunker:**
- Split by Markdown headers (#, ##, ###)
- `min_chunk_size` / `max_chunk_size` - chunk size limits

## 8. Dependencies

```txt
faiss-cpu>=1.7.0
tiktoken>=0.5.0
```

## 9. Implementation Plan

1. **Models + Storage** - `embeddings/models.py`, `embeddings/storage.py`
2. **Chunking** - `embeddings/chunker.py` (interface + 2 implementations)
3. **Embedder** - `embeddings/embedder.py` (OpenAI + Ollama)
4. **Index + Search** - `embeddings/indexer.py`, `embeddings/search.py`
5. **Config** - add to `config.py`
6. **Routes** - `embeddings/routes.py` + integration in `app/routes.py`
7. **CLI** - add commands to `synth-cli/main.py`
8. **UI** - add section to admin (optional)
