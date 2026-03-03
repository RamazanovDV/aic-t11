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

### Chat
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/health` | Проверка работоспособности |
| POST | `/api/chat` | Отправить сообщение |
| POST | `/api/chat/stream` | Streaming ответ |
| POST | `/api/chat/reset` | Сбросить историю |

### Sessions
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/sessions` | Список сессий |
| POST | `/api/sessions` | Создать сессию |
| GET | `/api/sessions/<id>` | Получить сессию |
| DELETE | `/api/sessions/<id>` | Удалить сессию |
| POST | `/api/sessions/<id>/rename` | Переименовать сессию |
| POST | `/api/sessions/<id>/copy` | Копировать сессию |
| POST | `/api/sessions/<id>/clear-debug` | Очистить debug данные |
| POST | `/api/sessions/export` | Экспорт сессий |
| POST | `/api/sessions/import` | Импорт сессий |

### Messages
| Метод | Путь | Описание |
|-------|------|----------|
| DELETE | `/api/sessions/<id>/messages/<index>` | Удалить сообщение |
| POST | `/api/sessions/<id>/messages/<index>/toggle` | Включить/выключить сообщение |

### Context
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/sessions/<id>/context-settings` | Настройки оптимизации контекста |
| POST | `/api/sessions/<id>/context-settings` | Сохранить настройки |
| POST | `/api/sessions/<id>/summarize` | Запустить суммаризацию |

### Checkpoints
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/sessions/<id>/checkpoints` | Список чекпоинтов |
| POST | `/api/sessions/<id>/checkpoints` | Создать чекпоинт |
| POST | `/api/sessions/<id>/checkpoints/<cp_id>/rename` | Переименовать чекпоинт |
| DELETE | `/api/sessions/<id>/checkpoints/<cp_id>` | Удалить чекпоинт |
| POST | `/api/sessions/<id>/checkpoints/<cp_id>/branch` | Создать ветку из чекпоинта |

### Branches
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/sessions/<id>/branches` | Список веток |
| POST | `/api/sessions/<id>/branches/<branch_id>/switch` | Переключиться на ветку |
| POST | `/api/sessions/<id>/branches/<branch_id>/rename` | Переименовать ветку |
| DELETE | `/api/sessions/<id>/branches/<branch_id>` | Удалить ветку |
| POST | `/api/sessions/<id>/branches/<branch_id>/reset` | Сбросить ветку |
| GET | `/api/sessions/<id>/tree` | Дерево сессии |

### Admin
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/admin/config` | Получить конфиг |
| POST | `/admin/config` | Обновить конфиг |
| POST | `/admin/config/validate` | Валидировать конфиг |
| GET | `/admin/providers/<name>/models` | Модели провайдера |
| POST | `/admin/models/fetch` | Получить модели |
| POST | `/admin/providers/fetch-models` | Получить все модели |
| GET | `/admin/context` | Список контекстных файлов |
| POST | `/admin/context` | Добавить контекстный файл |
| POST | `/admin/context/enabled` | Включить/выключить контекст |
| GET/POST/DELETE | `/admin/context/<filename>` | Управление файлом |
| GET | `/admin/models` | Список моделей |
| GET | `/admin/models/available` | Доступные модели |
| POST | `/admin/models` | Добавить модель |
| DELETE | `/admin/models/<name>` | Удалить модель |

## Аутентификация

Используйте заголовок `X-API-Key` для авторизации.

## Конфигурация

См. `config.example.yaml` для доступных опций.
