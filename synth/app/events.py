import json
import threading
from typing import Any


_subscribers: dict[str, list[Any]] = {}
_lock = threading.RLock()


def subscribe(session_id: str, response: Any) -> None:
    """Добавить подписчика на события сессии."""
    with _lock:
        if session_id not in _subscribers:
            _subscribers[session_id] = []
        if response not in _subscribers[session_id]:
            _subscribers[session_id].append(response)


def unsubscribe(session_id: str, response: Any) -> None:
    """Удалить подписчика."""
    with _lock:
        if session_id in _subscribers:
            if response in _subscribers[session_id]:
                _subscribers[session_id].remove(response)
            if not _subscribers[session_id]:
                del _subscribers[session_id]


def publish(session_id: str, event_type: str, data: dict | None = None) -> None:
    """Отправить событие всем подписчикам сессии."""
    if data is None:
        data = {}
    
    payload = {"type": event_type, **data}
    message = f"data: {json.dumps(payload)}\n\n"
    
    with _lock:
        if session_id not in _subscribers:
            return
        
        dead_subscribers = []
        for response in _subscribers[session_id]:
            try:
                response.write(message)
                response.flush()
            except Exception:
                dead_subscribers.append(response)
        
        for dead in dead_subscribers:
            _subscribers[session_id].remove(dead)
        
        if session_id in _subscribers and not _subscribers[session_id]:
            del _subscribers[session_id]


def get_subscriber_count(session_id: str) -> int:
    """Получить количество подписчиков сессии."""
    with _lock:
        return len(_subscribers.get(session_id, []))
