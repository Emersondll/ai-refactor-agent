# Pipeline Fixes F/G/H/I — Timestamp, Soul Language, Validator PT, Permanent-Skip Expiry

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir 4 classes de problema identificadas na execução de 2026-05-22: erro de `java.sql.Timestamp` em testes gerados; instruções LLM mistas (PT + EN); mensagens PT no validator; e entradas `permanent_skip` de bugs já corrigidos bloqueando arquivos válidos.

**Architecture:** Todas as mudanças são em arquivos Python do pipeline. Nenhuma mudança no projeto Java alvo. Três arquivos principais tocados: `soul.md`, `java/refactor.py`, `java/validator.py`.

**Tech Stack:** Python 3.12, regex, `java/refactor.py` (active_rules + `_categorize_build_error` + `FailedFilesTracker`), `soul.md`, `java/validator.py`.

---

## Diagnóstico dos Problemas

### Problema 1 — `java.sql.Timestamp` formato errado em testes (ATIVO AGORA)

**Erro capturado:**
```
TransactionDocumentTest.setUp:29 » IllegalArgument Timestamp format must be yyyy-mm-dd hh:mm:ss[.fffffffff]
```

**Root cause:** `TransactionDocument.java` declara `private Timestamp timestamp` com `import java.sql.Timestamp`. O LLM gera o setUp com:
```java
this.timestamp = Timestamp.valueOf("2023-01-15T10:00:00"); // ERRADO — "T" é ISO, não SQL
```
O formato correto para `Timestamp.valueOf()` é `"yyyy-mm-dd hh:mm:ss"` (espaço entre data e hora, **sem** `T`).

**Gaps no código atual:**
- `_JDK_IMPORT_MAP` em `refactor.py:52` não tem `Timestamp` → `_auto_inject_missing_imports` não injeta `import java.sql.Timestamp;`
- Nenhuma regra preventiva em `active_rules` para classes com `java.sql.Timestamp`
- `_categorize_build_error` não tem handler para `IllegalArgumentException` com mensagem de Timestamp format → cai no fallback genérico

**Arquivos afetados:**
- `java/refactor.py` — `_JDK_IMPORT_MAP` (~linha 52), seção `active_rules` (~linha 1492), `_categorize_build_error` (~linha 140)

---

### Problema 2 — `soul.md` em Português: instruções LLM mistas

**Root cause:** `soul.md` (carregado como `_SOUL` em `ai/prompt.py:23` e injetado no TOPO de TODOS os prompts) está **100% em Português**. Já todos os `BASE_CONSTRAINTS`, `BASE_CONSTRAINTS_TEST`, e seções `active_rules` construídas em `refactor.py` estão em **Inglês**.

Resultado: todo prompt enviado aos LLMs começa em PT e termina em EN. Isso é uma inconsistência estrutural — LLMs multilíngues têm comportamento mais estável quando o idioma das instruções é único.

**Exemplo de prompt atual (estrutura mista):**
```
[SOUL — Português]
Você é um engenheiro sênior Java...
Você nunca inventa, nunca assume...

[BASE_CONSTRAINTS — Inglês]
### TECHNICAL CONSTRAINTS (MANDATORY)
PRESERVE the package declaration exactly as-is...

[active_rules — Inglês]
### TEST CLASS — MANDATORY NAME AND PACKAGE...
```

**Nota:** `report_runner.py:188` tem `"Escreva em Português do Brasil"` — isso é **correto** e **deve permanecer** (o relatório final é para o usuário, não para o LLM de refatoração/testes).

**Arquivos afetados:**
- `soul.md` — traduzir para Inglês, manter todo conteúdo comportamental

---

### Problema 3 — `validator.py` com mensagens em Português

**Root cause:** `java/validator.py` linhas 236 e 238 retornam mensagens em Português:
```python
# linha 236:
return False, f"O arquivo se chama '{file_name}.java' mas você gerou a classe '{found_name}'."
# linha 238:
return False, f"Não foi encontrada a classe '{file_name}' no código gerado."
```

Essas mensagens **não chegam ao LLM** diretamente (em `refactor.py:766-773` o `reason` é substituído por mensagem English antes de chamar o LLM). Mas aparecem em dois lugares:
1. `failed_files.json` — como `reason` de entradas `permanent_skip` de runs anteriores (ex: `MerchantCategoryCodesServiceImplTest`)
2. Logs internos de diagnóstico quando chamados por outros paths

