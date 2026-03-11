import json
import re
from typing import Any


VALID_STATES = {"planning", "execution", "validation", "done"}
REQUIRED_STATUS_KEYS = {"task_name", "state", "progress", "approved_plan", "already_done", "currently_doing"}


def validate_status_block(content: str) -> tuple[dict[str, Any] | None, str]:
    """Извлечь и валидировать JSON-блок статуса из ответа модели.
    
    Returns:
        tuple[parsed_status | None, cleaned_content]
    """
    cleaned_content = content
    
    json_pattern = r"```json\s*([\s\S]*?)\s*```"
    match = re.search(json_pattern, content)
    if match:
        status_json = match.group(1).strip()
        cleaned_content = content[:match.start()] + content[match.end():]
        return _parse_and_validate(status_json), cleaned_content.strip()
    
    json_pattern_short = r"\{\s*[\"']?status[\"']?\s*:"
    for line in content.split("\n"):
        stripped = line.strip()
        if re.search(json_pattern_short, stripped):
            if "{" in stripped and "}" in stripped:
                pass
    
    def find_matching_brace(s: str, start: int) -> int:
        count = 0
        i = start
        while i < len(s):
            if s[i] == '{':
                count += 1
            elif s[i] == '}':
                count -= 1
                if count == 0:
                    return i
            i += 1
        return -1
    
    for line in content.split("\n"):
        stripped = line.strip()
        if "{" in stripped:
            start = 0
            while start < len(stripped):
                start = stripped.find("{", start)
                if start == -1:
                    break
                end = find_matching_brace(stripped, start)
                if end != -1:
                    json_str = stripped[start:end+1]
                    try:
                        parsed = json.loads(json_str)
                        if isinstance(parsed, dict):
                            if "status" in parsed and isinstance(parsed["status"], dict):
                                cleaned_content = content.replace(json_str, "").strip()
                                return _parse_and_validate(json_str), cleaned_content
                            if any(k in parsed for k in ["task_name", "state", "progress", "project", "updated_project_info", "current_task_info"]):
                                cleaned_content = content.replace(json_str, "").strip()
                                return _parse_and_validate(json_str), cleaned_content
                    except json.JSONDecodeError:
                        pass
                start += 1
    
    return None, cleaned_content


def _parse_and_validate(status_json: str) -> dict[str, Any] | None:
    """Парсить и валидировать JSON статуса."""
    try:
        status = json.loads(status_json)
        if not isinstance(status, dict):
            return None
        
        if "status" in status and isinstance(status["status"], dict):
            status = status["status"]
        
        if not any(k in status for k in ["task_name", "state", "progress", "project", "updated_project_info", "current_task_info", "approved_plan", "already_done", "currently_doing"]):
            return None
        
        validated = {}
        
        if "task_name" in status:
            validated["task_name"] = str(status["task_name"]) if status["task_name"] else "conversation"
        else:
            validated["task_name"] = "conversation"
        
        if "state" in status:
            state = status["state"]
            validated["_proposed_state"] = state
            if state in VALID_STATES:
                validated["state"] = state
            elif state is None:
                validated["state"] = None
            else:
                validated["state"] = None
        else:
            validated["state"] = None
            validated["_proposed_state"] = None
        
        validated["progress"] = status.get("progress")
        validated["project"] = status.get("project")
        validated["updated_project_info"] = status.get("updated_project_info")
        validated["current_task_info"] = status.get("current_task_info")
        validated["approved_plan"] = status.get("approved_plan")
        validated["already_done"] = status.get("already_done")
        validated["currently_doing"] = status.get("currently_doing")
        validated["user_info"] = status.get("user_info")
        validated["active_subtasks"] = status.get("active_subtasks", [])
        validated["subtasks"] = status.get("subtasks", [])
        validated["invariants"] = status.get("invariants")
        validated["next_state"] = status.get("next_state")
        validated["schedule"] = status.get("schedule")
        
        return validated
        
    except (json.JSONDecodeError, TypeError):
        return None


def is_valid_status(status: dict[str, Any] | None) -> bool:
    """Проверить, является ли статус валидным."""
    if not status:
        return False
    
    if not isinstance(status, dict):
        return False
    
    has_any_field = any(
        k in status and status[k] is not None
        for k in ["task_name", "state", "progress", "project", "updated_project_info", "current_task_info", "approved_plan", "already_doing", "currently_doing", "invariants"]
    )
    
    return has_any_field
