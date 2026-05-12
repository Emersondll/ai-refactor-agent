# Token Reduction — Cache Layer + Prompt Decomposition

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduzir 55–65% do consumo de tokens adicionando cache de dep context por hash de arquivo, skip de fase por run, prompt decomposition (BASE_CONSTRAINTS + phase delta) e polimento condicional por fase.

**Architecture:** Novo módulo `memory/cache.py` com `Cache` class (dep context em disco por hash, phase tracking em memória por run, project dict em memória + disco). `ai/prompt.py` refatorado com `BASE_CONSTRAINTS` como constante + `build_prompt()` recebendo `dep_context` separado. `_polish_result()` em `model.py` condicionado ao conjunto `{07_solid, 08_architecture, 09_patterns}`. `java/context.py` e `java/refactor.py` injetados com o objeto `Cache`. `main.py` corrigido (bug de carregamento recursivo de fases + bug de ordem de argumentos) e integrado ao `Cache`.

**Tech Stack:** Python 3.12, hashlib (stdlib), json (stdlib), os (stdlib), pytest (dev)

---

## Mapa de Arquivos

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `memory/__init__.py` | Criar | Torna `memory` um pacote |
| `memory/cache.py` | Criar | Motor central de cache (disco + memória) |
| `tests/__init__.py` | Criar | Torna `tests` um pacote |
| `tests/memory/__init__.py` | Criar | Sub-pacote de testes |
| `tests/memory/test_cache.py` | Criar | Testes do Cache |
| `tests/ai/__init__.py` | Criar | Sub-pacote de testes |
| `tests/ai/test_prompt.py` | Criar | Testes do prompt.py |
| `tests/java/__init__.py` | Criar | Sub-pacote de testes |
| `tests/java/test_context.py` | Criar | Testes do context.py |
| `ai/prompt.py` | Modificar | BASE_CONSTRAINTS + dep_context param |
| `ai/model.py` | Modificar | _polish_result() condicional + dep_context param |
| `java/context.py` | Modificar | Cache-first + header compacto |
| `java/refactor.py` | Modificar | Phase skip + cache propagation |
| `phases/solid/07_solid.md` | Modificar | Remover regras duplicadas |
| `phases/solid/08_architecture.md` | Modificar | Remover regras duplicadas |
| `phases/solid/09_patterns.md` | Modificar | Remover regras duplicadas |
| `phases/clean/10_clean_code.md` | Modificar | Remover regras duplicadas |
| `phases/doc/01_javadoc.md` | Modificar | Remover regras duplicadas |
| `phases/struct/04_nomenclature.md` | Modificar | Remover regras duplicadas |
| `main.py` | Modificar | Fix 2 bugs + integrar Cache |
| `.gitignore` | Modificar | Adicionar `.refactor_cache/` |

---

## Task 1: `memory/cache.py` — Motor Central de Cache

**Files:**
- Create: `memory/__init__.py`
- Create: `memory/cache.py`
- Create: `tests/__init__.py`
- Create: `tests/memory/__init__.py`
- Create: `tests/memory/test_cache.py`

- [ ] **Step 1.1: Instalar pytest**

```bash
pip install pytest
```

Expected: `Successfully installed pytest-X.X.X`

- [ ] **Step 1.2: Criar estrutura de diretórios**

```bash
mkdir -p memory tests/memory tests/ai tests/java
touch memory/__init__.py tests/__init__.py tests/memory/__init__.py tests/ai/__init__.py tests/java/__init__.py
```

- [ ] **Step 1.3: Escrever os testes de `Cache` (TDD — devem FALHAR agora)**

Criar `tests/memory/test_cache.py`:

```python
import os
import pytest
from memory.cache import Cache, sha12


# --- sha12 ---

def test_sha12_returns_12_char_hex():
    result = sha12("some content")
    assert len(result) == 12
    assert all(c in "0123456789abcdef" for c in result)

def test_sha12_deterministic():
    assert sha12("abc") == sha12("abc")

def test_sha12_different_inputs_differ():
    assert sha12("abc") != sha12("xyz")


# --- dep_context ---

def test_dep_context_miss_returns_none(tmp_path):
    c = Cache(str(tmp_path))
    assert c.get_dep_context("nonexistent") is None

def test_dep_context_round_trip(tmp_path):
    c = Cache(str(tmp_path))
    c.set_dep_context("abc123", "// some context")
    assert c.get_dep_context("abc123") == "// some context"

def test_dep_context_persists_across_instances(tmp_path):
    Cache(str(tmp_path)).set_dep_context("abc123", "// persisted")
    assert Cache(str(tmp_path)).get_dep_context("abc123") == "// persisted"

def test_dep_context_empty_string_round_trip(tmp_path):
    c = Cache(str(tmp_path))
    c.set_dep_context("empty", "")
    assert c.get_dep_context("empty") == ""


# --- phase tracking ---

def test_phase_done_false_initially(tmp_path):
    c = Cache(str(tmp_path))
    assert c.is_phase_done("/some/File.java", "01_javadoc") is False

def test_phase_done_after_mark(tmp_path):
    c = Cache(str(tmp_path))
    c.mark_phase_done("/some/File.java", "01_javadoc")
    assert c.is_phase_done("/some/File.java", "01_javadoc") is True

def test_phase_done_other_phase_still_false(tmp_path):
    c = Cache(str(tmp_path))
    c.mark_phase_done("/some/File.java", "01_javadoc")
    assert c.is_phase_done("/some/File.java", "04_nomenclature") is False

def test_phase_done_other_file_still_false(tmp_path):
    c = Cache(str(tmp_path))
    c.mark_phase_done("/some/FileA.java", "01_javadoc")
    assert c.is_phase_done("/some/FileB.java", "01_javadoc") is False

def test_phase_tracking_is_per_run(tmp_path):
    # Nova instância = memória zerada
    Cache(str(tmp_path)).mark_phase_done("/some/File.java", "01_javadoc")
    assert Cache(str(tmp_path)).is_phase_done("/some/File.java", "01_javadoc") is False


# --- project dict ---

def test_project_dict_miss_returns_none(tmp_path):
    assert Cache(str(tmp_path)).get_project_dict() is None

def test_project_dict_round_trip(tmp_path):
    c = Cache(str(tmp_path))
    c.set_project_dict("- CustomerService (com.ex.CustomerService)")
    assert c.get_project_dict() == "- CustomerService (com.ex.CustomerService)"

def test_project_dict_in_memory_after_set(tmp_path):
    c = Cache(str(tmp_path))
    c.set_project_dict("- MyClass")
    # Segunda chamada na mesma instância usa in-memory (sem disk hit)
    assert c.get_project_dict() == "- MyClass"

def test_project_dict_persists_across_instances(tmp_path):
    Cache(str(tmp_path)).set_project_dict("- MyClass (com.ex.MyClass)")
    assert Cache(str(tmp_path)).get_project_dict() == "- MyClass (com.ex.MyClass)"
```

