"""Project RAG Manager - High-level API for managing project documentation."""

import os
from pathlib import Path
from typing import Any

from app.logger import info, warning, error


class ProjectRAGManager:
    """Manager for Project RAG operations."""
    
    def __init__(self):
        from synth.app.project_rag.indexer import ProjectRAGIndexer
        from synth.app.project_rag.search import ProjectRAGSearch
        
        self.indexer = ProjectRAGIndexer()
        self.search = ProjectRAGSearch()
    
    def index_project(self, project_path: str) -> dict[str, Any]:
        """Index all documentation for a project."""
        return self.indexer.index_project(project_path)
    
    def search_project(
        self,
        project_path: str,
        query: str,
        doc_types: list[str] | None = None,
        limit: int = 10
    ) -> list[dict[str, Any]]:
        """Search documentation in a project."""
        results = self.search.search(
            query=query,
            doc_types=doc_types,
            project_path=project_path,
            limit=limit
        )
        
        return [
            {
                "doc_type": r.doc_type,
                "path": r.path,
                "title": r.title,
                "content": r.content,
                "project_path": r.project_path,
                "score": r.score,
                "metadata": r.metadata
            }
            for r in results
        ]
    
    def get_project_docs(self, project_path: str) -> dict[str, Any]:
        """Get all documentation for a project."""
        return self.indexer.get_docs_for_project(project_path)
    
    def get_project_summary(self, project_path: str) -> dict[str, Any]:
        """Get summary of indexed documentation for a project."""
        return self.search.get_project_summary(project_path)
    
    def get_project_tree(self, project_path: str) -> dict[str, Any]:
        """Get documentation tree for a project."""
        return self.search.get_doc_tree(project_path)
    
    def get_indexed_projects(self) -> list[str]:
        """Get list of all indexed projects."""
        return self.indexer.get_indexed_projects()
    
    def answer_help_question(
        self,
        project_path: str,
        question: str,
        use_mcp: bool = False,
        git_repo_path: str | None = None
    ) -> dict[str, Any]:
        """Answer a help question about a project using RAG and optionally MCP.
        
        Args:
            project_path: Path to the project
            question: User's question
            use_mcp: Whether to use MCP tools for additional context
            git_repo_path: Path to git repository (for MCP)
        
        Returns:
            dict with answer and context sources
        """
        context_parts = []
        sources = []
        
        # Search for relevant documentation
        results = self.search_project(project_path, question, limit=5)
        
        for r in results:
            if r["score"] > 0:
                context_parts.append(f"### {r['title']} ({r['doc_type']}: {r['path']})\n\n{r['content'][:2000]}")
                sources.append({
                    "type": r["doc_type"],
                    "path": r["path"],
                    "title": r["title"],
                    "score": r["score"]
                })
        
        # Add MCP context if requested and available
        if use_mcp:
            mcp_context = self._get_mcp_context(git_repo_path or project_path)
            if mcp_context:
                context_parts.append(mcp_context)
                sources.append({
                    "type": "git",
                    "path": git_repo_path or project_path,
                    "title": "Git Repository Info"
                })
        
        return {
            "context": "\n\n---\n\n".join(context_parts),
            "sources": sources,
            "has_context": len(context_parts) > 0
        }
    
    def _get_mcp_context(self, repo_path: str) -> str | None:
        """Get additional context from git repository via MCP tools."""
        try:
            # Try to import MCP manager
            from synth.app.mcp import MCPManager
            
            context_parts = []
            
            # Get current branch
            try:
                result = MCPManager.call_tool("git_git_branch", {"repo_path": repo_path})
                if result and not result.is_error:
                    context_parts.append(f"Current Git Branch: {result.content}")
            except Exception:
                pass
            
            # Get recent commits
            try:
                result = MCPManager.call_tool("git_git_log", {
                    "repo_path": repo_path,
                    "max_count": 5,
                    "format": "%h - %s (%an, %ar)"
                })
                if result and not result.is_error:
                    context_parts.append(f"Recent commits:\n{result.content}")
            except Exception:
                pass
            
            if context_parts:
                return "\n\n".join(context_parts)
        
        except ImportError:
            pass
        except Exception as e:
            warning("ProjectRAG", f"Failed to get MCP context: {e}")
        
        return None
    
    def build_help_context(
        self,
        project_path: str,
        git_repo_path: str | None = None
    ) -> str:
        """Build comprehensive help context for a project.
        
        This is used for /help command to provide context about the project.
        """
        parts = []
        
        # Get project tree
        tree = self.get_project_tree(project_path)
        
        if tree["structure"]["readme"]:
            for readme in tree["structure"]["readme"]:
                parts.append(f"README: {readme['title']} ({readme['path']})")
        
        if tree["structure"]["docs"]:
            parts.append("\nDocumentation:")
            for doc in tree["structure"]["docs"][:10]:  # Limit to 10
                parts.append(f"  - {doc['title']} ({doc['path']})")
        
        if tree["structure"]["schemas"]:
            parts.append("\nSchemas:")
            for schema in tree["structure"]["schemas"]:
                parts.append(f"  - {schema['title']} ({schema['path']})")
        
        if tree["structure"]["api"]:
            parts.append("\nAPI Descriptions:")
            for api in tree["structure"]["api"]:
                parts.append(f"  - {api['title']} ({api['path']})")
        
        # Get git info if available
        if git_repo_path:
            try:
                from synth.app.mcp import MCPManager
                
                # Current branch
                try:
                    result = MCPManager.call_tool("git_git_branch", {"repo_path": git_repo_path})
                    if result and not result.is_error:
                        parts.append(f"\nGit Branch: {result.content}")
                except Exception:
                    pass
                
                # Status
                try:
                    result = MCPManager.call_tool("git_git_status", {"repo_path": git_repo_path, "short": True})
                    if result and not result.is_error:
                        parts.append(f"Git Status:\n{result.content}")
                except Exception:
                    pass
            
            except ImportError:
                pass
        
        return "\n".join(parts)
