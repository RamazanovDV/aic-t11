import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class RequestStatus:
    request_id: str
    status: str
    message_id: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


class RequestTracker:
    _requests: dict[str, RequestStatus] = {}
    _lock = threading.Lock()
    TTL_MINUTES = 10

    @classmethod
    def create_request(cls) -> str:
        request_id = str(uuid.uuid4())
        with cls._lock:
            cls._requests[request_id] = RequestStatus(
                request_id=request_id,
                status="thinking"
            )
        return request_id

    @classmethod
    def complete(cls, request_id: str, message_id: str) -> None:
        with cls._lock:
            if request_id in cls._requests:
                cls._requests[request_id].status = "completed"
                cls._requests[request_id].message_id = message_id
                cls._requests[request_id].updated_at = datetime.now()

    @classmethod
    def error(cls, request_id: str, error_message: str) -> None:
        with cls._lock:
            if request_id in cls._requests:
                cls._requests[request_id].status = "error"
                cls._requests[request_id].error = error_message
                cls._requests[request_id].updated_at = datetime.now()

    @classmethod
    def get_status(cls, request_id: str) -> RequestStatus | None:
        with cls._lock:
            return cls._requests.get(request_id)

    @classmethod
    def cleanup(cls) -> None:
        with cls._lock:
            now = datetime.now()
            cutoff = now - timedelta(minutes=cls.TTL_MINUTES)
            to_remove = [
                rid for rid, req in cls._requests.items()
                if req.updated_at < cutoff
            ]
            for rid in to_remove:
                del cls._requests[rid]