- [ ] **Step 1.4: Rodar testes para confirmar FALHA**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent"
python -m pytest tests/memory/test_cache.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'memory.cache'`

- [ ] **Step 1.5: Implementar `memory/cache.py`**

```python
"""
memory/cache.py — Motor de cache para redução de tokens.

Dep context: persiste em disco por hash do conteúdo do arquivo.
Phase tracking: em memória por run (zerado a cada nova instância).
Project dict: em memória + disco para reutilização entre runs.
"""

import hashlib
import os
from typing import Optional


def sha12(content: str) -> str:
    """Hash SHA-256 truncado em 12 chars — usado como chave de cache."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


class Cache:
    def __init__(self, repo_path: str):
        repo_abs = os.path.abspath(repo_path)
        repo_key = hashlib.sha256(repo_abs.encode()).hexdigest()[:8]
        self._base = os.path.join(repo_abs, ".refactor_cache", repo_key)
        self._dep_dir = os.path.join(self._base, "dep_ctx")
        os.makedirs(self._dep_dir, exist_ok=True)

        # In-memory: zerado a cada run (nova instância)
        self._phase_done: dict[str, set[str]] = {}
        self._project_dict: Optional[str] = None

    # --- Dep context (disco, keyed by file content hash) ---

    def get_dep_context(self, file_hash: str) -> Optional[str]:
        path = os.path.join(self._dep_dir, f"{file_hash}.txt")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return f.read()
            except OSError:
                return None
        return None

    def set_dep_context(self, file_hash: str, context: str) -> None:
        path = os.path.join(self._dep_dir, f"{file_hash}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(context)

    # --- Phase tracking (in-memory por run) ---

    def is_phase_done(self, file_path: str, phase_name: str) -> bool:
        return phase_name in self._phase_done.get(file_path, set())

    def mark_phase_done(self, file_path: str, phase_name: str) -> None:
        self._phase_done.setdefault(file_path, set()).add(phase_name)

    # --- Project dictionary (in-memory + disco) ---

    def get_project_dict(self) -> Optional[str]:
        if self._project_dict is not None:
            return self._project_dict
        path = os.path.join(self._base, "dict.txt")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self._project_dict = f.read()
            except OSError:
                pass
        return self._project_dict

    def set_project_dict(self, content: str) -> None:
        self._project_dict = content
        path = os.path.join(self._base, "dict.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError:
            pass
```

- [ ] **Step 1.6: Rodar testes para confirmar PASS**

```bash
python -m pytest tests/memory/test_cache.py -v
```

Expected: `17 passed`

- [ ] **Step 1.7: Commit**

```bash
git add memory/__init__.py memory/cache.py tests/__init__.py tests/memory/__init__.py tests/memory/test_cache.py tests/ai/__init__.py tests/java/__init__.py
git commit -m "feat: add memory/cache.py — dep context + phase tracking + project dict"
```

---

## Task 2: `ai/prompt.py` — BASE_CONSTRAINTS + dep_context separado

**Files:**
- Modify: `ai/prompt.py`
- Create: `tests/ai/test_prompt.py`

- [ ] **Step 2.1: Escrever testes (TDD — devem FALHAR antes da mudança)**

Criar `tests/ai/test_prompt.py`:

```python
from ai.prompt import build_prompt, BASE_CONSTRAINTS


def test_base_constraints_is_string():
    assert isinstance(BASE_CONSTRAINTS, str)
    assert len(BASE_CONSTRAINTS) > 0

def test_base_constraints_in_every_prompt():
    prompt = build_prompt("public class A {}", "# Rule\n- Do X", "refactor", "A.java")
    assert "PRESERVE the package declaration" in prompt
    assert "TECHNICAL CONSTRAINTS" in prompt

def test_no_java_example_block_in_prompt():
    prompt = build_prompt("public class A {}", "# Rule\n- Do X", "refactor", "A.java")
    # Exemplo Java foi removido — apenas o SOURCE FILE to process deve ter ```java
    count = prompt.count("```java")
    assert count == 1, f"Esperado 1 bloco java (source), mas encontrou {count}"

def test_phase_delta_appears_in_prompt():
    prompt = build_prompt("public class A {}", "# SOLID\n- Apply DIP", "refactor", "A.java")
    assert "Apply DIP" in prompt

def test_dep_context_included_when_provided():
    dep = "// SUGGESTED IMPORT: import com.ex.Service;\n// Class: com.ex.Service"
    prompt = build_prompt("public class A {}", "# Rule", "refactor", "A.java", dep_context=dep)
    assert "DEPENDENCY CONTEXT" in prompt
    assert "SUGGESTED IMPORT" in prompt

def test_dep_context_absent_when_empty():
    prompt = build_prompt("public class A {}", "# Rule", "refactor", "A.java", dep_context="")
    assert "DEPENDENCY CONTEXT" not in prompt

def test_test_mode_task_different_from_refactor():
    p_refactor = build_prompt("public class A {}", "# Rule", "refactor", "A.java")
    p_test = build_prompt("public class A {}", "# Rule", "test", "A.java")
    assert "testes unitários" in p_test or "JUnit" in p_test
    assert p_refactor != p_test

def test_source_file_appears_at_end():
    code = "public class MyClass { }"
    prompt = build_prompt(code, "# Rule", "refactor", "MyClass.java")
    assert prompt.endswith("```") or code in prompt
    assert prompt.index("SOURCE FILE") > prompt.index("PHASE RULES")
```

- [ ] **Step 2.2: Rodar testes para confirmar FALHA**

```bash
python -m pytest tests/ai/test_prompt.py -v 2>&1 | head -30
```

Expected: vários FAILED (BASE_CONSTRAINTS não existe, dep_context não existe)

- [ ] **Step 2.3: Substituir `ai/prompt.py` inteiro**

```python
"""
prompt.py — ai/prompt.py

