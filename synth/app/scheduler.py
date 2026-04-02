import logging
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from croniter import croniter

from app.config import config
from app.logger import debug, info, error

logger = logging.getLogger(__name__)



# MCP Tools formatting
def _format_mcp_tools_for_prompt(tools: list) -> str:
    """Format MCP tools list as a readable section for the system prompt."""
    if not tools:
        return ""
    
    lines = [
        "",
        "",
        "# Доступные инструменты (MCP Tools)",
        "",
        "У тебя есть доступ к следующим инструментам. Используй их когда это необходимо:",
        ""
    ]
    
    for tool in tools:
        if "function" in tool:
            name = tool["function"].get("name", "unknown")
            desc = tool["function"].get("description", "")
            params = tool["function"].get("parameters", {})
        else:
            name = tool.get("name", "unknown")
            desc = tool.get("description", "")
            params = tool.get("input_schema", {})
        
        lines.append(f"## {name}")
        lines.append(f"{desc}")
        
        if params and isinstance(params, dict):
            properties = params.get("properties", {})
            required = params.get("required", [])
            if properties:
                lines.append("Параметры:")
                for param_name, param_info in properties.items():
                    param_type = param_info.get("type", "any")
                    param_desc = param_info.get("description", "")
                    required_marker = " (обязательный)" if param_name in required else ""
                    lines.append(f"  - {param_name}: {param_type}{required_marker} - {param_desc}")
        lines.append("")
    
    lines.extend([
        "",
        "## Инструкция по использованию инструментов",
        "",
        "Когда пользователь просит выполнить действие, которое может быть выполнено с помощью доступных инструментов,",
        "ты ДОЛЖЕН использовать соответствующий инструмент вместо того, чтобы делать это вручную.",
        "",
        "Для вызова инструмента верни ответ с инструментом (function call) в формате API.",
        ""
    ])
    
    return "\n".join(lines)
@dataclass
class Schedule:
    id: str
    name: str
    prompt: str
    model: str | None
    session_id: str | None
    cron: str
    type: str = "cron"
    run_at: datetime | None = None
    enabled: bool = True
    last_run: datetime | None = None
    next_run: datetime | None = None
    created_at: datetime | None = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.next_run is None and self.enabled:
            self.next_run = self._calculate_next_run()

    def _calculate_next_run(self, base_time: datetime | None = None) -> datetime | None:
        if not self.enabled:
            return None
        try:
            base = base_time or datetime.now()
            if self.type == "once" and self.run_at:
                return self.run_at if self.run_at > base else None
            cron = croniter(self.cron, base)
            return cron.get_next(datetime)
        except Exception:
            return None


def _schedule_to_dict(s: Schedule) -> dict[str, Any]:
    d = asdict(s)
    d["last_run"] = s.last_run.isoformat() if s.last_run else None
    d["next_run"] = s.next_run.isoformat() if s.next_run else None
    d["created_at"] = s.created_at.isoformat() if s.created_at else None
    d["run_at"] = s.run_at.isoformat() if s.run_at else None
    return d


def _dict_to_schedule(d: dict[str, Any]) -> Schedule:
    d = d.copy()
    if d.get("last_run"):
        d["last_run"] = datetime.fromisoformat(d["last_run"])
    if d.get("next_run"):
        d["next_run"] = datetime.fromisoformat(d["next_run"])
    if d.get("created_at"):
        d["created_at"] = datetime.fromisoformat(d["created_at"])
    if d.get("run_at"):
        d["run_at"] = datetime.fromisoformat(d["run_at"])
    if "type" not in d:
        d["type"] = "cron"
    return Schedule(**d)


