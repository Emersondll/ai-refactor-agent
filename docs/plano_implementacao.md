# Plano de Implementação — Melhorias Pós-R7

**Gerado em:** 2026-05-15  
**Baseado em:** Execução R7 (2026-05-14 22:30 → 2026-05-15 00:07)

---

## Resumo Executivo R7

| Métrica | Valor |
|---|---|
| Duração total | 1h37min |
| Cobertura inicial | 72.51% |
| Cobertura pós-geração | 92.12% |
| Cobertura final | **92.57%** ✅ (meta: 90%) |
| Arquivos iniciados | 10 |
| Aceitos | 8 (80%) |
| Revertidos | **2 (20%)** |
| Tempo desperdiçado em revertidos | ~46 min (50% do tempo total) |
| Fases LLM executadas (09–14) | **ZERO** — pipeline parou antes |

---

## Falhas Documentadas no R7

### Falha 1 — TransactionControllerTest.java
**Duração:** 22:52 → 23:13 = **21 min** | **3 reparos, 3 erros distintos**

| Reparo | Erro | Causa raiz |
|---|---|---|
| 1 | `cannot find symbol: Hamcrest` + constructor errado | Import hallucination + record sem args |
| 2 | `package com.example.model does not exist` | **Package hallucination** — gemma4 inventou `com.example.*` |
| 3 | `reached end of file while parsing` / `try without catch` | **Output truncado** — `num_predict: 4096` excedido |

**Categoria retornada por `_categorize_build_error`:** genérica (não reconhece truncamento)  
**Resultado:** revertido — arquivo não existe no projeto

---

### Falha 2 — MerchantCategoryCodesServiceImplTest.java
**Duração:** 23:32 → 23:55 = **23 min** | **3 reparos**

**Erro terminal:**
```
IMPORT ERROR: Class 'class MerchantRepository' not found.
location: class com.example.service.MerchantServiceTest
```

**Causa raiz:**  
Package hallucination dupla: o LLM gerou o arquivo como `com.example.service.MerchantServiceTest`  
em vez de `com.caju.transactionauthorizer.service.impl.MerchantCategoryCodesServiceImplTest`.  
Prompt de reparo não reforça package e classe corretos.

---

## Causa Raiz Estrutural — Por Que os Reparos Falham

O repair loop atual tem um problema arquitetural: **cada tentativa de reparo começa com o código original**, não com o código da tentativa anterior que quase funcionou. O histórico de erros vai no prompt, mas:

1. O LLM ignora os erros anteriores e introduz bugs diferentes
2. Sem âncora de package explícita no prompt de reparo, o LLM "esquece" o package correto
3. Arquivos grandes truncam silenciosamente — o validator só detecta depois do Maven

---

## Plano de Implementação (Prioridade Decrescente)

### M1 — Nova categoria `TRUNCATED_OUTPUT` em `_categorize_build_error`
**Prioridade:** 🔴 CRÍTICO  
**Arquivo:** `java/refactor.py` → função `_categorize_build_error()`  
**Trigger:** `"reached end of file while parsing"` OU `"'try' without 'catch'"` no output Maven  
**Posição:** Inserir ANTES do fallback genérico (última linha)

**Instrução de reparo a retornar:**
```python
return (
    "TRUNCATED OUTPUT: Your previous code was cut off before completion.\n"
    "DO NOT rewrite the entire file.\n"
    "ONLY add the missing closing braces `}`, catch/finally blocks, and semicolons "
    "to complete what was already written.\n"
    "Count open `{` vs closed `}` in your previous output and close the difference."
)
```

**Impacto esperado:** evita 1 ciclo de reparo com erro genérico, direciona o modelo para corrigir só o fim do arquivo.

---

### M2 — `num_predict: 8192` para modo `test`
**Prioridade:** 🔴 CRÍTICO  
**Arquivo:** `ai/model.py` → função `call_model()`  
**Mudança:** adicionar parâmetro `num_predict: int = 4096` e passar `8192` quando `mode == "test"`  

**Como o pipeline passa o mode:**  
`_run_pipeline()` recebe `mode` mas `call_model()` não o recebe. A cadeia é:  
`call_ai(mode)` → `_run_pipeline(mode)` → `_try_local_agent()` → `call_model()`

**Solução:** adicionar `num_predict` como parâmetro em `call_model` e `_try_local_agent`. Em `_run_pipeline`, detectar `mode == "test"` e passar `num_predict=8192`.