BASE_CONSTRAINTS: constante global com regras técnicas e formato de output.
  Enviada em toda chamada — não modifique para não quebrar o output format.

build_prompt(): compõe BASE_CONSTRAINTS + phase delta + dep_context separado.
  dep_context é colocado em sua própria seção para ser facilmente identificável.
"""


BASE_CONSTRAINTS = """\
You are a senior Java engineer.

### TECHNICAL CONSTRAINTS (MANDATORY)
PRESERVE the package declaration exactly as-is.
PRESERVE all existing import statements.
ADD import statements for any NEW type you introduce in the code.
  Check [DEPENDENCY CONTEXT] below for '// SUGGESTED IMPORT' hints.
PRESERVE method signatures (name, parameters, return type).
PRESERVE class-level annotations.
DO NOT create new classes — work within the existing file only.
DO NOT introduce external dependencies not already in the project.
DO NOT modify Spring Boot main class structure.
DO NOT change public API or method signatures.
DO NOT modify existing test code.

### OUTPUT FORMAT (MANDATORY)
Return ONLY the complete Java source file.
Return exactly ONE code block in ```java format.
NO explanations, NO markdown outside the code block.
NO ANSI or invisible characters.\
"""


def _build_task(mode: str, file_name: str) -> str:
    if mode == "test":
        return (
            f"Escreva testes unitários abrangentes com JUnit 5 + Mockito para a classe '{file_name}'.\n"
            "DIRETRIZES TÉCNICAS:\n"
            "1. PACOTE: Use exatamente o mesmo pacote da classe original.\n"
            "2. IMPORTS: Importe explicitamente Mockito (@Mock, @InjectMocks, Mockito.when), "
            "JUnit 5 (@Test, @BeforeEach, Assertions) e TODAS as dependências.\n"
            "3. MOCKS: Use @InjectMocks na classe sendo testada e @Mock em suas dependências.\n"
            "4. INTEGRIDADE: Verifique as assinaturas da classe original. "
            "Não chame métodos inexistentes.\n"
            "5. COBERTURA: Inclua 'happy path', casos de borda e cenários de erro/exceção.\n"
            "6. JAVA RECORDS: Se encontrar 'record', use o construtor canônico (com todos os argumentos).\n"
            "7. FIDELIDADE: Teste apenas o que o código faz atualmente."
        )
    return (
        f"Refactor {file_name} applying the rules below.\n"
        "Preserve existing behavior. Apply only the rules relevant to this file."
    )


def build_prompt(code: str, phase_delta: str, mode: str, file_name: str,
                 dep_context: str = "") -> str:
    """
    Monta o prompt completo para o modelo.

    Args:
        code: Código Java do arquivo a processar.
        phase_delta: Regras específicas da fase (apenas o que é exclusivo).
        mode: 'refactor' ou 'test'.
        file_name: Nome do arquivo Java (ex: CustomerService.java).
        dep_context: Contexto de dependências compacto (opcional).
    """
    parts = [
        BASE_CONSTRAINTS,
        f"\n### PHASE RULES\n{phase_delta.strip()}",
        f"\n### TASK\n{_build_task(mode, file_name)}",
    ]
    if dep_context and dep_context.strip():
        parts.append(f"\n### DEPENDENCY CONTEXT\n{dep_context.strip()}")
    parts.append(f"\n### SOURCE FILE TO PROCESS\n```java\n{code}\n```")
    return "\n".join(parts)
```

- [ ] **Step 2.4: Rodar testes para confirmar PASS**

```bash
python -m pytest tests/ai/test_prompt.py -v
```

Expected: `8 passed`

- [ ] **Step 2.5: Commit**

```bash
git add ai/prompt.py tests/ai/test_prompt.py
git commit -m "refactor: decompose prompt into BASE_CONSTRAINTS + phase delta, add dep_context param"
```

---

## Task 3: `ai/model.py` — `_polish_result()` Condicional + dep_context

**Files:**
- Modify: `ai/model.py`

> Não há testes de unidade para `_run_pipeline()` pois requer mocks profundos de Ollama.
> A verificação é feita por inspeção dos logs em execução real (Task 7).

- [ ] **Step 3.1: Adicionar `PHASES_REQUIRING_POLISH` e atualizar `_run_pipeline()`**

Localizar o bloco em `ai/model.py` que começa com `def _run_pipeline(` (linha ~211) e substituir:

