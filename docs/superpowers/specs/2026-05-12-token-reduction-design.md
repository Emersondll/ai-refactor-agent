# Design: Cache Layer + Prompt Decomposition (Opção B)

**Data:** 2026-05-12  
**Status:** Aprovado  
**Objetivo:** Reduzir 55–65% do consumo de tokens do agente sem reduzir qualidade de refatoração  
**Escopo:** Projetos Java de 50–200 arquivos rodando via Ollama local

---

## Contexto

O agente atual sofre com alto consumo de tokens por três razões principais:

1. `_polish_result()` em `model.py` dobra o consumo na maioria das chamadas bem-sucedidas (toda chamada não-ultimate dispara uma segunda chamada ao modelo 14B)
2. `get_dependency_context()` em `java/context.py` executa `os.walk()` completo do projeto por arquivo por fase, sem nenhum cache (1200 walks para 100 arquivos × 12 fases)
3. Prompts contêm ~400 tokens de constantes idênticas repetidas em toda chamada, e as fases `.md` repetem regras já presentes no template base

Não há detecção de mudança entre fases: arquivos não alterados são reprocessados por todas as fases subsequentes.

---

## Arquitetura Alvo

```
ai-refactor-agent/
├── memory/                         ← NOVO módulo
│   ├── __init__.py
│   ├── cache.py                    # Motor de cache: hash → JSON em disco
│   ├── summaries.py                # Lê/grava class summaries
│   └── project_dict.py             # Singleton do project dictionary
│
├── ai/
│   ├── prompt.py                   # MODIFICADO: BASE_CONSTRAINTS + build_prompt()
│   └── model.py                    # MODIFICADO: _polish_result() condicional
│
├── java/
│   ├── context.py                  # MODIFICADO: cache-first, fallback p/ geração
│   └── refactor.py                 # MODIFICADO: skip por hash, injeta cache
│
├── phases/
│   ├── _base_rules.md              ← NOVO: regras globais (lidas uma vez por run)
│   └── {categoria}/*.md            # Apenas delta por fase (mais curtos)
│
└── .refactor_cache/                ← GERADO em runtime (no .gitignore)
    └── {repo_hash}/
        ├── dict.json               # Project dictionary persistido
        └── classes/
            └── {file_hash}.json    # Summary + dep_context compacto por arquivo
```

### Componentes inalterados

`scope_reducer.py`, `validator.py`, `compiler.py`, `flow.py`, `impact.py`, `agent_router.py`, `sanitizer.py` (java/), toda lógica de rollback/revert, `call_ai_with_correction()`, estrutura principal do `main.py`.

---

## Componente 1: `memory/cache.py`

**Responsabilidade:** Persistir e recuperar entradas de cache indexadas por hash de conteúdo de arquivo.

**Chave de cache:** `sha256(file_content.encode()).hexdigest()[:12]` — determinística, sem dependência de path ou timestamp.

**`repo_hash`** (nome do diretório raiz do cache): `sha256(os.path.abspath(repo_path).encode()).hexdigest()[:8]`

**Função helper compartilhada** (em `memory/cache.py`, importada onde necessário):
```python
import hashlib

def _sha(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:12]
```

**Schema do entry em disco** (`.refactor_cache/{repo_hash}/classes/{file_hash}.json`):

```json
{
  "file_path": "src/main/java/com/ex/CustomerService.java",
  "file_hash": "a3f9c12b4e8d",
  "class_name": "CustomerService",
  "dep_context": "// SUGGESTED IMPORT: ...\n// Class: ...",
  "processed_phases": ["01_javadoc", "04_nomenclature"],
  "last_output_hash": "b7e2a09f",
  "generated_at": "2026-05-12T14:30:00"
}
```

**API pública:**

