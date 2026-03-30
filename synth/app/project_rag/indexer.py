"""Project RAG Indexer for indexing project documentation."""

import os
import json
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field, asdict
import hashlib

from app.logger import info, warning, error


@dataclass
class ProjectDoc:
    """Represents a documentation file in a project."""
    path: str
    doc_type: str  # README, docs, schema, api
    content: str
    title: str = ""
    project_path: str = ""
    metadata: dict = field(default_factory=dict)


class ProjectDocIndex:
    """Index for storing project documentation metadata."""
    
    def __init__(self, index_path: Path):
        self.index_path = index_path
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.docs: list[dict] = []
        self._load()
    
    def _load(self) -> None:
        """Load index from disk."""
        if self.index_path.exists():
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.docs = data.get("docs", [])
            except Exception as e:
                warning("ProjectRAG", f"Failed to load index: {e}")
                self.docs = []
    
    def save(self) -> None:
        """Save index to disk."""
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump({"docs": self.docs}, f, ensure_ascii=False, indent=2)
    
    def add_doc(self, doc: ProjectDoc) -> None:
        """Add a document to the index."""
        doc_dict = asdict(doc)
        doc_dict["id"] = self._generate_id(doc)
        self.docs.append(doc_dict)
    
    def _generate_id(self, doc: ProjectDoc) -> str:
        """Generate unique ID for a document."""
        content = f"{doc.project_path}:{doc.path}:{doc.doc_type}"
        return hashlib.md5(content.encode()).hexdigest()[:12]
    
    def get_docs_by_type(self, doc_type: str) -> list[dict]:
        """Get all docs of a specific type."""
        return [d for d in self.docs if d.get("doc_type") == doc_type]
    
    def get_docs_by_project(self, project_path: str) -> list[dict]:
        """Get all docs for a specific project."""
        return [d for d in self.docs if d.get("project_path") == project_path]