```python
# Constante no topo do arquivo, após os imports:
PHASES_REQUIRING_POLISH: frozenset[str] = frozenset({
    "07_solid", "08_architecture", "09_patterns"
})
```

Dentro de `_run_pipeline()`, substituir:

```python
# ANTES (linha ~250):
if agent != "ultimate" and MODEL_SOLID and MODEL_SOLID not in _OOM_MODELS:
    log(f"  [Skill: Crítico] Solicitando revisão técnica para {MODEL_SOLID}...")
    result = _polish_result(result, prompt, MODEL_SOLID)
```

por:

```python
# DEPOIS:
phase_name = phase.split("/")[-1].replace(".md", "") if phase else ""
needs_polish = (
    agent != "ultimate"
    and phase_name in PHASES_REQUIRING_POLISH
    and MODEL_SOLID
    and MODEL_SOLID not in _OOM_MODELS
)
if needs_polish:
    log(f"  [Crítico] Revisando com {MODEL_SOLID} (fase estrutural: {phase_name})...")
    result = _polish_result(result, prompt, MODEL_SOLID)
```

- [ ] **Step 3.2: Atualizar `call_ai()` para aceitar e repassar `dep_context`**

Substituir a função `call_ai()` (linha ~299):

```python
# ANTES:
def call_ai(code: str, rules: str, mode: str, file_name: str,
            file_path: str = "", phase: str = "") -> str | None:
    """Entrada principal — gera código a partir das regras da fase."""
    prompt = build_prompt(code, rules, mode, file_name)
    return _run_pipeline(prompt, code, file_path, file_name, mode, phase)
```

por:

```python
# DEPOIS:
def call_ai(code: str, rules: str, mode: str, file_name: str,
            file_path: str = "", phase: str = "",
            dep_context: str = "") -> str | None:
    """Entrada principal — gera código a partir das regras da fase."""
    prompt = build_prompt(code, rules, mode, file_name, dep_context=dep_context)
    return _run_pipeline(prompt, code, file_path, file_name, mode, phase)
```

- [ ] **Step 3.3: Verificar que não quebrou imports**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent"
python -c "from ai.model import call_ai, PHASES_REQUIRING_POLISH; print('OK', PHASES_REQUIRING_POLISH)"
```

Expected: `OK frozenset({'07_solid', '08_architecture', '09_patterns'})`

- [ ] **Step 3.4: Rodar todos os testes acumulados**

```bash
python -m pytest tests/ -v
```

Expected: todos passando (os testes de Task 1 e Task 2 devem continuar PASS)

- [ ] **Step 3.5: Commit**

```bash
git add ai/model.py
git commit -m "refactor: make _polish_result() conditional on SOLID/Architecture phases only"
```

---

## Task 4: `java/context.py` — Cache-First + Header Compacto

**Files:**
- Modify: `java/context.py`
- Create: `tests/java/test_context.py`

- [ ] **Step 4.1: Escrever testes (TDD — devem FALHAR agora)**

Criar `tests/java/test_context.py`:

```python
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from memory.cache import Cache


def make_cache(tmp_path):
    return Cache(str(tmp_path))


# --- _extract_simplified_header ---

def test_header_includes_public_method_signature():
    from java.context import _extract_simplified_header
    code = """\
package com.ex;
public class MyService {
    private String name;
    public String getName() {
        return name;
    }
    private void helper() {}
}"""
    header = _extract_simplified_header(code, "com.ex.MyService")
    assert "getName()" in header
    assert "private String name" not in header    # campos privados excluídos
    assert "helper" not in header                 # métodos privados excluídos

def test_header_excludes_private_fields():
    from java.context import _extract_simplified_header
    code = """\
package com.ex;
public class OrderService {
    private final OrderRepository repo;
    private int count;
    public void save(Order o) { repo.save(o); }
}"""
    header = _extract_simplified_header(code, "com.ex.OrderService")
    assert "private final OrderRepository" not in header
    assert "private int count" not in header

def test_header_includes_class_declaration():
    from java.context import _extract_simplified_header
    code = "package com.ex;\npublic class Foo {\n    public void run() {}\n}"
    header = _extract_simplified_header(code, "com.ex.Foo")
    assert "class Foo" in header or "Foo" in header


# --- get_dependency_context cache behavior ---

def test_dep_context_cache_hit_avoids_rebuild(tmp_path):
    from java.context import get_dependency_context
    from memory.cache import sha12

    cache = make_cache(tmp_path)
    file_code = "package com.ex;\nimport com.ex.MyDep;\npublic class A {}"
    file_hash = sha12(file_code)

    # Pre-populate cache
    cached_value = "// CACHED CONTEXT"
    cache.set_dep_context(file_hash, cached_value)

    # get_dependency_context deve retornar o valor do cache SEM fazer os.walk
    with patch("java.context._build_dep_context") as mock_build:
        result = get_dependency_context(file_code, "/any/repo", cache=cache)
        mock_build.assert_not_called()
    assert result == cached_value

def test_dep_context_cache_miss_calls_build_and_stores(tmp_path):
    from java.context import get_dependency_context
    from memory.cache import sha12

    cache = make_cache(tmp_path)
    file_code = "package com.ex;\npublic class B {}"
    file_hash = sha12(file_code)

    with patch("java.context._build_dep_context", return_value="// BUILT") as mock_build:
        result = get_dependency_context(file_code, "/any/repo", cache=cache)
        mock_build.assert_called_once()

    assert result == "// BUILT"
    # Deve ter sido armazenado
    assert cache.get_dep_context(file_hash) == "// BUILT"

