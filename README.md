# T6 AI Agent

AI-агент с веб-интерфейсом и CLI для взаимодействия с LLM провайдерами.

## Возможности

- **Backend API** - Flask-сервер для обработки запросов к LLM
- **Web UI** - Адаптивный интерфейс (htmx + CSS)
- **CLI** - Командная строка для управления
- **Множественные провайдеры** - OpenAI, Anthropic, Ollama, кастомные OpenAI-совместимые
- **Контекст** - Markdown-файлы подмешиваются в system prompt
- **Сессии** - История хранится в памяти

## Быстрый старт

### 1. Установка зависимостей

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate     # Windows

pip install -r requirements.txt
```

### 2. Настройка

Скопируйте примеры конфигов и заполните свои API ключи:

```bash
cp config.example.yaml config.yaml
cp ui/config.example.yaml ui/config.yaml
cp cli/config.example.yaml cli/config.yaml
```

### 3. Запуск

```bash
# Terminal 1 - Backend (порт 5000)
python run.py

# Terminal 2 - Web UI (порт 5001)
python run_ui.py
```

### 4. Использование

- **Web UI**: http://localhost:5001
- **CLI**: см. раздел ниже

## Конфигурация

### Backend (`config.yaml`)

```yaml
app:
  host: "0.0.0.0"
  port: 5000

auth:
  api_key: "your-secret-api-key"

llm:
  default_provider: "openai"

  providers:
    openai:
      url: "https://api.openai.com/v1/chat/completions"
      api_key: "sk-..."
      model: "gpt-4o-mini"

    # Добавьте других провайдеров...
    # Кастомный OpenAI-совместимый провайдер:
    custom:
      url: "https://your-api.com/v1/chat/completions"
      api_key: "key"
      model: "model-name"

context:
  dir: "context"  # Markdown файлы для контекста
```

### Контекстные файлы

Создайте Markdown-файлы в директории `context/`. Они будут автоматически загружены в system prompt.

## CLI

```bash
# Отправить сообщение
python cli/main.py chat "Привет, как дела?"

# С провайдером
python cli/main.py chat "Привет" -p ollama

# Сессия
python cli/main.py chat "Привет" -s my-session

# Сбросить историю
python cli/main.py session reset

# Проверить здоровье бэкенда
python cli/main.py health

# Показать настройки
python cli/main.py settings show
```

## API

### Эндпоинты

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/health` | Проверка работоспособности |
| POST | `/chat` | Отправить сообщение |
| POST | `/chat/reset` | Сбросить историю |

### Заголовки

- `X-API-Key` - API ключ для аутентификации
- `X-Session-Id` - Идентификатор сессии

### Пример запроса

```bash
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-api-key" \
  -H "X-Session-Id: my-session" \
  -d '{"message": "Привет", "provider": "openai"}'
```

## Структура проекта

```
t6/
├── backend/           # Flask API сервер
│   └── app/
│       ├── routes.py  # API эндпоинты
│       ├── config.py  # Загрузка конфига
│       ├── context.py # Загрузка markdown
│       ├── session.py # Управление сессиями
│       └── llm/       # Провайдеры
├── ui/                # Web UI
│   ├── app.py
│   ├── static/
│   └── templates/
├── cli/               # CLI
│   └── main.py
├── context/           # Markdown файлы
├── config.example.yaml
└── run.py
```

## Требования

- Python 3.13+
- Flask 3.1+
- PyYAML 6.0+
- Requests 2.32+
- Click 8.1+

## Лицензия

MIT
