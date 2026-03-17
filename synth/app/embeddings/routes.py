from pathlib import Path
from typing import Any
import uuid

from flask import Blueprint, jsonify, request

from app.embeddings.config import embeddings_config
from app.embeddings.embedder import create_embedder
from app.embeddings.indexer import EmbeddingIndexer
from app.embeddings.models import Chunk, EmbeddingIndex
from app.embeddings.search import EmbeddingSearch
from app.embeddings.storage import embedding_storage
from app.config import config


_embedding_index_store: dict[str, dict[str, Any]] = {}


def require_auth(f):
    def wrapper(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")
        if not api_key or api_key != config.api_key:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)

    wrapper.__name__ = f.__name__
    return wrapper


embeddings_bp = Blueprint("embeddings", __name__)


@embeddings_bp.route("/embeddings/config", methods=["GET"])
def get_embeddings_config():
    return jsonify({
        "default_provider": embeddings_config.default_provider,
        "default_model": embeddings_config.default_model,
        "supported_providers": embeddings_config.supported_providers,
    })


@embeddings_bp.route("/embeddings", methods=["POST"])
@require_auth
def create_embedding_index():
    global _embedding_index_store
    
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    action = data.get("action", "create")
    name = data.get("name", "")
    chunks_data = data.get("chunks", [])
    
    if action in ("start", "continue", "finish"):
        if not name:
            return jsonify({"error": "Missing required field: name"}), 400
        
        if action == "start":
            provider = data.get("provider", embeddings_config.default_provider)
            model = data.get("model", embeddings_config.default_model)
            chunking_strategy = data.get("chunking_strategy", "fixed")
            chunking_params = data.get("chunking_params", {})
            description = data.get("description", "")
            
            existing_index = embedding_storage.get_index_by_name(name)
            version = 1
            if existing_index:
                version = existing_index.version + 1
            
            store_key = f"{name}_{uuid.uuid4().hex[:8]}"
            
            embedder_config = embeddings_config.get_embedder_config(provider)
            embedder = create_embedder(provider, {**embedder_config, "model": model})
            
            all_chunks = [Chunk(
                id=c["id"],
                content=c["content"],
                metadata=c.get("metadata", {})
            ) for c in chunks_data]
            
            _embedding_index_store[store_key] = {
                "name": name,
                "description": description,
                "provider": provider,
                "model": model,
                "chunking_strategy": chunking_strategy,
                "chunking_params": chunking_params,
                "chunks": all_chunks,
                "embedder": embedder,
                "created_at": EmbeddingIndex().created_at,
                "version": version,
            }
            
            return jsonify({
                "status": "started",
                "store_key": store_key,
                "version": version,
                "chunks_received": len(chunks_data),
            })
        
        elif action == "continue":
            store_key = data.get("store_key")
            if not store_key or store_key not in _embedding_index_store:
                return jsonify({"error": "Invalid or expired store_key. Start a new index creation."}), 400
            
            try:
                store = _embedding_index_store[store_key]
                new_chunks = [Chunk(
                    id=c["id"],
                    content=c["content"],
                    metadata=c.get("metadata", {})
                ) for c in chunks_data]
                store["chunks"].extend(new_chunks)
                
                print(f"[EMBEDDINGS] Continue: received {len(chunks_data)} chunks, total: {len(store['chunks'])}", flush=True)
                
                return jsonify({
                    "status": "continued",
                    "chunks_received": len(chunks_data),
                    "total_chunks": len(store["chunks"]),
                })
            except Exception as e:
                import traceback
                print(f"[EMBEDDINGS] Continue error: {e}", flush=True)
                print(traceback.format_exc(), flush=True)
                return jsonify({"error": str(e)}), 500
        
        elif action == "finish":
            store_key = data.get("store_key")
            if not store_key or store_key not in _embedding_index_store:
                return jsonify({"error": "Invalid or expired store_key. Start a new index creation."}), 400
            
            store = _embedding_index_store[store_key]
            
            new_chunks = [Chunk(
                id=c["id"],
                content=c["content"],
                metadata=c.get("metadata", {})
            ) for c in chunks_data]
            store["chunks"].extend(new_chunks)
            
            chunks = store["chunks"]
            embedder = store["embedder"]
            version = store.get("version", 1)
            
            # Log chunk sizes to debug
            sizes = [len(c.content) for c in chunks]
            print(f"[EMBEDDINGS] Finish: {len(chunks)} chunks, size range: {min(sizes)}-{max(sizes)}", flush=True)
            
            indexer = EmbeddingIndexer(embedder)
            
            import sys
            print(f"[EMBEDDINGS] Creating index from {len(chunks)} chunks...", flush=True)
            
            try:
                index_meta, faiss_index = indexer.create_index_from_chunks(chunks)
                print(f"[EMBEDDINGS] Index created, dimension={index_meta.dimension}", flush=True)
            except Exception as e:
                import traceback
                print(f"[EMBEDDINGS] Failed to create index: {e}", flush=True)
                print(traceback.format_exc(), flush=True)
                return jsonify({"error": f"Failed to create index: {str(e)}"}), 500
            
            index_meta.id = EmbeddingIndex().id
            index_meta.name = store["name"]
            index_meta.description = store["description"]
            index_meta.version = version
            index_meta.provider = store["provider"]
            index_meta.model = store["model"]
            index_meta.chunking_strategy = store["chunking_strategy"]
            index_meta.chunking_params = store["chunking_params"]
            index_meta.source_dir = ""
            
            try:
                print(f"[EMBEDDINGS] Saving index to disk...", flush=True)
                saved_index = embedding_storage.save_index(index_meta, chunks, faiss_index)
                print(f"[EMBEDDINGS] Index saved successfully", flush=True)
            except Exception as e:
                import traceback
                print(f"[EMBEDDINGS] Failed to save index: {e}", flush=True)
                print(traceback.format_exc(), flush=True)
                return jsonify({"error": f"Failed to save index: {str(e)}"}), 500
            
            del _embedding_index_store[store_key]
            
            return jsonify(saved_index.to_dict()), 201
    
    if "source_dir" in data:
        return _create_index_from_directory(data)
    
    if not name:
        return jsonify({"error": "Missing required field: name"}), 400
    
    if not chunks_data:
        return jsonify({"error": "Missing chunks data. Provide source_dir or chunks."}), 400
    
    return _create_index_from_chunks(data)