def test_dep_context_no_cache_calls_build_directly(tmp_path):
    from java.context import get_dependency_context

    with patch("java.context._build_dep_context", return_value="// NO CACHE") as mock_build:
        result = get_dependency_context("public class C {}", "/any/repo", cache=None)
        mock_build.assert_called_once()
    assert result == "// NO CACHE"
```

- [ ] **Step 4.2: Rodar testes para confirmar FALHA**

```bash
python -m pytest tests/java/test_context.py -v 2>&1 | head -20
```

Expected: FAILED — funções `_build_dep_context` e assinatura `cache=` não existem ainda

- [ ] **Step 4.3: Substituir `java/context.py` inteiro**

```python
"""
java/context.py — Localização: java/context.py

Cache-first: se dep_context para este arquivo já está em cache (por hash),
retorna imediatamente sem fazer os.walk no projeto.

_build_dep_context: lógica original de geração (renomeada de função interna).
_extract_simplified_header: otimizada para emitir apenas assinaturas
  de métodos públicos/protegidos — remove campos privados e comentários.
"""

import os
import re
from core.utils import read_file
from memory.cache import sha12


def get_dependency_context(file_code: str, repo_path: str,
                           cache=None) -> str:
    """
    Retorna contexto de dependências para o arquivo.
    Cache-first: usa hash do conteúdo do arquivo como chave.
    """
    if cache is not None:
        file_hash = sha12(file_code)
        cached = cache.get_dep_context(file_hash)
        if cached is not None:
            return cached

    context = _build_dep_context(file_code, repo_path)

    if cache is not None:
        cache.set_dep_context(sha12(file_code), context)

    return context


def _build_dep_context(file_code: str, repo_path: str) -> str:
    """Gera contexto de dependências varrendo o projeto (sem cache)."""
    package_match = re.search(r'^package\s+([\w.]+);', file_code, re.MULTILINE)
    target_package = package_match.group(1) if package_match else "unknown"

    all_potential_classes = re.findall(r'\b([A-Z]\w+)\b', file_code)
    imports = re.findall(r'^import\s+([\w.]+);', file_code, re.MULTILINE)
    short_imports = {imp.split('.')[-1]: imp for imp in imports}

    context_parts = [f"// TARGET_CLASS_PACKAGE: {target_package}"]
    processed_classes = set()

    for cls_name, full_imp in short_imports.items():
        if not full_imp.startswith("com."):
            continue
        processed_classes.add(cls_name)
        _add_context_for_class(full_imp, repo_path, context_parts)

    for cls_name in all_potential_classes:
        if cls_name in processed_classes or len(cls_name) < 3:
            continue
        if cls_name in {"String", "Long", "Integer", "BigDecimal", "List",
                        "Map", "Optional", "Set", "Boolean", "Double",
                        "Object", "Override", "Autowired", "Service",
                        "Repository", "Controller", "Entity", "Component"}:
            continue
        found_path = _find_class_file(cls_name, repo_path)
        if found_path:
            rel = os.path.relpath(found_path,
                                  os.path.join(repo_path, "src", "main", "java"))
            full_pkg = rel.replace("/", ".").replace(".java", "")
            _add_context_for_class(full_pkg, repo_path, context_parts)
            processed_classes.add(cls_name)

    if len(context_parts) <= 1:
        return ""

    return "\n--- DEPENDENCY CONTEXT (SIGNATURES) ---\n" + "\n".join(context_parts)


def _add_context_for_class(full_imp: str, repo_path: str,
                            context_parts: list) -> None:
    parts = full_imp.split('.')
    potential_path = os.path.join(repo_path, "src", "main", "java",
                                  *parts) + ".java"
    if os.path.exists(potential_path):
        dep_code = read_file(potential_path)
        header = _extract_simplified_header(dep_code, full_imp)
        context_parts.append(f"// SUGGESTED IMPORT: import {full_imp};")
        context_parts.append(header)


def _find_class_file(class_name: str, repo_path: str) -> str | None:
    main_java = os.path.join(repo_path, "src", "main", "java")
    for root, _, files in os.walk(main_java):
        if f"{class_name}.java" in files:
            return os.path.join(root, f"{class_name}.java")
    return None


def _extract_simplified_header(code: str, full_name: str) -> str:
    """
    Extrai apenas assinaturas de métodos públicos/protegidos.
    Remove: campos privados, comentários, imports, corpos de métodos.
    Objetivo: ~80-120 tokens por dependência (vs ~400 tokens antes).
    """
    lines = code.splitlines()
    header_lines = []
    class_def_found = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue
        if stripped.startswith(('//', '/*', '*', 'import ', 'package ')):
            if stripped.startswith('package '):
                header_lines.append(stripped)
            continue

        if any(kw in stripped for kw in ('class ', 'interface ', 'enum ', 'record ')):
            class_def_found = True
            decl = stripped.split('{')[0].strip()
            header_lines.append(decl + " {")
            continue

        if not class_def_found:
            continue

        # Apenas membros públicos/protegidos com parênteses (métodos)
        if ('public ' in stripped or 'protected ' in stripped) and '(' in stripped:
            signature = stripped.split('{')[0].strip()
            if not signature.endswith(';'):
                signature += ";"
            header_lines.append("    " + signature)

    header_lines.append("}")
    return f"// Class: {full_name}\n" + "\n".join(header_lines)
