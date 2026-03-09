# AGENTS.md - Instructions for AI Coding Agents

## Project Overview
Synth is a multi-user AI agent with web interface and CLI. Backend is Flask (port 5000), UI is Flask + htmx (port 5001), CLI is Click-based.

## Project Structure
```
synth/      # Flask API (port 5000): routes.py, session.py, storage.py, auth.py, config.py, models.py, tsm.py
synth-ui/   # Flask + htmx web UI (port 5001)
synth-cli/  # Click-based CLI
context/    # Markdown files for system prompt
data/       # Session data (gitignored)
```

## Build/Lint/Test Commands
### Setup
```bash
for dir in synth synth-ui synth-cli; do cd $dir && python -m venv venv && source venv/bin/activate && pip install -r requirements.txt && cd ..; done
cp synth/config.example.yaml synth/config.yaml && cp synth-ui/config.example.yaml synth-ui/config.yaml && cp synth-cli/config.example.yaml synth-cli/config.yaml
```

### Running
```bash
cd synth && source venv/bin/activate && python run.py      # port 5000
cd synth-ui && source venv/bin/activate && python run.py   # port 5001
cd synth-cli && source venv/bin/activate
python main.py chat "Hello"           # Send message
python main.py repl                   # Interactive mode
python main.py session list           # List sessions
python main.py session new <name>     # Create session
python main.py session reset -s <id>  # Reset session
python main.py health                 # Check backend
```

### Testing
```bash
pytest                                    # all tests
cd synth && pytest                        # specific component
pytest synth/tests/test_session.py       # single file
pytest synth/tests/test_session.py::test_func  # single test
pytest -k "pattern"                       # by pattern
pytest -v --tb=short                      # verbose
```

### Linting
```bash
ruff check .           # lint
ruff check --fix .     # auto-fix
```

## Code Style
### Imports (order: stdlib, third-party, local)
```python
import json
import requests
from flask import Blueprint, jsonify, request
from app.config import config
from app.session import session_manager
```

### Formatting
- 4 spaces indentation, 120 char max line length
- Blank lines between logical sections, no trailing whitespace

### Type Hints
```python
def get_session_id() -> str:
    session_id: str | None = request.headers.get("X-Session-Id")
    return session_id or "default"
```

### Naming Conventions
- Variables/functions: `snake_case`, Classes: `PascalCase`, Constants: `UPPER_SNAKE_CASE`
- Private methods: prefix with `_`, Blueprint names: `Blueprint("api", __name__)`

### Error Handling
```python
try:
    response = requests.post(url, json=payload, timeout=60)
    response.raise_for_status()
except requests.RequestException as e:
    return jsonify({"error": f"Backend error: {str(e)}"}), 500
```

## Flask Routes Pattern
```python
api_bp = Blueprint("api", __name__)

def require_auth(f):
    def wrapper(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")
        if not api_key or api_key != config.api_key:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@api_bp.route("/chat", methods=["POST"])
@require_auth
def chat():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing 'message' field"}), 400
    return jsonify({"message": response})

def get_session_id() -> str:
    session_id = request.headers.get("X-Session-Id")
    return session_id or request.cookies.get("session_id", "default")
```

## CLI (Click) Pattern
```python
import click

@click.group()
def cli(): """T6 AI Assistant CLI""" pass

@cli.command()
@click.argument("message")
@click.option("-p", "--provider", default=None)
@click.option("-s", "--session", default=None)
def chat(message: str, provider: str | None, session: str | None):
    """Send a message to the AI""" ...

@cli.group()
def session():
    """Manage sessions""" pass
```

## Session Management
```python
from app.session import session_manager
session_id = get_session_id()
session = session_manager.get_session(session_id)
session.add_user_message(content, source="web")
session.add_assistant_message(content, usage, model=model)
session_manager.save_session(session_id)
```

## Storage/Models
```python
from app.storage import storage
from app.models import User
user = storage.load_user(user_id)
storage.save_user(user)
users = storage.list_users()
```

## HTML/Jinja2
```html
{% extends "base.html" %}
{% block content %}{{ content|safe }}{% endblock %}
```

## JavaScript (ES6+)
Use `const` by default, `let` when needed. Strict equality (`===` and `!==`). Event listeners via `addEventListener`, not inline onclick.

## Configuration
Store sensitive data in YAML config files (gitignored). Use `.gitignore` to exclude `config.yaml`, `venv/`, `data/`.

### Environment Variables
- `T6_SESSION_ID` - Session ID for CLI (default: "cli-default")
- `T6_BACKEND_URL` - Backend URL override

### config.yaml Structure
```yaml
backend:
  url: "http://localhost:5000"
  api_key: "your-key"
auth:
  api_key: "your-auth-key"
llm:
  default_provider: "openai"
  providers:
    openai:
      url: "https://api.openai.com/v1/chat/completions"
      api_key: "sk-"
      model: "gpt-4"
```

## Common Tasks
**Add LLM Provider** - Edit `synth/config.yaml` with provider config.
**Add API Endpoint** - Add route in `synth/app/routes.py`, use `@require_auth`.

## Git Practices
- Commit with clear messages describing the "why"
- Never commit secrets/credentials
- Run lint before committing

## Important Notes
### Debug Usage
The `debug` field in messages is intended ONLY for user-facing information in Debug mode. It must NEVER be used in any internal mechanisms, UI logic, or backend processing. Use dedicated fields (like `status`) for such purposes.