**Arquivos afetados:**
- `java/validator.py` — linhas 236 e 238

---

### Problema 4 — Entradas `permanent_skip` de bugs já corrigidos

**Estado atual de `logs/failed_files.json`:**

| Arquivo | Fase | Reason/Stack | Bug que corrigiu |
|---------|------|-------------|------------------|
| `BalanceServiceImplTest.java` | `initial_coverage_fix` | `"actual and formal argument lists differ in length"` | Fix **A** (CONSTRUCTOR CALL com tipos) |
| `MerchantCategoryCodesServiceImplTest.java` | `initial_coverage_fix` | `"INTEGRITY ERROR: O arquivo se chama..."` | Fix **B** (expected_class no repair loop) |
| `TransactionServiceImpl.java` | `solid-dip` | `compile_failed` | Investigação necessária (não é teste) |

**Root cause:** `_AUTO_EXPIRE_STACK_PATTERNS` em `refactor.py:508` só contém `"com.example"`. O método `reset()` verifica apenas o campo `stack_trace`. Entradas sem `stack_trace` (como `MerchantCategoryCodesServiceImplTest`) nunca expiram.

**Gaps:**
1. Padrão para construtor mismatch ausente (`"actual and formal argument lists differ in length"`)
2. Padrão para integrity error PT ausente (`"O arquivo se chama"`)
3. `reset()` checa apenas `stack_trace`, não `reason`

**Arquivos afetados:**
- `java/refactor.py` — `_AUTO_EXPIRE_STACK_PATTERNS` (~linha 508) e método `reset()` em `FailedFilesTracker` (~linha 600)

---

## Mapa de Arquivos

| Arquivo | Mudança |
|---------|---------|
| `soul.md` | Traduzir de PT → EN (Task 2) |
| `java/refactor.py` | 4 mudanças: `_JDK_IMPORT_MAP` + regra preventiva Timestamp + handler `_categorize_build_error` + `_AUTO_EXPIRE_STACK_PATTERNS` + `reset()` |
| `java/validator.py` | 2 mensagens PT → EN (Task 3) |

---

## Task 1: Fixes para `java.sql.Timestamp` (Problema 1)

**Files:**
- Modify: `java/refactor.py:52-78` (`_JDK_IMPORT_MAP`)
- Modify: `java/refactor.py:1490-1500` (bloco BigDecimal na seção `active_rules`)
- Modify: `java/refactor.py:140-240` (`_categorize_build_error`)

### Fix 1a — Adicionar `Timestamp` ao `_JDK_IMPORT_MAP`

- [ ] **Step 1: Localizar o bloco `_JDK_IMPORT_MAP`**

Abrir `java/refactor.py` e localizar o dict que começa em ~linha 52:
```python
_JDK_IMPORT_MAP: dict[str, str] = {
    "BigDecimal":    "import java.math.BigDecimal;",
    ...
}
```

- [ ] **Step 2: Adicionar entrada `Timestamp`**

Inserir logo após a entrada `"Period"`:
```python
    "Timestamp":     "import java.sql.Timestamp;",
    "Date":          "import java.util.Date;",
```
**Razão:** `_auto_inject_missing_imports` consulta este mapa. Sem a entrada, testes com `Timestamp` ficam sem o import e a geração falha antes mesmo do formato errado se manifestar.

- [ ] **Step 3: Verificar que não há teste unitário quebrado por esta adição**

Rodar (no venv ativado, Java 22):
```bash
cd /home/emerson/Área\ de\ trabalho/ai-refactor-agent && python -m pytest tests/ -q -k "import" 2>&1 | tail -20
```
Esperado: zero failures relacionados ao mapa de imports.

---

### Fix 1b — Regra preventiva em `active_rules`

- [ ] **Step 4: Localizar o bloco de regra BigDecimal em `active_rules`**

Em `java/refactor.py`, localizar o bloco que começa com (~ linha 1491):
```python
        # C: regra preventiva — quando a classe de produção declara campos BigDecimal
        if re.search(r'\bBigDecimal\b', original):
            active_rules += (
                "\n\n### BIGDECIMAL CONSTRUCTION (MANDATORY — VIOLATION CAUSES COMPILE FAILURE)\n"
                ...
            )
```

- [ ] **Step 5: Adicionar bloco de regra `java.sql.Timestamp` IMEDIATAMENTE APÓS o bloco BigDecimal**

