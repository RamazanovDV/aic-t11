# AGENTS.md - Instructions for AI Coding Agents

## Project Overview

T6 is an AI agent with web interface and CLI. Backend is Flask, UI is Flask + htmx, CLI is Click-based.

## Project Structure

```
t6/
├── backend/app/         # Flask API (port 5000)
│   ├── routes.py        # API endpoints
│   ├── config.py        # YAML config loader
│   ├── session.py      # Session management
│   ├── storage.py      # File-based persistence
│   ├── context.py      # Markdown context loader
│   └── llm/            # LLM providers
├── ui/                 # Web UI (Flask + htmx, port 5001)
├── cli/                # Click-based CLI
├── context/            # Markdown files for system prompt
├── config.yaml         # Backend config
├── run.py              # Backend entry point
└── run_ui.py           # UI entry point
```

## Build/Lint/Test Commands

### Setup
```bash
cd /home/eof/dev/aic/t6
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install pytest ruff black mypy  # dev dependencies
```

### Running the Application
```bash
python run.py              # Backend (port 5000)
python run_ui.py           # UI (port 5001)
python cli/main.py         # CLI interactive
python cli/main.py chat "Hello"
python cli/main.py session list
python cli/main.py health
```

### Testing
```bash
pytest                                  # Run all tests
pytest tests/test_routes.py -v          # Single test file
pytest tests/test_routes.py::test_health # Single test

# Quick app verification
python -c "from backend.app import create_app; create_app(); print('OK')"
python -c "from ui.app import create_app; create_app(); print('OK')"
python cli/main.py --help
```

### Linting
```bash
ruff check .           # Lint
ruff check --fix .     # Auto-fix
black .                # Format
mypy .                 # Type check
```

## Code Style Guidelines

### General Principles
- Write clean, readable, Pythonic code
- Keep functions small and focused (single responsibility)
- Use meaningful variable and function names

### Imports (order: stdlib, third-party, local)
```python
import os
from pathlib import Path
import requests
from flask import Blueprint, jsonify, request
from backend.app.config import config
```

### Formatting
- 4 spaces indentation, 120 char max line length
- Blank lines between logical sections, no trailing whitespace

### Type Hints
```python
def get_session_id() -> str:
    session_id: str | None = request.headers.get("X-Session-Id")
    return session_id or "default"

from typing import Optional, Callable
def process(callback: Callable[[str], int]) -> None: ...
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
    return jsonify({"message": response, "session_id": session_id})
```

### CLI (Click)
```python
import click

@click.group()
def cli(): """T6 AI Assistant CLI""" pass

@cli.command()
@click.argument("message")
@click.option("-p", "--provider", default=None)
def chat(message: str, provider: str | None): """Send a message""" ...
```

### HTML/Jinja2
```html
{% extends "base.html" %}
{% block content %}{{ content|safe }}{% endblock %}
```

### Configuration
- Store sensitive data in YAML config files
- Config files excluded from git (see .gitignore)

## Common Tasks

### Add LLM Provider
Add to `config.yaml`:
```yaml
llm:
  providers:
    new_provider:
      url: "https://api.example.com/v1/chat/completions"
      api_key: "your-key"
      model: "model-name"
```

### Add API Endpoint
1. Add route in `backend/app/routes.py`
2. Use `@require_auth` if needed
3. Return JSON: `return jsonify({"data": "value"})`

## Important Files
- `.gitignore` - Excludes config.yaml, venv/
- `requirements.txt` - Python dependencies
