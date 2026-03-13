import logging
from typing import Any

from app.config import config


LOG_LEVELS = {
    "NONE": None,
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

LEVEL_NAMES = {v: k for k, v in LOG_LEVELS.items() if v is not None}
LEVEL_NAMES[None] = "NONE"


def get_level_for_group(group: str) -> int | None:
    debug_config = config._config.get("debug", {})
    groups = debug_config.get("groups", {})
    level_name = groups.get(group, "INFO")
    return LOG_LEVELS.get(level_name)


def set_level_for_group(group: str, level_name: str) -> None:
    if "debug" not in config._config:
        config._config["debug"] = {}
    if "groups" not in config._config["debug"]:
        config._config["debug"]["groups"] = {}
    config._config["debug"]["groups"][group] = level_name
    config.save()


def get_all_groups() -> dict[str, str]:
    debug_config = config._config.get("debug", {})
    groups = debug_config.get("groups", {})
    default_groups = {
        "ANTHROPIC": "INFO",
        "MCP": "INFO",
        "ROUTES": "WARNING",
        "ORCHESTRATOR": "INFO",
        "CHAT_STREAM": "WARNING",
        "TSM": "INFO",
        "STORAGE": "WARNING",
        "SCHEDULER": "INFO",
        "INIT": "INFO",
        "DEBUG": "DEBUG",
    }
    return {**default_groups, **groups}


def log(group: str, level_name: str, message: str) -> None:
    level = LOG_LEVELS.get(level_name)
    if level is None:
        return

    group_level = get_level_for_group(group)
    if group_level is None:
        return

    if level < group_level:
        return

    logger = logging.getLogger(f"app.{group}")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(f"[{group}] %(message)s"))
        logger.addHandler(handler)

    log_func = {
        logging.DEBUG: logger.debug,
        logging.INFO: logger.info,
        logging.WARNING: logger.warning,
        logging.ERROR: logger.error,
        logging.CRITICAL: logger.critical,
    }.get(level, logger.debug)

    log_func(message)


def debug(group: str, message: str) -> None:
    log(group, "DEBUG", message)


def info(group: str, message: str) -> None:
    log(group, "INFO", message)


def warning(group: str, message: str) -> None:
    log(group, "WARNING", message)


def error(group: str, message: str) -> None:
    log(group, "ERROR", message)


def critical(group: str, message: str) -> None:
    log(group, "CRITICAL", message)