def _create_index_from_directory(data: dict) -> tuple:
    required_fields = ["name", "source_dir"]
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"Missing required field: {field}"}), 400

    name = data["name"]
    description = data.get("description", "")
    source_dir = Path(data["source_dir"])
    if not source_dir.exists():
        return jsonify({"error": f"Source directory not found: {source_dir}"}), 400

    provider = data.get("provider", embeddings_config.default_provider)
    model = data.get("model", embeddings_config.default_model)
    chunking_strategy = data.get("chunking_strategy", "structure")
    chunking_params = data.get("chunking_params", {})

    existing_index = embedding_storage.get_index_by_name(name)
    version = 1
    if existing_index:
        version = existing_index.version + 1

    embedder_config = embeddings_config.get_embedder_config(provider)
    embedder = create_embedder(provider, {**embedder_config, "model": model})

    indexer = EmbeddingIndexer(embedder)

    try:
        index_meta, chunks, faiss_index = indexer.create_index(
            source_dir=source_dir,
            chunking_strategy=chunking_strategy,
            chunking_params=chunking_params,
        )
    except Exception as e:
        return jsonify({"error": f"Failed to create index: {str(e)}"}), 500

    index_meta.id = EmbeddingIndex().id
    index_meta.name = name
    index_meta.description = description
    index_meta.version = version
    index_meta.provider = provider
    index_meta.model = model
    index_meta.chunking_strategy = chunking_strategy
    index_meta.chunking_params = chunking_params
    index_meta.source_dir = str(source_dir)

    saved_index = embedding_storage.save_index(index_meta, chunks, faiss_index)

    return jsonify(saved_index.to_dict()), 201


