# config.py — Localização: raiz do projeto (ai-refactor-agent/)

import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ===========================================================================
# MODELOS — hierarquia por RAM disponível
#
# dolphin-mixtral:8x7b (26GB) foi removido como TERTIARY — OOM na máquina.
# Substituído por qwen3.5 (6.6GB) e gemma4 (9.6GB) que cabem na RAM.
#
# Modelos especializados por papel (Role-Based Models):
MODEL_DOC   = "neural-chat:7b"     # (4.1GB) -> Javadoc / Documentação
MODEL_STRUCT = "qwen2.5-coder:7b"   # (4.7GB) -> Estrutura / Nomenclatura (Melhor para Java)
MODEL_CLEAN  = "gemma4:latest"     # (9.6GB) -> Clean Code / Testes
MODEL_SOLID  = "qwen2.5-coder:14b" # (9.0GB) -> SOLID / Arquitetura (O Crítico)

CLAUDE_MODEL        = "claude-3-5-sonnet-20240620"
CLAUDE_API_KEY      = os.getenv("ANTHROPIC_API_KEY")
USE_CLAUDE_FALLBACK = os.getenv("USE_CLAUDE_FALLBACK", "false").lower() == "true"

TIMEOUT     = 600
MAX_RETRIES = 2

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PHASES_DIR = os.path.join(BASE_DIR, "phases")
REPOS_DIR  = os.path.join(BASE_DIR, "repos")
LOGS_DIR   = os.path.join(BASE_DIR, "logs")