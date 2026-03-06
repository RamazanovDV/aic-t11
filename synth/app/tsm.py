from typing import Optional, Any
from app.config import config


VALID_STATES = {"planning", "execution", "validation", "done"}

STATE_TRANSITIONS = {
    "planning": ["execution"],
    "execution": ["validation", "planning"],
    "validation": ["done", "execution"],
    "done": [],
}

STATE_PROMPTS = {
    "planning": "TSM_PLANNING.md",
    "execution": "TSM_EXECUTION.md",
    "validation": "TSM_VALIDATION.md",
    "done": "TSM_DONE.md",
}

TSM_MODES = ["simple", "orchestrator", "deterministic"]

TSM_MODE_NAMES = {
    "simple": "Simple Prompt",
    "orchestrator": "Orchestrator",
    "deterministic": "Deterministic",
}

TSM_MODE_DESCRIPTIONS = {
    "simple": "Базовый системный промпт с инструкцией по статусу задачи. Простой но слабый вариант.",
    "orchestrator": "Отдельный system prompt-оркестратор. Следит и запускает подзадачи с собственными промтами.",
    "deterministic": "Детерминированный переход. Жёсткая проверка состояний и чёткое определение артефактов каждого этапа.",
}


def get_tsm_mode(session) -> str:
    """Получить текущий режим TSM из настроек сессии."""
    return session.session_settings.get("tsm_mode", "simple")


def set_tsm_mode(session, mode: str) -> None:
    """Установить режим TSM для сессии."""
    if mode not in TSM_MODES:
        raise ValueError(f"Invalid TSM mode: {mode}. Must be one of: {TSM_MODES}")
    session.session_settings["tsm_mode"] = mode


def get_tsm_prompt(session) -> str:
    """Получить промт TSM в зависимости от режима."""
    mode = get_tsm_mode(session)
    
    if mode == "simple":
        return _get_simple_prompt()
    elif mode == "orchestrator":
        return _get_orchestrator_prompt()
    elif mode == "deterministic":
        return _get_deterministic_prompt(session)
    
    return _get_simple_prompt()


def _get_simple_prompt() -> str:
    """Получить простой промт - улучшенная версия STATUS.md."""
    return config.get_context_file("STATUS_SIMPLE.md") or ""


def _get_orchestrator_prompt() -> str:
    """Получить промт оркестратора."""
    return config.get_context_file("STATUS_ORCHESTRATOR.md") or ""


def _get_deterministic_prompt(session) -> str:
    """Получить детерминированный промт для текущего состояния."""
    current_state = session.status.get("state")
    task_name = session.status.get("task_name", "разговор на свободную тему")
    
    if task_name == "разговор на свободную тему":
        return config.get_context_file("TSM_PLANNING.md") or ""
    
    if not current_state:
        current_state = "planning"
    
    prompt_file = STATE_PROMPTS.get(current_state)
    if prompt_file:
        prompt = config.get_context_file(prompt_file) or ""
    else:
        prompt = config.get_context_file("TSM_PLANNING.md") or ""
    
    allowed_transitions = STATE_TRANSITIONS.get(current_state, [])
    allowed_str = ", ".join(allowed_transitions) if allowed_transitions else "нет"
    
    context_info = f"""

[КОНТЕКСТ]
Текущее состояние: {current_state}
Допустимые переходы: {allowed_str}
"""
    
    return prompt + context_info


def validate_state_transition(current_state: Optional[str], new_state: Optional[str], task_name: str = "разговор на свободную тему") -> tuple[bool, Optional[str]]:
    """Валидировать переход состояния."""
    if task_name == "разговор на свободную тему":
        return True, None
    
    if new_state is None:
        return True, None
    
    if new_state not in VALID_STATES:
        return False, f"Недопустимое состояние: {new_state}. Допустимые: {VALID_STATES}"
    
    if current_state is None:
        return True, None
    
    allowed = STATE_TRANSITIONS.get(current_state, [])
    if new_state not in allowed:
        return False, f"Недопустимый переход из '{current_state}' в '{new_state}'. Допустимые: {allowed}"
    
    return True, None


def process_state_transition(session, parsed_status: dict[str, Any]) -> dict[str, Any]:
    """Обработать переход состояния из статуса."""
    mode = get_tsm_mode(session)
    
    if mode != "deterministic":
        return parsed_status
    
    current_state = session.status.get("state")
    task_name = session.status.get("task_name", "разговор на свободную тему")
    
    if task_name == "разговор на свободную тему":
        return parsed_status
    
    proposed_state = parsed_status.get("state")
    proposed_next = parsed_status.get("next_state")
    
    target_state = proposed_next or proposed_state
    
    if target_state and target_state != current_state:
        is_valid, error = validate_state_transition(current_state, target_state, task_name)
        
        if is_valid:
            _log_transition(session, current_state, target_state)
            parsed_status["_transition_logged"] = True
            parsed_status["_transition_info"] = {
                "from": current_state,
                "to": target_state,
                "validated": True,
            }
        else:
            parsed_status["_transition_error"] = error
            parsed_status["_transition_info"] = {
                "from": current_state,
                "to": target_state,
                "validated": False,
                "error": error,
            }
            if current_state:
                parsed_status["state"] = current_state
    
    return parsed_status


