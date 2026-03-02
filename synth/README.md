# Synth Backend

Flask API сервер для Synth AI Agent.

## Возможности

- REST API для взаимодействия с LLM провайдерами
- Поддержка OpenAI, Anthropic, Ollama и кастомных OpenAI-совместимых провайдеров
- Управление сессиями с историей диалогов
- Контекстные файлы (Markdown)
- Оптимизация контекста: суммаризация, скользящее окно, sticky notes
- Ветки и чекпоинты
- Админ-панель

## Установка

```bash
cd synth
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Настройка

```bash
cp config.example.yaml config.yaml
# Отредактируйте config.yaml, добавив API ключи
```

## Запуск

```bash
source venv/bin/activate
python run.py
```

Сервер запустится на http://localhost:5000

## API Endpoints

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/health` | Проверка работоспособности |
| POST | `/chat` | Отправить сообщение |
| POST | `/chat/stream` | Streaming ответ |
| POST | `/chat/reset` | Сбросить историю |
| GET | `/sessions` | Список сессий |
| GET | `/sessions/<id>` | Получить сессию |
| DELETE | `/sessions/<id>` | Удалить сессию |
| POST | `/sessions/<id>/rename` | Переименовать сессию |
| POST | `/sessions/<id>/copy` | Копировать сессию |
| POST | `/sessions/<id>/clear-debug` | Очистить debug данные |
| GET | `/sessions/<id>/context-settings` | Настройки оптимизации контекста |
| POST | `/sessions/<id>/context-settings` | Сохранить настройки |
| POST | `/sessions/<id>/summarize` | Запустить суммаризацию |
| POST | `/sessions/export` | Экспорт сессий |
| POST | `/sessions/import` | Импорт сессий |

## Аутентификация

Используйте заголовок `X-API-Key` для авторизации.

## Конфигурация

См. `config.example.yaml` для доступных опций.
