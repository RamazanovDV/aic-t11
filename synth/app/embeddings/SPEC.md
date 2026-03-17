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
GET  /api/embeddings/list     # List (for UI dropdown)
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

## 6. Admin UI

- Tab "Эмбединги" in admin page
- Table with all indexes (name, version, provider, strategy, chunks, files, ratings, date)
- Delete button with confirmation

## 7. Chat Integration (RAG)

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

## 8. UI Integration

- RAG modal in chat (🔍 button)
- Select embedding index from dropdown
- Toggle RAG on/off
- Set top_k parameter

## 9. Chunking Strategies

**FixedChunker:**
- `chunk_size` - size in tokens
- `overlap` - overlap in tokens

**StructureChunker:**
- Split by Markdown headers (#, ##, ###)
- `min_chunk_size` / `max_chunk_size` - chunk size limits

## 10. Dependencies

```txt
faiss-cpu>=1.7.0
```

## 11. Known Issues

- Ollama embedding API is unstable with large texts (>~1500 chars)
- StructureChunker has bug with some files: 'list' object has no attribute 'metadata'
- Chunk size must be kept small (≤50) for Ollama to work reliably

## 12. Session Settings Persistence

RAG settings are stored in session.session_settings:

```python
session_settings = {
    "debug_enabled": True,
    "stream_enabled": True,
    "rag_settings": {
        "enabled": False,
        "index_name": "",
        "version": None,
        "top_k": 5
    }
}
```

### API Endpoints

```
GET  /api/sessions/<session_id>/rag-settings   # Get RAG settings
PUT  /api/sessions/<session_id>/rag-settings   # Update RAG settings
```

When sending chat message without explicit RAG params, settings are loaded from session.

## 13. Debug Info

DebugCollector captures RAG information:

```python
debug_collector.capture_rag_info(
    query="user message",
    index_name="My Index",
    version=1,
    top_k=5,
    results=[{"content": "...", "metadata": {...}, "distance": 0.5}],
    context_added="\n\n## Relevant Context\n[1] Source: file.md\n..."
)
```

Debug info includes:
- Query that was searched
- Index name and version used
- Top-K parameter
- Results found (content, source, distance)
- Context that was added to system prompt

In admin panel debug settings, "RAG" group is available (INFO by default).
