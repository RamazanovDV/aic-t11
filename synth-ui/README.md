# Synth UI

Веб-интерфейс для Synth AI Agent.

## Возможности

- Адаптивный интерфейс (htmx + CSS)
- Выбор провайдера и модели
- MCP серверы - подключение внешних инструментов
- Debug режим для просмотра запросов/ответов LLM
- Статистика по токенам с warning/abort индикацией
- Две панели для параллельных сессий
- Настройки оптимизации контекста
- Scheduled tasks UI - управление запланированными задачами
- Управление сессиями

## Установка

```bash
cd synth-ui
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Настройка

```bash
cp config.example.yaml config.yaml
# Отредактируйте config.yaml
```

## Запуск

```bash
source venv/bin/activate
python run.py
```

UI будет доступно на http://localhost:5001

## Админ-панель

Доступна по адресу: http://localhost:5000/admin (через backend)

## Конфигурация

См. `config.example.yaml` для доступных опций.
