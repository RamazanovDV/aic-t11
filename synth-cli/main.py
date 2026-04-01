import json
from chunker import create_chunker
import os
from pathlib import Path

import click
import requests
import yaml


class CLIConfig:
    def __init__(self):
        config_path = Path(__file__).parent / "config.yaml"
        if not config_path.exists():
            config_path = Path(__file__).parent.parent / "ui" / "config.yaml"
        
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found")

        with open(config_path, "r") as f:
            self._config = yaml.safe_load(f)

    @property
    def backend_url(self) -> str:
        return self._config.get("backend", {}).get("url", "http://localhost:5000")

    @property
    def backend_api_key(self) -> str:
        return self._config.get("backend", {}).get("api_key", "")

    @property
    def auth_api_key(self) -> str:
        return self._config.get("auth", {}).get("api_key", "")


config = CLIConfig()


def get_session_id() -> str:
    return os.environ.get("T6_SESSION_ID", "cli-default")


def get_headers() -> dict:
    return {
        "X-API-Key": config.backend_api_key or config.auth_api_key,
        "X-Session-Id": get_session_id(),
    }


@click.group()
@click.option('--interactive', '-i', is_flag=True, help='Start interactive mode')
@click.pass_context
def cli(ctx, interactive):
    """T6 AI Assistant CLI"""
    ctx.ensure_object(dict)
    ctx.obj['INTERACTIVE'] = interactive


def interactive_mode():
    """Run CLI in interactive/repl mode"""
    click.echo("\n=== T6 AI Assistant CLI ===")
    click.echo("Type 'help' for commands, 'exit' to quit\n")
    
    current_session = get_session_id()
    current_provider = None
    
    while True:
        try:
            prompt = f"t6[{current_session}]> "
            user_input = input(prompt).strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ('exit', 'quit', 'q'):
                click.echo("Goodbye!")
                break
            
            if user_input.lower() == 'help':
                click.echo("""
Commands:
  chat <message>           Send a message to AI
  session                  Show current session
  session <name>          Switch to session
  session list             List all sessions
  provider                 Show current provider
  provider <name>          Set provider (openai, anthropic, ollama, itphx)
  clear                    Clear screen
  help                     Show this help
  exit                     Exit interactive mode
""")
                continue
            
            if user_input.lower() == 'clear':
                os.system('clear' if os.name == 'posix' else 'cls')
                continue
            
            if user_input.lower() == 'session list':
                list_sessions()
                continue
            
            if user_input.lower() == 'session':
                click.echo(f"Current session: {current_session}")
                continue
            
            if user_input.lower().startswith('session '):
                name = user_input[8:].strip()
                os.environ["T6_SESSION_ID"] = name
                current_session = name
                click.echo(f"Switched to session: {current_session}")
                continue
            
            if user_input.lower() == 'provider':
                click.echo(f"Current provider: {current_provider or 'default'}")
                continue
            
            if user_input.lower().startswith('provider '):
                current_provider = user_input[9:].strip()
                click.echo(f"Provider set to: {current_provider}")
                continue
            
            # Treat everything else as a chat message
            message = user_input
            send_chat(message, current_provider, current_session)
            
        except KeyboardInterrupt:
            click.echo("\nUse 'exit' to quit")
            continue
        except EOFError:
            click.echo("\nGoodbye!")
            break


def send_chat(message: str, provider: str | None, session_id: str):
    url = f"{config.backend_url}/chat"
    headers = get_headers()
    headers["X-Session-Id"] = session_id
    
    payload = {"message": message, "source": "cli", "username": "cli"}
    if provider:
        payload["provider"] = provider

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        click.echo()
        click.echo(data.get("message", ""))
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