class ProjectRAGIndexer:
    """Indexer for project documentation (README, docs, schemas)."""
    
    # Supported file extensions and their types
    SUPPORTED_EXTENSIONS = {
        ".md": "markdown",
        ".txt": "text",
        ".rst": "rst",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".xml": "xml",
        ".html": "html",
    }
    
    def __init__(self, data_dir: Path | None = None):
        from app.config import config
        
        if data_dir is None:
            data_dir = config.data_dir
        
        self.data_dir = data_dir
        self.index_dir = data_dir / "project_rag"
        self.index_dir.mkdir(parents=True, exist_ok=True)
    
    def index_project(self, project_path: str) -> dict[str, Any]:
        """Index all documentation for a project.
        
        Returns:
            dict with indexed files count and any errors.
        """
        path = Path(project_path).resolve()
        
        if not path.exists():
            return {"success": False, "error": f"Path does not exist: {project_path}"}
        
        info("ProjectRAG", f"Indexing project: {project_path}")
        
        results = {
            "success": True,
            "project_path": str(path),
            "indexed": {
                "readme": 0,
                "docs": 0,
                "schemas": 0,
                "api": 0,
            },
            "errors": []
        }
        
        # Index README files
        readme_results = self._index_readme(path)
        results["indexed"]["readme"] = readme_results["count"]
        results["errors"].extend(readme_results.get("errors", []))
        
        # Index docs directory
        docs_results = self._index_docs(path)
        results["indexed"]["docs"] = docs_results["count"]
        results["errors"].extend(docs_results.get("errors", []))
        
        # Index schema files (json schemas, yaml configs, etc.)
        schema_results = self._index_schemas(path)
        results["indexed"]["schemas"] = schema_results["count"]
        results["errors"].extend(schema_results.get("errors", []))
        
        # Index API descriptions (openapi, swagger, etc.)
        api_results = self._index_api(path)
        results["indexed"]["api"] = api_results["count"]
        results["errors"].extend(api_results.get("errors", []))
        
        total = sum(results["indexed"].values())
        info("ProjectRAG", f"Indexed {total} files for {project_path}")
        
        return results
    
    def _index_readme(self, project_path: Path) -> dict[str, Any]:
        """Index README files."""
        results = {"count": 0, "errors": []}
        index = ProjectDocIndex(self.index_dir / "readme_index.json")
        
        readme_names = ["README.md", "README.rst", "README.txt", "README", "readme.md"]
        
        for readme_name in readme_names:
            readme_path = project_path / readme_name
            if readme_path.exists() and readme_path.is_file():
                try:
                    content = readme_path.read_text(encoding="utf-8")
                    title = self._extract_title(content) or readme_name
                    
                    doc = ProjectDoc(
                        path=str(readme_path.relative_to(project_path)),
                        doc_type="readme",
                        content=content,
                        title=title,
                        project_path=str(project_path),
                        metadata={
                            "filename": readme_name,
                            "size": readme_path.stat().st_size,
                        }
                    )
                    
                    index.add_doc(doc)
                    results["count"] += 1
                    info("ProjectRAG", f"Indexed: {readme_path}")
                except Exception as e:
                    error("ProjectRAG", f"Failed to index {readme_path}: {e}")
                    results["errors"].append(f"{readme_path}: {e}")
        
        index.save()
        return results
    
    def _index_docs(self, project_path: Path) -> dict[str, Any]:
        """Index docs directory."""
        results = {"count": 0, "errors": []}
        index = ProjectDocIndex(self.index_dir / "docs_index.json")
        
        docs_path = project_path / "docs"
        if not docs_path.exists():
            return results
        
        for ext in [".md", ".rst", ".txt"]:
            for file_path in docs_path.rglob(f"*{ext}"):
                if file_path.is_file():
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        title = self._extract_title(content) or file_path.name
                        
                        doc = ProjectDoc(
                            path=str(file_path.relative_to(project_path)),
                            doc_type="docs",
                            content=content,
                            title=title,
                            project_path=str(project_path),
                            metadata={
                                "size": file_path.stat().st_size,
                                "extension": ext,
                            }
                        )
                        
                        index.add_doc(doc)
                        results["count"] += 1
                        info("ProjectRAG", f"Indexed: {file_path}")
                    except Exception as e:
                        error("ProjectRAG", f"Failed to index {file_path}: {e}")
                        results["errors"].append(f"{file_path}: {e}")
        
        index.save()
        return results
    
    def _index_schemas(self, project_path: Path) -> dict[str, Any]:
        """Index schema files (JSON schemas, YAML configs, etc.)."""
        results = {"count": 0, "errors": []}
        index = ProjectDocIndex(self.index_dir / "schemas_index.json")
        
        schema_dirs = ["schemas", "schema", "models", "types", "definitions"]
        schema_files = []
        
        # Find schema directories
        for schema_dir in schema_dirs:
            schema_path = project_path / schema_dir
            if schema_path.exists():
                for ext in [".json", ".yaml", ".yml"]:
                    schema_files.extend(schema_path.rglob(f"*{ext}"))
        
        # Also look for schema-like files in root
        for ext in [".json", ".yaml", ".yml"]:
            for pattern in ["*schema*", "*model*", "*type*", "*definition*"]:
                for file_path in project_path.glob(f"{pattern}{ext}"):
                    if file_path not in schema_files:
                        schema_files.append(file_path)
        
        for file_path in schema_files:
            if file_path.is_file():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    
                    # Try to parse and format JSON/YAML for better context
                    formatted_content = self._format_structured_content(file_path, content)
                    
                    doc = ProjectDoc(
                        path=str(file_path.relative_to(project_path)),
                        doc_type="schema",
                        content=formatted_content,
                        title=file_path.stem,
                        project_path=str(project_path),
                        metadata={
                            "size": file_path.stat().st_size,
                            "extension": file_path.suffix,
                        }
                    )
                    
                    index.add_doc(doc)
                    results["count"] += 1
                    info("ProjectRAG", f"Indexed schema: {file_path}")
                except Exception as e:
                    error("ProjectRAG", f"Failed to index schema {file_path}: {e}")
                    results["errors"].append(f"{file_path}: {e}")
        
        index.save()
        return results
    
    def _index_api(self, project_path: Path) -> dict[str, Any]:
        """Index API description files (OpenAPI, GraphQL, etc.)."""
        results = {"count": 0, "errors": []}
        index = ProjectDocIndex(self.index_dir / "api_index.json")
        
        api_files = []
        
        # Look for API description files
        api_patterns = [
            "*openapi*", "*swagger*", "*api*",
            "api.yaml", "api.yml", "api.json",
            "openapi.yaml", "openapi.yml", "openapi.json",
            "swagger.yaml", "swagger.yml", "swagger.json",
        ]
        
        for pattern in api_patterns:
            api_files.extend(project_path.glob(pattern))
        
        # Also check api/ directory
        api_dir = project_path / "api"
        if api_dir.exists():
            for ext in [".yaml", ".yml", ".json"]:
                api_files.extend(api_dir.rglob(f"*{ext}"))
        
        for file_path in api_files:
            if file_path.is_file() and file_path.name not in ["package.json", "tsconfig.json"]:
                try:
                    content = file_path.read_text(encoding="utf-8")
                    formatted_content = self._format_structured_content(file_path, content)
                    
                    doc = ProjectDoc(
                        path=str(file_path.relative_to(project_path)),
                        doc_type="api",
                        content=formatted_content,
                        title=file_path.stem,
                        project_path=str(project_path),
                        metadata={
                            "size": file_path.stat().st_size,
                            "extension": file_path.suffix,
                        }
                    )
                    
                    index.add_doc(doc)
                    results["count"] += 1
                    info("ProjectRAG", f"Indexed API: {file_path}")
                except Exception as e:
                    error("ProjectRAG", f"Failed to index API {file_path}: {e}")
                    results["errors"].append(f"{file_path}: {e}")
        
        index.save()
        return results
    
    def _extract_title(self, content: str) -> str:
        """Extract title from markdown content."""
        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
        return ""
    
    def _format_structured_content(self, file_path: Path, content: str) -> str:
        """Format structured content (JSON/YAML) for better readability."""
        ext = file_path.suffix.lower()
        
        if ext in [".json"]:
            try:
                import json
                data = json.loads(content)
                return json.dumps(data, indent=2, ensure_ascii=False)
            except:
                return content
        
        return content
    
    def get_indexed_projects(self) -> list[str]:
        """Get list of all indexed projects."""
        projects = set()
        
        for index_file in self.index_dir.glob("*_index.json"):
            index = ProjectDocIndex(index_file)
            for doc in index.docs:
                if doc.get("project_path"):
                    projects.add(doc["project_path"])
        
        return sorted(projects)
    
    def get_docs_for_project(self, project_path: str) -> dict[str, list[dict]]:
        """Get all indexed docs for a project grouped by type."""
        result = {
            "readme": [],
            "docs": [],
            "schemas": [],
            "api": []
        }
        
        for doc_type in result.keys():
            index_file = self.index_dir / f"{doc_type}_index.json"
            if index_file.exists():
                index = ProjectDocIndex(index_file)
                result[doc_type] = index.get_docs_by_project(project_path)
        
        return result
