# API Endpoints

## Обзор

Synth предоставляет REST API на порту 5000. Все эндпоинты требуют аутентификации через `X-API-Key` заголовок или сессионные куки.

## Аутентификация

### POST /auth/login
Вход пользователя в систему.

```json
// Request
{
    "username": "user",
    "password": "pass"
}

// Response
{
    "message": "Login successful",
    "user": {
        "id": "user_xxx",
        "username": "user",
        "email": "user@example.com",
        "role": "user",
        "team_role": "developer"
    }
}
```

### POST /auth/logout
Выход из системы.

### GET /auth/me
Получить текущего пользователя.

## Пользователи

### GET /api/users
Список всех пользователей (только админ).

### POST /api/users
Создать нового пользователя (только админ).

### GET /api/users/<user_id>
Получить информацию о пользователе.

### PUT /api/users/<user_id>
Обновить данные пользователя.

### DELETE /api/users/<user_id>
Удалить пользователя (только админ).

### GET /api/profile
Получить профиль текущего пользователя.

### PUT /api/profile
Обновить профиль текущего пользователя.

## Сессии

### POST /api/chat
Отправить сообщение в чат.

```json
// Request
{
    "message": "Привет",
    "provider": "openai",
    "model": "gpt-4o",
    "debug": false,
    "source": "web",
    "mcp_servers": ["filesystem"]
}

// Response
{
    "message": "Ответ от AI",
    "session_id": "abc123",
    "model": "gpt-4o",
    "usage": {
        "input_tokens": 100,
        "output_tokens": 200,
        "total_tokens": 300
    },
    "total_tokens": 1500,
    "message_id": "msg_xxx"
}
```

### GET /api/chat/status/<request_id>
Получить статус асинхронного запроса.

### GET /api/chat/message/<message_id>
Получить конкретное сообщение.

### POST /api/note
Добавить заметку в сессию.

## Проекты

### GET /api/projects/<project_name>/schedules
Получить список расписаний проекта.

### POST /api/projects/<project_name>/schedules
Создать новое расписание.

### PUT /api/projects/<project_name>/schedules/<schedule_id>
Обновить расписание.

### DELETE /api/projects/<project_name>/schedules/<schedule_id>
Удалить расписание.

### POST /api/projects/<project_name>/schedules/<schedule_id>/run
Запустить расписание вручную.

## MCP

### GET /mcp/servers
Список настроенных MCP серверов.

### GET /mcp/servers/<server_name>/tools
Получить инструменты MCP сервера.

### GET /session/mcp
Получить MCP сервера текущей сессии.

### PUT /session/mcp
Обновить MCP сервера сессии.

### POST /session/mcp
Добавить MCP сервер в сессию.

### DELETE /session/mcp/<server_name>
Удалить MCP сервер из сессии.

## Системные

### GET /api/health
Проверка здоровья API.

### GET /admin/
Админ-панель (рендерит HTML).