```python
        # F (Timestamp): regra preventiva — quando a classe usa java.sql.Timestamp
        # Timestamp.valueOf() exige formato "yyyy-mm-dd hh:mm:ss" (espaço, não T ISO).
        if re.search(r'\bjava\.sql\.Timestamp\b', original) or \
           (re.search(r'\bTimestamp\b', original) and 'import java.sql.Timestamp' in original):
            active_rules += (
                "\n\n### JAVA SQL TIMESTAMP CONSTRUCTION (MANDATORY — VIOLATION CAUSES RUNTIME FAILURE)\n"
                "This class uses java.sql.Timestamp. For ALL test values involving Timestamp:\n"
                "  CORRECT: Timestamp.valueOf(\"2023-01-15 10:00:00\")  ← space between date and time\n"
                "  WRONG:   Timestamp.valueOf(\"2023-01-15T10:00:00\")  ← T is ISO format, NOT SQL format\n"
                "  WRONG:   new Timestamp(longValue)  ← use valueOf() with string for readability\n"
                "The format MUST be exactly: \"yyyy-mm-dd hh:mm:ss\" or \"yyyy-mm-dd hh:mm:ss.nnnnnnnnn\"\n"
                "NEVER use ISO-8601 format (with 'T') — it throws IllegalArgumentException at runtime.\n"
                "ALWAYS add: import java.sql.Timestamp;\n"
            )
```

- [ ] **Step 6: Verificar que a detecção funciona para `TransactionDocument.java`**

Teste manual rápido no Python REPL:
```python
import re
original = open("repos/card-transaction-authorizer/src/main/java/com/caju/transactionauthorizer/document/TransactionDocument.java").read()
print(bool(re.search(r'\bjava\.sql\.Timestamp\b', original)))
# Deve imprimir: False  (o import é java.sql.Timestamp mas sem o pacote no corpo)
print('import java.sql.Timestamp' in original)
# Deve imprimir: True
print(bool(re.search(r'\bTimestamp\b', original)))
# Deve imprimir: True
```
Resultado esperado: a condição `re.search(r'\bTimestamp\b', original) and 'import java.sql.Timestamp' in original` é `True` → regra injetada.

---

### Fix 1c — Handler em `_categorize_build_error`

- [ ] **Step 7: Localizar o início da função `_categorize_build_error`**

Em `java/refactor.py`, função `_categorize_build_error` (~linha 140). Localizar o primeiro bloco `if`:
```python
    # Erro de construtor de record (detectar ANTES de cannot find symbol)
    if "constructor" in out and "in record" in out ...
```

- [ ] **Step 8: Inserir handler `IllegalArgumentException` + Timestamp ANTES do primeiro bloco `if`**

O handler deve ser o PRIMEIRO verificado pois `IllegalArgumentException` pode co-ocorrer com outras strings:
```python
    # F: IllegalArgumentException com mensagem de formato Timestamp
    if "illegalargument" in out and "timestamp format" in out:
        return (
            "TIMESTAMP FORMAT ERROR: java.sql.Timestamp.valueOf() received an invalid format string.\n"
            "The format MUST be exactly: \"yyyy-mm-dd hh:mm:ss\" (space between date and time, NOT 'T').\n\n"
            "FIND in your @BeforeEach or test body every occurrence of:\n"
            "  Timestamp.valueOf(\"...T...\")   ← WRONG — 'T' is ISO-8601, not SQL format\n"
            "REPLACE with:\n"
            "  Timestamp.valueOf(\"2023-01-15 10:00:00\")   ← CORRECT — space, not T\n\n"
            "ONE CHANGE ONLY — do NOT modify any other code. Do NOT change assertions, imports, or class structure.\n"
        )
```

- [ ] **Step 9: Verificar que o handler está posicionado ANTES do bloco `if "constructor" in out...`**

Ler as primeiras 10 linhas da função após a inserção para confirmar a ordem.

- [ ] **Step 10: Commit**

```bash
cd /home/emerson/Área\ de\ trabalho/ai-refactor-agent
git add java/refactor.py
git commit -m "fix: F — java.sql.Timestamp import, preventive rule, and repair handler

_JDK_IMPORT_MAP: add Timestamp → import java.sql.Timestamp
active_rules: inject JAVA SQL TIMESTAMP CONSTRUCTION rule when class imports Timestamp
_categorize_build_error: add handler for IllegalArgument + Timestamp format error

Resolves: TransactionDocumentTest.setUp:29 » IllegalArgument Timestamp format

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Traduzir `soul.md` para Inglês (Problema 2)

**Files:**
- Modify: `soul.md` (raiz do projeto)

**Contexto:** `soul.md` é carregado uma única vez em `ai/prompt.py:23` como `_SOUL` e injetado no início de TODOS os prompts (refatoração e geração de testes). Qualquer LLM que receba um prompt do pipeline lê primeiro o soul. Ter o soul em PT enquanto todo o resto está em EN cria ambiguidade de idioma para o modelo.

**Regra crítica:** NÃO adicionar blocos ` ```java ` no soul.md — quebraria o teste `test_no_java_example_block_in_prompt`. Manter apenas texto prosa.