def list_sessions():
    url = f"{config.backend_url}/sessions"
    headers = {
        "X-API-Key": config.backend_api_key or config.auth_api_key,
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        sessions = data.get("sessions", [])
        if not sessions:
            click.echo("No sessions found")
            return

        click.echo(f"Found {len(sessions)} session(s):\n")
        for s in sessions:
            sid = s.get("session_id", "unknown")
            count = s.get("message_count", 0)
            updated = s.get("updated_at", "N/A")
            click.echo(f"  {sid}: {count} messages, updated: {updated}")
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


@cli.command()
@click.argument("message")
@click.option("-p", "--provider", default=None, help="LLM provider")
@click.option("-s", "--session", default=None, help="Session ID")
def chat(message: str, provider: str | None, session: str | None):
    """Send a message to the AI"""
    if session:
        os.environ["T6_SESSION_ID"] = session

    send_chat(message, provider, get_session_id())


@cli.group()
def session():
    """Manage sessions"""
    pass


@session.command("list")
def session_list():
    """List all sessions"""
    list_sessions()


@session.command("new")
@click.argument("name", required=False, default="default")
def session_new(name: str):
    """Create a new session (just sets it as current)"""
    os.environ["T6_SESSION_ID"] = name
    click.echo(click.style(f"Session set to: {name}", fg="green"))


@session.command("show")
@click.argument("session_id", required=False)
def session_show(session_id: str | None):
    """Show session messages"""
    sid = session_id or get_session_id()
    url = f"{config.backend_url}/sessions/{sid}"
    headers = {
        "X-API-Key": config.backend_api_key or config.auth_api_key,
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 404:
            click.echo(click.style(f"Session '{sid}' not found", fg="yellow"))
            return
        response.raise_for_status()
        data = response.json()
        
        messages = data.get("messages", [])
        if not messages:
            click.echo(f"Session '{sid}' is empty")
            return

        click.echo(f"Session: {sid}\n")
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            click.echo(f"{role.upper()}: {content[:100]}{'...' if len(content) > 100 else ''}")
            click.echo()
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


@session.command("delete")
@click.argument("session_id")
def session_delete(session_id: str):
    """Delete a session"""
    if session_id == "default":
        click.echo(click.style("Cannot delete default session", fg="red"), err=True)
        return

    url = f"{config.backend_url}/sessions/{session_id}"
    headers = {
        "X-API-Key": config.backend_api_key or config.auth_api_key,
    }

    try:
        response = requests.delete(url, headers=headers, timeout=10)
        response.raise_for_status()
        click.echo(click.style(f"Session '{session_id}' deleted", fg="green"))
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


@session.command("rename")
@click.argument("old_id")
@click.argument("new_name")
def session_rename(old_id: str, new_name: str):
    """Rename a session"""
    url = f"{config.backend_url}/sessions/{old_id}/rename"
    headers = {
        "X-API-Key": config.backend_api_key or config.auth_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json={"new_name": new_name}, timeout=10)
        response.raise_for_status()
        click.echo(click.style(f"Session '{old_id}' renamed to '{new_name}'", fg="green"))
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


@session.command("reset")
@click.option("-s", "--session", default=None, help="Session ID to reset")
def session_reset(session: str | None):
    """Reset chat history"""
    sid = session or get_session_id()
    url = f"{config.backend_url}/chat/reset"
    headers = get_headers()
    headers["X-Session-Id"] = sid

    try:
        response = requests.post(url, headers=headers, timeout=30)
        response.raise_for_status()
        click.echo(click.style(f"Session '{sid}' reset successfully", fg="green"))
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


@session.command("export")
@click.argument("session_id", required=False)
@click.option("-o", "--output", default=None, help="Output file")
def session_export(session_id: str | None, output: str | None):
    """Export session(s) to file"""
    if session_id:
        url = f"{config.backend_url}/sessions/{session_id}"
        headers = {
            "X-API-Key": config.backend_api_key or config.auth_api_key,
        }
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            click.echo(click.style(f"Error: {e}", fg="red"), err=True)
            return
    else:
        url = f"{config.backend_url}/sessions/export"
        headers = {
            "X-API-Key": config.backend_api_key or config.auth_api_key,
        }
        try:
            response = requests.post(url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            click.echo(click.style(f"Error: {e}", fg="red"), err=True)
            return

    filename = output or f"t6-session-{session_id or 'all'}.json"
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)
    
    click.echo(click.style(f"Exported to {filename}", fg="green"))


@session.command("import")
@click.argument("file_path", type=click.Path(exists=True))
def session_import(file_path: str):
    """Import session from file"""
    with open(file_path, "r") as f:
        data = json.load(f)

    url = f"{config.backend_url}/sessions/import"
    headers = {
        "X-API-Key": config.backend_api_key or config.auth_api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        click.echo(click.style(f"Imported: {result.get('session_id')}", fg="green"))
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


@cli.command()
def health():
    """Check backend health"""
    url = f"{config.backend_url}/health"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            click.echo(click.style("Backend: OK", fg="green"))
        else:
            click.echo(click.style(f"Backend: {response.status_code}", fg="yellow"))
    except requests.RequestException as e:
        click.echo(click.style(f"Backend: unreachable - {e}", fg="red"), err=True)


@cli.command()
def repl():
    """Start interactive REPL mode"""
    interactive_mode()


def main():
    import sys
    if len(sys.argv) == 1:
        interactive_mode()
    else:
        cli(obj={})


def login(username: str, password: str) -> dict:
    url = f"{config.backend_url}/api/auth/login"
    try:
        response = requests.post(url, json={"username": username, "password": password}, timeout=10)
        if response.status_code == 200:
            return {"success": True, "cookies": response.cookies}
        else:
            return {"success": False, "error": response.json().get("error", "Login failed")}
    except requests.RequestException as e:
        return {"success": False, "error": str(e)}


def get_auth_headers(use_cookies: bool = False) -> dict:
    headers = {
        "X-API-Key": config.backend_api_key or config.auth_api_key,
    }
    if use_cookies:
        return headers
    return headers


@click.group()
def embeddings():
    """Manage embedding indexes"""
    pass


@embeddings.command("create")
@click.option("--name", required=True, help="Index name")
@click.option("--description", default="", help="Index description")
@click.option("--source", "source_dir", required=True, help="Source directory to index")
@click.option("--provider", default=None, help="Embedding provider (default: from config)")
@click.option("--model", default=None, help="Embedding model (default: from config)")
@click.option("--strategy", default="fixed", help="Chunking strategy (fixed/structure)")
@click.option("--chunk-size", default=50, help="Chunk size (for fixed strategy)")
@click.option("--overlap", default=5, help="Chunk overlap (for fixed strategy)")
@click.option("--min-chunk", default=20, help="Min chunk size (for structure strategy)")
@click.option("--max-chunk", default=150, help="Max chunk size (for structure strategy)")
@click.option("--batch-size", default=50, help="Number of chunks per batch")
@click.option("--username", prompt=True, help="Username for authentication")
@click.option("--password", prompt=True, hide_input=True, help="Password for authentication")
def embeddings_create(name, description, source_dir, provider, model, strategy, chunk_size, overlap, min_chunk, max_chunk, batch_size, username, password):
    """Create a new embedding index"""
    login_result = login(username, password)
    if not login_result.get("success"):
        click.echo(click.style(f"Login failed: {login_result.get('error')}", fg="red"), err=True)
        return

    cookies = login_result.get("cookies", {})
    headers = get_auth_headers()
    
    try:
        config_response = requests.get(
            f"{config.backend_url}/api/embeddings/config",
            headers=headers,
            cookies=cookies,
            timeout=30
        )
        if config_response.ok:
            embed_config = config_response.json()
            default_provider = embed_config.get("default_provider", "ollama")
            default_model = embed_config.get("default_model", "nomic-embed-text-v2-moe:latest")
        else:
            default_provider = "ollama"
            default_model = "nomic-embed-text-v2-moe:latest"
    except Exception:
        default_provider = "ollama"
        default_model = "nomic-embed-text-v2-moe:latest"
    
    effective_provider = provider or default_provider
    effective_model = model or default_model
    
    if not provider or not model:
        click.echo(f"Using default settings: provider={effective_provider}, model={effective_model}")
    
    source_path = Path(source_dir)
    if not source_path.exists():
        click.echo(click.style(f"Source directory not found: {source_dir}", fg="red"), err=True)
        return

    chunking_params = {}
    if strategy == "fixed":
        chunking_params = {"chunk_size": chunk_size, "overlap": overlap}
    else:
        chunking_params = {"min_chunk_size": min_chunk, "max_chunk_size": max_chunk, "preserve_headers": True}

    click.echo(f"Reading files from {source_dir}...")
    chunker = create_chunker(strategy, chunking_params)
    chunks = chunker.chunk_directory(source_path)
    
    if not chunks:
        click.echo(click.style("No chunks created", fg="red"), err=True)
        return

    click.echo(f"Created {len(chunks)} chunks, sending in batches of {batch_size}...")

    headers["Content-Type"] = "application/json"

    url = f"{config.backend_url}/api/embeddings"

    total_batches = (len(chunks) + batch_size - 1) // batch_size
    
    store_key = None
    
    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, len(chunks))
        batch_chunks = chunks[start:end]
        
        is_first = batch_idx == 0
        is_last = batch_idx == total_batches - 1
        
        payload = {
            "name": name,
            "description": description if is_first else "",
            "provider": effective_provider,
            "model": effective_model,
            "chunking_strategy": strategy,
            "chunking_params": chunking_params if is_first else {},
            "action": "start" if is_first else ("finish" if is_last else "continue"),
            "store_key": store_key,
            "batch_index": batch_idx,
            "total_batches": total_batches,
            "chunks": [
                {
                    "id": c.id,
                    "content": c.content,
                    "metadata": c.metadata
                }
                for c in batch_chunks
            ]
        }

        try:
            response = requests.post(url, headers=headers, json=payload, cookies=cookies, timeout=300)
            response.raise_for_status()
            result = response.json()
            
            if is_first and store_key is None:
                store_key = result.get("store_key")
            
            if is_last:
                click.echo(click.style(f"Index created: {result.get('id')}", fg="green"))
                click.echo(f"Version: {result.get('version')}")
                click.echo(f"Chunks: {result.get('chunk_count')}")
            else:
                click.echo(f"Batch {batch_idx + 1}/{total_batches} sent...")
                
        except requests.RequestException as e:
            click.echo(click.style(f"Error: {e}", fg="red"), err=True)
            return


@embeddings.command("list")
@click.option("--username", prompt=True, help="Username for authentication")
@click.option("--password", prompt=True, hide_input=True, help="Password for authentication")
def embeddings_list(username, password):
    """List all embedding indexes"""
    login_result = login(username, password)
    if not login_result.get("success"):
        click.echo(click.style(f"Login failed: {login_result.get('error')}", fg="red"), err=True)
        return

    cookies = login_result.get("cookies", {})

    url = f"{config.backend_url}/api/embeddings"
    headers = get_auth_headers()

    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=10)
        response.raise_for_status()
        indexes = response.json()

        if not indexes:
            click.echo("No indexes found")
            return

        click.echo(f"Found {len(indexes)} index(es):\n")
        for idx in indexes:
            click.echo(f"  {idx.get('name')} (v{idx.get('version')})")
            click.echo(f"    ID: {idx.get('id')}")
            click.echo(f"    Provider: {idx.get('provider')}/{idx.get('model')}")
            click.echo(f"    Strategy: {idx.get('chunking_strategy')}")
            click.echo(f"    Files: {idx.get('file_count')}, Chunks: {idx.get('chunk_count')}")
            click.echo(f"    Ratings: +{idx.get('ratings', {}).get('thumbs_up', 0)} / -{idx.get('ratings', {}).get('thumbs_down', 0)}")
            click.echo()
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


@embeddings.command("info")
@click.argument("index_id")
@click.option("--username", prompt=True, help="Username for authentication")
@click.option("--password", prompt=True, hide_input=True, help="Password for authentication")
def embeddings_info(index_id, username, password):
    """Get embedding index info"""
    login_result = login(username, password)
    if not login_result.get("success"):
        click.echo(click.style(f"Login failed: {login_result.get('error')}", fg="red"), err=True)
        return

    cookies = login_result.get("cookies", {})

    url = f"{config.backend_url}/api/embeddings/{index_id}"
    headers = get_auth_headers()

    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=10)
        if response.status_code == 404:
            click.echo(click.style(f"Index '{index_id}' not found", fg="yellow"))
            return
        response.raise_for_status()
        idx = response.json()

        click.echo(f"Index: {idx.get('name')}")
        click.echo(f"Version: {idx.get('version')}")
        click.echo(f"ID: {idx.get('id')}")
        click.echo(f"Description: {idx.get('description')}")
        click.echo(f"Provider: {idx.get('provider')}/{idx.get('model')}")
        click.echo(f"Strategy: {idx.get('chunking_strategy')}")
        click.echo(f"Chunking params: {idx.get('chunking_params')}")
        click.echo(f"Source: {idx.get('source_dir')}")
        click.echo(f"Files: {idx.get('file_count')}")
        click.echo(f"Chunks: {idx.get('chunk_count')}")
        click.echo(f"Dimension: {idx.get('dimension')}")
        click.echo(f"Ratings: +{idx.get('ratings', {}).get('thumbs_up', 0)} / -{idx.get('ratings', {}).get('thumbs_down', 0)}")
        click.echo(f"Created: {idx.get('created_at')}")
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


