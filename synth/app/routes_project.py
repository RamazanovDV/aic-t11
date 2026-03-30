"""API routes for Project RAG functionality."""

from flask import Blueprint, jsonify, request

project_rag_bp = Blueprint("project_rag", __name__)


def require_user(f):
    """Decorator to require user authentication."""
    from functools import wraps
    from app.auth import get_auth_provider, get_current_user
    from app.config import config
    
    @wraps(f)
    def wrapper(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")
        if not api_key or api_key != config.api_key:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper


@project_rag_bp.route("/api/project-rag/index", methods=["POST"])
@require_user
def index_project():
    """Index a project's documentation.
    
    Request body:
    {
        "project_path": "/path/to/project"
    }
    """
    data = request.get_json()
    if not data or "project_path" not in data:
        return jsonify({"error": "Missing 'project_path' field"}), 400
    
    project_path = data["project_path"]
    
    try:
        from app.project_rag import ProjectRAGManager
        rag_manager = ProjectRAGManager()
        result = rag_manager.index_project(project_path)
        
        return jsonify({
            "success": result.get("success", True),
            "project_path": result.get("project_path"),
            "indexed": result.get("indexed", {}),
            "total": sum(result.get("indexed", {}).values()),
            "errors": result.get("errors", [])
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@project_rag_bp.route("/api/project-rag/search", methods=["POST"])
@require_user
def search_project():
    """Search in project documentation.
    
    Request body:
    {
        "project_path": "/path/to/project",
        "query": "search query",
        "doc_types": ["readme", "docs", "schema", "api"],  // optional
        "limit": 10  // optional
    }
    """
    data = request.get_json()
    if not data or "project_path" not in data:
        return jsonify({"error": "Missing 'project_path' field"}), 400
    if not data or "query" not in data:
        return jsonify({"error": "Missing 'query' field"}), 400
    
    project_path = data["project_path"]
    query = data["query"]
    doc_types = data.get("doc_types")
    limit = data.get("limit", 10)
    
    try:
        from app.project_rag import ProjectRAGManager
        rag_manager = ProjectRAGManager()
        results = rag_manager.search_project(
            project_path=project_path,
            query=query,
            doc_types=doc_types,
            limit=limit
        )
        
        return jsonify({
            "query": query,
            "project_path": project_path,
            "count": len(results),
            "results": results
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@project_rag_bp.route("/api/project-rag/projects", methods=["GET"])
@require_user
def list_indexed_projects():
    """List all indexed projects."""
    try:
        from app.project_rag import ProjectRAGManager
        rag_manager = ProjectRAGManager()
        projects = rag_manager.get_indexed_projects()
        
        return jsonify({
            "projects": projects,
            "count": len(projects)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@project_rag_bp.route("/api/project-rag/<path:project_path>/summary", methods=["GET"])
@require_user
def get_project_summary(project_path: str):
    """Get summary of indexed documentation for a project."""
    try:
        from app.project_rag import ProjectRAGManager
        rag_manager = ProjectRAGManager()
        summary = rag_manager.get_project_summary(project_path)
        
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@project_rag_bp.route("/api/project-rag/<path:project_path>/tree", methods=["GET"])
@require_user
def get_project_tree(project_path: str):
    """Get documentation tree for a project."""
    try:
        from app.project_rag import ProjectRAGManager
        rag_manager = ProjectRAGManager()
        tree = rag_manager.get_project_tree(project_path)
        
        return jsonify(tree)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@project_rag_bp.route("/api/project-rag/<path:project_path>/docs", methods=["GET"])
@require_user
def get_project_docs(project_path: str):
    """Get all indexed documents for a project."""
    try:
        from app.project_rag import ProjectRAGManager
        rag_manager = ProjectRAGManager()
        docs = rag_manager.get_project_docs(project_path)
        
        return jsonify({
            "project_path": project_path,
            "docs": docs
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@project_rag_bp.route("/api/project-rag/help", methods=["POST"])
@require_user
def help_question():
    """Answer a help question about a project using RAG.
    
    Request body:
    {
        "project_path": "/path/to/project",
        "question": "What is the project about?",
        "use_mcp": true,  // optional, use MCP for git info
        "git_repo_path": "/path/to/repo"  // optional
    }
    """
    data = request.get_json()
    if not data or "project_path" not in data:
        return jsonify({"error": "Missing 'project_path' field"}), 400
    if not data or "question" not in data:
        return jsonify({"error": "Missing 'question' field"}), 400
    
    project_path = data["project_path"]
    question = data["question"]
    use_mcp = data.get("use_mcp", False)
    git_repo_path = data.get("git_repo_path") or project_path
    
    try:
        from app.project_rag import ProjectRAGManager
        rag_manager = ProjectRAGManager()
        
        result = rag_manager.answer_help_question(
            project_path=project_path,
            question=question,
            use_mcp=use_mcp,
            git_repo_path=git_repo_path
        )
        
        return jsonify({
            "question": question,
            "project_path": project_path,
            "has_context": result.get("has_context", False),
            "sources": result.get("sources", []),
            "context": result.get("context", "")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
