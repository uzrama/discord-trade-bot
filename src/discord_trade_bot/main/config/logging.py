import logging

import coloredlogs


def setup_logging(level: str | int = logging.INFO) -> None:
    # 2023-10-27 15:30:00 INFO [module_name]
    log_format = "[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    field_styles = coloredlogs.DEFAULT_FIELD_STYLES.copy()
    field_styles["name"] = {"color": "blue"}
    field_styles["asctime"] = {"color": "black", "bright": True}

    level_styles = coloredlogs.DEFAULT_LEVEL_STYLES.copy()
    level_styles["debug"] = {"color": "black", "bright": True}
    level_styles["info"] = {"color": "green"}
    level_styles["warning"] = {"color": "yellow"}
    level_styles["error"] = {"color": "red", "bold": True}
    level_styles["critical"] = {"color": "red", "bold": True, "background": "white"}

    coloredlogs.install(level=level, fmt=log_format, datefmt=date_format, field_styles=field_styles, level_styles=level_styles)

    # Suppress noisy loggers
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("taskiq").setLevel(logging.INFO)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