@embeddings.command("delete")
@click.argument("index_id")
@click.option("--username", prompt=True, help="Username for authentication")
@click.option("--password", prompt=True, hide_input=True, help="Password for authentication")
def embeddings_delete(index_id, username, password):
    """Delete an embedding index"""
    login_result = login(username, password)
    if not login_result.get("success"):
        click.echo(click.style(f"Login failed: {login_result.get('error')}", fg="red"), err=True)
        return

    cookies = login_result.get("cookies", {})

    url = f"{config.backend_url}/api/embeddings/{index_id}"
    headers = get_auth_headers()

    try:
        response = requests.delete(url, headers=headers, cookies=cookies, timeout=10)
        if response.status_code == 404:
            click.echo(click.style(f"Index '{index_id}' not found", fg="yellow"))
            return
        response.raise_for_status()
        click.echo(click.style(f"Index '{index_id}' deleted", fg="green"))
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


@embeddings.command("search")
@click.argument("query")
@click.option("--name", "index_name", help="Index name to search in")
@click.option("--id", "index_id", help="Index ID to search in")
@click.option("--top-k", default=5, help="Number of results")
@click.option("--username", prompt=True, help="Username for authentication")
@click.option("--password", prompt=True, hide_input=True, help="Password for authentication")
def embeddings_search(query, index_name, index_id, top_k, username, password):
    """Search in embedding index"""
    if not index_name and not index_id:
        click.echo(click.style("Must provide either --name or --id", fg="red"), err=True)
        return

    login_result = login(username, password)
    if not login_result.get("success"):
        click.echo(click.style(f"Login failed: {login_result.get('error')}", fg="red"), err=True)
        return

    cookies = login_result.get("cookies", {})

    url = f"{config.backend_url}/api/embeddings/search"
    headers = get_auth_headers()
    headers["Content-Type"] = "application/json"

    payload = {
        "query": query,
        "top_k": top_k,
    }
    if index_name:
        payload["index_name"] = index_name
    if index_id:
        payload["index_id"] = index_id

    try:
        response = requests.post(url, headers=headers, json=payload, cookies=cookies, timeout=60)
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])

        if not results:
            click.echo("No results found")
            return

        click.echo(f"Found {len(results)} result(s):\n")
        for i, result in enumerate(results, 1):
            metadata = result.get("metadata", {})
            source = metadata.get("source", "unknown")
            section = metadata.get("section", "")
            click.echo(f"--- Result {i} (distance: {result.get('distance', 0):.4f}) ---")
            click.echo(f"Source: {source}")
            if section:
                click.echo(f"Section: {section}")
            click.echo(f"Content: {result.get('content', '')[:300]}...")
            click.echo()
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