```

- [ ] **Step 4.4: Rodar testes para confirmar PASS**

```bash
python -m pytest tests/java/test_context.py -v
```

Expected: `9 passed`

- [ ] **Step 4.5: Rodar todos os testes acumulados**

```bash
python -m pytest tests/ -v
```

Expected: todos passando

- [ ] **Step 4.6: Commit**

```bash
git add java/context.py tests/java/test_context.py
git commit -m "refactor: cache-first dep context with compact header extraction"
```

---

## Task 5: `java/refactor.py` — Phase Skip + Cache Propagation

**Files:**
- Modify: `java/refactor.py`

> Testes de unidade para `refactor_file()` requerem mocks profundos de maven e IA.
> Verificação por execução real em Task 7 (integration test).

- [ ] **Step 5.1: Atualizar `_generate_and_validate()` para receber `cache` e passar `dep_context` separado**

Substituir a função `_generate_and_validate()` (começa na linha ~149):

```python
def _generate_and_validate(original: str, rules: str, mode: str,
                             file_name: str, file_path: str,
                             phase: str = "",
                             cache=None) -> tuple[str | None, str]:
    """
    Chama a IA e valida o resultado com injeção de contexto de dependências.
    dep_context é obtido do cache ou gerado, e passado separado para build_prompt.
    """
    from java.context import get_dependency_context

    dep_context = ""
    try:
        root = file_path
        while root != "/" and not os.path.exists(os.path.join(root, "pom.xml")):
            root = os.path.dirname(root)
        if os.path.exists(os.path.join(root, "pom.xml")):
            dep_context = get_dependency_context(original, root, cache=cache)
    except Exception:
        pass

    test_context = ""
    try:
        test_file = _test_path_for(file_path, root)
        if test_file and os.path.exists(test_file):
            from core.utils import read_file as _read
            test_code = _read(test_file)
            test_context = (
                "\n\n[CONTEXTO DE TESTE] O teste abaixo valida esta classe. "
                "Sua refatoração DEVE garantir que ele continue passando:\n\n"
                f"```java\n{test_code}\n```"
            )
            log("  [Contexto] Teste unitário injetado.", "OK")
    except Exception:
        pass

    phase_delta = rules + test_context

    new_code = call_ai(original, phase_delta, mode, file_name,
                       file_path=file_path, phase=phase,
                       dep_context=dep_context)

    if not new_code:
        return None, "IA não gerou código"

    valid, reason = is_valid_java(original, new_code)
    if valid:
        from java.validator import validate_class_name_matches_file
        is_name_ok, name_error = validate_class_name_matches_file(new_code, file_path)
        if is_name_ok:
            return new_code, ""
        reason = f"ERRO DE INTEGRIDADE: {name_error}"

    log(f"  Validator rejeitou: {reason} — tentando correção", "WARN")

    rejected_code = new_code
    for attempt in range(1, MAX_VALIDATOR_RETRIES + 1):
        log(f"  Correção validator {attempt}/{MAX_VALIDATOR_RETRIES}: {reason[:60]}")
        corrected = call_ai_with_correction(
            original=original, rules=phase_delta, mode=mode,
            file_name=file_name, file_path=file_path,
            bad_output=rejected_code, error_reason=reason, phase=phase
        )
        if not corrected:
            log(f"  Correção {attempt}: sem resposta", "WARN")
            break
        valid, reason = is_valid_java(original, corrected)
        if valid:
            from java.validator import validate_class_name_matches_file
            is_name_ok, name_error = validate_class_name_matches_file(corrected, file_path)
            if is_name_ok:
                log(f"  Correção {attempt}: aceita ✓", "OK")
                return corrected, ""
            reason = (f"ERRO DE INTEGRIDADE: {name_error}. "
                      f"O nome da classe deve ser '{file_name.replace('.java','')}'.")
        log(f"  Correção {attempt}: ainda rejeitado — {reason}", "WARN")
        rejected_code = corrected

    return None, reason
```

- [ ] **Step 5.2: Atualizar assinaturas de `_refactor_whole_file()` e `_refactor_by_method()`**

Em `_refactor_whole_file()`, mudar apenas a linha de assinatura e a chamada a `_generate_and_validate()`:

```python
# Assinatura: adicionar cache=None no final
def _refactor_whole_file(file: str, original: str, rules: str,
                          repo_path: str, phase: str,
                          reporter: PhaseReporter,
                          exec_logger: ExecutionLogger | None,
                          cache=None) -> bool:
    file_name = os.path.basename(file)
    mode = _mode_for(file)

    # Mudar esta chamada para incluir cache=cache
    new_code, reason = _generate_and_validate(
        original, rules, mode, file_name, file, phase=phase, cache=cache
    )
    # O RESTO DA FUNÇÃO (_refactor_whole_file) CONTINUA EXATAMENTE IGUAL
    # (validação, write_file, maven_test, _attempt_global_sync, etc.)
```

Em `_refactor_by_method()`, mudar apenas a assinatura e as chamadas a `_generate_and_validate()`:

```python
# Assinatura: adicionar cache=None no final
def _refactor_by_method(file: str, original: str, rules: str,
                         repo_path: str, phase: str,
                         reporter: PhaseReporter,
                         exec_logger: ExecutionLogger | None,
                         cache=None) -> bool:
    file_name = os.path.basename(file)
    mode = _mode_for(file)

    header = extract_class_header(original)
    methods = get_processable_methods(original)

    if not methods:
        log(f"  {file_name}: nenhum método extraível — tentando arquivo inteiro")
        return _refactor_whole_file(file, original, rules, repo_path, phase,
                                    reporter, exec_logger, cache=cache)

    log(f"  {file_name}: {len(methods)} métodos a processar")
    current_code = original
    methods_changed = 0
    methods_failed = 0

    for method in methods:
        log(f"    → {method.name}() [{len(method.full_text.splitlines())}L]")
        context = build_method_context(header, method)

        # Mudar esta chamada para incluir cache=cache
        ai_response, reason = _generate_and_validate(
            original=context, rules=rules, mode=mode,
            file_name=file_name, file_path=file,
            phase=phase, cache=cache,
        )
        # O RESTO DO LOOP (extract_refactored_method, replace_method_in_file, etc.)
        # CONTINUA EXATAMENTE IGUAL ao código original

    # O RESTANTE DA FUNÇÃO (_refactor_by_method) CONTINUA EXATAMENTE IGUAL
