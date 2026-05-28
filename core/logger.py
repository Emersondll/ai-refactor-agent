# core/logger.py
#
# Terminal logger — real-time output during execution.
# Used throughout the project: model.py, refactor.py, repo.py, main.py, etc.
#
# Does NOT persist to file. For auditable file tracking, use execution_logger.py.

from datetime import datetime


def log(msg: str, level: str = "INFO") -> None:
    """Prints a formatted line to the terminal.

    Args:
        msg:   message to display
        level: INFO | OK | WARN | ERR | PHASE
    """
    icons = {
        "INFO":  "·",
        "OK":    "OK",
        "WARN":  "WARN",
        "ERR":   "ERR",
        "PHASE": "RUN",
    }
    icon = icons.get(level, "·")
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {icon:4} {msg}")