@embeddings.command("rate")
@click.argument("index_id")
@click.option("--thumbs-up", "thumbs_up", is_flag=True, help="Thumbs up")
@click.option("--thumbs-down", "thumbs_down", is_flag=True, help="Thumbs down")
@click.option("--username", prompt=True, help="Username for authentication")
@click.option("--password", prompt=True, hide_input=True, help="Password for authentication")
def embeddings_rate(index_id, thumbs_up, thumbs_down, username, password):
    """Rate an embedding index"""
    if not thumbs_up and not thumbs_down:
        click.echo(click.style("Must provide either --thumbs-up or --thumbs-down", fg="red"), err=True)
        return

    login_result = login(username, password)
    if not login_result.get("success"):
        click.echo(click.style(f"Login failed: {login_result.get('error')}", fg="red"), err=True)
        return

    cookies = login_result.get("cookies", {})

    url = f"{config.backend_url}/api/embeddings/{index_id}/rate"
    headers = get_auth_headers()
    headers["Content-Type"] = "application/json"

    rating = "thumbs_up" if thumbs_up else "thumbs_down"

    try:
        response = requests.post(url, headers=headers, json={"rating": rating}, cookies=cookies, timeout=10)
        if response.status_code == 404:
            click.echo(click.style(f"Index '{index_id}' not found", fg="yellow"))
            return
        response.raise_for_status()
        result = response.json()
        click.echo(click.style("Rating updated", fg="green"))
        click.echo(f"Ratings: +{result.get('ratings', {}).get('thumbs_up', 0)} / -{result.get('ratings', {}).get('thumbs_down', 0)}")
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


