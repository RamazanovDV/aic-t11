# Synth CLI

Командная строка для Synth AI Agent.

## Установка

```bash
cd synth-cli
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Настройка

```bash
cp config.example.yaml config.yaml
# Отредактируйте config.yaml, указав URL бэкенда и API ключ
```

## Использование

```bash
# Отправить сообщение
python main.py chat "Привет, как дела?"

# С провайдером
python main.py chat "Привет" -p ollama

# Сессия
python main.py chat "Привет" -s my-session

# Управление сессиями
python main.py session list
python main.py session reset
python main.py session delete my-session

# Импорт/экспорт
python main.py session export
python main.py session import path/to/session.json

# Сбросить историю
python main.py chat reset

# Проверить здоровье бэкенда
python main.py health

# Показать настройки
python main.py settings show
```

## Переменные окружения

- `T6_SESSION_ID` - ID сессии (по умолчанию: cli-default)
- `T6_BACKEND_URL` - URL бэкенда (по умолчанию: http://localhost:5000)