```

- [ ] **Step 5.3: Atualizar `refactor_file()` — phase skip + mark_phase_done**

Substituir a função `refactor_file()` completa:

```python
def refactor_file(file: str, rules: str, repo_path: str,
                  phase: str, reporter: PhaseReporter,
                  exec_logger: ExecutionLogger | None = None,
                  cache=None) -> bool:
    file_name = os.path.basename(file)

    # Phase skip: se já processamos este arquivo nesta fase neste run, pula
    if cache is not None:
        phase_name = phase.split("/")[-1].replace(".md", "")
        if cache.is_phase_done(file, phase_name):
            log(f"  {file_name}: cache hit — {phase_name} já aplicada neste run", "OK")
            reporter.record_skipped(phase, file_name, f"cache: {phase_name} já aplicada")
            return False

    log(f"Processando [{_mode_for(file)}]: {file_name}")

    if exec_logger:
        exec_logger.log_file_processing(phase, file_name, "unknown", "unknown")

    original = read_file(file)

    skip, reason = should_skip(file, original)
    if skip:
        log(f"  {file_name} PULADO: {reason}", "WARN")
        if exec_logger:
            exec_logger.log_file_skipped(phase, file_name, reason)
        reporter.record_skipped(phase, file_name, reason)
        return False

    if is_large_file(original, LARGE_FILE_THRESHOLD):
        log(f"  {file_name}: arquivo grande → processamento por método")
        success = _refactor_by_method(file, original, rules, repo_path, phase,
                                      reporter, exec_logger, cache=cache)
    else:
        success = _refactor_whole_file(file, original, rules, repo_path, phase,
                                       reporter, exec_logger, cache=cache)

    if success and cache is not None:
        phase_name = phase.split("/")[-1].replace(".md", "")
        cache.mark_phase_done(file, phase_name)

    return success
```

- [ ] **Step 5.4: Atualizar `build_project_dictionary` para usar cache**

Em `_refactor_whole_file()`, onde está a chamada `build_project_dictionary(repo_path)` (dentro do bloco "cannot find symbol"), substituir por:

```python
# ANTES:
from java.dictionary import build_project_dictionary
proj_map = build_project_dictionary(repo_path)

# DEPOIS:
from java.dictionary import build_project_dictionary
proj_map = None
if cache is not None:
    proj_map = cache.get_project_dict()
if proj_map is None:
    proj_map = build_project_dictionary(repo_path)
    if cache is not None:
        cache.set_project_dict(proj_map)
```

- [ ] **Step 5.5: Verificar que imports estão corretos**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent"
python -c "from java.refactor import refactor_file; print('OK')"
```

Expected: `OK`

- [ ] **Step 5.6: Rodar todos os testes**

```bash
python -m pytest tests/ -v
```

Expected: todos passando

- [ ] **Step 5.7: Commit**

```bash
git add java/refactor.py
git commit -m "refactor: add phase skip via Cache + separate dep_context from rules in refactor pipeline"
```

---

## Task 6: Phase Files — Remover Regras Duplicadas

**Files:**
- Modify: `phases/solid/07_solid.md`
- Modify: `phases/solid/08_architecture.md`
- Modify: `phases/solid/09_patterns.md`
- Modify: `phases/clean/10_clean_code.md`
- Modify: `phases/doc/01_javadoc.md`
- Modify: `phases/struct/04_nomenclature.md`

> As regras globais (não criar classes, preservar assinaturas, não modificar testes)
> foram movidas para `BASE_CONSTRAINTS` em `ai/prompt.py` — Task 2.
> Cada fase agora deve conter APENAS o que é exclusivo dela.

- [ ] **Step 6.1: Verificar `phases/solid/09_patterns.md` (arquivo não lido ainda)**

```bash
cat "/home/emerson/Área de trabalho/ai-refactor-agent/phases/solid/09_patterns.md"
cat "/home/emerson/Área de trabalho/ai-refactor-agent/phases/doc/02_final_keywords.md"
cat "/home/emerson/Área de trabalho/ai-refactor-agent/phases/doc/03_documentation.md"
cat "/home/emerson/Área de trabalho/ai-refactor-agent/phases/struct/05_structure.md"
cat "/home/emerson/Área de trabalho/ai-refactor-agent/phases/struct/06_tracking.md"
cat "/home/emerson/Área de trabalho/ai-refactor-agent/phases/claude/11_unit_tests.md"
cat "/home/emerson/Área de trabalho/ai-refactor-agent/phases/claude/12_integration_tests.md"
```

Ler o conteúdo de cada arquivo antes de editar.

- [ ] **Step 6.2: Remover de `phases/solid/07_solid.md` a linha final duplicada**

A última linha `"Do not change public API or method signatures."` está agora coberta por `BASE_CONSTRAINTS`. Remover essa linha do arquivo.

- [ ] **Step 6.3: Remover de `phases/solid/08_architecture.md` a linha final duplicada**

A última linha `"Do not change method signatures, return types, or existing test code."` está coberta por `BASE_CONSTRAINTS`. Remover.

- [ ] **Step 6.4: Remover de `phases/clean/10_clean_code.md` a linha final duplicada**

A última linha `"Do not change method signatures, return types, or public API."` está coberta por `BASE_CONSTRAINTS`. Remover.

- [ ] **Step 6.5: Remover de `phases/doc/01_javadoc.md` a linha duplicada**

A última linha `"Do not alter existing code — only add comments."` — manter, pois é específica do Javadoc (comportamento diferente das outras fases).