cli.add_command(embeddings)


@click.group()
def git():
    """Git repository management"""
    pass


@git.command("clone")
@click.option("--project", required=True, help="Project name")
@click.option("--url", required=True, help="Repository URL")
@click.option("--name", help="Repository name (default: derived from URL)")
@click.option("--type", "repo_type", default="https", help="Repository type (https/ssh)")
@click.option("--branch", default="main", help="Branch to checkout")
@click.option("--agent", help="Agent name for SSH key")
@click.option("--auto-index/--no-auto-index", default=True, help="Auto-index after clone")
@click.option("--username", prompt=True, help="Username for authentication")
@click.option("--password", prompt=True, hide_input=True, help="Password for authentication")
def git_clone(project, url, name, repo_type, branch, agent, auto_index, username, password):
    """Clone a git repository"""
    login_result = login(username, password)
    if not login_result.get("success"):
        click.echo(click.style(f"Login failed: {login_result.get('error')}", fg="red"), err=True)
        return

    cookies = login_result.get("cookies", {})
    headers = get_auth_headers()
    headers["Content-Type"] = "application/json"

    payload = {
        "url": url,
        "name": name,
        "type": repo_type,
        "branch": branch,
        "required_agent": agent,
        "auto_index": auto_index
    }

    url_api = f"{config.backend_url}/projects/{project}/git-repos"
    try:
        response = requests.post(url_api, headers=headers, json=payload, cookies=cookies, timeout=120)
        response.raise_for_status()
        result = response.json()
        click.echo(click.style(f"Repository cloned: {result.get('repo', {}).get('name')}", fg="green"))
        click.echo(f"Path: {result.get('repo', {}).get('local_path')}")
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