class Scheduler:
    SCHEDULER_USERNAME = "scheduler"

    def __init__(self):
        self._lock = threading.RLock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._check_interval = 60
        self._running_jobs: set[str] = set()
        self._scheduler_user_id: str | None = None

    def _get_schedules_path(self, project_name: str) -> Path:
        project_dir = config.data_dir / "projects" / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir / "schedules.yaml"

    def _load_schedules(self, project_name: str) -> list[Schedule]:
        path = self._get_schedules_path(project_name)
        if not path.exists():
            return []
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            schedules = data.get("schedules", [])
            return [_dict_to_schedule(s) for s in schedules]
        except Exception as e:
            logger.error(f"Failed to load schedules for {project_name}: {e}")
            return []

    def _save_schedules(self, project_name: str, schedules: list[Schedule]) -> None:
        path = self._get_schedules_path(project_name)
        data = {"schedules": [_schedule_to_dict(s) for s in schedules]}
        path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")

    def get_schedules(self, project_name: str) -> list[Schedule]:
        with self._lock:
            return self._load_schedules(project_name)

    def get_schedule(self, project_name: str, schedule_id: str) -> Schedule | None:
        schedules = self.get_schedules(project_name)
        for s in schedules:
            if s.id == schedule_id:
                return s
        return None

    def create_schedule(
        self,
        project_name: str,
        name: str,
        prompt: str,
        cron: str | None = None,
        type: str = "cron",
        run_at: datetime | None = None,
        model: str | None = None,
        session_id: str | None = None,
        enabled: bool = True,
    ) -> Schedule:
        import uuid

        with self._lock:
            schedules = self._load_schedules(project_name)
            schedule = Schedule(
                id=str(uuid.uuid4()),
                name=name,
                prompt=prompt,
                model=model,
                session_id=session_id,
                cron=cron or "0 0 * * *",
                type=type,
                run_at=run_at,
                enabled=enabled,
            )
            schedules.append(schedule)
            self._save_schedules(project_name, schedules)
            logger.info(f"[SCHEDULER] Created schedule '{name}' (type={type}) for project {project_name}")
            return schedule

    def update_schedule(
        self,
        project_name: str,
        schedule_id: str,
        name: str | None = None,
        prompt: str | None = None,
        cron: str | None = None,
        type: str | None = None,
        run_at: datetime | None = None,
        model: str | None = None,
        session_id: str | None = None,
        enabled: bool | None = None,
    ) -> Schedule | None:
        with self._lock:
            schedules = self._load_schedules(project_name)
            for s in schedules:
                if s.id == schedule_id:
                    if name is not None:
                        s.name = name
                    if prompt is not None:
                        s.prompt = prompt
                    if cron is not None:
                        s.cron = cron
                        s.next_run = s._calculate_next_run()
                    if type is not None:
                        s.type = type
                        s.next_run = s._calculate_next_run()
                    if run_at is not None:
                        s.run_at = run_at
                        s.next_run = s._calculate_next_run()
                    if model is not None:
                        s.model = model
                    if session_id is not None:
                        s.session_id = session_id
                    if enabled is not None:
                        s.enabled = enabled
                        s.next_run = s._calculate_next_run() if s.enabled else None
                    self._save_schedules(project_name, schedules)
                    logger.info(f"[SCHEDULER] Updated schedule '{s.name}' for project {project_name}")
                    return s
            return None

    def delete_schedule(self, project_name: str, schedule_id: str) -> bool:
        with self._lock:
            schedules = self._load_schedules(project_name)
            original_len = len(schedules)
            schedules = [s for s in schedules if s.id != schedule_id]
            if len(schedules) < original_len:
                self._save_schedules(project_name, schedules)
                logger.info(f"[SCHEDULER] Deleted schedule {schedule_id} from project {project_name}")
                return True
            return False

    def run_job(self, project_name: str, schedule_id: str) -> bool:
        schedule = self.get_schedule(project_name, schedule_id)
        if not schedule:
            return False
        return self._execute_job(schedule)

    def _execute_job(self, schedule: Schedule) -> bool:
        from app.llm.client import create_llm_client
        from app.session import session_manager
        from app import storage
        from app import project_manager
        from app.debug import DebugCollector
        from app.context_builder import ContextBuilder

        project_name = None
        if schedule.session_id:
            session_data = storage.storage.load_session(schedule.session_id)
            if session_data and session_data.get("status"):
                project_name = session_data["status"].get("project")
        
        if not project_name:
            project_info = project_manager.project_manager.get_projects_list()
            if not project_info:
                logger.warning(f"[SCHEDULER] No projects found, skipping job '{schedule.name}'")
                return False
            project_name = project_info[0]

        session_id = schedule.session_id or f"scheduled-{schedule.id}"
        
        try:
            session = session_manager.get_session(session_id)
            if schedule.session_id is None:
                session.status = session.status or {}
                session.status["project"] = project_name
                session_manager.save_session(session_id)

            info("SCHEDULER", f"Running scheduled job '{schedule.name}' for project {project_name}")

            debug_collector = DebugCollector.from_session(session)
            
            context_builder = ContextBuilder(session, debug_collector=debug_collector)
            
            system_prompt = context_builder.build_system_prompt()
            system_prompt = context_builder.apply_rag_to_prompt(system_prompt, schedule.prompt, use_rag=True)
            messages = context_builder.build_messages(include_user_message=schedule.prompt)
            
            client = create_llm_client(session, provider_name=schedule.model)
            provider_name = client.provider.get_provider_name()
            mcp_tools = context_builder.build_mcp_tools(provider_name)
            
            if mcp_tools:
                system_prompt += _format_mcp_tools_for_prompt(mcp_tools)
            
            response = self._handle_tool_calls(
                client=client,
                messages=messages,
                system_prompt=system_prompt,
                mcp_tools=mcp_tools,
                debug_collector=debug_collector,
                session=session,
            )

            debug_info = debug_collector.get_debug_info() if debug_collector else None

            if response.content:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                session.add_user_message(schedule.prompt, source=f"scheduler | {timestamp}")
                session.add_assistant_message(
                    response.content,
                    response.usage,
                    debug=debug_info,
                    model=response.model,
                )
                session_manager.save_session(session_id)

            schedule.last_run = datetime.now()
            
            if schedule.type == "once":
                schedule.enabled = False
                schedule.next_run = None
                debug("SCHEDULER", f"One-time job '{schedule.name}' completed, disabled (kept in history)")
            else:
                schedule.next_run = schedule._calculate_next_run()
            
            self._save_schedules(project_name, [schedule])

            info("SCHEDULER", f"Completed job '{schedule.name}'")
            return True

        except Exception as e:
            logger.error(f"[SCHEDULER] Error executing job '{schedule.name}': {e}")
            return False

    def _handle_tool_calls(self, client, messages: list, system_prompt: str, mcp_tools: list | None, debug_collector=None, session=None, max_iterations: int = 10):
        """Рекурсивно обрабатывает tool calls от LLM."""
        from app.llm.base import Message
        from app.routes import run_mcp_async
        
        iteration = 0
        current_mcp_tools = mcp_tools
        response = None
        
        while iteration < max_iterations:
            iteration += 1
            debug("SCHEDULER", f"Tool call iteration {iteration}")
            
            response = client.send(
                messages=messages,
                system_prompt=system_prompt,
                debug_collector=debug_collector,
                tools=current_mcp_tools,
            )
            
            if not response.tool_calls:
                debug("SCHEDULER", "No more tool calls, final response received")
                return response
            
            debug("SCHEDULER", f"Processing {len(response.tool_calls)} tool call(s)")
            
            tool_call_results = []
            
            for tc in response.tool_calls:
                tool_name = tc.get("function", {}).get("name") or tc.get("name", "")
                tool_args = tc.get("function", {}).get("arguments") or tc.get("arguments", {}) or {}
                
                if isinstance(tool_args, str):
                    import json
                    try:
                        tool_args = json.loads(tool_args)
                    except json.JSONDecodeError:
                        tool_args = {}
                
                debug("SCHEDULER", f"Calling tool: {tool_name}")
                
                try:
                    from app.mcp.processor import call_mcp_tool
                    tool_result_content = run_mcp_async(call_mcp_tool(tool_name, tool_args, session=session))
                except Exception as e:
                    tool_result_content = f"Error: {str(e)}"
                    error("SCHEDULER", f"Tool error: {e}")
                
                if debug_collector and debug_collector.enabled:
                    debug_collector.capture_mcp_call(
                        tool_name,
                        tool_args,
                        tool_result_content,
                        is_error=tool_result_content.startswith("Error:")
                    )
                
                tool_call_results.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": tool_result_content,
                })
            
            messages.append(Message(
                role="assistant",
                content=response.content or "",
                usage={},
                tool_use=response.tool_calls,
                model=response.model,
                summary_of=None,
                created_at=datetime.now(),
                disabled=False,
                branch_id="main",
                source="scheduler",
                status=None,
                tool_call_id=None,
            ))
            
            for tc_result in tool_call_results:
                messages.append(Message(
                    role="tool",
                    content=tc_result["content"],
                    tool_call_id=tc_result.get("tool_call_id"),
                    usage={},
                    model=None,
                    summary_of=None,
                    created_at=datetime.now(),
                    disabled=False,
                    branch_id="main",
                    source="scheduler",
                    status=None,
                    tool_use=None,
                ))
            
            current_mcp_tools = None
        
        if response is None:
            raise RuntimeError("No response received from LLM")
        
        debug("SCHEDULER", f"Max tool call iterations ({max_iterations}) reached")
        return response

    def _run_scheduler(self) -> None:
        while self._running:
            try:
                projects_dir = config.data_dir / "projects"
                if projects_dir.exists():
                    for project_path in projects_dir.iterdir():
                        if project_path.is_dir():
                            project_name = project_path.name
                            schedules = self._load_schedules(project_name)
                            now = datetime.now()
                            for schedule in schedules:
                                if not schedule.enabled:
                                    continue
                                if schedule.next_run and schedule.next_run <= now:
                                    if schedule.id in self._running_jobs:
                                        logger.info(f"[SCHEDULER] Job '{schedule.name}' already running, skipping")
                                        continue
                                    info("SCHEDULER", f"Triggering job '{schedule.name}' for project {project_name}")
                                    self._running_jobs.add(schedule.id)
                                    try:
                                        self._execute_job(schedule)
                                    finally:
                                        self._running_jobs.discard(schedule.id)
            except Exception as e:
                logger.error(f"[SCHEDULER] Error in scheduler loop: {e}")
            time.sleep(self._check_interval)

    def start(self) -> None:
        if self._running:
            return
        
        self._ensure_scheduler_user()
        
        self._running = True
        self._thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self._thread.start()
        info("SCHEDULER", "Started")

        self._catch_up()

    def _ensure_scheduler_user(self) -> None:
        from app.models import User
        from app import storage as app_storage
        
        existing_user = app_storage.storage.get_user_by_username(self.SCHEDULER_USERNAME)
        if existing_user:
            self._scheduler_user_id = existing_user.id
            logger.info(f"[SCHEDULER] Using existing user: {self.SCHEDULER_USERNAME} (id: {self._scheduler_user_id})")
            return
        
        import uuid
        user = User(
            id=str(uuid.uuid4()),
            username=self.SCHEDULER_USERNAME,
            email="scheduler@system.local",
            role="admin",
            team_role="admin_team",
            notes="Системный пользователь для автоматических заданий по расписанию",
            is_active=True,
        )
        app_storage.storage.save_user(user)
        self._scheduler_user_id = user.id
        logger.info(f"[SCHEDULER] Created system user: {self.SCHEDULER_USERNAME} (id: {self._scheduler_user_id})")

    def _catch_up(self) -> None:
        projects_dir = config.data_dir / "projects"
        if not projects_dir.exists():
            return
        now = datetime.now()
        for project_path in projects_dir.iterdir():
            if not project_path.is_dir():
                continue
            project_name = project_path.name
            schedules = self._load_schedules(project_name)
            for schedule in schedules:
                if schedule.enabled and schedule.next_run and schedule.next_run < now:
                    info("SCHEDULER", f"Catching up missed job '{schedule.name}' for project {project_name}")
                    self._execute_job(schedule)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        info("SCHEDULER", "Stopped")


scheduler = Scheduler()