- [ ] **Step 1: Traduzir `soul.md` para Inglês mantendo 100% do conteúdo**

Substituir o arquivo `soul.md` pela versão abaixo (mesmas seções, mesmas regras, mesmo tom, em Inglês):

```markdown
# SOUL — Java Refactoring Agent Identity

You are a senior Java engineer with 15 years of experience in high-availability critical systems.
Your specialty is surgical refactoring: improving code without ever altering its external behavior.

---

## Who you are

You are methodical, conservative, and precise.
You never invent, never assume, never guess.
You read code as a contract — each method is a promise to its caller.

You were trained on the principles of:
- Robert C. Martin (Clean Code, SOLID)
- Martin Fowler (Refactoring)
- Joshua Bloch (Effective Java)

---

## What you NEVER do

1. **Never change the package name.** The package is tied to the physical path of the file in the Maven project. Changing the package breaks the build for the entire project.

2. **Never invent imports.** If a symbol does not exist in the original code, do not add it unless you are absolutely certain the dependency exists on the classpath.

3. **Never remove business logic.** You may reorganize, rename, extract — but never delete functional behavior.

4. **Never change public signatures without necessity.** Renaming or altering the parameters of a public method breaks all callers.

5. **Never add annotations that did not exist.** `@Version`, `@Transactional`, `@Cacheable` have runtime behavioral implications.

6. **Never convert an interface to a class or vice versa.** These are immutable architectural contracts in this context.

---

## How you decide what to change

Before changing anything, you ask yourself:
- Does this change make the code more readable WITHOUT altering behavior?
- Can this change break something in another file that depends on this one?
- Is the file already good enough for this rule? If so, return it EXACTLY as received.

If the file already satisfies the rule for this phase, return the code **identical to the original**.
This is not a failure — it is the correct diagnosis of already well-written code.

---

## Code style you produce

- Methods with ≤ 30 lines
- Maximum 3 levels of nesting
- Prefer early return over deep else
- Names that need no comments
- No `System.out.println` — only SLF4J
- No silenced exceptions with empty catch

---

## Mandatory response format

You respond ALWAYS with the complete Java file inside a single code block delimited by triple-backtick java.
Never explain what changed. Never add comments outside the code.
Never truncate the file with "// rest of code..." or similar.
The file you return replaces the original file — it must be 100% complete and compilable.
```

- [ ] **Step 2: Verificar que não há bloco java no novo soul.md**

```bash
grep -c '```java' /home/emerson/Área\ de\ trabalho/ai-refactor-agent/soul.md
```
Esperado: `0`

- [ ] **Step 3: Verificar que o soul ainda é carregado corretamente**

```bash
cd /home/emerson/Área\ de\ trabalho/ai-refactor-agent
python -c "
from ai.prompt import _SOUL
assert len(_SOUL) > 100, 'soul vazio'
assert 'never invent' in _SOUL.lower() or 'Never invent' in _SOUL, 'conteúdo ausente'
assert 'Você' not in _SOUL, 'Português ainda presente'
print('OK:', len(_SOUL), 'chars, idioma: EN')
"
```
Esperado: `OK: NNN chars, idioma: EN`

- [ ] **Step 4: Rodar suite de testes relacionados ao prompt**

```bash
cd /home/emerson/Área\ de\ trabalho/ai-refactor-agent
python -m pytest tests/ -q -k "prompt or soul" 2>&1 | tail -20
```
Esperado: todos passando, especialmente `test_no_java_example_block_in_prompt`.

- [ ] **Step 5: Commit**

```bash
git add soul.md
git commit -m "fix: G — translate soul.md from Portuguese to English

Unifies prompt language: all LLM instructions now consistently in English.
Content unchanged — identical behavioral rules, same structure, EN wording.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Traduzir mensagens PT em `validator.py` (Problema 3)

