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
MODEL_DOC      = os.getenv("MODEL_DOC",      "qwen2.5-coder:7b")  # (4.7GB) -> Javadoc / Documentação (code-aware: não muda estrutura)
MODEL_STRUCT   = os.getenv("MODEL_STRUCT",   "qwen2.5-coder:7b")  # (4.7GB) -> Estrutura / Nomenclatura (Melhor para Java)
MODEL_CLEAN    = os.getenv("MODEL_CLEAN",    "gemma4:latest")      # (9.6GB) -> Clean Code / Testes
MODEL_SOLID    = os.getenv("MODEL_SOLID",    "qwen2.5-coder:14b")  # (9.0GB) -> SOLID / Arquitetura (O Crítico)
MODEL_RECOVERY = os.getenv("MODEL_RECOVERY", "qwen2.5-coder:14b")  # (9.0GB) -> Autocura — modelo DIFERENTE de MODEL_CLEAN (second opinion real)
MODEL_REVIEWER  = os.getenv("MODEL_REVIEWER", MODEL_STRUCT)  # qwen2.5-coder:7b — revisor de diffs (rápido, sem swap de RAM)
CLAUDE_MODEL        = "claude-sonnet-4-6"
CLAUDE_API_KEY      = os.getenv("ANTHROPIC_API_KEY")
USE_CLAUDE_FALLBACK = os.getenv("USE_CLAUDE_FALLBACK", "true").lower() == "true"
FLOW_MODE           = os.getenv("FLOW_MODE", "false").lower() == "true"

TIMEOUT      = 600   # refatoração — tempo máximo por chamada Ollama
TIMEOUT_TEST = 420   # geração de testes — 7 min por chamada; cobre ~50s KV cache + ~250s geração (gemma4 9B) com margem
MAX_RETRIES  = 2
OLLAMA_SEED  = int(os.getenv("OLLAMA_SEED", "42"))  # fixed seed → reproducible generation run-to-run

# M4: comma-separated list of test file basenames to force-retry even if they
# are in failed_files.json as permanent_skip. Useful when a recent fix should
# unblock specific files. Example: FORCE_RETRY=TransactionControllerTest.java,FooTest.java
FORCE_RETRY = [
    s.strip()
    for s in os.getenv("FORCE_RETRY", "").split(",")
    if s.strip()
]

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
# Community Tools
# ---------------------------------------------------------------------------
GJF_PATH = os.getenv("GJF_PATH", "google-java-format")

# ---------------------------------------------------------------------------
# Agent Loop (disabled by default — enable via .env)
# ---------------------------------------------------------------------------
USE_AGENT_MODE   = os.getenv("USE_AGENT_MODE",  "false").lower() == "true"
AGENT_MAX_CYCLES = int(os.getenv("AGENT_MAX_CYCLES", "20"))
# PLANNER_MODE: "local" → MODEL_PLANNER planeja (totalmente local)
#               "claude" → Claude API planeja, Ollama executa (híbrido)
PLANNER_MODE      = os.getenv("PLANNER_MODE", "local").lower()
USE_LOCAL_PLANNER = PLANNER_MODE == "local"  # compatibilidade com código legado
# Modelo dedicado ao planner local — menor e mais rápido que MODEL_SOLID
# O planner só precisa gerar JSON de decisões, não código Java complexo
MODEL_PLANNER     = os.getenv("MODEL_PLANNER", MODEL_STRUCT)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PHASES_DIR = os.path.join(BASE_DIR, "phases")
REPOS_DIR  = os.path.join(BASE_DIR, "repos")
LOGS_DIR   = os.path.join(BASE_DIR, "logs")