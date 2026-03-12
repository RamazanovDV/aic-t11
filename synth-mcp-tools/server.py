import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

try:
    import requests
except ImportError:
    requests = None


class MCPConfig:
    def __init__(self, config_path: Path | None = None):
        self._config: dict[str, Any] = {}
        self._load_config(config_path)

    def _load_config(self, config_path: Path | None = None) -> None:
        if config_path is None:
            env_path = os.environ.get("T6_CONFIG_PATH")
            if env_path:
                config_path = Path(env_path)
            else:
                server_dir = Path(__file__).parent
                config_path = server_dir / "config.yaml"
                if not config_path.exists():
                    synth_dir = server_dir.parent / "synth"
                    config_path = synth_dir / "config.yaml"

        if not config_path or not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, "r") as f:
            self._config = yaml.safe_load(f) or {}

    @property
    def storage(self) -> dict[str, Any]:
        return self._config.get("storage", {})

    @property
    def data_dir(self) -> Path:
        dir_name = self.storage.get("data_dir", "./data")
        server_dir = Path(__file__).parent
        synth_dir = server_dir.parent / "synth"
        base = synth_dir if synth_dir.exists() else server_dir
        return base / dir_name

    @property
    def summarizer_config(self) -> dict[str, Any]:
        return self._config.get("summarizer", {})

    @property
    def summarizer_provider(self) -> str:
        return self.summarizer_config.get("provider", "openai")

    @property
    def summarizer_model(self) -> str:
        return self.summarizer_config.get("model", "gpt-4o-mini")

    @property
    def summarizer_temperature(self) -> float:
        return self.summarizer_config.get("temperature", 0.3)

    @property
    def providers(self) -> dict[str, dict[str, Any]]:
        return self._config.get("providers", {})

    def get_provider_config(self, name: str) -> dict[str, Any]:
        return self.providers.get(name, {}).copy()


mcp_config = MCPConfig()


def search_sessions(query: str, session_ids: list[str] | None = None) -> list[dict]:
    results = []
    sessions_dir = mcp_config.data_dir / "sessions"

    if not sessions_dir.exists():
        return results

    query_lower = query.lower()

    for session_file in sessions_dir.glob("*.json"):
        if session_file.name == "index.json":
            continue

        session_id = session_file.stem
        if session_ids and session_id not in session_ids:
            continue

        try:
            with open(session_file, "r") as f:
                data = json.load(f)

            session_id = data.get("session_id", session_id)
            messages = data.get("messages", [])

            for i, msg in enumerate(messages):
                content = msg.get("content", "")
                if query_lower in content.lower():
                    msg_result = {
                        "session_id": session_id,
                        "message_index": i,
                        "role": msg.get("role"),
                        "model": msg.get("model"),
                        "created_at": msg.get("created_at"),
                        "content_preview": content[:500] + "..." if len(content) > 500 else content,
                    }
                    results.append(msg_result)

        except Exception as e:
            print(f"[SEARCH] Error reading session {session_file}: {e}", file=sys.stderr)

    return results


def search_projects(query: str) -> list[dict]:
    results = []
    projects_dir = mcp_config.data_dir / "projects"

    if not projects_dir.exists():
        return results

    query_lower = query.lower()

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        project_name = project_dir.name

        files_to_check = {
            "info.md": "info",
            "current_task.md": "current_task",
            "schedules.yaml": "schedules",
        }

        for filename, field_type in files_to_check.items():
            file_path = project_dir / filename
            if not file_path.exists():
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
                if query_lower in content.lower():
                    results.append({
                        "project": project_name,
                        "field": field_type,
                        "file": filename,
                        "content_preview": content[:500] + "..." if len(content) > 500 else content,
                    })
            except Exception as e:
                print(f"[SEARCH] Error reading {file_path}: {e}", file=sys.stderr)

        project_data_dir = project_dir / "project_data"
        if project_data_dir.exists() and project_data_dir.is_dir():
            for data_file in project_data_dir.iterdir():
                if not data_file.is_file():
                    continue

                try:
                    content = data_file.read_text(encoding="utf-8")
                    if query_lower in content.lower():
                        results.append({
                            "project": project_name,
                            "field": "project_data",
                            "file": f"project_data/{data_file.name}",
                            "content_preview": content[:500] + "..." if len(content) > 500 else content,
                        })
                except Exception as e:
                    print(f"[SEARCH] Error reading {data_file}: {e}", file=sys.stderr)

    return results