**Impacto esperado:** elimina truncamentos em arquivos de teste com 80–150 linhas.

---

### M3 — Injetar package e class name no prompt de reparo
**Prioridade:** 🔴 CRÍTICO  
**Arquivo:** `ai/model.py` → `_build_validator_correction_prompt()`  
**Mudança:** receber `original_code: str` como parâmetro adicional e extrair o package via regex.

**Lógica a adicionar:**
```python
import re
pkg_match = re.search(r'^(package\s+[\w.]+;)', original_code, re.MULTILINE)
package_line = pkg_match.group(1) if pkg_match else ""

class_match = re.search(r'(?:public\s+)?(?:class|interface|record|enum)\s+(\w+)', original_code)
class_name = class_match.group(1) if class_match else ""
```

**Texto a injetar no topo do prompt de correção:**
```
### MANDATORY CONSTRAINTS (non-negotiable)
- Package MUST be exactly: {package_line}
- Class name MUST be exactly: {class_name}
- Do NOT use com.example.*, com.test.*, or any invented package.
```

**Impacto esperado:** elimina a alucinação de package que causou os reparos 2 de ambas as falhas.

---

### M4 — Reforçar instrução de ASSERTION ERROR
**Prioridade:** 🟡 IMPORTANTE  
**Arquivo:** `java/refactor.py` → `_categorize_build_error()` → bloco `assertionerror`  
**Mudança:** adicionar linha explícita sobre "executar mentalmente":

```python
return (
    f"ASSERTION ERROR: The expected value in the test is wrong.\n"
    f"Detail: {line.strip()}\n"
    "Run the method mentally with the test input to find the ACTUAL return value.\n"
    "Fix assertEquals/assertThat to match what the method ACTUALLY returns NOW.\n"
    "Do NOT guess what 'should' happen — test current behavior, not desired behavior."
)
```

---

### M5 — Detecção precoce de output truncado em `clean_output`
**Prioridade:** 🟡 IMPORTANTE  
**Arquivo:** `ai/sanitizer.py` → `_finalize()`  
**Mudança:** após extrair o bloco java, verificar balanço de chaves:

```python
def _is_balanced(code: str) -> bool:
    open_b = code.count('{')
    close_b = code.count('}')
    return open_b == close_b

# No final de _finalize(), antes do return:
if not _is_balanced(code):
    return None  # rejeita output truncado antes do Maven
```

**Impacto esperado:** detecta truncamento **antes** de chamar `mvn compile`, economizando 30–60s por tentativa.

---

### M6 — Persistência de skip permanente entre runs
**Prioridade:** 🟢 PERFORMANCE  
**Arquivo:** `java/refactor.py` → `FailedFilesTracker`  
**Regra:** se um arquivo foi revertido em 3+ runs consecutivos, adiciona flag `permanent_skip: true`.  
**No `reset()`:** limpar apenas entradas sem `permanent_skip: true`.  
**No `generate_tests()`/`_refactor_whole_file()`:** verificar `is_permanent_skip(file_path)` antes de processar.

**Estrutura JSON:**
```json
{
  "file": "...TransactionControllerTest.java",
  "permanent_skip": true,
  "skip_reason": "3 runs consecutivos sem sucesso",
  "fail_count": 7
}
```

**Impacto esperado:** economiza 21 min por run no TransactionControllerTest (7 runs × 21 min = **147 min desperdiçados até agora**).

---

## Causa Raiz Adicional — TransactionController (Field Injection)

O `TransactionController` usa `@Autowired private TransactionService service` (field injection).  
Isso torna o teste sem Spring context **impossível de forma elegante** — não há construtor público com injeção.

**Impacto:** o LLM gera MockMvc ou Spring context (@WebMvcTest) porque é a única saída "natural", mas a skill proíbe ambos. Resultado: loop de falha garantido.

**Solução estrutural:** a fase 11 (SOLID DIP) converte field injection → constructor injection.  
Mas a fase de testes vem ANTES da refatoração. **Ordem atual do pipeline é o problema.**

**Proposta M7 — Nova opção de skip inteligente por tipo de arquitetura:**  
Se o arquivo de teste depende de um arquivo de produção com field injection (`@Autowired` sem construtor), marcar como `deferred_skip` e processar APÓS a fase 11.

---

### M8 — Complementação de testes existentes com cobertura parcial
**Prioridade:** 🟡 IMPORTANTE  
**Arquivo:** `java/refactor.py` → `generate_tests()`  
**Status:** a implementar antes do R9