@git.command("list")
@click.option("--project", required=True, help="Project name")
@click.option("--username", prompt=True, help="Username for authentication")
@click.option("--password", prompt=True, hide_input=True, help="Password for authentication")
def git_list(project, username, password):
    """List git repositories in a project"""
    login_result = login(username, password)
    if not login_result.get("success"):
        click.echo(click.style(f"Login failed: {login_result.get('error')}", fg="red"), err=True)
        return

    cookies = login_result.get("cookies", {})
    headers = get_auth_headers()

    url_api = f"{config.backend_url}/projects/{project}/git-repos"
    try:
        response = requests.get(url_api, headers=headers, cookies=cookies, timeout=10)
        response.raise_for_status()
        result = response.json()
        repos = result.get("repos", [])

        if not repos:
            click.echo("No repositories found")
            return

        click.echo(f"Repositories in {project}:\n")
        for repo in repos:
            click.echo(f"  {repo.get('name')}")
            click.echo(f"    URL: {repo.get('url')}")
            click.echo(f"    Branch: {repo.get('branch')}")
            click.echo(f"    Status: {repo.get('status', 'unknown')}")
            click.echo(f"    Last fetch: {repo.get('last_fetch', 'never')}")
            click.echo()
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


@git.command("fetch")
@click.option("--project", required=True, help="Project name")
@click.option("--repo", required=True, help="Repository name")
@click.option("--reindex/--no-reindex", default=True, help="Reindex after fetch")
@click.option("--username", prompt=True, help="Username for authentication")
@click.option("--password", prompt=True, hide_input=True, help="Password for authentication")
def git_fetch(project, repo, reindex, username, password):
    """Fetch updates from a repository"""
    login_result = login(username, password)
    if not login_result.get("success"):
        click.echo(click.style(f"Login failed: {login_result.get('error')}", fg="red"), err=True)
        return

    cookies = login_result.get("cookies", {})
    headers = get_auth_headers()
    headers["Content-Type"] = "application/json"

    payload = {"reindex": reindex}

    url_api = f"{config.backend_url}/projects/{project}/git-repos/{repo}/fetch"
    try:
        response = requests.post(url_api, headers=headers, json=payload, cookies=cookies, timeout=60)
        response.raise_for_status()
        click.echo(click.style(f"Fetch successful for {repo}", fg="green"))
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


