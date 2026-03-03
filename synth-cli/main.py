import json
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


if __name__ == "__main__":
    main()