**Problema atual:**  
O pipeline usa `if os.path.exists(test_path): continue` — ignora completamente qualquer arquivo de teste que já exista, mesmo que a cobertura da classe seja de 30%. Classes como `TransactionServiceImpl` têm teste existente (`TransactionServiceImplTest.java`) mas provavelmente não cobrem todos os cenários.

**Comportamento desejado:**  
Se o arquivo de teste já existe MAS a cobertura da classe de produção correspondente está abaixo do threshold (90%), o pipeline deve **ler o teste existente** e **pedir ao LLM para adicionar** os casos faltantes — sem reescrever os que já existem.

**Implementação técnica:**

```python
# Em generate_tests(), substituir o skip simples por:
if os.path.exists(test_path):
    # Verificar cobertura da classe específica
    _, _, coverage, missed_lines = maven_test_with_coverage(repo_path, file_name)
    if coverage >= 90.0 or not missed_lines:
        continue  # cobertura OK — não precisa complementar
    # Complementar: passa teste existente + linhas não cobertas
    existing_test = read_file(test_path)
    complement_rules = (
        f"{rules}\n\n"
        "### EXISTING TESTS (DO NOT MODIFY OR REMOVE)\n"
        f"```java\n{existing_test}\n```\n\n"
        "### UNCOVERED LINES\n"
        f"Lines not covered: {missed_lines}\n\n"
        "ADD new @Test methods to cover the uncovered lines above.\n"
        "NEVER remove or modify existing @Test methods.\n"
        "Return the COMPLETE file with all existing tests plus the new ones."
    )
    # Usa complement_rules em vez de rules para a geração
```

**Risco:** médio — modificar testes existentes pode quebrar assertions. Mitigação: a instrução "NEVER remove or modify existing @Test methods" + `mvn test` de validação garante que o pipeline reverte se algo quebrar.

**Impacto esperado:**  
- Eleva cobertura de classes já parcialmente cobertas para ≥90%
- Elimina o caso onde `generate_tests` termina sem atingir a meta porque todas as classes já têm teste (mas parcial)
- Especialmente relevante para `TransactionServiceImpl` (lógica complexa com switch de categoria MCC)

---

## Sequência de Implementação Recomendada

```
M5 (detectar truncado antes do Maven)     — menor risco, sem efeito colateral
  ↓
M2 (num_predict 8192 para test)           — resolve truncamento na origem
  ↓
M3 (package injection no prompt reparo)   — resolve hallucination de package
  ↓
M1 (categoria TRUNCATED_OUTPUT)           — fallback quando M2+M5 não bastarem
  ↓
M4 (assertion error reforço)              — melhoria qualitativa do reparo
  ↓
M6 (persistent skip)                      — otimização de performance
  ↓
M7 (deferred skip por field injection)    — melhoria arquitetural de longo prazo
  ↓
M8 (complementação de testes existentes)  — aumenta cobertura de classes já parcialmente testadas
```

---

## Estimativa de Impacto Esperado (R8)

| Métrica | R7 atual | R8 estimado |
|---|---|---|
| Taxa de aceitação | 80% (8/10) | ~90% (9/10) |
| Tempo desperdiçado | ~46 min | ~10 min |
| Cobertura final | 92.57% | ~95% |
| Arquivos sem teste (revertidos) | 2 | 0–1 |
| Tempo total estimado | 1h37min | ~1h10min |

---

## Arquivos a Modificar

| Arquivo | Melhorias | Risco | Status |
|---|---|---|---|
| `java/refactor.py` | M1, M4 | Baixo — só adiciona casos novos | ✅ Implementado |
| `ai/model.py` | M2, M3 | Médio — altera assinatura de funções | ✅ Implementado |
| `ai/sanitizer.py` | M5 | Baixo — só rejeita mais cedo | ✅ Implementado |
| `java/refactor.py` | M6 (FailedFilesTracker) | Médio — altera estado persistente | ✅ Implementado |
| `java/refactor.py` | M7 (deferred field injection) | Baixo — skip condicional | ✅ Implementado |
| `java/refactor.py` | M8 (complementação de testes) | Médio — modifica testes existentes | ✅ Implementado |

---

## Testes de Validação Pós-Implementação

