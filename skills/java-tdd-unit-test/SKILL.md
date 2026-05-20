---
name: java-tdd-unit-test
description: Use when the audit/coverage phase of the refactoring agent needs to generate unit tests to reach 90% coverage and preserve behavior before refactoring begins — or when generated tests fail to compile due to hallucinated symbols, enum values, or constructor mismatches.
---

# Java TDD Unit Test — Fase de Auditoria de Cobertura

## LLM INSTRUCTIONS

Generate a complete JUnit 5 + Mockito test class that brings coverage above 90%.
Apply all rules in PHASE RULES — they are injected by the pipeline and take precedence.
Test only what the code does TODAY — not future or hypothetical behaviour.
Use the DEPENDENCY CONTEXT to verify enum values, constructor signatures, and method names — never invent them.

## Test Generation Rules

Rules loaded by `_build_task(mode="test")` in `ai/prompt.py` as the TASK section.
Not sent verbatim — the pipeline inserts them via `load_skill("java-tdd-unit-test", section="Test Generation Rules")`.

TECHNICAL GUIDELINES:
1. PACKAGE: Copy the package declaration verbatim from the source class. Never abbreviate or invent a package path.
2. IMPORTS — add all required imports with full canonical paths:
   - import org.junit.jupiter.api.Test;
   - import org.junit.jupiter.api.BeforeEach;
   - import org.junit.jupiter.api.extension.ExtendWith;
   - import static org.junit.jupiter.api.Assertions.*;
   - import org.mockito.Mock;
   - import org.mockito.InjectMocks;
   - import org.mockito.Mockito;
   - import org.mockito.junit.jupiter.MockitoExtension;
   Add imports for every project type used — derive package paths from the production imports listed in PHASE RULES. Never invent a package path.
3. MOCKS: Add @ExtendWith(MockitoExtension.class) on the test class. Annotate the class under test with @InjectMocks. Annotate each dependency with @Mock.
4. INTEGRITY: Use ONLY methods, constructors, and public fields declared in the source class. Do NOT call methods that do not exist. Verify exact signatures against the DEPENDENCY CONTEXT.
5. COVERAGE: Include happy path, edge cases, and exception/error scenarios for each public method.
6. JAVA RECORDS: When instantiating any record (either the class under test or any record used as an argument), ALWAYS use the canonical constructor with ALL declared fields in the correct order. NEVER call new RecordClass() with no arguments — records have no default no-arg constructor.
7. CONTROLLERS (@RestController): NEVER use @SpringBootTest, @WebMvcTest, @AutoConfigureMockMvc, or MockMvc — these load the full Spring context and cause test failures. Use @ExtendWith(MockitoExtension.class) + @InjectMocks for the controller + @Mock for each dependency. Call controller methods directly (e.g. controller.create(request)). For methods returning ResponseEntity, assert on the returned object status (e.g. assertEquals(HttpStatus.OK, response.getStatusCode())).
8. FIDELITY: Test only what the code currently does. Do NOT add behaviour, validations, or scenarios that do not exist in the source class today.

## Repair Strategy

Fix ONLY the specific error reported below. Do NOT rewrite the whole test class.
Preserve all passing tests. Do NOT change method signatures, working imports, or unrelated code.
Make the smallest possible change that resolves the reported error.

---

## Pipeline Documentation

Esta seção documenta o comportamento do código Python — não é enviada ao LLM.

### Responsabilidade

Governa o ciclo `AUDIT_COVERAGE` em `java/refactor.py → generate_tests()`.
Acionado por `main.py` quando `global_cov < 90.0`.
Segunda passagem: `AUDIT_COVERAGE_POST_DIP` — após fases 01–14, para classes liberadas pelo solid-dip.

```
AUDIT_COVERAGE (main.py)
  └── coverage < 90%?
        └── generate_tests()  ← esta skill governa este ciclo
              └── RED → GREEN → REFACTOR (por arquivo)
        └── gate: re-mede cobertura após geração

AUDIT_COVERAGE_POST_DIP (main.py, após fases 01-14)
  └── generate_tests()  ← mesma skill, phase="post_solid_dip_coverage"
        └── M7 não adia mais classes com field injection convertidas pelo solid-dip
        └── M8 pula classes já cobertas (≥90%) sem custo
```

### Estrutura do prompt de geração de testes

```
BASE_CONSTRAINTS_TEST       ← ai/prompt.py (específico para modo test — não contamina com regras de refatoração)
PHASE RULES                 ← active_rules em generate_tests(): mandatory prefix + imports + bigdecimal + field injection
TASK                        ← _build_task("test"): carrega ## Test Generation Rules desta skill + enum constraint dinâmico
DEPENDENCY CONTEXT          ← get_dependency_context() — simplifiedHeader com enum constants e assinaturas
SOURCE FILE TO PROCESS      ← classe de produção
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
| `cannot find symbol` em classe | Self-import ausente (F1) | `_s1_imports` deve incluir `_self_import` |
| `com.example.*` no package | LLM alucinando package (F2) | Package guard em `generate_tests()` |
| `NoSuchMethodError` | Construtor com assinatura errada | Injetar construtor real no contexto |
| Cobertura < 90% após retries | Classe muito complexa ou estática | Registrar em `failed_files.json` |

### Arquivos-chave

| Arquivo | Responsabilidade |
|---|---|
| `main.py` | Aciona `generate_tests()` quando `coverage < 90%`; carrega esta skill via `load_skill` |
| `java/refactor.py → generate_tests()` | Ciclo RED-GREEN-REFACTOR por arquivo; monta `active_rules` e `_s1_imports` |
| `java/refactor.py → _categorize_build_error()` | Categoriza erro Maven em instrução cirúrgica de reparo (G1, F4, S2, D, A) |
| `java/context.py → _extract_simplified_header` | Extrai enum constants e assinaturas reais |
| `ai/prompt.py → _build_task(mode="test")` | Carrega `## Test Generation Rules` desta skill + enum constraint dinâmico |
| `java/compiler.py → maven_test_with_coverage` | Mede cobertura e retorna `missed_lines` |

### Ambiente Java

Para qualquer comando Maven/Java executado diretamente via Bash (fora do agente):

```bash
sdk use java 22-open
mvn ...
```

O projeto usa `<java.version>22</java.version>` no `pom.xml` — não alterar para 21.