- [ ] **Step 6.6: Remover de `phases/struct/04_nomenclature.md` linhas duplicadas**

As linhas `"Do NOT rename: public API methods..."` e `"Do NOT rename identifiers in other files"` são específicas desta fase — manter. Verificar se há outras duplicadas.

- [ ] **Step 6.7: Commit das fases**

```bash
git add phases/
git commit -m "refactor: trim phase files — remove rules already in BASE_CONSTRAINTS"
```

---

## Task 7: `main.py` — Fix 2 Bugs + Integração do Cache

**Files:**
- Modify: `main.py`
- Modify: `.gitignore`

Esta task corrige dois bugs críticos que impedem o agente de funcionar:

- **Bug 1:** `os.listdir(PHASES_DIR)` retorna nomes de subdiretórios (`['doc', 'solid', ...]`), nenhum termina em `.md`, portanto `phases = []` e o loop nunca executa.
- **Bug 2:** `refactor_file(f_path, phase_file, rules, reporter, exec_logger)` — argumentos na ordem errada. A assinatura é `(file, rules, repo_path, phase, reporter, exec_logger)`.

- [ ] **Step 7.1: Adicionar `.refactor_cache/` ao `.gitignore`**

```bash
echo ".refactor_cache/" >> "/home/emerson/Área de trabalho/ai-refactor-agent/.gitignore"
```

- [ ] **Step 7.2: Substituir o bloco de import e a função `main()` em `main.py`**

Localizar e substituir o import do topo:

```python
# ANTES:
from git_utils.repo import clone_or_update, commit_and_push

# DEPOIS:
from git_utils.repo import clone_or_update, commit_and_push
from memory.cache import Cache
```

- [ ] **Step 7.3: Corrigir o carregamento de fases (Bug 1)**

Localizar (linha ~102):

```python
# ANTES (BUG — não recursivo):
phases = sorted([f for f in os.listdir(PHASES_DIR) if f.endswith(".md")])
for phase_file in phases:
    phase_path = os.path.join(PHASES_DIR, phase_file)
    rules = read_file(phase_path)
```

Substituir por:

```python
# DEPOIS (recursivo via os.walk):
phase_paths = []
for root, _, files in os.walk(PHASES_DIR):
    for f in sorted(files):
        if f.endswith(".md") and not f.startswith("_"):
            phase_paths.append(os.path.join(root, f))
phase_paths = sorted(phase_paths)  # garante ordem numérica global

for phase_path in phase_paths:
    phase_file = os.path.basename(phase_path)
    rules = read_file(phase_path)
```

- [ ] **Step 7.4: Inicializar o Cache e corrigir a chamada `refactor_file` (Bug 2)**

Logo após `repo_path` ser definido (linha ~72, após `log(f"Repositório: {repo_path}", "OK")`), adicionar:

```python
cache = Cache(repo_path)
```

Localizar o loop de fases e corrigir a chamada (Bug 2):

```python
# ANTES (BUG — argumentos fora de ordem):
for f_path in files:
    refactor_file(f_path, phase_file, rules, reporter, exec_logger)

# DEPOIS (ordem correta + cache injetado):
for f_path in files:
    refactor_file(f_path, rules, repo_path, phase_file,
                  reporter, exec_logger, cache=cache)
```

- [ ] **Step 7.5: Verificar imports do main.py**

```bash
cd "/home/emerson/Área de trabalho/ai-refactor-agent"
python -c "import main; print('imports OK')" 2>&1
```

Expected: `imports OK` (pode falhar por `input()` mas não por ImportError)

- [ ] **Step 7.6: Rodar todos os testes**

```bash
python -m pytest tests/ -v
```

Expected: todos passando

- [ ] **Step 7.7: Verificar que as fases são carregadas corretamente**

```bash
python -c "
import os
PHASES_DIR = 'phases'
phase_paths = []
for root, _, files in os.walk(PHASES_DIR):
    for f in sorted(files):
        if f.endswith('.md') and not f.startswith('_'):
            phase_paths.append(os.path.join(root, f))
phase_paths = sorted(phase_paths)
for p in phase_paths:
    print(p)
"
```

Expected: lista com os 12 arquivos `.md` em ordem:
```
phases/clean/10_clean_code.md
phases/claude/11_unit_tests.md
phases/claude/12_integration_tests.md
phases/doc/01_javadoc.md
phases/doc/02_final_keywords.md
phases/doc/03_documentation.md
phases/solid/07_solid.md
phases/solid/08_architecture.md
phases/solid/09_patterns.md
phases/struct/04_nomenclature.md
phases/struct/05_structure.md
phases/struct/06_tracking.md
```

- [ ] **Step 7.8: Commit final**

```bash
git add main.py .gitignore
git commit -m "fix: load phases recursively (bug 1), fix refactor_file arg order (bug 2), integrate Cache"
```

---

## Verificação Final

- [ ] **Rodar todos os testes uma última vez**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: todos passando, zero falhas

- [ ] **Verificar que o cache dir é criado ao importar Cache**

```bash
python -c "
from memory.cache import Cache
import tempfile, os
with tempfile.TemporaryDirectory() as d:
    c = Cache(d)
    c.set_dep_context('test', '// hello')
    assert c.get_dep_context('test') == '// hello'
    c.mark_phase_done('/file.java', '01_javadoc')
    assert c.is_phase_done('/file.java', '01_javadoc')
    assert not c.is_phase_done('/file.java', '07_solid')
    print('Cache: OK')
"
```

Expected: `Cache: OK`

- [ ] **Commit de consolidação (se necessário)**

```bash
git log --oneline -8
```

Confirmar que os commits estão em ordem correta e as mensagens fazem sentido.