Antes de iniciar o R8:
1. `sdk use java 22-open && cd repos/card-transaction-authorizer && mvn test -q` — confirmar build limpo
2. Verificar que `failed_files.json` foi resetado (apenas M6 pode manter entradas permanentes)
3. Confirmar que `live_state.json` está `{"active_skill": "", "current_model": "gemma4:latest"}`

---

## Falhas Documentadas no R15 (2026-05-15)

> **Status (2026-05-15):** C21 e C22 implementados. C23 verificado. C24-C26 implementados na mesma sessão.

### Falha C21 — TransactionCodeModelTest.java (REINCIDÊNCIA)
**Horário:** 18:15:00 → 18:34:57 = **19 min** | resultado: FILE_REVERTED  
**Erro terminal:** `COMPILATION/EXECUTION ERROR` — esgotou 3 reparos sem sucesso  
**Causa raiz confirmada:** mesmo padrão do R14 — gemma4 não sabe que `TransactionCodeModel` é um Java `record`, gera:
- Assertions de igualdade incorretas para `record` com string vazia
- Assertions de `toString()` esperando `"ABC"` mas `record` retorna `TransactionCodeModel[code=ABC]`
- Eventualmente gera "implicitly declared classes" (Java 21 preview) — código sem `package` + `class` declaration

**Impacto:** 19 min desperdiçados por run. Com M1–M8 já implementados, este arquivo ainda falha — indica que os reparos existentes não conhecem a semântica de `record`.

**Correção proposta (não implementar):**
Injetar no prompt de geração de testes a informação de que a classe-alvo é um `record`:
```
# Em _build_test_prompt() — antes de chamar call_ai():
if re.search(r'\brecord\s+\w+', production_code):
    extra = (
        "\n### JAVA RECORD SEMANTICS\n"
        "This class is a Java RECORD. Records auto-generate:\n"
        "- equals/hashCode based on all fields\n"
        "- toString() returning 'ClassName[field1=val1, field2=val2]'\n"
        "- An all-args canonical constructor\n"
        "NEVER assert toString() returns just the field value — it always includes the class name.\n"
    )
    rules += extra
```

---

### Falha C22 — TransactionModelTest.java (NOVA)
**Horário:** 18:34:57 → 19:01:58 = **27 min** | resultado: FILE_REVERTED  
**Erro terminal:** `IMPORT ERROR: Class 'class TransactionModel' not found.`  
**Categoria retornada:** IMPORT ERROR — 3 tentativas de reparo, todas falharam  
**Causa raiz:** Package hallucination — mesmo padrão de M3 (já implementado), mas M3 injeta o package no prompt de **reparo**. O erro persiste porque:
1. O LLM gerou o arquivo inicial com package errado
2. O reparo M3 injeta o package correto, mas o LLM alucina o import da classe de produção (`TransactionModel`) com package inexistente
3. `TransactionModel` pode ser um `record` também — o LLM não sabe o import correto

**Correção proposta (não implementar):**
No prompt de **geração inicial** (não só no reparo), injetar os imports das classes referenciadas na classe de produção:
```python
# Em _build_test_prompt():
import_block = _extract_imports(production_code)  # extrai "import com.caju...."
rules += f"\n### REQUIRED IMPORTS (use these exactly)\n{import_block}\n"
```

---

### C23 — Custo temporal acumulado por arquivo com 3 reparos (RISCO SISTÊMICO)
**Observação:** No R15, só os dois arquivos acima desperdiçaram **19 + 27 = 46 min** — idêntico ao R7 e R14.  
M6 (persistent skip) está implementado — verificar se está sendo ativado corretamente para estes arquivos.  

**Diagnóstico pendente:** Checar se `failed_files.json` após R15 marca estes dois arquivos com `permanent_skip: true`.  
Se não estiver funcionando, a causa pode ser que o reset() limpa as entradas entre runs mesmo com `permanent_skip`.

---

## Sequência de Implementação Recomendada (pós-R15)

```
C21 (injetar semântica de record no prompt de geração)    — resolve 100% dos erros de TransactionCodeModelTest
  ↓
C22 (injetar imports da classe de produção no prompt)     — resolve alucinação de import em TransactionModelTest
  ↓
C23 (verificar se M6 permanent_skip está ativando)        — diagnóstico antes de implementar nova lógica
```

---

*Plano gerado a partir de análise de `execution.jsonl`, `execution.log` e `failed_files.json` do R7.*  
*Seção C21–C23 adicionada após monitoramento do R15 em 2026-05-15.*