@git.command("review")
@click.option("--project", required=True, help="Project name")
@click.option("--repo", required=True, help="Repository name")
@click.option("--target", default="HEAD", help="Target branch/commit")
@click.option("--base", help="Base branch/commit for diff")
@click.option("--commit", help="Specific commit to review")
@click.option("--include-rag/--no-rag", default=True, help="Include RAG context")
@click.option("--format", "output_format", type=click.Choice(["json", "text"]), default="text", help="Output format")
@click.option("--username", prompt=True, help="Username for authentication")
@click.option("--password", prompt=True, hide_input=True, help="Password for authentication")
def git_review(project, repo, target, base, commit, include_rag, output_format, username, password):
    """Perform code review"""
    login_result = login(username, password)
    if not login_result.get("success"):
        click.echo(click.style(f"Login failed: {login_result.get('error')}", fg="red"), err=True)
        return

    cookies = login_result.get("cookies", {})
    headers = get_auth_headers()
    headers["Content-Type"] = "application/json"

    payload = {
        "project": project,
        "repo": repo,
        "target": target,
        "base": base,
        "include_rag": include_rag
    }
    if commit:
        payload["commit"] = commit

    url_api = f"{config.backend_url}/api/git/review"
    try:
        response = requests.post(url_api, headers=headers, json=payload, cookies=cookies, timeout=120)
        response.raise_for_status()
        result = response.json()

        if output_format == "json":
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"Review ID: {result.get('review_id')}")
            click.echo(f"Summary: {result.get('summary')}")
            click.echo()
            findings = result.get("findings", [])
            if findings:
                click.echo(f"Findings ({len(findings)}):\n")
                for f in findings:
                    severity_color = "red" if f.get("severity") == "critical" else "yellow" if f.get("severity") == "major" else "white"
                    click.echo(f"  [{f.get('severity').upper()}] {f.get('file')}:{f.get('line')}")
                    click.echo(f"    {f.get('message')}")
                    if f.get('suggestion'):
                        click.echo(f"    Suggestion: {f.get('suggestion')}")
                    click.echo()
            else:
                click.echo("No findings")
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


@git.command("remove")
@click.option("--project", required=True, help="Project name")
@click.option("--repo", required=True, help="Repository name")
@click.option("--delete-local/--no-delete-local", default=False, help="Delete local copy")
@click.option("--username", prompt=True, help="Username for authentication")
@click.option("--password", prompt=True, hide_input=True, help="Password for authentication")
def git_remove(project, repo, delete_local, username, password):
    """Remove a git repository"""
    login_result = login(username, password)
    if not login_result.get("success"):
        click.echo(click.style(f"Login failed: {login_result.get('error')}", fg="red"), err=True)
        return

    cookies = login_result.get("cookies", {})
    headers = get_auth_headers()
    headers["Content-Type"] = "application/json"

    payload = {"delete_local": delete_local}

    url_api = f"{config.backend_url}/projects/{project}/git-repos/{repo}"
    try:
        response = requests.delete(url_api, headers=headers, json=payload, cookies=cookies, timeout=30)
        response.raise_for_status()
        click.echo(click.style(f"Repository {repo} removed", fg="green"))
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


cli.add_command(git)


if __name__ == "__main__":
    main()
