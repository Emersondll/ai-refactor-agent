# core/logger.py
#
# Logger de terminal — saída em tempo real durante execução.
# Usado em todo o projeto: model.py, refactor.py, repo.py, main.py, etc.
#
# NÃO persiste em arquivo. Para rastreamento auditável em arquivo,
# use execution_logger.py.

from datetime import datetime


def log(msg: str, level: str = "INFO") -> None:
    """
    Imprime uma linha formatada no terminal.

    Args:
        msg:   mensagem a exibir
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