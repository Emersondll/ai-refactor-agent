# config.py — Location: project root (ai-refactor-agent/)

import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ===========================================================================
# MODELS — hierarchy by available RAM
#
# dolphin-mixtral:8x7b (26GB) removed as TERTIARY — OOM on this machine.
# Replaced by qwen3.5 (6.6GB) and gemma4 (9.6GB) which fit in RAM.
#
# Role-Based Models:
MODEL_DOC      = os.getenv("MODEL_DOC",      "qwen2.5-coder:7b")  # (4.7GB) -> Javadoc / Documentation (code-aware: does not change structure)
MODEL_STRUCT   = os.getenv("MODEL_STRUCT",   "qwen2.5-coder:7b")  # (4.7GB) -> Structure / Naming (best for Java)
MODEL_CLEAN    = os.getenv("MODEL_CLEAN",    "gemma4:latest")      # (9.6GB) -> Clean Code / Tests
MODEL_SOLID    = os.getenv("MODEL_SOLID",    "qwen2.5-coder:14b")  # (9.0GB) -> SOLID / Architecture (The Critic)
MODEL_RECOVERY = os.getenv("MODEL_RECOVERY", "qwen2.5-coder:14b")  # (9.0GB) -> Self-heal — DIFFERENT from MODEL_CLEAN (real second opinion)
MODEL_REVIEWER  = os.getenv("MODEL_REVIEWER", MODEL_STRUCT)  # qwen2.5-coder:7b — diff reviewer (fast, no RAM swap)
CLAUDE_MODEL        = "claude-sonnet-4-6"
CLAUDE_API_KEY      = os.getenv("ANTHROPIC_API_KEY")
USE_CLAUDE_FALLBACK = os.getenv("USE_CLAUDE_FALLBACK", "true").lower() == "true"
FLOW_MODE           = os.getenv("FLOW_MODE", "false").lower() == "true"

TIMEOUT      = 600   # refactoring — max time per Ollama call
TIMEOUT_TEST = 420   # test generation — 7 min per call; covers ~50s KV cache + ~250s generation (gemma4 9B) with margin
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

# M8: maximum age (in days) for a permanent_skip entry. Older entries are
# auto-removed by FailedFilesTracker.reset() regardless of pattern matching.
# Long-term safety net so nothing stays stuck forever.
MAX_SKIP_AGE_DAYS = int(os.getenv("MAX_SKIP_AGE_DAYS", "30"))

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
#               "claude" → Claude API plans, Ollama executes (hybrid)
PLANNER_MODE      = os.getenv("PLANNER_MODE", "local").lower()
USE_LOCAL_PLANNER = PLANNER_MODE == "local"  # legacy compatibility
# Dedicated model for the local planner — smaller and faster than MODEL_SOLID
# The planner only needs to generate decision JSON, not complex Java code
MODEL_PLANNER     = os.getenv("MODEL_PLANNER", MODEL_STRUCT)

# GitHub URL of the repository being refactored — shown in the refactoring report.
# Set via .env: REPO_GITHUB_URL=https://github.com/org/repo
REPO_GITHUB_URL = os.getenv("REPO_GITHUB_URL", "")

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PHASES_DIR = os.path.join(BASE_DIR, "phases")
REPOS_DIR  = os.path.join(BASE_DIR, "repos")
LOGS_DIR   = os.path.join(BASE_DIR, "logs")