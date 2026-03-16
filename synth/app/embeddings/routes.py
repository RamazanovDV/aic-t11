from pathlib import Path

from flask import Blueprint, jsonify, request

from app.embeddings.config import embeddings_config
from app.embeddings.embedder import create_embedder
from app.embeddings.indexer import EmbeddingIndexer
from app.embeddings.models import EmbeddingIndex
from app.embeddings.search import EmbeddingSearch
from app.embeddings.storage import embedding_storage
from app.config import config


def require_auth(f):
    def wrapper(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")
        if not api_key or api_key != config.api_key:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)

    wrapper.__name__ = f.__name__
    return wrapper


embeddings_bp = Blueprint("embeddings", __name__)


@embeddings_bp.route("/embeddings", methods=["POST"])
@require_auth
def create_embedding_index():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

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


@embeddings_bp.route("/embeddings", methods=["GET"])
@require_auth
def list_embedding_indexes():
    indexes = embedding_storage.list_indexes()
    return jsonify([idx.to_dict() for idx in indexes])


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
