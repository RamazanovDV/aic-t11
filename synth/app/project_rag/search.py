"""Project RAG Search module for searching indexed project documentation."""

import os
import json
from pathlib import Path
from typing import Any, Literal
from dataclasses import dataclass, field

from app.logger import info, warning, error


@dataclass
class SearchResult:
    """Represents a search result from project documentation."""
    doc_type: str
    path: str
    title: str
    content: str
    project_path: str
    score: float = 0.0
    metadata: dict = field(default_factory=dict)


class ProjectRAGSearch:
    """Search for information in indexed project documentation."""
    
    def __init__(self, data_dir: Path | None = None):
        from app.config import config
        
        if data_dir is None:
            data_dir = config.data_dir
        
        self.data_dir = data_dir
        self.index_dir = data_dir / "project_rag"
    
    def search(
        self,
        query: str,
        doc_types: list[str] | None = None,
        project_path: str | None = None,
        limit: int = 10
    ) -> list[SearchResult]:
        """Search for query in indexed project documentation.
        
        Args:
            query: Search query
            doc_types: Filter by document types (readme, docs, schema, api)
            project_path: Filter by specific project
            limit: Maximum number of results
        
        Returns:
            List of SearchResult objects sorted by relevance.
        """
        if doc_types is None:
            doc_types = ["readme", "docs", "schema", "api"]
        
        results: list[SearchResult] = []
        query_lower = query.lower()
        query_words = query_lower.split()
        
        for doc_type in doc_types:
            index_file = self.index_dir / f"{doc_type}_index.json"
            if not index_file.exists():
                continue
            
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                docs = data.get("docs", [])
                
                for doc in docs:
                    # Filter by project if specified
                    if project_path and doc.get("project_path") != project_path:
                        continue
                    
                    # Calculate relevance score
                    score = self._calculate_score(query_lower, query_words, doc)
                    
                    if score > 0:
                        result = SearchResult(
                            doc_type=doc.get("doc_type", doc_type),
                            path=doc.get("path", ""),
                            title=doc.get("title", ""),
                            content=doc.get("content", ""),
                            project_path=doc.get("project_path", ""),
                            score=score,
                            metadata=doc.get("metadata", {})
                        )
                        results.append(result)
            
            except Exception as e:
                warning("ProjectRAG", f"Failed to search {doc_type}: {e}")
        
        # Sort by score (descending) and limit
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]
    
    def _calculate_score(
        self,
        query_lower: str,
        query_words: list[str],
        doc: dict
    ) -> float:
        """Calculate relevance score for a document."""
        score = 0.0
        content_lower = doc.get("content", "").lower()
        title_lower = doc.get("title", "").lower()
        path_lower = doc.get("path", "").lower()
        
        # Exact match in content
        if query_lower in content_lower:
            score += 10.0
        
        # Title match (higher weight)
        if query_lower in title_lower:
            score += 20.0
        
        # Path match
        if query_lower in path_lower:
            score += 5.0
        
        # Word matches in content
        for word in query_words:
            if len(word) < 3:
                continue
            if word in content_lower:
                score += 2.0
            if word in title_lower:
                score += 5.0
            if word in path_lower:
                score += 1.0
        
        # Boost for shorter documents (more focused)
        content_len = len(doc.get("content", ""))
        if content_len < 1000:
            score *= 1.5
        elif content_len < 5000:
            score *= 1.2
        
        return score
    
    def search_by_project(
        self,
        project_path: str,
        query: str,
        limit: int = 10
    ) -> list[SearchResult]:
        """Search only within a specific project."""
        return self.search(
            query=query,
            doc_types=None,
            project_path=project_path,
            limit=limit
        )
    
    def get_project_summary(self, project_path: str) -> dict[str, Any]:
        """Get a summary of all indexed documentation for a project."""
        summary = {
            "project_path": project_path,
            "total_docs": 0,
            "by_type": {
                "readme": {"count": 0, "files": []},
                "docs": {"count": 0, "files": []},
                "schema": {"count": 0, "files": []},
                "api": {"count": 0, "files": []}
            }
        }
        
        for doc_type in summary["by_type"].keys():
            index_file = self.index_dir / f"{doc_type}_index.json"
            if not index_file.exists():
                continue
            
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                docs = [d for d in data.get("docs", []) 
                       if d.get("project_path") == project_path]
                
                summary["by_type"][doc_type]["count"] = len(docs)
                summary["by_type"][doc_type]["files"] = [
                    {
                        "path": d.get("path", ""),
                        "title": d.get("title", ""),
                        "size": d.get("metadata", {}).get("size", 0)
                    }
                    for d in docs
                ]
                summary["total_docs"] += len(docs)
            
            except Exception as e:
                warning("ProjectRAG", f"Failed to get summary for {doc_type}: {e}")
        
        return summary
    
    def get_readme_content(self, project_path: str) -> str | None:
        """Get the README content for a project."""
        results = self.search(
            query="README",
            doc_types=["readme"],
            project_path=project_path,
            limit=1
        )
        
        if results:
            return results[0].content
        return None
    
    def get_doc_tree(self, project_path: str) -> dict[str, Any]:
        """Build a tree structure of documentation for a project."""
        tree = {
            "project_path": project_path,
            "structure": {
                "readme": [],
                "docs": [],
                "schemas": [],
                "api": []
            }
        }
        
        for doc_type, type_key in [
            ("readme", "readme"),
            ("docs", "docs"),
            ("schema", "schemas"),
            ("api", "api")
        ]:
            index_file = self.index_dir / f"{doc_type}_index.json"
            if not index_file.exists():
                continue
            
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                docs = [d for d in data.get("docs", [])
                       if d.get("project_path") == project_path]
                
                tree["structure"][type_key] = [
                    {
                        "path": d.get("path", ""),
                        "title": d.get("title", "")
                    }
                    for d in docs
                ]
            
            except Exception as e:
                warning("ProjectRAG", f"Failed to build tree for {doc_type}: {e}")
        
        return tree
