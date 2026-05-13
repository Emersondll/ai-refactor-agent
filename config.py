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
MODEL_RECOVERY = "gemma4:latest"   # -> Autocura Local Especializada (Second Opinion)
CLAUDE_MODEL        = "claude-3-5-sonnet-20240620"
CLAUDE_API_KEY      = os.getenv("ANTHROPIC_API_KEY")
USE_CLAUDE_FALLBACK = os.getenv("USE_CLAUDE_FALLBACK", "true").lower() == "true"
FLOW_MODE           = os.getenv("FLOW_MODE", "false").lower() == "true"

TIMEOUT     = 600
MAX_RETRIES = 2

# ---------------------------------------------------------------------------
# Performance Skills (all disabled by default — enable via .env)
# ---------------------------------------------------------------------------
USE_LLMLINGUA    = os.getenv("USE_LLMLINGUA",    "false").lower() == "true"
USE_RAG_CONTEXT  = os.getenv("USE_RAG_CONTEXT",  "false").lower() == "true"
USE_MEM0         = os.getenv("USE_MEM0",         "false").lower() == "true"
USE_CONTEXT7     = os.getenv("USE_CONTEXT7",     "false").lower() == "true"
LLMLINGUA_RATIO  = float(os.getenv("LLMLINGUA_RATIO", "0.6"))
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_BASE_URL    = os.getenv("OLLAMA_BASE_URL",    "http://localhost:11434")

# ---------------------------------------------------------------------------
# Agent Loop (disabled by default — enable via .env)
# ---------------------------------------------------------------------------
USE_AGENT_MODE   = os.getenv("USE_AGENT_MODE",   "false").lower() == "true"
AGENT_MAX_CYCLES = int(os.getenv("AGENT_MAX_CYCLES", "20"))

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PHASES_DIR = os.path.join(BASE_DIR, "phases")
REPOS_DIR  = os.path.join(BASE_DIR, "repos")
LOGS_DIR   = os.path.join(BASE_DIR, "logs")