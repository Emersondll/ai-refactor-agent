# Local AI Code Refactor Agent

Agente autônomo de refatoração Java que roda **100% localmente** via Ollama. Aplica 14 fases de qualidade — ferramentas determinísticas + LLM método a método — mantendo o build Maven sempre verde.

---

## Arquitetura do Pipeline

```
main.py
  ├── Fase AUDIT_COVERAGE     → java/refactor.py (geração de testes TDD)
  └── Fases 01–14 (loop sequencial via phases/configs/*.yml)
        ├── tool: community   → java/community_runner.py
        ├── tool: llm         → java/llm_runner.py
        │                          ├── method_level: true  → java/method_runner.py (_run_method_level)
        │                          ├── class_level:  true  → java/method_runner.py (_run_class_level)
        │                          └── (sem flag)          → llm_runner loop por arquivo
        └── tool: flow/flow-dry → java/flow_runner.py
```

### As 14 Fases

| # | Skill | Tool | Runner | Granularidade |
|---|-------|------|--------|---------------|
| 01 | clean-imports | community | community_runner | arquivo |
| 02 | format | community | community_runner | arquivo |
| 03 | final-keywords | community | community_runner | arquivo |
| 04 | naming-conventions | community | community_runner | arquivo |
| 05 | dead-code | community | community_runner | arquivo |
| 06 | simplify-code | community | community_runner | arquivo |
| 07 | modernize-syntax | community | community_runner | arquivo |
| 08 | static-analysis | community | community_runner | arquivo |
| 09 | guard-clauses | llm → method | method_runner | **método** |
| 10 | method-extraction | llm → method | method_runner | **método** |
| 11 | solid-dip | llm → class | method_runner | **classe comprimida** |
| 12 | controller-lean | llm → method | method_runner | **método** |
| 13 | flow-refactor | flow | flow_runner | endpoint/fluxo |
| 14 | dry-check | flow-dry | flow_runner | grupo de arquivos |

---

## Refatoração Método a Método (Fases 09, 10, 12)

```
Para cada arquivo Java (excl. testes):
  │
  ├── cache.is_phase_done?       → skip
  ├── _is_structural_type?       → skip (FILE_SKIPPED — azul no dashboard)
  │     record / interface / @Entity / @Document / DTO / /dto/
  │
  └── Para cada método:
        ├── cache.is_method_done?           → skip
        ├── detect_fn(method.body)?         → padrão ausente → marcar done, skip
        │
        ├── build_method_context()
        │     └── esqueleto da classe (outros métodos como assinatura)
        │         + método alvo completo
        │
        ├── call_ai(method.full_text, dep_context=esqueleto)
        │     └── LLM devolve APENAS o método refatorado
        │
        ├── extract_method_from_response()
        ├── merge_method(código_atual, original, novo)  ← substituição cirúrgica por linha
        ├── mvn compile -q
        │     ├── OK  → mark_method_done + FILE_ACCEPTED
        │     └── ERR → write_file(código_anterior)   + FILE_REVERTED
        └── mark_phase_done(arquivo) após todos os métodos avaliados
```

## Refatoração Classe Comprimida (Fase 11 — solid-dip)

```
Para cada arquivo Java:
  ├── _is_structural_type? → skip
  ├── Coleta done_keys de fases anteriores (guard-clauses, controller-lean, method-extraction)
  ├── compress_done_methods(code, done_keys)
  │     └── substitui corpos já refatorados por /* [refactored] */ (reduz tokens)
  ├── call_ai(compressed_class)
  │     └── LLM devolve classe inteira
  ├── mvn compile -q
  │     ├── OK  → write + mark_phase_done + FILE_ACCEPTED
  │     └── ERR → git checkout -- arquivo   + FILE_REVERTED
  └── mark_phase_done
```

---

## Módulos Java

| Arquivo | Papel |
|---------|-------|
| `java/method_extractor.py` | Extrai `MethodDef` (signature, body, start/end line) sem parser AST — contagem de chaves |
| `java/class_builder.py` | `build_method_context`, `compress_done_methods`, `merge_method`, `extract_method_from_response` |
| `java/method_runner.py` | Orquestra refatoração método a método (`_run_method_level`) e classe comprimida (`_run_class_level`) |
| `java/llm_runner.py` | Dispatch → method_runner ou loop file-level; detectores de padrão; `_is_structural_type()` |
| `java/flow_runner.py` | Refatoração por cadeia de endpoint; DRY check; repair loop de produção |
| `java/flow_mapper.py` | Análise estática — mapeia endpoints, resolve interface→impl, classifica exclusivo/compartilhado |
| `java/community_runner.py` | Executa ferramentas OpenRewrite/GJF/PMD |
| `java/refactor.py` | Geração de testes TDD — `generate_tests()` com repair loop e JaCoCo |
| `java/llm_reviewer.py` | Revisa diff pós-fase com `review_criteria` do yml → APPROVE/REJECT/SKIP |

