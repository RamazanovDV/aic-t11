# Руководство по Embeddings

Модуль семантического поиска и RAG (Retrieval-Augmented Generation) для Synth AI Agent.

## Возможности

- **Семантический поиск** - поиск по смыслу, а не по ключевым словам
- **RAG в чате** - добавление релевантного контекста к LLM-ответам
- **Несколько стратегий чанкинга** - фиксированный размер и структурный
- **Версионирование** - один name = новая версия
- **Оценка качества** - thumbs up/down для будущего анализа

## Быстрый старт

### Создание индекса

```bash
# Через CLI
python -m main.py embeddings create \
    --name "My Knowledge" \
    --source /path/to/docs \
    --strategy fixed \
    --chunk-size 50 \
    --overlap 5
```

```bash
# Через API
curl -X POST http://localhost:5000/api/embeddings \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-secret-api-key" \
    -d '{
        "name": "My Knowledge",
        "description": "База знаний компании",
        "source_dir": "/path/to/docs",
        "chunking_strategy": "fixed",
        "chunking_params": {"chunk_size": 50, "overlap": 5}
    }'
```

### Поиск

```bash
# Через CLI
python -m main.py embeddings search "вопрос" --name "My Knowledge" --top-k 5
```

```bash
# Через API
curl -X POST http://localhost:5000/api/embeddings/search \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-secret-api-key" \
    -d '{
        "query": "вопрос",
        "index_name": "My Knowledge",
        "top_k": 5
    }'
```

### Использование в чате (RAG)

```bash
curl -X POST http://localhost:5000/api/chat \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-secret-api-key" \
    -d '{
        "message": "回答 вопрос",
        "use_rag": true,
        "rag_index_name": "My Knowledge",
        "rag_top_k": 3
    }'
```

## Стратегии чанкинга

### Fixed (фиксированный размер)

Разбивает текст на чанки одинакового размера с перекрытием.

**Параметры:**

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `chunk_size` | int | 512 | Размер чанка в токенах |
| `overlap` | int | 50 | Перекрытие между чанками в токенах |

**Рекомендации:**
- Малые размеры (15-50 токенов) - быстрее, точнее, но больше чанков
- Большие размеры (100+) - могут вызывать ошибки Ollama

### Structure (структурный)

Разбивает текст по заголовкам Markdown (#, ##, ###).

**Параметры:**

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `min_chunk_size` | int | 100 | Минимальный размер чанка |
| `max_chunk_size` | int | 1000 | Максимальный размер чанка |
| `preserve_headers` | bool | true | Сохранять заголовки в чанках |

**Рекомендации:**
- max_chunk_size не должен превышать ~350 слов из-за ограничений Ollama
- Сохраняет контекст разделов документа

## Провайдеры

### Ollama (рекомендуется)

Модель: `nomic-embed-text-v2-moe:latest`

**Ограничения:**
- Нестабильна с текстами > ~1500 символов
- При превышении возвращает 500 ошибку

**Рекомендуемые настройки:**
- chunk_size ≤ 50 для fixed
- max_chunk_size ≤ 150 для structure

### OpenAI

Модели: `text-embedding-3-small`, `text-embedding-ada-002`

```json
{
    "provider": "openai",
    "model": "text-embedding-3-small"
}
```

## CLI команды

```bash
# Создать индекс
python main.py embeddings create --name "Name" --source ./docs --strategy fixed --chunk-size 50

# Список индексов
python main.py embeddings list

# Информация об индексе
python main.py embeddings info <index_id>

# Поиск
python main.py embeddings search "query" --name "Name" --top-k 5

# Удалить индекс
python main.py embeddings delete <index_id>

# Оценить
python main.py embeddings rate <index_id> --thumbs-up
python main.py embeddings rate <index_id> --thumbs-down
```

## API Endpoints

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/embeddings` | Список всех индексов |
| POST | `/api/embeddings` | Создать индекс |
| GET | `/api/embeddings/<id>` | Информация об индексе |
| DELETE | `/api/embeddings/<id>` | Удалить индекс |
| POST | `/api/embeddings/search` | Семантический поиск |
| POST | `/api/embeddings/<id>/rate` | Оценить (thumbs_up/thumbs_down) |
| PATCH | `/api/embeddings/<id>` | Обновить метаданные |

### Создание индекса

```json
POST /api/embeddings
{
    "name": "Название",
    "description": "Описание",
    "source_dir": "/path/to/markdown/files",
    "provider": "ollama",
    "model": "nomic-embed-text-v2-moe:latest",
    "chunking_strategy": "fixed",
    "chunking_params": {
        "chunk_size": 50,
        "overlap": 5
    }
}
```

### Поиск

```json
POST /api/embeddings/search
{
    "query": "ваш вопрос",
    "index_name": "Название",     // или index_id
    "top_k": 5
}
```

### Оценка

```json
POST /api/embeddings/<id>/rate
{
    "rating": "thumbs_up"   // или "thumbs_down"
}
```

## Структура хранения

```
data/embeddings/
├── index.json           # Список всех индексов
└── {index_id}/
    ├── config.json      # Параметры индекса
    ├── metadata.json    # Чанки с метаданными
    └── index.faiss      # FAISS индекс
```

## Метаданные чанка

Каждый чанк содержит:

| Поле | Описание |
|------|----------|
| `id` | UUID чанка |
| `content` | Текстовое содержимое |
| `source` | Путь к исходному файлу |
| `title` | Название файла |
| `section` | Заголовок раздела (для structure) |
| `chunk_index` | Номер чанка в документе |
| `total_chunks` | Всего чанков в документе |

## Версионирование

При создании индекса с существующим именем создаётся новая версия:

```json
{
    "name": "My Knowledge",
    "version": 2   // автоматически увеличивается
}
```

Поиск всегда использует последнюю версию.

## Известные проблемы

1. **Ollama 500 errors** - при слишком больших чанках
   - Решение: используйте меньший chunk_size

2. **StructureChunker** - работает хуже на файлах без заголовков
   - Решение: используйте fixed стратегию для таких файлов

## Примеры индексов

| Индекс | Стратегия | Параметры | Чанков |
|--------|-----------|-----------|--------|
| AI-Challenge-Fixed-15 | fixed | size=15, overlap=3 | 530 |
| AI-Challenge-Fixed-25 | fixed | size=25, overlap=5 | 322 |
| AI-Challenge-Fixed-50 | fixed | size=50, overlap=5 | 152 |
| AI-Challenge-Structure-100 | structure | max=100 | 38 |
| AI-Challenge-Structure-150 | structure | max=150 | 37 |

## Админ-панель

В разделе "Эмбединги" админ-панели (http://localhost:5001/admin) можно:
- Просмотреть все индексы
- Удалить индексы
- Видеть статистику (количество чанков, файлов, оценки)