**Files:**
- Modify: `java/validator.py:236` e `java/validator.py:238`

- [ ] **Step 1: Localizar e substituir as duas mensagens em `validate_class_name_matches_file`**

Arquivo: `java/validator.py`

**Linha 236** — substituir:
```python
        return False, f"O arquivo se chama '{file_name}.java' mas você gerou a classe '{found_name}'."
```
Por:
```python
        return False, f"File is named '{file_name}.java' but generated class is '{found_name}'."
```

**Linha 238** — substituir:
```python
    return False, f"Não foi encontrada a classe '{file_name}' no código gerado."
```
Por:
```python
    return False, f"Class '{file_name}' not found in the generated code."
```

- [ ] **Step 2: Verificar que as mensagens novas seguem o padrão das outras mensagens do validador**

Confirmar que `check_syntax` ainda usa mensagens em inglês (`"Syntax error:"`, `"Parse failed:"`).

- [ ] **Step 3: Rodar testes do validator**

```bash
cd /home/emerson/Área\ de\ trabalho/ai-refactor-agent
python -m pytest tests/ -q -k "validator or class_name or package" 2>&1 | tail -20
```
Esperado: todos passando.

- [ ] **Step 4: Commit**

```bash
git add java/validator.py
git commit -m "fix: H — translate Portuguese error messages in validator.py to English

Lines 236 and 238 of validate_class_name_matches_file() now return English.
These messages appear in failed_files.json; translating maintains log consistency.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Expirar `permanent_skip` de bugs já corrigidos (Problema 4)

**Files:**
- Modify: `java/refactor.py:508-510` (`_AUTO_EXPIRE_STACK_PATTERNS`)
- Modify: `java/refactor.py` — método `reset()` de `FailedFilesTracker` (~linha 600)

**Contexto dos arquivos bloqueados:**

| Arquivo | Campo com padrão detectável | Bug corrigido por |
|---------|-----------------------------|-------------------|
| `BalanceServiceImplTest.java` | `stack_trace`: `"actual and formal argument lists differ in length"` | Fix A (CONSTRUCTOR CALL com tipos) |
| `MerchantCategoryCodesServiceImplTest.java` | `reason`: `"O arquivo se chama"` (mensagem PT — impossível após fix B) | Fix B (expected_class no repair loop) |

**Nota sobre `TransactionServiceImpl.java`:** Está em `solid-dip`, não em geração de testes. É um arquivo de produção complexo. **Não adicionar** auto-expire para `compile_failed` genérico — seria perigoso. Este arquivo merece investigação manual separada.

### Fix 4a — Expandir `_AUTO_EXPIRE_STACK_PATTERNS` e cobrir campo `reason`

- [ ] **Step 1: Localizar `_AUTO_EXPIRE_STACK_PATTERNS`**

Em `java/refactor.py`, localizar (~linha 508):
```python
_AUTO_EXPIRE_STACK_PATTERNS = [
    "com.example",  # F2 Package Guard: LLM escrevia package errado; corrigido deterministicamente
]
```

- [ ] **Step 2: Adicionar novos padrões**

Substituir por:
```python
_AUTO_EXPIRE_STACK_PATTERNS = [
    "com.example",              # F2 Package Guard: package hallucination no longer possible
    "actual and formal argument lists differ in length",  # Fix A: CONSTRUCTOR CALL hint now includes types
    "O arquivo se chama",       # Fix B/H: old Portuguese integrity error — impossible after fix B
]
```

- [ ] **Step 3: Localizar o método `reset()` em `FailedFilesTracker`**

Localizar o trecho que faz a verificação de `permanent_skip` (~ linha 600):
```python
for entry in ...:
    if entry.get("permanent_skip"):
        st = entry.get("stack_trace", "")
        if next((p for p in _AUTO_EXPIRE_STACK_PATTERNS if p in st), None):
            ...
```

- [ ] **Step 4: Estender a verificação para incluir o campo `reason`**

O campo `MerchantCategoryCodesServiceImplTest` tem o padrão em `reason`, não em `stack_trace`. Substituir a linha:
```python
        st = entry.get("stack_trace", "")
```
Por:
```python
        st = (entry.get("stack_trace") or "") + " " + (entry.get("reason") or "")
```
Esta alteração de uma linha garante que os padrões são verificados nos dois campos, sem mudar qualquer outra lógica.

- [ ] **Step 5: Verificar com teste manual o comportamento**

```python
# Simular no Python REPL
import json, sys
sys.path.insert(0, '/home/emerson/Área de trabalho/ai-refactor-agent')
from java.refactor import _AUTO_EXPIRE_STACK_PATTERNS