def _log_transition(session, from_state: str, to_state: str) -> None:
    """Логировать переход состояния."""
    if "transition_log" not in session.status:
        session.status["transition_log"] = []
    
    from datetime import datetime
    log_entry = {
        "from": from_state,
        "to": to_state,
        "timestamp": datetime.now().isoformat(),
    }
    
    session.status["transition_log"].append(log_entry)


def get_allowed_transitions(current_state: Optional[str]) -> list[str]:
    """Получить список допустимых переходов из текущего состояния."""
    if current_state is None:
        return []
    return STATE_TRANSITIONS.get(current_state, [])


def get_current_state_info(session) -> dict:
    """Получить информацию о текущем состоянии TSM."""
    task_name = session.status.get("task_name", "разговор на свободную тему")
    current_state = session.status.get("state")
    
    return {
        "mode": get_tsm_mode(session),
        "mode_name": TSM_MODE_NAMES.get(get_tsm_mode(session), "Unknown"),
        "task_name": task_name,
        "state": current_state,
        "allowed_transitions": get_allowed_transitions(current_state) if current_state else [],
        "transition_log": session.status.get("transition_log", [])[-5:] if session.status.get("transition_log") else [],
    }


def process_orchestrator_response(
    session,
    llm_messages: list,
    provider,
    system_prompt: str,
    debug_mode: bool = False,
    debug_prompt: str | None = None
) -> dict:
    """
    Обработать ответ оркестратора и при необходимости вызвать сабагентов.
    
    Логика:
    - Модель возвращает subtasks (план подзадач)
    - Оркестратор ведёт internal active_subtasks (уже запущенные задачи)
    - При каждом ответе сравниваем subtasks с active_subtasks и запускаем новые
    
    Args:
        session: объект сессии
        llm_messages: список сообщений для LLM
        provider: провайдер LLM
        system_prompt: системный промт для LLM
        debug_mode: включить отладочный вывод
        debug_prompt: системный промт для отладки (если отличается от system_prompt)
    
    Returns:
        dict: {
            "final_content": str,  # финальный ответ пользователю
            "final_status": dict,   # финальный статус
            "debug": {...},         # вся цепочка для debug
            "usage": dict           # суммарное использование токенов
        }
    """
    from app.status_validator import validate_status_block
    from app.llm.base import Message
    
    prompt_for_debug = debug_prompt if debug_prompt is not None else system_prompt
    
    debug_info = {}
    if debug_mode:
        debug_info = {
            "orchestrator_request": {
                "system_prompt": prompt_for_debug,
                "messages_count": len(llm_messages)
            },
            "subagent_calls": [],
            "orchestrator_responses": []
        }
    
    total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    
    current_content = None
    current_status = None
    subtask_results = []
    
    active_subtasks_internal: list[dict] = []
    
    iteration = 0
    max_iterations = 10
    
    def build_system_prompt(base_prompt: str, active_list: list[dict]) -> str:
        if not active_list:
            return base_prompt
        active_info = "\n[УЖЕ ЗАПУЩЕНЫ И ВЫПОЛНЯЮТСЯ]:\n"
        for st in active_list:
            active_info += f"- {st.get('name', 'unnamed')}: {st.get('id', '?')}\n"
        return base_prompt + active_info
    
    while iteration < max_iterations:
        iteration += 1
        
        current_system_prompt = build_system_prompt(system_prompt, active_subtasks_internal)
        
        try:
            response = provider.chat(llm_messages, current_system_prompt, debug=False)
        except Exception as e:
            if debug_mode:
                debug_info["error"] = str(e)
            raise
        
        if debug_mode:
            debug_info["orchestrator_responses"].append({
                "content": response.content[:500] if response.content else "",
                "usage": response.usage,
                "status": session.status
            })
        
        current_content = response.content
        
        total_usage["input_tokens"] += response.usage.get("input_tokens", 0)
        total_usage["output_tokens"] += response.usage.get("output_tokens", 0)
        total_usage["total_tokens"] += response.usage.get("total_tokens", 0)
        
        parsed_status, cleaned_content = validate_status_block(response.content)
        
        print("[TSM] === MODEL RESPONSE START ===")
        print(f"[TSM] Response length: {len(response.content)}")
        print("[TSM] Response content (first 500 chars):")
        print(response.content[:500])
        print("[TSM] === MODEL RESPONSE END ===")
        
        print(f"[TSM] Iteration {iteration}: parsed_status = {parsed_status is not None}")
        
        if not parsed_status:
            print("[TSM] No parsed status found, breaking")
            break
        
        if debug_mode and response.content:
            debug_info['raw_model_response'] = response.content
        
        session.update_status(parsed_status)
        current_status = parsed_status
        
        model_subtasks = parsed_status.get("subtasks", [])
        
        new_subtasks = []
        for st in model_subtasks:
            st_id = st.get("id")
            if not any(s.get("id") == st_id for s in active_subtasks_internal):
                new_subtasks.append(st)
                active_subtasks_internal.append(st)
        
        print(f"[TSM] Model subtasks: {len(model_subtasks)}, New to launch: {len(new_subtasks)}, Already running: {len(active_subtasks_internal)}")
        
        if not new_subtasks and not active_subtasks_internal:
            print("[TSM] No and no active ones subtasks to launch, breaking")
            break
        
        if not new_subtasks:
            print("[TSM] All subtasks already running, waiting for completion")
            break
        
        subtask_results = []
        
        for idx, subtask in enumerate(new_subtasks):
            subtask_id = subtask.get("id", f"task_{idx}")
            subtask_name = subtask.get("name", "unnamed")
            subtask_prompt = subtask.get("prompt", "")
            
            print(f"[TSM] Processing subtask {idx+1}/{len(new_subtasks)}: {subtask_name}")
            
            if not subtask_prompt:
                print(f"[TSM] No prompt for subtask {subtask_name}, skipping")
                continue
            
            subagent_call_info = {
                "subtask_id": subtask_id,
                "subtask_name": subtask_name,
                "orchestrator_prepared_prompt": subtask_prompt[:200] + "..." if len(subtask_prompt) > 200 else subtask_prompt,
            }
            
            subagent_messages = [
                Message(role="user", content=subtask_prompt, usage={})
            ]
            
            try:
                subagent_response = provider.chat(subagent_messages, subtask_prompt, debug=False)
            except Exception as e:
                if debug_mode:
                    subagent_call_info["error"] = str(e)
                    debug_info["subagent_calls"].append(subagent_call_info)
                print(f"[TSM] Error calling subagent {subtask_name}: {e}")
                subtask_results.append({
                    "id": subtask_id,
                    "name": subtask_name,
                    "success": False,
                    "error": str(e)
                })
                continue
            
            subagent_content = subagent_response.content
            
            if debug_mode:
                subagent_call_info["subagent_response"] = {
                    "content": subagent_content[:500] if subagent_content else ""
                }
                debug_info["subagent_calls"].append(subagent_call_info)
            
            total_usage["input_tokens"] += subagent_response.usage.get("input_tokens", 0)
            total_usage["output_tokens"] += subagent_response.usage.get("output_tokens", 0)
            total_usage["total_tokens"] += subagent_response.usage.get("total_tokens", 0)
            
            subtask_results.append({
                "id": subtask_id,
                "name": subtask_name,
                "success": True,
                "content": subagent_content
            })
            
            subagent_result_message = Message(
                role="subagent",
                content=subagent_content,
                usage={}
            )
            llm_messages.append(subagent_result_message)
            
            for st in active_subtasks_internal:
                if st.get("id") == subtask_id:
                    st["completed"] = True
                    break
        
        active_subtasks_internal = [st for st in active_subtasks_internal if not st.get("completed", False)]
        
        if subtask_results:
            completed_tasks = []
            failed_tasks = []
            for result in subtask_results:
                if result["success"]:
                    completed_tasks.append(f"✅ {result['name']}")
                else:
                    failed_tasks.append(f"❌ {result['name']}: {result.get('error', 'error')}")
            
            tasks_summary = "\n".join(completed_tasks)
            if failed_tasks:
                tasks_summary += "\n" + "\n".join(failed_tasks)
            
            continuation_prompt = f"""Результаты выполнения подзадач:

{tasks_summary}

Пожалуйста, суммаризируй эти результаты и продолжи работу над основной задачей. 
Обнови статус в JSON-блоке."""
            
            llm_messages.append(Message(role="user", content=continuation_prompt, usage={}))
            
            current_content += f"\n\n---\n\n**Результаты подзадач:**\n{tasks_summary}"
            
            continue  # Продолжаем цикл для обработки результатов моделью
        else:
            break
    
    if debug_mode:
        try:
            debug_usage = response.usage
        except UnboundLocalError:
            debug_usage = {}
        debug_info["final_orchestrator_response"] = {
            "content": current_content[:500] if current_content else "",
            "usage": debug_usage
        }
        if current_status:
            debug_info['raw_status'] = current_status
    
    return {
        "final_content": current_content,
        "final_status": current_status,
        "debug": debug_info if debug_mode else None,
        "usage": total_usage
    }