---

## Cache em Dois Níveis

```
memory/cache.py
  ├── is_phase_done(file, phase)              → arquivo inteiro já processado
  ├── mark_phase_done(file, phase)
  ├── is_method_done(file, method_key, phase) → chave = "file_path#signature_normalizada"
  ├── mark_method_done(file, method_key, phase)
  └── done_method_keys(file, phase)           → usado pelo compress_done_methods
```

---

## Skills LLM

Todas em `~/.claude/skills/<nome>/SKILL.md`. Carregadas via `load_skill(name, section="LLM INSTRUCTIONS")`.

| Fase | Skill | detect_pattern | method_level | class_level |
|------|-------|---------------|:---:|:---:|
| 09 | `java-guard-clauses` | `nested_if` (≥3) | ✓ | — |
| 10 | `java-method-extraction` | `long_method` (>30 linhas) | ✓ | — |
| 11 | `java-solid-dip` | `concrete_new` | — | ✓ |
| 12 | `java-controller-lean` | `controller_logic` | ✓ | — |
| 13 | `java-flow-refactor` | — | — | — |
| 14 | `java-dry-extraction` | — | — | — |
| AUDIT | `java-tdd-unit-test` | — | — | — |

---

## Dashboard em Tempo Real

`dashboard.html` atualizado a cada 10 segundos com dados de `logs/execution.jsonl`.

| Cor do hexágono | Significado |
|----------------|-------------|
| Cinza | Pendente (ainda não processado) |
| Dourado | Em processamento agora |
| Azul-claro | Pulado (record/interface/DTO/entity — sem lógica de negócio) |
| Verde | Concluído com sucesso |
| Vermelho | Falha / autocura (compile falhou, arquivo revertido) |

```bash
# Iniciar o servidor do dashboard (opcional — main.py faz isso automaticamente)
python3 -m http.server 8000
# Acessar: http://localhost:8000/dashboard.html
```

---

## Técnicas de Qualidade Integradas

- **Reviewer Pattern**: diff pós-fase avaliado por `llm_reviewer.py` com critérios específicos por skill → APPROVE/REJECT/SKIP
- **TDD Unit Test Skill** (`java-tdd-unit-test`): gera testes autonomamente antes da refatoração, documentando o comportamento atual; injeta record semantics (C21) e package/imports reais (C22) no prompt
- **JaCoCo Guardrail**: cobertura mínima ≥ 90% exigida; ciclo RED-GREEN-REPAIR expande testes até atingir a meta
- **Structured Repair Loop**: falha de compilação → `_categorize_build_error()` → instrução direcionada → LLM corrige; até `MAX_VALIDATOR_RETRIES` por arquivo com timeout de 10 min
- **Ollama OOM Recovery**: `wait_for_ollama_recovery()` aguarda até 3×30s após cascade de RAM antes de continuar
- **Enum Constraints Injection**: `_extract_enum_constraints(dep_context)` parseia blocos `enum` e injeta valores reais no prompt — LLM não pode alucinar constantes
- **Structural Type Skip**: `_is_structural_type()` detecta records, interfaces, @Entity, @Document, DTOs e emite FILE_SKIPPED — zero tokens desperdiçados em tipos sem lógica de negócio
- **Class Compression**: métodos já refatorados em fases anteriores são comprimidos para `/* [refactored] */` antes de enviar ao LLM da fase solid-dip — reduz tokens preservando contexto estrutural
- **Self-Healing Build**: falha Maven → captura erro exato → novo ciclo de correção com `_categorize_build_error`
- **Dependency Context Injection**: assinaturas das classes dependentes (incluindo constantes de enum) injetadas no prompt via `java/context.py`

---

## Hierarquia de Modelos

| Papel | Tamanho | Responsabilidade |
|-------|---------|-----------------|
| Ultimate | 14B+ | SOLID, arquitetura, revisão crítica |
| Advanced | 9B | Clean code, lógica de negócio |
| Standard | 7B | Estrutura, nomenclatura |
| Light | 4B | Javadoc, `final` |

```bash
ollama pull qwen2.5-coder:14b   # Ultimate — revisão crítica e SOLID
ollama pull gemma4:latest        # Advanced — clean code e geração de testes
ollama pull qwen2.5-coder:7b    # Standard — estrutura
```

---

## Requisitos

- **Ollama** rodando localmente
- **Python 3.12+**
- **Maven** (validação de build)
- **Java 22** via SDKMAN — `sdk use java 22-open` antes de qualquer comando Maven