def _create_index_from_chunks(data: dict) -> tuple:
    from app.embeddings.indexer import EmbeddingIndexer
    from app.embeddings.models import Chunk
    
    name = data.get("name", "Unnamed")
    description = data.get("description", "")
    provider = data.get("provider", embeddings_config.default_provider)
    model = data.get("model", embeddings_config.default_model)
    chunking_strategy = data.get("chunking_strategy", "fixed")
    chunking_params = data.get("chunking_params", {})
    chunks_data = data.get("chunks", [])
    
    chunks = [Chunk(
        id=c["id"],
        content=c["content"],
        metadata=c.get("metadata", {})
    ) for c in chunks_data]
    
    if not chunks:
        return jsonify({"error": "No chunks provided"}), 400
    
    existing_index = embedding_storage.get_index_by_name(name)
    version = 1
    if existing_index:
        version = existing_index.version + 1
    
    embedder_config = embeddings_config.get_embedder_config(provider)
    embedder = create_embedder(provider, {**embedder_config, "model": model})
    
    indexer = EmbeddingIndexer(embedder)
    
    try:
        index_meta, faiss_index = indexer.create_index_from_chunks(chunks)
    except Exception as e:
        return jsonify({"error": f"Failed to create index: {str(e)}"}), 500
    
    index_meta.id = EmbeddingIndex().id
    index_meta.name = name
    index_meta.description = description
    index_meta.version = version
    index_meta.provider = provider
    index_meta.model = model
    index_meta.chunking_strategy = chunking_strategy
    index_meta.chunking_params = chunking_params
    index_meta.source_dir = ""
    
    saved_index = embedding_storage.save_index(index_meta, chunks, faiss_index)
    
    return jsonify(saved_index.to_dict()), 201


@embeddings_bp.route("/embeddings", methods=["GET"])
@require_auth
def list_embedding_indexes():
    indexes = embedding_storage.list_indexes()
    return jsonify([idx.to_dict() for idx in indexes])


@embeddings_bp.route("/embeddings/by-name/<name>", methods=["GET"])
@require_auth
def get_indexes_by_name(name: str):
    all_indexes = embedding_storage.list_indexes()
    matching = [idx.to_dict() for idx in all_indexes if idx.name == name]
    return jsonify(sorted(matching, key=lambda x: x.get("version", 1), reverse=True))


@embeddings_bp.route("/embeddings/<index_id>", methods=["GET"])
@require_auth
def get_embedding_index(index_id: str):
    index_data = embedding_storage.load_index(index_id)
    if not index_data:
        return jsonify({"error": "Index not found"}), 404

    index_meta, chunks, _ = index_data
    return jsonify(index_meta.to_dict())


@embeddings_bp.route("/embeddings/<index_id>", methods=["DELETE"])
@require_auth
def delete_embedding_index(index_id: str):
    success = embedding_storage.delete_index(index_id)
    if not success:
        return jsonify({"error": "Index not found"}), 404

    return jsonify({"status": "deleted", "id": index_id})


@embeddings_bp.route("/embeddings/search", methods=["POST"])
@require_auth
def search_embeddings():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    if "query" not in data:
        return jsonify({"error": "Missing required field: query"}), 400

    query = data["query"]
    index_name = data.get("index_name")
    index_id = data.get("index_id")
    top_k = data.get("top_k", 5)

    if not index_name and not index_id:
        return jsonify({"error": "Must provide either index_name or index_id"}), 400

    try:
        search_engine = EmbeddingSearch()
        results = search_engine.search(
            query=query,
            index_name=index_name,
            index_id=index_id,
            top_k=top_k,
        )
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@embeddings_bp.route("/embeddings/<index_id>/rate", methods=["POST"])
@require_auth
def rate_embedding_index(index_id: str):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    rating = data.get("rating")
    if rating not in ["thumbs_up", "thumbs_down"]:
        return jsonify({"error": "Invalid rating. Must be 'thumbs_up' or 'thumbs_down'"}), 400

    index_meta = embedding_storage.get_index_by_id(index_id)
    if not index_meta:
        return jsonify({"error": "Index not found"}), 404

    ratings = index_meta.ratings
    ratings[rating] = ratings.get(rating, 0) + 1

    embedding_storage.update_index_metadata(index_id, {"ratings": ratings})

    return jsonify({"status": "rated", "ratings": ratings})


@embeddings_bp.route("/embeddings/<index_id>", methods=["PATCH"])
@require_auth
def update_embedding_index(index_id: str):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    allowed_fields = ["name", "description"]
    updates = {k: v for k, v in data.items() if k in allowed_fields}

    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    success = embedding_storage.update_index_metadata(index_id, updates)
    if not success:
        return jsonify({"error": "Index not found"}), 404

    return jsonify({"status": "updated", "updates": updates})