```python
class Cache:
    def __init__(self, repo_path: str): ...

    # Entradas por arquivo (summary + fases)
    def get(self, file_path: str) -> dict | None: ...
    def set(self, file_path: str, data: dict) -> None: ...

    # Dep context indexado por file_hash
    def get_dep_context(self, file_hash: str) -> str | None: ...
    def set_dep_context(self, file_hash: str, context: str) -> None: ...

    # Controle de fases por arquivo
    def mark_phase_done(self, file_path: str, phase_name: str,
                        output_hash: str) -> None: ...
    def is_phase_done(self, file_path: str, phase_name: str,
                      current_hash: str) -> bool: ...

    # Project dictionary persistido
    def load_dict(self) -> str | None: ...
    def save_dict(self, content: str) -> None: ...
```

**`is_phase_done` logic:** Retorna `True` apenas se `phase_name` está em `processed_phases` E o hash do conteúdo atual do arquivo bate com o `last_output_hash` gravado. Isso garante que arquivos revertidos (rollback) não sejam considerados processados.

---

## Componente 2: `memory/project_dict.py`

**Responsabilidade:** Singleton do project dictionary — construído uma vez por run, persistido em disco entre runs do mesmo repo.

```python
_DICT_CACHE: str | None = None

def get_project_dictionary(repo_path: str, cache: Cache) -> str:
    global _DICT_CACHE
    if _DICT_CACHE is not None:
        return _DICT_CACHE
    # Tenta ler do disco
    persisted = cache.load_dict()
    if persisted:
        _DICT_CACHE = persisted
        return _DICT_CACHE
    # Gera e persiste
    _DICT_CACHE = _build_dict(repo_path)
    cache.save_dict(_DICT_CACHE)
    return _DICT_CACHE

def reset():
    global _DICT_CACHE
    _DICT_CACHE = None
```

`reset()` é chamado em `main.py` ao iniciar nova run (novo repo ou nova execução).

---

## Componente 3: `ai/prompt.py` — BASE + PHASE_DELTA

**Problema:** ~400 tokens de constantes (constraints, output format, example) repetidos em toda chamada.

**Solução:** Separar em constante global + função de composição.