## Configuração

```bash
git clone <repo>
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # editar conforme necessário
sdk use java 22-open
python main.py
```

### Parâmetros principais do `.env`

#### Modelos Ollama

| Parâmetro | Padrão | Descrição |
|-----------|--------|-----------|
| `MODEL_DOC` | `neural-chat:7b` | Leve — Javadoc e `final` |
| `MODEL_STRUCT` | `qwen2.5-coder:7b` | Padrão — estrutura e nomenclatura |
| `MODEL_CLEAN` | `gemma4:latest` | Avançado — clean code e testes |
| `MODEL_SOLID` | `qwen2.5-coder:14b` | Ultimate — SOLID e revisão crítica |
| `MODEL_RECOVERY` | `gemma4:latest` | Autocura — repair loop |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Endereço do Ollama |

#### Modo de execução

| Parâmetro | Valores | Padrão | Descrição |
|-----------|---------|--------|-----------|
| `USE_AGENT_MODE` | `true/false` | `false` | `true` = agent loop agêntico; `false` = pipeline fixo 01→14 |
| `PLANNER_MODE` | `local/claude` | `local` | Quem planeja: `local` = MODEL_SOLID; `claude` = Claude API |
| `USE_CLAUDE_FALLBACK` | `true/false` | `false` | Permite Claude escrever Java como fallback (independe do PLANNER_MODE) |
| `AGENT_MAX_CYCLES` | inteiro | `20` | Máximo de ciclos do agent loop |

#### Skills de performance (opt-in)

| Parâmetro | Padrão | Descrição |
|-----------|--------|-----------|
| `USE_LLMLINGUA` | `false` | Comprime `dep_context` (nunca o código-fonte) |
| `USE_RAG_CONTEXT` | `false` | LlamaIndex + ChromaDB para contexto semântico |
| `USE_MEM0` | `false` | Memória semântica entre runs |
| `USE_CONTEXT7` | `false` | Docs ao vivo de bibliotecas via Context7 MCP |

#### Modos de operação

```
Pipeline fixo (padrão):
  USE_AGENT_MODE=false
  USE_CLAUDE_FALLBACK=false

Agent loop totalmente local:
  USE_AGENT_MODE=true
  PLANNER_MODE=local
  USE_CLAUDE_FALLBACK=false

Híbrido (Claude planeja, Ollama executa):
  USE_AGENT_MODE=true
  PLANNER_MODE=claude
  USE_CLAUDE_FALLBACK=false
  ANTHROPIC_API_KEY=sk-ant-...
```

---

## Estrutura do Projeto

```
ai/               # Prompts, roteamento de modelos, compressão, Context7
java/
  method_extractor.py   # Extrai MethodDef (signature, body, linhas) sem AST
  class_builder.py      # compress / merge / build_method_context
  method_runner.py      # Runner método a método e classe comprimida
  llm_runner.py         # Dispatch e loop file-level; _is_structural_type()
  flow_runner.py        # Refatoração por fluxo de endpoint; DRY check
  flow_mapper.py        # Análise estática de endpoint chains
  community_runner.py   # Executa OpenRewrite / GJF / PMD
  llm_reviewer.py       # Revisa diff → APPROVE/REJECT/SKIP
  refactor.py           # Geração de testes TDD + repair loop
phases/
  configs/      # 14 arquivos .yml — um por fase
agent/          # Loop agêntico (planner + observation + executor)
core/           # Logger, utilitários, load_skill(), ExecutionLogger
memory/         # Cache de fases e métodos
dashboard/      # data.py → dashboard_status.json (10s)
logs/           # execution.log, execution.jsonl, live_state.json
~/.claude/skills/
  java-tdd-unit-test/     # Governa geração de testes (AUDIT_COVERAGE)
  java-guard-clauses/     # Fase 09 — early return
  java-method-extraction/ # Fase 10 — helpers privados
  java-solid-dip/         # Fase 11 — injeção por construtor
  java-controller-lean/   # Fase 12 — SRP no controller
  java-flow-refactor/     # Fase 13 — refatoração por cadeia de endpoint
  java-dry-extraction/    # Fase 14 — extração DRY para XyzUtils
```

---

## Como Usar

```bash
sdk use java 22-open
source .venv/bin/activate
python main.py
```

O agente solicita URL ou caminho local do repositório, cria branch `refactor/ai-<timestamp>`, executa todas as fases e faz commit ao final.

> Todo Maven é executado com `sdk use java 22-open` via `ENV_WRAPPER` em `java/compiler.py`.

---

Desenvolvido para ser o braço direito do desenvolvedor Java que busca excelência e privacidade total.
