# AGENTS.md - Instructions for AI Coding Agents

## Project Overview

T6 is an AI agent with web interface and CLI. Backend is Flask (port 5000), UI is Flask + htmx (port 5001), CLI is Click-based.

## Project Structure

```
t6/
├── backend/           # Flask API
│   ├── app/           # routes.py, config.py, session.py, storage.py, context.py, llm/
│   ├── requirements.txt
│   ├── config.yaml    # (gitignored)
│   └── run.py
├── ui/                # Flask + htmx web UI
│   ├── app.py
│   ├── static/, templates/
│   └── requirements.txt
├── cli/               # Click-based CLI
│   └── main.py
├── context/           # Markdown files for system prompt
└── data/              # Session data (gitignored)
```

## Build/Lint/Test Commands

### Setup
```bash
# All components
for dir in backend ui cli; do
  cd $dir && python -m venv venv && source venv/bin/activate && pip install -r requirements.txt && cd ..
done

# Copy config examples and edit with your API keys
cp backend/config.example.yaml backend/config.yaml
cp ui/config.example.yaml ui/config.yaml
cp cli/config.example.yaml cli/config.yaml
```

### Running
```bash
# Backend (port 5000)
cd backend && source venv/bin/activate && python run.py

# UI (port 5001) - separate terminal
cd ui && source venv/bin/activate && python run.py

# CLI
cd cli && source venv/bin/activate
python main.py chat "Hello"
python main.py session list
python main.py health
```

### Testing
```bash
# Run all tests (from project root)
pytest

# Run tests for specific component
cd backend && pytest
cd ui && pytest

# Run single test file
pytest path/to/test_file.py

# Run tests matching pattern
pytest -k test_name

# Run with verbose output
pytest -v

# Run with shorter traceback
pytest --tb=short
```

Tests should be placed in `tests/` directories within each component (e.g., `backend/tests/`, `ui/tests/`).

### Linting & Formatting
```bash
ruff check .           # Lint
ruff check --fix .    # Auto-fix
black .                # Format
mypy .                 # Type check
```

## Code Style

### Imports (order: stdlib, third-party, local)
```python
import os
from pathlib import Path
import requests
from flask import Blueprint, jsonify, request
```

### Formatting
- 4 spaces indentation, 120 char max line length
- Blank lines between logical sections, no trailing whitespace

### Type Hints
```python
def get_session_id() -> str:
    session_id: str | None = request.headers.get("X-Session-Id")
    return session_id or "default"

from typing import Optional
def process(items: list[str], flag: Optional[bool] = None) -> None: ...
```

### Naming Conventions - **Variables/functions**: `snake_case`, **Classes**: `PascalCase`, **Constants**: `UPPER_SNAKE_CASE`, **Private methods**: prefix with `_`

### Error Handling
```python
try:
    response = requests.post(url, json=payload, timeout=60)
    response.raise_for_status()
except requests.RequestException as e:
    return jsonify({"error": f"Backend error: {str(e)}"}), 500
```

### Flask Routes
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
```

### CLI (Click)
```python
import click

@click.group()
def cli(): """T6 CLI""" pass

@cli.command()
@click.argument("message")
def chat(message: str): """Send a message""" ...
```

### HTML/Jinja2
```html
{% extends "base.html" %}
{% block content %}{{ content|safe }}{% endblock %}
```

### JavaScript (chat.html)
- Use ES6+ syntax (async/await, arrow functions, template literals)
- Use `const` by default, `let` when needed, avoid `var`
- Always use strict equality (`===` and `!==`)
- Use meaningful variable names
- Prefer async/await over raw promises
- Use backticks for string interpolation: `` `value: ${x}` ``
- Add event listeners via `addEventListener`, not inline onclick unless necessary

Example:
```javascript
async function loadPanelMessages(panelIndex) {
    const panel = panels[panelIndex];
    if (!panel?.sessionId) return;
    
    try {
        const response = await fetch(`/api/sessions/${panel.sessionId}/messages`);
        const data = await response.json();
        panel.messages = data.messages || [];
    } catch (err) {
        console.error('Failed to load messages:', err);
    }
}
```

### Debug Mode
The UI includes a debug toggle to view raw LLM requests/responses. Debug data is stored in session files and can be cleared via API or UI.

### Configuration
- Store sensitive data in YAML config files (gitignored)
- Use `.gitignore` to exclude `config.yaml`, `venv/`, `data/`

### Environment Variables
- `T6_SESSION_ID` - Session ID for CLI (defaults to "cli-default")
- `T6_BACKEND_URL` - Backend URL override for CLI

## Common Tasks

**Add LLM Provider** - Add to `backend/config.yaml`:
```yaml
llm:
  providers:
    new_provider:
      url: "https://api.example.com/v1/chat/completions"
      api_key: "your-key"
      model: "model-name"
```

**Add API Endpoint** - Add route in `backend/app/routes.py`, use `@require_auth` if needed, return JSON.

**Session Management** - Sessions are stored in `data/` directory. Use `session_manager` from `app/session.py` to manage session history.

## Git Practices

- Commit frequently with clear, concise messages describing the "why" not the "what"
- Never commit secrets, keys, or credentials - use `.gitignore` for sensitive files
- Run lint/typecheck before committing when possible
- Ask before amending or force-pushing