"""Project updates handling from session status."""

from app import project_manager, scheduler
from app.logger import error
from datetime import datetime


def handle_project_updates(session) -> None:
    """Обработать обновления проекта из статуса"""
    status = session.status
    
    project_name = status.get("project")
    if not project_name:
        return
    
    if not project_manager.project_manager.project_exists(project_name):
        project_manager.project_manager.create_project(project_name)
    
    updated_info = status.get("updated_project_info")
    if updated_info:
        project_manager.project_manager.update_project_info(project_name, updated_info)
    
    current_task = status.get("current_task_info")
    if current_task:
        project_manager.project_manager.save_current_task(project_name, current_task)

    invariants = status.get("invariants")
    if invariants:
        project_manager.project_manager.save_invariants(project_name, invariants)

    schedule_data = status.get("schedule")
    if schedule_data and project_name:
        try:
            model = schedule_data.get("model") or session.model
            schedule_type = schedule_data.get("type", "cron")
            
            run_at = None
            if schedule_type == "once" and schedule_data.get("run_at"):
                run_at = datetime.fromisoformat(schedule_data.get("run_at"))
            
            scheduler.scheduler.create_schedule(
                project_name=project_name,
                name=schedule_data.get("name", "Scheduled task"),
                prompt=schedule_data.get("prompt", ""),
                cron=schedule_data.get("cron", "0 0 * * *"),
                type=schedule_type,
                run_at=run_at,
                model=model,
                session_id=session.session_id,
                enabled=True,
            )
        except Exception as e:
            error("PROJECT_UPDATES", f"Failed to create schedule from status block: {e}")