```python
BASE_CONSTRAINTS = """\
You are a senior Java engineer.

### TECHNICAL CONSTRAINTS (MANDATORY)
PRESERVE the package declaration exactly as-is.
PRESERVE all existing import statements.
ADD import statements for any NEW type you introduce in the code.
  Check [DEPENDENCY CONTEXT] for '// SUGGESTED IMPORT' hints.
PRESERVE method signatures (name, parameters, return type).
PRESERVE class-level annotations.
DO NOT introduce external dependencies not already in the project.
DO NOT modify Spring Boot main class structure.

### OUTPUT FORMAT (MANDATORY)
Return ONLY the complete Java source file.
Return exactly ONE code block in ```java format.
NO explanations, NO markdown outside the code block.
NO ANSI or invisible characters.\
"""

def build_prompt(code: str, phase_delta: str, mode: str,
                 file_name: str, dep_context: str = "") -> str:
    task = _build_task(mode, file_name)
    parts = [
        BASE_CONSTRAINTS,
        f"\n### PHASE RULES\n{phase_delta.strip()}",
        f"\n### TASK\n{task}",
    ]
    if dep_context:
        parts.append(f"\n### DEPENDENCY CONTEXT\n{dep_context}")
    parts.append(f"\n### SOURCE FILE TO PROCESS\n```java\n{code}\n```")
    return "\n".join(parts)
```

O exemplo de output Java é **removido** — modelos 7B/14B treinados em Java já conhecem o formato ```` ```java ``` ````. O exemplo adicionava ~80 tokens sem ganho mensurável.

### Phase files: BASE_RULES + DELTA

Arquivo novo: `phases/_base_rules.md` — contém regras que se repetem em todas as fases (não criar novas classes, não alterar assinaturas públicas, não modificar testes, etc.). Carregado uma vez por run em `main.py`.

Cada `.md` de fase existente é reduzido para conter apenas:
- Objetivo específico da fase
- Regras exclusivas
- Exemplos BEFORE/AFTER apenas se estritamente necessários para a fase

Meta: cada fase de 200–300 tokens reduzida para 80–150 tokens.

---

## Componente 4: `java/context.py` — Cache-First

**Problema:** `get_dependency_context()` faz project walk completo por arquivo por fase.

**Solução:** Cache-first com fallback para geração.

```python
def get_dependency_context(file_code: str, repo_path: str,
                           cache: Cache) -> str:
    file_hash = _sha(file_code)
    cached = cache.get_dep_context(file_hash)
    if cached is not None:
        return cached
    context = _build_dep_context(file_code, repo_path)
    cache.set_dep_context(file_hash, context)
    return context
```

Adicionalmente, `_extract_simplified_header()` é otimizado: remove campos privados, comentários internos, mantém apenas assinaturas de métodos públicos/protegidos. Reduz dep_context de ~400 tokens por dependência para ~80–120 tokens.

---

## Componente 5: `model.py` — `_polish_result()` Condicional

**Problema:** Toda chamada não-ultimate dispara segunda chamada ao modelo 14B.

**Solução:** Polimento apenas em fases estruturalmente críticas.

```python
PHASES_REQUIRING_POLISH = {"07_solid", "08_architecture", "09_patterns"}

# Em _run_pipeline():
phase_name = phase.split("/")[-1].replace(".md", "")
needs_polish = agent != "ultimate" and phase_name in PHASES_REQUIRING_POLISH
if needs_polish and MODEL_SOLID not in _OOM_MODELS:
    result = _polish_result(result, prompt, MODEL_SOLID)
```

Fases de documentação (01–03), nomenclatura (04–06), clean code (10) e testes (11–12) são determinísticas — não requerem revisão crítica do modelo pesado.

---

## Componente 6: `java/refactor.py` — Skip por Fase

**Problema:** Fases subsequentes reprocessam arquivos que não foram modificados.

**Solução:** Checar cache antes de cada processamento.

```python
def refactor_file(file: str, rules: str, repo_path: str, phase: str,
                  reporter: PhaseReporter,
                  exec_logger: ExecutionLogger | None = None,
                  cache: Cache | None = None) -> bool:
    file_name = os.path.basename(file)
    original = read_file(file)

    if cache:
        phase_name = phase.split("/")[-1].replace(".md", "")
        current_hash = _sha(original)
        if cache.is_phase_done(file, phase_name, current_hash):
            log(f"  {file_name}: cache hit — fase {phase_name} já aplicada", "OK")
            reporter.record_skipped(phase, file_name, "cache hit")
            return False  # sem mudança necessária

    # ... resto do fluxo inalterado
```

Após aceitação (build ok), `cache.mark_phase_done(file, phase_name, sha(new_code))` é chamado.

---

## Integração em `main.py`

Apenas 4 linhas novas na inicialização:

```python
from memory.cache import Cache
from memory.project_dict import reset as reset_dict

# Logo após definir repo_path:
cache = Cache(repo_path)
reset_dict()
```

O objeto `cache` é passado para `refactor_file()` e `get_dependency_context()`.

---

## `.gitignore`

Adicionar:
```
.refactor_cache/
```

---

## Estimativa de Redução de Tokens

| Otimização | Redução estimada |
|---|---|
| `_polish_result()` condicional | ~35–40% |
| Dep context cache + formato compacto | ~15–20% |
| Skip de arquivos por fase | ~10–15% |
| Phase delta (fases mais curtas) | ~8–12% |
| Project dictionary singleton | ~3–5% |
| **Total combinado** | **~55–65%** |

---

## Critérios de Sucesso

- Build do projeto Java alvo continua passando após refatoração
- Nenhum arquivo novo de dependência quebrado
- Logs mostram "cache hit" em fases subsequentes para arquivos não modificados
- Redução mensurável de chamadas ao modelo (contável via logs)
- `_polish_result()` chamado apenas nas fases 07, 08, 09

---

## Fora do Escopo

- Embeddings / busca vetorial
- SQLite ou banco de dados
- Reescrita do pipeline principal (SCAN → REDUCE → SUMMARIZE → PLAN → REFACTOR → VALIDATE)
- Alteração de `scope_reducer.py`, `validator.py`, `compiler.py`
- Interface nova ou CLI nova
