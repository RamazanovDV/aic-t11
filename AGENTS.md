# AGENTS.md - Instructions for AI Coding Agents

## Project Overview

Synth is a multi-user AI agent with web interface and CLI. Backend is Flask (port 5000), UI is Flask + htmx (port 5001), CLI is Click-based.

## Project Structure

```
synth/
├── synth/              # Flask API
│   ├── app/           # routes.py, config.py, session.py, storage.py, context.py, llm/
│   ├── requirements.txt
│   ├── config.yaml    # (gitignored)
│   └── run.py
├── synth-ui/          # Flask + htmx web UI
│   ├── app.py
│   ├── static/, templates/
│   └── requirements.txt
├── synth-cli/         # Click-based CLI
│   └── main.py
├── context/           # Markdown files for system prompt
└── data/              # Session data (gitignored)
```

## Build/Lint/Test Commands

### Setup
```bash
# All components
for dir in synth synth-ui synth-cli; do
  cd $dir && python -m venv venv && source venv/bin/activate && pip install -r requirements.txt && cd ..
done

# Copy config examples and edit with your API keys
cp synth/config.example.yaml synth/config.yaml
cp synth-ui/config.example.yaml synth-ui/config.yaml
cp synth-cli/config.example.yaml synth-cli/config.yaml
```

### Running
```bash
# Backend (port 5000)
cd synth && source venv/bin/activate && python run.py

# UI (port 5001) - separate terminal
cd synth-ui && source venv/bin/activate && python run.py

# CLI
cd synth-cli && source venv/bin/activate
python main.py chat "Hello"
python main.py session list
python main.py health
```

### Testing
```bash
# Run all tests (from project root)
pytest

# Run tests for specific component
cd synth && pytest
cd synth-ui && pytest

# Run single test file
pytest synth/tests/test_session.py

# Run specific test function
pytest synth/tests/test_session.py::test_get_messages_for_llm

# Run tests matching pattern
pytest -k "test_name"

# Run with verbose output
pytest -v

# Run with shorter traceback
pytest --tb=short
```

Tests should be placed in `tests/` directories within each component (e.g., `synth/tests/`, `synth-ui/tests/`).

### Linting & Formatting
```bash
ruff check .           # Lint
ruff check --fix .     # Auto-fix
black .                # Format
mypy .                 # Type check

# Lint specific file
ruff check synth/app/routes.py
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

### Naming Conventions
- **Variables/functions**: `snake_case`
- **Classes**: `PascalCase`
- **Constants**: `UPPER_SNAKE_CASE`
- **Private methods**: prefix with `_`

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
def cli(): """Synth CLI""" pass

@cli.command()
@click.argument("message")
def chat(message: str): """Send a message""" ...
```

### HTML/Jinja2
```html
{% extends "base.html" %}
{% block content %}{{ content|safe }}{% endblock %}
```

### JavaScript
- Use ES6+ syntax (async/await, arrow functions, template literals)
- Use `const` by default, `let` when needed, avoid `var`
- Always use strict equality (`===` and `!==`)
- Use meaningful variable names
- Prefer async/await over raw promises
- Add event listeners via `addEventListener`, not inline onclick

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

## Context Optimization

Synth supports several context optimization strategies:

1. **none** - No optimization, all messages sent to LLM
2. **summarization** - Compresses old messages into summaries
3. **sliding_window** - Keeps only N recent messages
4. **sticky_notes** - Extracts key facts (name, preferences, goals) and sends them with N recent messages

Configure via API: `POST /api/sessions/{id}/context-settings`

## Session Management

- Sessions stored in `data/sessions/` as JSON files
- Use `session_manager` from `app/session.py` to manage session history
- Session data includes: messages, facts (key-value for sticky_notes), branches, checkpoints

## Debug Mode

The UI includes a debug toggle to view raw LLM requests/responses. Debug data is stored in session files and can be cleared via API or UI.

## Configuration

- Store sensitive data in YAML config files (gitignored)
- Use `.gitignore` to exclude `config.yaml`, `venv/`, `data/`

### Environment Variables
- `T6_SESSION_ID` - Session ID for CLI (defaults to "cli-default")
- `T6_BACKEND_URL` - Backend URL override for CLI

## Common Tasks

**Add LLM Provider** - Add to `synth/config.yaml`:
```yaml
llm:
  providers:
    new_provider:
      url: "https://api.example.com/v1/chat/completions"
      api_key: "your-key"
      model: "model-name"
```

**Add API Endpoint** - Add route in `synth/app/routes.py`, use `@require_auth` if needed, return JSON.

**Add Context File** - Create `.md` file in `data/context/`, enable in admin panel.

## Git Practices

- Commit frequently with clear, concise messages describing the "why" not the "what"
- Never commit secrets, keys, or credentials - use `.gitignore` for sensitive files
- Run lint/typecheck before committing when possible
- Ask before amending or force-pushing
