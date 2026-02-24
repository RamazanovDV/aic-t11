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
def cli():
    """T6 AI Assistant CLI"""
    pass


@cli.command()
@click.argument("message")
@click.option("-p", "--provider", default=None, help="LLM provider (openai, anthropic, ollama, itphx)")
@click.option("-s", "--session", default=None, help="Session ID")
def chat(message: str, provider: str | None, session: str | None):
    """Send a message to the AI"""
    if session:
        os.environ["T6_SESSION_ID"] = session

    url = f"{config.backend_url}/chat"
    headers = get_headers()
    
    payload = {"message": message}
    if provider:
        payload["provider"] = provider

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        
        click.echo(data.get("message", ""))
        
        if session:
            click.echo(click.style(f"\n[Session: {data.get('session_id', 'default')}]", fg="blue"))
    except requests.RequestException as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)


@cli.group()
def session():
    """Manage sessions"""
    pass


@session.command("list")
def session_list():
    """List sessions (placeholder - backend stores in memory)"""
    click.echo("Sessions are stored in memory. Use --session flag to switch.")


@session.command("show")
@click.argument("session_id", required=False)
def session_show(session_id: str | None):
    """Show session info"""
    sid = session_id or get_session_id()
    click.echo(f"Current session: {sid}")


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


@cli.group()
def settings():
    """Manage settings"""
    pass


@settings.command("show")
def settings_show():
    """Show current settings"""
    click.echo(f"Backend URL: {config.backend_url}")
    click.echo(f"API Key: {'*' * 8}{config.backend_api_key[-4:] if config.backend_api_key else 'not set'}")


@settings.command("set")
@click.argument("key")
@click.argument("value")
def settings_set(key: str, value: str):
    """Set a setting (writes to ui/config.yaml)"""
    config_path = Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        config_path = Path(__file__).parent.parent / "ui" / "config.yaml"
    
    if not config_path.exists():
        click.echo(click.style("Config file not found", fg="red"), err=True)
        return

    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)

    if key == "provider":
        cfg.setdefault("llm", {})["default_provider"] = value
    elif key in ("backend_url", "url"):
        cfg.setdefault("backend", {})["url"] = value
    elif key == "api_key":
        cfg.setdefault("backend", {})["api_key"] = value
    else:
        click.echo(click.style(f"Unknown setting: {key}", fg="red"), err=True)
        return

    with open(config_path, "w") as f:
        yaml.dump(cfg, f)

    click.echo(click.style(f"Setting '{key}' updated to '{value}'", fg="green"))


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


if __name__ == "__main__":
    cli()
