---
name: java-tdd-unit-test
description: Use when the audit/coverage phase of the refactoring agent needs to generate unit tests to reach 90% coverage and preserve behavior before refactoring begins — or when generated tests fail to compile due to hallucinated symbols, enum values, or constructor mismatches.
---

# Java TDD Unit Test — Fase de Auditoria de Cobertura

## LLM INSTRUCTIONS

Generate JUnit 5 + Mockito unit tests to bring coverage above 90%.
Target: happy path, edge cases, and exception scenarios.
Test only what the code does TODAY — not future or hypothetical behavior.

## Repair Strategy

When a generated test fails to compile or run, inject this section as the repair prompt.
Keep it under 5 lines — the error detail from _categorize_build_error() is already in the prompt.

Fix ONLY the error pointed out below. Do NOT rewrite the whole test class.
Preserve all passing tests. Do NOT change method signatures or add new dependencies.
If the error mentions an enum value: use ONLY values in ALLOWED ENUM VALUES.
If the error mentions a constructor: check DEPENDENCY CONTEXT for the exact argument list.
If the error mentions @SpringBootTest or MockMvc: remove them, use @InjectMocks + @Mock only.

---

## Pipeline Documentation

Esta seção documenta o comportamento do código Python — não é enviada ao LLM.

### Responsabilidade

Governa o ciclo `AUDIT_COVERAGE` em `java/refactor.py → generate_tests()`.
Acionado por `main.py` quando `global_cov < 90.0`.

```
AUDIT_COVERAGE (main.py)
  └── coverage < 90%?
        └── generate_tests()  ← esta skill governa este ciclo
              └── RED → GREEN → REFACTOR (por arquivo)
        └── gate: re-mede cobertura após geração
```

### Princípio fundamental

Testes gerados nesta fase devem validar o que o código **faz hoje**.
São a rede de segurança — se quebrarem após refatoração, a refatoração introduziu regressão.

### Anti-Alucinação

```
NUNCA invente valores de enum    → leia o DEPENDENCY CONTEXT
NUNCA assuma construtores        → use assinatura exata da classe fonte
NUNCA chame métodos privados     → apenas membros públicos são testáveis
NUNCA use @SpringBootTest        → JUnit 5 + Mockito puro
NUNCA teste comportamento futuro → teste o que o código faz AGORA
```

### Autonomia — Regra Absoluta

Claude NUNCA cria arquivos de teste manualmente.
Se um teste falha, a correção é no pipeline (skill, prompt, context.py) — não no arquivo.
A execução deve ser completamente autônoma, sem ações de contorno.

### Checklist de diagnóstico

| Sintoma | Causa provável | Ação |
|---|---|---|
| `cannot find symbol` em enum | `_extract_simplified_header` não inclui constantes | Verificar `context.py` |
| `cannot find symbol` em método | Método privado ou inexistente | Corrigir o prompt com dep_context |
| `NoSuchMethodError` | Construtor com assinatura errada | Injetar construtor real no contexto |
| Cobertura < 90% após retries | Classe muito complexa ou estática | Registrar em `failed_files.json` |

### Arquivos-chave

| Arquivo | Responsabilidade |
|---|---|
| `main.py` | Aciona `generate_tests()` quando `coverage < 90%`; carrega esta skill via `load_skill` |
| `java/refactor.py → generate_tests()` | Ciclo RED-GREEN-REFACTOR por arquivo |
| `java/context.py → _extract_simplified_header` | Extrai enum constants e assinaturas reais |
| `ai/prompt.py → _build_task(mode="test")` | Regras anti-alucinação detalhadas no prompt |
| `java/compiler.py → maven_test_with_coverage` | Mede cobertura e retorna `missed_lines` |

### Ambiente Java

Para qualquer comando Maven/Java executado diretamente via Bash (fora do agente):

```bash
sdk use java 22-open
mvn ...
```

O projeto usa `<java.version>22</java.version>` no `pom.xml` — não alterar para 21.
