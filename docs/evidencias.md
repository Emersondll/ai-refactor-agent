# Evidências de Execução — R7

**Início:** 2026-05-14T22:30:17  
**Branch:** refactor/ai-agent-automation  
**Cobertura inicial:** 72.51%

---

## Checkpoint 1 — 23:12 (42 min)

### Fase: initial_coverage_fix

| Arquivo | Status | Tempo | Observação |
|---|---|---|---|
| BalanceDocumentTest.java | ✅ ACEITO | 9 min | cold start do modelo |
| MerchantDocumentTest.java | ✅ ACEITO | 4 min | — |
| TransactionDocumentTest.java | ✅ ACEITO | 4:27 min | — |
| MerchantCategoryCodesDocumentTest.java | ✅ ACEITO | 4:13 min | Fix de enum hallucination ✓ |
| TransactionControllerTest.java | ❌ REVERTIDO | 21:11 min | 3 reparos — 3 erros distintos |
| TransactionCodeModelTest.java | ⚠️ em reparo | — | ASSERTION ERROR |

---

### Análise detalhada: TransactionControllerTest.java

O LLM gerou 3 versões diferentes com 3 bugs distintos — não aprende entre tentativas:

| Reparo | Erro | Causa raiz |
|---|---|---|
| 1 (22:56) | `cannot find symbol: Hamcrest` + `constructor TransactionModel wrong args` | Import inexistente + record com args errados |
| 2 (23:04) | `package com.example.model does not exist` | **Hallucination de package** — gemma4 inventou `com.example.*` em vez de `com.caju.*` |
| 3 (23:13) | `reached end of file` + `try without catch` | **Arquivo truncado** — output excedeu `num_predict: 4096` |

**Padrão:** cada reparo parte do zero sem memória do que foi tentado antes. O histórico de erros existe no prompt, mas o LLM ignora e introduz novos bugs.

---

### Análise detalhada: TransactionCodeModelTest.java

```
testEdgeCaseEmptyCode:52 expected: <true> but was: <false>
```

**Causa:** LLM gerou teste que assume que `isEmpty()` retorna `true` para código vazio, mas a implementação retorna `false`. LLM testou comportamento DESEJADO, não ATUAL. Skill `java-tdd-unit-test` tem regra "test only current behavior" mas é ignorada em edge cases.

---

## Plano de Melhorias Identificadas

### M1 — Nova categoria `TRUNCATED_OUTPUT` em `_categorize_build_error` ⚡ CRÍTICO
- **Trigger:** `reached end of file while parsing` OU `'try' without 'catch'`
- **Instrução de reparo:** `"The previous output was TRUNCATED before completion. Complete the file: add the missing catch/finally block and ALL closing braces needed. Do NOT rewrite — only close what is open."`
- **Arquivo:** `java/refactor.py` → `_categorize_build_error()`

### M2 — Aumentar `num_predict` para modo test ⚡ CRÍTICO
- **Causa:** `call_model()` usa `num_predict: 4096` para todos os modos. Arquivos de teste grandes excedem o limite
- **Fix:** adicionar parâmetro `num_predict` em `call_model()`, modo `test` → `8192`
- **Arquivo:** `ai/model.py`

### M3 — Injetar package explícito no prompt de reparo ⚡ CRÍTICO
- **Causa:** no reparo 2, gemma4 hallucinou `com.example.model` em vez de `com.caju.transactionauthorizer`. O prompt de reparo não reforça o package correto
- **Fix:** em `_build_validator_correction_prompt()`, injetar `"MANDATORY: package declaration MUST be exactly: package com.caju.transactionauthorizer.controller;"` extraído do arquivo original
- **Arquivo:** `ai/model.py` → `_build_validator_correction_prompt()`

### M4 — Assertion error: reforçar "teste o comportamento atual" no reparo ⚡ IMPORTANTE
- **Causa:** categoria `ASSERTION ERROR` instrui o LLM a corrigir o valor esperado, mas não deixa claro que deve executar o código mentalmente para descobrir o valor real
- **Fix:** adicionar na instrução de reparo: `"Run the method mentally with the test input and use the ACTUAL return value as the expected value. Do NOT guess what 'should' happen."`
- **Arquivo:** `java/refactor.py` → `_categorize_build_error()`

### M5 — Detecção precoce de output truncado em `clean_output` (PREVENTIVO)
- **Fix:** após extrair o bloco java, contar `{` vs `}` — se desbalanceado, rejeitar antes do Maven
- **Arquivo:** `ai/sanitizer.py`

### M6 — Persistência de falhas recorrentes entre runs (PERFORMANCE)
- **Observação:** TransactionControllerTest falha em 100% dos runs (R1→R7) — 21 min queimados por run
- **Fix:** `failed_files.json` não limpar entradas `permanent_skip` no `reset()`. Após 3 runs consecutivos, pular automaticamente
- **Arquivo:** `java/refactor.py` → `FailedFilesTracker`

---

## Checkpoint 2 — 00:07 (Pipeline Finalizado)

### Pipeline R7 — COMPLETO

| Fase | Início | Fim | Status |
|---|---|---|---|
| HEALTH_CHECK | 22:30 | 22:30 | ✅ |
| AUDIT_COVERAGE (72.51%) | 22:30 | 22:30 | ⚠️ abaixo 90% |
| initial_coverage_fix | 22:30 | 00:04 | 8 aceitos, 2 revertidos |
| SANITIZATION | 00:06 | 00:07 | ✅ |
| FINAL_VALIDATION | 00:07 | 00:07 | ✅ 92.57% |
| COMMIT_PUSH | 00:07 | — | ✅ |

**Cobertura:** 72.51% → 92.12% (pós-geração) → **92.57%** (final) ✅

### Falhas Confirmadas

| Arquivo | Tempo | Causa terminal |
|---|---|---|
| TransactionControllerTest.java | 21 min | `reached end of file` — output truncado (num_predict: 4096) |
| MerchantCategoryCodesServiceImplTest.java | 23 min | Package hallucination (`com.example.service` em vez de `com.caju.*`) |

### Observação crítica
Fases 09–14 (refatoração LLM semântica) **não foram executadas** — o pipeline estava apenas na fase de cobertura (generate_tests). As 6 skills de refatoração ainda aguardam primeiro teste real.

---

*Monitoramento encerrado. Ver `plano_implementacao.md` para próximos passos.*
