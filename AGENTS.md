# AGENTS.md - Инструкции для агентов

## О проекте

T6 - AI-агент с веб-интерфейсом и CLI. Backend на Flask, UI на Flask + htmx, CLI на Click.

## Быстрый старт для агента

```bash
cd /home/eof/dev/aic/t6
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Запуск
python run.py        # Backend :5000
python run_ui.py     # UI :5001
```

## Структура кода

### Backend (`backend/app/`)

- `routes.py` - API эндпоинты (`/health`, `/chat`, `/chat/reset`)
- `config.py` - Загрузка YAML конфига
- `session.py` - Управление сессиями (в памяти)
- `context.py` - Загрузка markdown файлов в system prompt
- `llm/` - Провайдеры LLM
  - `base.py` - Базовый класс, фабрика
  - `providers.py` - OpenAI, Anthropic, Ollama, GenericOpenAI

### Web UI (`ui/`)

- `app.py` - Flask приложение, проксирует запросы к backend
- `templates/` - HTML шаблоны (base, chat, settings)
- `static/style.css` - Адаптивные стили (dark theme)

### CLI (`cli/`)

- `main.py` - Click-based CLI команды

## Конфигурация

- `config.yaml` - Backend (порт 5000)
- `ui/config.yaml` - UI (порт 5001)
- `cli/config.yaml` - CLI
- `context/` - Markdown файлы для system prompt

## Тестирование

```bash
# Backend тест
python -c "from backend.app import create_app; app = create_app()"

# UI тест
python -c "from ui.app import create_app; app = create_app()"

# CLI тест
python cli/main.py --help
```

## Частые задачи

### Добавить нового провайдера

1. Добавить в `config.yaml`:
```yaml
llm:
  providers:
    new_provider:
      url: "https://api.example.com"
      api_key: "key"
      model: "model"
```

2. Провайдер автоматически подхватится как GenericOpenAIProvider (если OpenAI-совместимый API).

### Добавить новую страницу UI

1. Создать шаблон в `ui/templates/`
2. Добавить route в `ui/app.py`

### Изменить system prompt

Редактировать `backend/app/context.py` - функция `get_system_prompt()`.

## Важные файлы

- `.gitignore` - Исключает `config.yaml`, `ui/config.yaml`, `cli/config.yaml`, `venv/`
- `requirements.txt` - Зависимости
- `README.md` - Документация