def summarize_text(content: str, max_length: int = 200) -> str:
    provider = mcp_config.summarizer_provider
    model = mcp_config.summarizer_model
    temperature = mcp_config.summarizer_temperature
    provider_config = mcp_config.get_provider_config(provider)

    if not provider_config:
        return f"Error: Provider '{provider}' not configured"

    api_key = provider_config.get("api_key")
    api_url = provider_config.get("url", "").rstrip("/")

    if provider == "openai":
        if not api_key:
            return "Error: OpenAI API key not configured"
        url = f"{api_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": f"Создай краткое резюме (не более {max_length} слов) следующего текста:\n\n{content}"
                }
            ],
            "temperature": temperature,
            "max_tokens": 1000
        }
    elif provider == "anthropic":
        if not api_key:
            return "Error: Anthropic API key not configured"
        url = f"{api_url}/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "max_tokens": 1000,
            "temperature": temperature,
            "messages": [
                {
                    "role": "user",
                    "content": f"Создай краткое резюме (не более {max_length} слов) следующего текста:\n\n{content}"
                }
            ]
        }
    elif provider == "ollama":
        url = f"{api_url}/chat"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": f"Создай краткое резюме (не более {max_length} слов) следующего текста:\n\n{content}"
                }
            ],
            "stream": False
        }
    else:
        api_key = provider_config.get("api_key", "")
        if api_key:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
        else:
            headers = {"Content-Type": "application/json"}
        url = f"{api_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": f"Создай краткое резюме (не более {max_length} слов) следующего текста:\n\n{content}"
                }
            ],
            "temperature": temperature,
            "max_tokens": 1000
        }
        provider = "generic"

    if not requests:
        return "Error: requests library not installed"

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        if provider in ("openai", "generic"):
            result = response.json()
            return result.get("choices", [{}])[0].get("message", {}).get("content", "")
        elif provider == "anthropic":
            result = response.json()
            return result.get("content", [{}])[0].get("text", "")
        elif provider == "ollama":
            result = response.json()
            return result.get("message", {}).get("content", "")

    except requests.RequestException as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"

    return "Error: Unexpected error in summarize"


ALLOWED_EXTENSIONS = {".json", ".txt", ".md", ".yaml", ".yml", ".csv"}


def save_to_file(project_name: str, filename: str, content: str, mode: str = "overwrite") -> str:
    if ".." in filename or filename.startswith("/"):
        return "Error: Invalid filename"

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return f"Error: Extension '{ext}' not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"

    project_dir = mcp_config.data_dir / "projects" / project_name

    if not project_dir.exists():
        return f"Error: Project '{project_name}' does not exist"

    project_data_dir = project_dir / "project_data"
    project_data_dir.mkdir(exist_ok=True)

    file_path = project_data_dir / filename

    try:
        if mode == "append" and file_path.exists():
            existing = file_path.read_text(encoding="utf-8")
            file_path.write_text(existing + "\n" + content, encoding="utf-8")
        else:
            file_path.write_text(content, encoding="utf-8")

        return f"OK: File saved to {file_path}"

    except Exception as e:
        return f"Error: {str(e)}"


app = Server("synth-tools")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search",
            description="Search for text in sessions and projects. Searches session messages (excluding debug data) and project files (info.md, current_task.md, schedules.yaml, and project_data/*)",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to search for"
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["all", "sessions", "projects"],
                        "default": "all",
                        "description": "Search scope"
                    },
                    "session_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific session IDs to search (optional, for sessions scope only)"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="summarize",
            description="Summarize text using the configured LLM summarizer provider",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Text to summarize"
                    },
                    "max_length": {
                        "type": "integer",
                        "default": 200,
                        "description": "Maximum words in summary"
                    }
                },
                "required": ["content"]
            }
        ),
        Tool(
            name="save_to_file",
            description="Save content to a file in project's project_data directory",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "Project name"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Filename (relative path inside project_data)"
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to save"
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["overwrite", "append"],
                        "default": "overwrite",
                        "description": "Write mode"
                    }
                },
                "required": ["project_name", "filename", "content"]
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "search":
            query = arguments.get("query", "")
            scope = arguments.get("scope", "all")
            session_ids = arguments.get("session_ids")

            if not query:
                return [TextContent(type="text", text="Error: query is required")]

            results = []

            if scope in ("all", "sessions"):
                session_results = search_sessions(query, session_ids)
                results.extend(session_results)

            if scope in ("all", "projects"):
                project_results = search_projects(query)
                results.extend(project_results)

            return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False, indent=2))]

        elif name == "summarize":
            content = arguments.get("content", "")
            max_length = arguments.get("max_length", 200)

            if not content:
                return [TextContent(type="text", text="Error: content is required")]

            summary = summarize_text(content, max_length)
            return [TextContent(type="text", text=summary)]

        elif name == "save_to_file":
            project_name = arguments.get("project_name", "")
            filename = arguments.get("filename", "")
            content = arguments.get("content", "")
            mode = arguments.get("mode", "overwrite")

            if not project_name or not filename or content is None:
                return [TextContent(type="text", text="Error: project_name, filename and content are required")]

            result = save_to_file(project_name, filename, content, mode)
            return [TextContent(type="text", text=result)]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
