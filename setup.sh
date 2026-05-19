#!/usr/bin/env bash
# setup.sh — Instalação e inicialização do AI Refactor Agent
# Uso: ./setup.sh
# Todas as etapas verificam se já estão instaladas antes de agir.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── cores ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}[ok]${RESET}   $*"; }
info() { echo -e "${CYAN}[...]${RESET}  $*"; }
warn() { echo -e "${YELLOW}[aviso]${RESET} $*"; }
err()  { echo -e "${RED}[erro]${RESET}  $*" >&2; }
step() { echo -e "\n${BOLD}${CYAN}▶ $*${RESET}"; }

# ═══════════════════════════════════════════════════════════════════════════
# 1. Python 3.12+
# ═══════════════════════════════════════════════════════════════════════════
step "Verificando Python 3.12+"

PYTHON_BIN=""
for cmd in python3.12 python3.13 python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(sys.version_info[:2])")
        if "$cmd" -c "import sys; exit(0 if sys.version_info >= (3,12) else 1)" 2>/dev/null; then
            PYTHON_BIN="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    err "Python 3.12+ não encontrado."
    err "Instale via: sudo apt install python3.12  ou  https://www.python.org/downloads/"
    exit 1
fi

ok "Python encontrado: $($PYTHON_BIN --version)"

# ═══════════════════════════════════════════════════════════════════════════
# 2. SDKMAN + Java 22
# ═══════════════════════════════════════════════════════════════════════════
step "Verificando SDKMAN"

if [ ! -f "$HOME/.sdkman/bin/sdkman-init.sh" ]; then
    info "SDKMAN não encontrado. Instalando..."
    curl -s "https://get.sdkman.io" | bash
    ok "SDKMAN instalado."
else
    ok "SDKMAN já instalado."
fi

# shellcheck disable=SC1091
source "$HOME/.sdkman/bin/sdkman-init.sh"

step "Verificando Java 22-open"

if sdk list java 2>/dev/null | grep -q "22\..*open.*installed"; then
    ok "Java 22-open já instalado."
else
    info "Instalando Java 22-open via SDKMAN..."
    sdk install java 22-open
    ok "Java 22-open instalado."
fi

sdk use java 22-open > /dev/null 2>&1
ok "Java ativo: $(java -version 2>&1 | head -1)"

# ═══════════════════════════════════════════════════════════════════════════
# 3. Ollama — binário
# ═══════════════════════════════════════════════════════════════════════════
step "Verificando Ollama"

if ! command -v ollama &>/dev/null; then
    info "Ollama não encontrado. Instalando..."
    curl -fsSL https://ollama.com/install.sh | sh
    ok "Ollama instalado."
else
    ok "Ollama já instalado: $(ollama --version 2>/dev/null || echo 'versão desconhecida')"
fi

# ── serviço ────────────────────────────────────────────────────────────────
step "Verificando serviço Ollama"

if ! curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
    info "Iniciando ollama serve em background..."
    nohup ollama serve > /tmp/ollama.log 2>&1 &
    OLLAMA_PID=$!
    for i in $(seq 1 10); do
        sleep 2
        if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
            ok "Ollama respondendo (PID $OLLAMA_PID)."
            break
        fi
        if [ "$i" -eq 10 ]; then
            err "Ollama não respondeu após 20s. Verifique: tail /tmp/ollama.log"
            exit 1
        fi
    done
else
    ok "Ollama já está rodando."
fi

# ── modelos ────────────────────────────────────────────────────────────────
step "Verificando modelos Ollama"

MODELS=(
    "gemma4:latest"
    "qwen2.5-coder:14b"
    "qwen2.5-coder:7b"
    "neural-chat:7b"
    "nomic-embed-text"
)

for model in "${MODELS[@]}"; do
    if ollama list 2>/dev/null | grep -q "^${model%:*}"; then
        ok "Modelo já disponível: $model"
    else
        info "Baixando $model (pode demorar alguns minutos)..."
        ollama pull "$model"
        ok "$model baixado."
    fi
done

# ═══════════════════════════════════════════════════════════════════════════
# 4. Skills LLM
# ═══════════════════════════════════════════════════════════════════════════
step "Instalando skills LLM"

SKILLS_SRC="$SCRIPT_DIR/skills"
SKILLS_DST="$HOME/.claude/skills"

if [ ! -d "$SKILLS_SRC" ]; then
    warn "Diretório skills/ não encontrado no repo. Pulando instalação de skills."
else
    mkdir -p "$SKILLS_DST"
    for skill_dir in "$SKILLS_SRC"/*/; do
        skill_name="$(basename "$skill_dir")"
        dst="$SKILLS_DST/$skill_name"
        if [ -f "$dst/SKILL.md" ]; then
            ok "Skill já instalada: $skill_name"
        else
            mkdir -p "$dst"
            cp "$skill_dir/SKILL.md" "$dst/SKILL.md"
            ok "Skill instalada: $skill_name"
        fi
    done
fi

# ═══════════════════════════════════════════════════════════════════════════
# 5. Ambiente Python (venv + dependências)
# ═══════════════════════════════════════════════════════════════════════════
step "Configurando ambiente Python"

if [ ! -d ".venv" ]; then
    info "Criando virtualenv..."
    "$PYTHON_BIN" -m venv .venv
    ok "Virtualenv criado em .venv/"
else
    ok "Virtualenv já existe."
fi

# shellcheck disable=SC1091
source .venv/bin/activate

info "Instalando dependências (pip)..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
ok "Dependências instaladas."

# ═══════════════════════════════════════════════════════════════════════════
# 6. Arquivo .env
# ═══════════════════════════════════════════════════════════════════════════
step "Verificando .env"

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        warn ".env criado a partir de .env.example."
        warn "Edite .env antes de continuar — adicione GITHUB_TOKEN e GITHUB_USERNAME."
        echo ""
        read -rp "Pressione ENTER após editar o .env para continuar, ou Ctrl+C para sair: "
    else
        err ".env não encontrado e .env.example também não existe."
        exit 1
    fi
else
    ok ".env encontrado."
fi

# ═══════════════════════════════════════════════════════════════════════════
# 7. Iniciar agente
# ═══════════════════════════════════════════════════════════════════════════
step "Iniciando o AI Refactor Agent"
echo ""
echo -e "${BOLD}Dashboard:  http://localhost:8000/dashboard.html${RESET}"
echo -e "${BOLD}Relatório:  http://localhost:8000/report.html${RESET}"
echo ""

python3 main.py