entries = json.load(open('logs/failed_files.json'))
for e in entries:
    if e.get('permanent_skip'):
        st = (e.get('stack_trace') or '') + ' ' + (e.get('reason') or '')
        match = next((p for p in _AUTO_EXPIRE_STACK_PATTERNS if p in st), None)
        print(f"{e['file'].split('/')[-1]}: {'EXPIRA' if match else 'PERMANECE'} ({match or 'sem padrão'})")
```

Resultado esperado:
```
TransactionServiceImpl.java: PERMANECE (sem padrão)
MerchantCategoryCodesServiceImplTest.java: EXPIRA (O arquivo se chama)
BalanceServiceImplTest.java: EXPIRA (actual and formal argument lists differ in length)
BalanceDocumentTest.java: PERMANECE (sem padrão)   # prev_run=True, não permanent_skip=True
```

- [ ] **Step 6: Rodar testes relacionados ao FailedFilesTracker**

```bash
cd /home/emerson/Área\ de\ trabalho/ai-refactor-agent
python -m pytest tests/ -q -k "failed_files or tracker or expire or skip" 2>&1 | tail -20
```
Esperado: todos passando.

- [ ] **Step 7: Commit**

```bash
git add java/refactor.py
git commit -m "fix: I — expand permanent_skip auto-expire to cover constructor mismatch and old PT integrity errors

_AUTO_EXPIRE_STACK_PATTERNS: add constructor mismatch pattern (fixed by A)
  and old Portuguese integrity error pattern (impossible after fix B/H).
reset(): check both stack_trace and reason fields — MerchantCategoryCodesServiceImplTest
  stores the expired pattern in reason, not in stack_trace.

BalanceServiceImplTest and MerchantCategoryCodesServiceImplTest will be retried
on the next run with fixes A and B active.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5 (Investigação): `TransactionServiceImpl.java` — solid-dip bloqueado

**Files:**
- Read: `repos/card-transaction-authorizer/src/main/java/.../TransactionServiceImpl.java`

Este arquivo está em `permanent_skip` com `solid-dip compile_failed`. Não é geração de testes — é refatoração de produção. **Não adicionar auto-expire** sem entender o erro.

- [ ] **Step 1: Ler o arquivo de produção atual**

```bash
cat "repos/card-transaction-authorizer/src/main/java/com/caju/transactionauthorizer/service/impl/TransactionServiceImpl.java"
```

- [ ] **Step 2: Entender por que solid-dip falhou**

O `stack_trace` em `failed_files.json` apenas diz `compile_failed`. Para saber o erro real, verificar `execution.log` de runs anteriores ou executar manualmente o solid-dip nesse arquivo isoladamente.

- [ ] **Step 3: Decidir a ação**

Opções:
- **A) Adicionar à blocklist permanente** (`_BOOTSTRAP_RE` ou `_SKIP_PATTERNS`) se o arquivo tiver estrutura que solid-dip não consegue processar (ex: generics complexos, múltiplas interfaces).
- **B) Corrigir o bug de solid-dip** para esse padrão específico.
- **C) Deixar em `permanent_skip`** se o arquivo já está bem estruturado e DIP não é necessário.

Esta task não gera commit sozinha — o resultado alimenta a decisão de um fix adicional se necessário.

---

## Self-Review

**Spec coverage:**
- ✅ Problema 1 (Timestamp) → Task 1 (3 fixes: import map, preventive rule, repair handler)
- ✅ Problema 2 (soul PT) → Task 2 (tradução completa)
- ✅ Problema 3 (validator PT) → Task 3 (2 mensagens)
- ✅ Problema 4 (permanent_skip) → Task 4 (patterns + reset() fix)
- ✅ TransactionServiceImpl → Task 5 (investigação)

**Placeholder scan:** nenhum TODO/TBD presente; todos os code blocks contêm código real.

**Type consistency:** os campos `stack_trace` e `reason` em `failed_files.json` são strings; a concatenação com `" "` é segura para os padrões de substring matching usados.

**Ordem de execução recomendada:** Task 1 → Task 2 → Task 3 → Task 4 → Task 5. Tasks 2 e 3 são independentes e podem ser feitas em paralelo. Task 4 depende de nenhuma outra (os padrões funcionam independentemente da tradução). Task 1 é a mais urgente (erro ativo agora).
