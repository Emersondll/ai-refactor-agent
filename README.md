# AI Refactor Agent

Agente autônomo de refatoração Java que roda **100% localmente** via Ollama.

---

## Screenshots

### Dashboard em Tempo Real
![Dashboard — Pipeline e métricas](docs/images/dashboard_overview.png)

> Pipeline de 16 fases com status ao vivo, cobertura de testes, ETC e modelo LLM ativo.

### Colmeia de Classes (Honeycomb)
![Dashboard — Colmeia de arquivos](docs/images/dashboard_full.png)

> Cada hexágono representa uma classe Java. Cores: verde = refatorado, laranja = pulado (estrutural/conforme), vermelho = revertido, dourado = em processamento.

### Visualizador de Relatório
![Relatório de Refatoração](docs/images/report_viewer.png)

> Relatório narrativo gerado por LLM ao final de cada ciclo — acessível em `http://localhost:8000/report.html`. Aplica 16 fases de qualidade — ferramentas determinísticas + LLM método a método — mantendo o build Maven sempre verde e gerando um relatório narrativo ao final de cada ciclo.

---

## Arquitetura do Pipeline

```
main.py
  ├── HEALTH_CHECK                 → maven_test (valida estado inicial)
  ├── AUDIT_COVERAGE               → java/refactor.py · generate_tests()
  │     ├── P0: data holder?       → java/data_holder_test_gen.py (template Python, sem LLM)
  │     │                                 ├── sucesso → commit_single_file (P2) + continue
  │     │                                 └── falha   → fallback para LLM
  │     └── LLM path               → call_ai (seed fixo P1) → repair loop
  │                                       ├── P4: _try_surgical_patch (Python, antes do LLM)
  │                                       └── call_ai_with_correction (fallback LLM)
  │
  ├── Fases 01–14 (loop sequencial via phases/configs/*.yml)
  │     ├── tool: community        → java/community_runner.py
  │     ├── tool: llm              → java/llm_runner.py
  │     │                               ├── method_level: true  → java/method_runner.py (_run_method_level)
  │     │                               ├── class_level:  true  → java/method_runner.py (_run_class_level)
  │     │                               └── (sem flag)          → llm_runner loop por arquivo
  │     ├── tool: flow             → java/flow_runner.py
  │     └── tool: flow-dry         → java/flow_runner.py (dry_check)
  │
  ├── AUDIT_COVERAGE_POST_DIP (S5) → java/refactor.py (segunda passagem — classes liberadas pelo solid-dip)
  ├── SANITIZATION                 → java/sanitizer.py (imports mortos, código inativo via regex)
  ├── JAVADOC                      → java/javadoc_runner.py (Javadoc em métodos públicos)
  ├── FINAL_VALIDATION             → maven_test + JaCoCo (cobertura final)
  ├── REPORT                       → java/report_runner.py (relatório Markdown por classe)
  └── COMMIT_PUSH                  → git_utils/repo.py (branch refactor/ai-agent-automation, push final)
```

### As 16 Fases

| # | Skill / Fase | Tool | Runner | Granularidade |
|---|-------------|------|--------|---------------|
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
| 11 | solid-dip | llm → class | method_runner | **classe completa** |
| 12 | controller-lean | llm → method | method_runner | **método** |
| 13 | flow-refactor | flow | flow_runner | endpoint/fluxo |
| 14 | dry-check | flow-dry | flow_runner | grupo de arquivos |
| 15 | JAVADOC | — | javadoc_runner | arquivo |
| 16 | REPORT | — | report_runner | sessão completa |

---

## Refatoração Método a Método (Fases 09, 10, 12)

```
Para cada arquivo Java (excl. testes):
  │
  ├── cache.is_phase_done?       → skip
  ├── _is_structural_type?       → skip (FILE_SKIPPED — laranja no dashboard)
  │     record / interface / @Entity / @Document / DTO
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
        ├── merge_method(código_atual, original, novo)
        ├── mvn compile -q
        │     ├── OK  → mark_method_done + FILE_ACCEPTED
        │     └── ERR → write_file(código_anterior) + FILE_REVERTED
        └── mark_phase_done(arquivo) após todos os métodos avaliados
```

## Refatoração Classe Completa (Fase 11 — solid-dip)

```
Para cada arquivo Java:
  ├── _is_structural_type? → skip
  ├── skip_compression: true (flag no yml)
  │     → envia código ORIGINAL completo ao LLM (contexto total das dependências)
  ├── call_ai(full_class)
  │     └── LLM devolve classe inteira (apenas constructor injection adicionado)
  ├── mvn compile -q
  │     ├── OK  → write + mark_phase_done + FILE_ACCEPTED
  │     └── ERR → repair loop (A1: até MAX_RETRIES tentativas com call_ai_with_correction)
  │               → esgotado: git checkout -- arquivo + FILE_REVERTED
  └── mark_phase_done
```

---

## Determinismo do Pipeline (P0–P4)

Cinco mecanismos eliminam o whack-a-mole de fixes reativos sobre geração não-determinística:

| ID | Onde | O quê |
|----|------|-------|
| **P0** | `java/data_holder_test_gen.py` (novo) + `generate_tests()` | Gerador determinístico de testes para data holders puros (`@Document`/`@Entity`/POJO com só campos + ctor + getters/setters). `is_pure_data_holder()` exige `return field;` e `this.field = param;` literais (ternário/método/concat reprovam). Tipos suportados: `String`, `BigDecimal`, `BigInteger`, `Timestamp` (formato SQL), `Long`/`Integer`/`Double`/`Boolean`, `LocalDate`, `LocalDateTime`. Outros tipos → `None` → fallback LLM. Bypassa LLM completamente — zero repair loop, totalmente reproduzível. |
| **P1** | `config.py` + `ai/model.py · call_model()` | `OLLAMA_SEED=42` (override via env) injetado em `options`. Mesmo prompt → mesma saída run-a-run. Fixes "grudam" em vez de re-rolar. Repair loop não é afetado: muda o prompt a cada tentativa. |
| **P2** | `git_utils/repo.py · commit_single_file()` | Commit local por arquivo aceito (sem push) em ambos os pontos de aceitação (determinístico P0 e LLM). Run interrompido não perde trabalho — próximo run vê os commits e pula. `commit_and_push` no final ainda dá `push` em tudo. |
| **P3** | `java/refactor.py · _build_active_rules()` (helper extraído) | Consolidou 12+ blocos `### ... (MANDATORY)` do `active_rules`. Fundiu `IMPORTS PRESENT` + `SELF-IMPORT` + `IMPORT PROHIBITION` em um único `### IMPORTS`. Cada bloco condicional comprimido para ≤4 linhas. Mandatoriedade declarada uma vez no topo. Regression test (`tests/java/test_active_rules_preservation.py`) verifica 18 frases-chave preservadas de todos os fixes anteriores. |
| **P4** | `java/refactor.py · _try_surgical_patch()` | Patch Python de uma linha para erros de asserção determinísticos: `assertNull(expr)` ↔ `assertEquals("X", expr)` (S1/S4) e value swap simples (G1). Tentado ANTES de `call_ai_with_correction` no repair loop. Se o patch passa no build → `continue`; senão fallback LLM. Janela ±3 linhas para tolerar off-by-N do Maven. |

> **Por que importa:** o LLM (Ollama, 7–9B) é não-determinístico. Sem isso, cada run regenerava testes com variações novas que caíam em falhas novas — handlers de erro eram adicionados sem cessar. P0 elimina o LLM para tarefas mecânicas. P1 torna o que sobra reproduzível. P2 dá crash-safety. P3 reduz ruído de prompt. P4 evita regeneração de arquivo inteiro para edições de uma linha.

---

## Fase Javadoc (pós-sanitização)

```
Para cada arquivo Java de produção:
  ├── _all_public_methods_documented? → FILE_SKIPPED (already_documented)
  ├── call_ai(full_class, regras javadoc)        ← MODEL_DOC (qwen2.5-coder:7b, code-aware)
  │     └── LLM adiciona /** */ onde falta — sem tocar em corpos de método
  ├── _strip_comments(new_code) == _strip_comments(original)?
  │     ├── NÃO → J1: retry com MODEL_STRUCT (qwen2.5-coder:7b) + prompt de crítica
  │     │         ├── retry aceito?   → continua para compile
  │     │         └── retry rejeitado → FILE_SKIPPED (code_structure_changed)
  │     └── SIM → continua para compile
  ├── mvn compile -q
  │     ├── OK  → FILE_ACCEPTED
  │     └── ERR → write_file(original) + FILE_REVERTED
  └── continua para próximo arquivo
```

---

## Relatório de Refatoração (pós-validação final)

```
report_runner.run_report()
  ├── Lê execution.jsonl — isola sessão atual (desde GIT_BRANCH_CREATED)
  ├── Agrupa eventos por arquivo:
  │     accepted  → fases onde FILE_ACCEPTED
  │     skipped   → fases onde FILE_SKIPPED (com motivo)
  │     reverted  → fases onde FILE_REVERTED
  ├── Serializa sumário compacto
  ├── Chama LLM (Claude → modelo local fallback)
  │     → gera relatório Markdown narrativo em Português
  │     → seções: Visão Geral, Cobertura, Classes Modificadas, Puladas, Revertidas
  ├── Fallback puro Python se LLM indisponível
  ├── Salva em logs/refactoring_report.md
  └── Salva em REFACTORING_REPORT.md na raiz do repo alvo (commitado)
```

**Visualização:** `http://localhost:8000/report.html` (link no dashboard) — renderização Markdown com tema escuro, atualização automática a cada 30s.

---

## Módulos Java

| Arquivo | Papel |
|---------|-------|
| `java/method_extractor.py` | Extrai `MethodDef` (signature, body, start/end line) sem parser AST — contagem de chaves |
| `java/class_builder.py` | `build_method_context`, `compress_done_methods`, `merge_method`, `extract_method_from_response` |
| `java/method_runner.py` | Orquestra refatoração método a método e classe completa; `skip_compression` flag para solid-dip |
| `java/llm_runner.py` | Dispatch → method_runner ou loop file-level; `_is_structural_type()` |
| `java/flow_runner.py` | Refatoração por cadeia de endpoint; DRY check; repair loop; emite eventos exec_logger |
| `java/flow_mapper.py` | Análise estática — mapeia endpoints, resolve interface→impl |
| `java/community_runner.py` | Executa ferramentas OpenRewrite / GJF / PMD |
| `java/refactor.py` | Geração de testes TDD — `generate_tests()` com repair loop, `_build_active_rules()` (P3), `_try_surgical_patch()` (P4), `_categorize_build_error()` com handlers A–F/S1–S4/P1/P2/G1 |
| `java/data_holder_test_gen.py` | **(P0)** Gerador determinístico de testes para data holders puros — Python template, sem LLM |
| `java/validator.py` | `is_valid_java`, `validate_class_name_matches_file`, `validate_package_matches_path` |
| `java/sanitizer.py` | Sanitização final — remove métodos privados não usados via regex (escopo estreito) |
| `java/context.py` | `get_dependency_context()` — extrai esqueleto da classe + `// CONSTRUCTOR CALL:` hint |
| `java/compiler.py` | `maven_test`, `maven_test_with_coverage` (JaCoCo), `get_global_coverage`; `ENV_WRAPPER` injeta `sdk use java 22-open` |
| `java/llm_reviewer.py` | Revisa diff pós-fase com `review_criteria` → APPROVE/REJECT/SKIP |
| `java/javadoc_runner.py` | Insere Javadoc em métodos públicos; J1 retry com `MODEL_STRUCT`; filtro de data holders |
| `java/report_runner.py` | Gera relatório Markdown narrativo por classe; fallback estruturado sem LLM |

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

10 skills em `skills/<nome>/SKILL.md` na raiz do projeto. Carregadas via `core.utils.load_skill(name, section="...")` e injetadas como instrução de prompt nas LLMs locais (Ollama). São snippets de prompt em Markdown — NÃO são subagentes Claude.

### Mapa de execução

| Momento | Skill | Onde é carregada | Trigger |
|---------|-------|-----------------|---------|
| Toda chamada de refatoração | `java-refactor-context` | `ai/prompt.py → _build_task()` | sempre — base de instrução para qualquer fase LLM |
| `AUDIT_COVERAGE` (pré-refatoração) | `java-tdd-unit-test` | `java/refactor.py → generate_tests()` | cobertura JaCoCo < 90% |
| Fase 09 | `java-guard-clauses` | `method_runner._run_method_level()` | detecta ≥ 3 níveis de `if` aninhado |
| Fase 10 | `java-method-extraction` | `method_runner._run_method_level()` | detecta método > 30 linhas |
| Fase 11 | `java-solid-dip` | `method_runner._run_class_level()` | detecta `new ConcreteClass()` hardcoded |
| Fase 12 | `java-controller-lean` | `method_runner._run_method_level()` | detecta lógica de negócio em `@RestController` |
| Fase 13 | `java-flow-refactor` | `flow_runner.py` | todos os endpoints mapeados pelo `flow_mapper` |
| Fase 14 | `java-dry-extraction` | `flow_runner.dry_check()` | grupos de arquivos com padrões repetidos |
| `AUDIT_COVERAGE_POST_DIP` (S5) | `java-tdd-unit-test` | `main.py → generate_tests()` | após fases 01–14 — classes com field injection convertidas pelo solid-dip |
| Fase 15 | `java-javadoc` | `javadoc_runner.py` | método público sem `/** */` detectado |
| Repair loop (fases 09–14) | `java-repair-guide` | `java/refactor.py → call_ai_with_correction()` | compilação Maven falha após geração LLM |

### Parâmetros das fases LLM (09–12)

| Skill | yml | method_level | class_level | skip_compression | detect_pattern |
|-------|-----|:---:|:---:|:---:|----------------|
| `java-guard-clauses` | `09_guard_clauses.yml` | ✓ | — | — | `nested_if` |
| `java-method-extraction` | `10_method_extraction.yml` | ✓ | — | — | `long_method` |
| `java-solid-dip` | `11_solid_dip.yml` | — | ✓ | ✓ | `concrete_new` |
| `java-controller-lean` | `12_controller_lean.yml` | ✓ | — | — | `controller_logic` |

> **solid-dip** usa `skip_compression: true` — envia a classe inteira ao LLM (sem compressão de métodos) para preservar o contexto completo de dependências. Proibições absolutas: nunca criar interfaces, nunca alterar assinaturas, nunca adicionar lógica — apenas substituir `new ConcreteClass()` por injeção via construtor.

> **java-refactor-context** é a skill de contexto base: toda chamada de refatoração LLM (fases 09–14 e repair loop) começa com as instruções dessa skill como sistema de regras globais, antes das regras específicas da fase.

### Tipos ignorados em todas as fases LLM

`_is_structural_type()` em `llm_runner.py` detecta e emite `FILE_SKIPPED` (laranja neon no dashboard) para: records, interfaces, `@Entity`, `@Document`, `@Table`, `*Dto.java`, `*DTO.java`, `*Request.java`, `*Response.java`, qualquer arquivo em `/dto/`. Zero tokens consumidos nesses tipos.

---

## Dashboard em Tempo Real

`dashboard.html` atualizado a cada 10 segundos com dados de `logs/execution.jsonl`.

| Cor do hexágono | Significado |
|----------------|-------------|
| Cinza | Pendente (ainda não processado) |
| Dourado pulsante | Em processamento agora |
| Laranja neon | Pulado (record/interface/DTO/entity — sem lógica de negócio, ou código já conforme) |
| Verde | Concluído com sucesso |
| Vermelho | Falha / autocura (compile falhou, arquivo revertido) |

**Funcionalidades do dashboard:**
- **ETC ao vivo**: conta regressiva; após `PIPELINE_COMPLETE` mostra duração real (`✓ 3h 44m`) e muda label para "Duração Total"
- **Card de classe ativa**: mostra arquivo e timer; ao finalizar mostra `✓ Pipeline concluído` em verde
- **Tooltips de hexágono**: hover mostra `Arquivo.java::assinaturaDométodo` para fases método a método
- **Fase COMMIT_PUSH**: marcada como `done` automaticamente ao final
- **Link para relatório**: botão "Ver Relatório de Refatoração" no topo abre `report.html`

```bash
# Servidor do dashboard (main.py inicia automaticamente)
python3 -m http.server 8000
# Dashboard:  http://localhost:8000/dashboard.html
# Relatório:  http://localhost:8000/report.html
```

---

## Técnicas de Qualidade Integradas

- **Reviewer Pattern**: diff pós-fase avaliado por `llm_reviewer.py` com critérios específicos por skill → APPROVE/REJECT/SKIP
- **TDD Unit Test Skill**: gera testes autonomamente antes da refatoração preservando comportamento atual; gate de 90% de cobertura
- **JaCoCo Guardrail**: cobertura mínima ≥ 90%; alerta de regressão se cobertura cair > 1pp após refatoração
- **Repair Loop (A1)**: falha de compilação → captura erro exato → `call_ai_with_correction()` → até `MAX_RETRIES` tentativas com `_categorize_build_error()` identificando o tipo (String→BigDecimal, construtor inválido, símbolo ausente, etc.)
- **Structural Type Skip**: `_is_structural_type()` detecta records, interfaces, @Entity, @Document, DTOs — zero tokens desperdiçados
- **Controller Guard (C1)**: `controller-lean` só roda em classes `@RestController`; ServiceImpl pulados automaticamente
- **Agent Gitignore**: `_ensure_agent_gitignore()` injeta `.refactor_cache/` e `.rag_store/` no `.gitignore` do repo alvo antes de cada commit — evita arquivos internos no histórico
- **Deferred Field Injection (M7)**: detecta classes com `@Autowired` em campo sem construtor — adia geração de testes até solid-dip converter para constructor injection; `_dip_prefiltered` detecta quando solid-dip nunca vai processar e usa `@InjectMocks` imediatamente
- **Post-DIP Coverage (S5)**: segunda passagem de `generate_tests()` após todas as fases — classes que M7 adiou e que solid-dip converteu agora recebem testes com construtor injetado; classes já cobertas (≥ 90%) puladas por M8 sem custo
- **Deterministic Import Injection (S1/F1)**: `_auto_inject_missing_imports()` injeta imports ausentes deterministicamente após geração e após cada reparo; usa `_s1_imports = prod_imports + [self_import]` — o self-import (ex: `import com.caju.transactionauthorizer.document.MerchantDocument;`) é derivado do package + nome do arquivo de produção, cobrindo o caso em que a classe testada não se importa a si mesma
- **Import-Aware Repair (S2/S4)**: `_categorize_build_error()` inclui import exato ao reportar símbolo ausente; C1 vincula import ao `@Mock` correspondente no prompt, reduzindo alucinação de tipo nas gerações de teste
- **Package Guard (F2)**: após C2 validar o nome da classe no repair loop, nova checagem de package — se o LLM alterou `package` para `com.example.model` (ou qualquer valor que difira de `_test_pkg`), injeta `PACKAGE CRITICAL ERROR` em `combined_out` e força nova tentativa sem gravar o arquivo corrompido no disco
- **Surgical Assertion Fix (G1/F4)**: `_categorize_build_error()` extrai `expected: <X> but was: <Y>` do output Maven e retorna instrução cirúrgica — "find the assertion containing X and replace with Y, ONE LINE CHANGE only" — evita que o LLM reescreva o teste inteiro ao corrigir um valor errado, o que causava erros de compilação no reparo seguinte; F4 (null vs "") é caso especial do mesmo handler
- **Javadoc Retry (J1)**: quando `neural-chat:7b` (MODEL_DOC) modifica código além de comentários, `javadoc_runner.py` executa retry com `MODEL_STRUCT` (qwen2.5-coder:7b, temp=0.05) antes de rejeitar — reduz de ~11 para ~2–3 falhas `code_structure_changed` por ciclo
- **Constructor Call Hint (C1)**: `_extract_simplified_header()` em `context.py` gera `// CONSTRUCTOR CALL: new Foo(a, b)` para classes regulares com construtor explícito (não só records) — o LLM usa esse hint ao instanciar objetos nos testes, eliminando chamadas `new Foo()` sem args em `@Document`/`@Entity`
- **Repair-to-DepContext Bridge (R1)**: `_categorize_build_error()` no RECORD/CONSTRUCTOR ERROR agora instrui explicitamente: "Look in DEPENDENCY CONTEXT for `// CONSTRUCTOR CALL:` and copy that EXACT call" — fecha o loop entre o hint do dep_context (C1) e o reparo do erro (D/R1)
- **Test Timeout Margin (T1)**: `TIMEOUT_TEST` aumentado de 300s para 420s — o custo real por arquivo é ~50s (construção do KV cache do prompt no Ollama) + ~250s (geração), totalizando ~300s. Com o limite anterior o attempt 1 expirava sistematicamente para cada arquivo novo; o attempt 2 sempre sucedia porque o KV cache já estava computado. Com 420s o attempt 1 passa com margem mesmo para prompts maiores ou variação de hardware
- **Permanent Skip Expiry (P1)**: `_AUTO_EXPIRE_STACK_PATTERNS = ["com.example"]` em `refactor.py`. `FailedFilesTracker.reset()` descarta automaticamente entradas `permanent_skip` cujo `stack_trace` contenha um padrão de bug já corrigido no pipeline — ex: package hallucination `com.example.*` corrigida pelo F2 (Package Guard). Na prática, TransactionCodeModelTest e TransactionControllerTest que foram bloqueados permanentemente antes do F2 voltam à fila no próximo run sem intervenção manual. `clear_permanent_skips(file_path=None)` disponível para remoção manual (arquivo específico ou todos)
- **JUnit Static Import Detection (P2)**: `_JUNIT_ASSERTION_METHODS` frozenset com 18 métodos JUnit 5 (`assertTrue`, `assertEquals`, `assertNull`, etc.). `_categorize_build_error()` no branch `METHOD ERROR` extrai o nome do método com regex e, se for um método JUnit, retorna `STATIC IMPORT ERROR` com a linha exata a adicionar (`import static org.junit.jupiter.api.Assertions.*;`) — em vez de "método não existe na classe", que levava o LLM a corrigir o problema errado e consumir as 3 tentativas de reparo até permanent_skip. `_auto_inject_missing_imports()` também injeta o import static deterministicamente quando detecta uso de assertions sem ele, antes mesmo do repair loop
- **A — Constructor Type Hints**: `_extract_simplified_header()` em `context.py` agora inclui o tipo de cada parâmetro no hint `// CONSTRUCTOR CALL:` (ex: `new Foo(String account, BigDecimal amount, Long version)`), não apenas o nome. Leitura de parênteses balanceados suporta anotações como `@JsonProperty("x")` em records sem quebrar no `)` interno
- **B — Expected Class in Repair Prompt**: `_build_validator_correction_prompt` em `ai/model.py` ganhou parâmetro `expected_class` — usa o nome do arquivo de destino (ex: `MerchantCategoryCodesServiceImplTest`) em vez do nome da classe de produção, impedindo o LLM de continuar abreviando o nome no repair loop de INTEGRITY ERROR
- **C — Data Holder Javadoc Skip**: `javadoc_runner.py` pula `@Document`/`@Entity`/record/enum com razão `data_holder` antes de qualquer chamada LLM — zero tokens em classes onde Javadoc adiciona nada
- **D — Ollama VRAM Unload Pre-Javadoc**: `main.py` descarrega `MODEL_CLEAN` via `keep_alive=0` antes da fase JAVADOC — libera VRAM saturada após ~3h de geração de testes e evita cascata de timeouts
- **E — BigDecimal→Long Handler**: handler específico em `_categorize_build_error` para `incompatible types: BigDecimal cannot be converted to Long` — retorna `"Use 1L for Long literals or Long.valueOf(1)"` em vez de cair no handler genérico de ResponseEntity
- **F — java.sql.Timestamp Trinity**: 3 camadas para o formato SQL (espaço, não `T`): `Timestamp` no `_JDK_IMPORT_MAP` (auto-inject); regra preventiva `### JAVA SQL TIMESTAMP CONSTRUCTION` quando classe usa `java.sql.Timestamp`; handler de primeira prioridade em `_categorize_build_error` para `IllegalArgumentException + timestamp format` retornando instrução cirúrgica
- **G — Single-Language Prompts**: `soul.md` traduzido integralmente para inglês — todo prompt agora é 100% EN, eliminando confusão de idioma do LLM (PT no soul + EN nos constraints). `report_runner.py` mantém PT intencionalmente (relatório para o usuário, não para o LLM)
- **H — English Validator Messages**: `validate_class_name_matches_file` em `validator.py` traduzido para EN — mensagens em `failed_files.json` agora consistentes com o resto do log
- **I — Stack+Reason Auto-Expire**: `_AUTO_EXPIRE_STACK_PATTERNS` expandido com padrões pós-A (`actual and formal argument lists differ in length`) e pós-H (`O arquivo se chama`). `FailedFilesTracker.reset()` agora concatena `stack_trace + reason` antes de checar padrões — `BalanceServiceImplTest` (padrão em stack_trace) e `MerchantCategoryCodesServiceImplTest` (padrão em reason) desbloqueados automaticamente
- **P0 — Deterministic Data Holder Tests**: classes puras (`@Document`/`@Entity`/POJO com só campos+ctor+getters/setters) bypassam o LLM. `is_pure_data_holder()` exige `return field;` e `this.field = param;` literais. Tabela de tipos suportados (String, BigDecimal, Timestamp SQL format, Long, etc.). Tipo não suportado → `None` → fallback LLM. **Elimina o LLM para a maior fonte histórica de falhas.**
- **P1 — Fixed Ollama Seed**: `OLLAMA_SEED=42` injetado em `call_model` options torna geração reproduzível run-a-run. Repair loop não é afetado (muda o prompt a cada tentativa)
- **P2 — Per-File Commit**: `commit_single_file` em `git_utils/repo.py` chamado em ambos os pontos de aceitação de `generate_tests` (P0 determinístico + LLM). Run interrompido preserva os testes aceitos
- **P3 — Slim active_rules**: helper `_build_active_rules()` consolidou 12+ blocos `### MANDATORY` (IMPORTS PRESENT + SELF-IMPORT + IMPORT PROHIBITION → único `### IMPORTS`; condicionais compactados a ≤4 linhas; mandatoriedade declarada uma vez). Regression test verifica 18 frases-chave preservadas
- **P4 — Surgical Python Patch**: `_try_surgical_patch()` aplica patch de uma linha para asserções determinísticas (`assertNull`↔`assertEquals` + value swap) ANTES de `call_ai_with_correction`. Janela ±3 linhas para off-by-N do Maven. Elimina regeneração de arquivo inteiro para erros conhecidos
- **S4 — assertNull Mirror Handler**: handler em `_categorize_build_error` para `expected: <null> but was: <X>` quando X é valor real não-null (espelho do S1) — retorna instrução de substituir `assertNull(expr)` por `assertEquals("X", expr)`. Regra preventiva `### SETTER/GETTER TEST PATTERN` no `active_rules` quando classe tem construtor com parâmetros
- **Opção 1 — Pro-active Constructor Validator**: `_fix_constructor_calls(test_code, dep_context)` parseia `// CONSTRUCTOR CALL: new X(Type1 p1, ...)` do dep_context e, para cada `new X(args)` no código gerado cuja contagem não bate com a assinatura canônica, reescreve com sample values da tabela tipo→literal (String→`"sampleA"`, BigDecimal→`new BigDecimal("100.00")`, Long→`1L`, Timestamp SQL format, etc.). Splitter de args respeita parens balanceadas + generics + strings. Hookado em ambos os call sites de `generate_tests` (geração inicial + repair) após `_auto_inject_missing_imports`, antes de `write_file`. Pré-Maven — catches o erro de compile mais frequente (record/class constructor mismatch) sem queimar 3 tentativas de reparo. Postura defensiva: se algum tipo requerido não está na tabela, deixa a chamada intacta
- **Opção 2 — int/double→Long/BigDecimal Handler (Fix E2)**: estende a branch `incompatible types` de `_categorize_build_error` com dois casos antes do fallback genérico — `int|short|byte → Long` retorna instrução de adicionar sufixo `L` (1 → 1L); `int|double|short|byte|float → BigDecimal` retorna instrução de envolver em `new BigDecimal("...")` ou `BigDecimal.valueOf(...)`. Handler E original (BigDecimal→Long) preservado intacto. Sem este fix, esses erros caíam no handler-fantasma que falava de `ResponseEntity` — completamente irrelevante e enganoso
- **Opção 5 — Fail-Fast em Alucinação Irrecuperável**: `_is_irrecoverable_hallucination(repair_hint, prod_imports)` inspeciona o retorno de `_categorize_build_error`. Retorna `True` quando (a) `IMPORT ERROR` nomeia classe ausente de `_prod_imports` + `_JDK_IMPORT_MAP` + JUnit/Mockito/Spring conhecidos (e não é STATIC IMPORT que P2 corrige), OU (b) `METHOD ERROR` nomeia método que NÃO está no allowlist `_UBIQUITOUS_METHOD_NAMES` (distingue `getName`/`getValue` recuperáveis de `getCode`/`getFooBar` irrecuperáveis). Hookado logo após `_categorize_build_error` no repair loop: se `True`, `break` sai do loop antes de queimar 3 tentativas × ~5min. Economiza ~50–70% do tempo em arquivos condenados
- **Opção 6 — Project-Wide Import Map**: `build_project_imports(repo_path)` varre `src/main/java/` uma vez por run, mapeia `{ShortName: "import full.pkg.ShortName;"}` para toda classe/enum/interface/record `public`. `_auto_inject_missing_imports` (S1) ganhou parâmetro opcional `project_imports` consultado como fallback após `prod_map` e `_JDK_IMPORT_MAP`. Quando o LLM escreve `TransactionStatusCode.APPROVED` no teste de um controller que não importa a enum, S1 agora injeta `import com.caju.transactionauthorizer.enums.TransactionStatusCode;` deterministicamente — sem Maven failure, sem repair loop. Política de colisão de nomes curtos: last-seen wins (aceitável para este codebase onde short names são únicos)
- **Opção 8 — Enum Support em P0**: `_extract_enum_constants(dep_context, enum_name)` parseia bloco `public enum X { ... }` do dep_context (lida com constantes simples e com constructor args como `APPROVED("00")`). `generate_data_holder_test` aceita parâmetro `dep_context` — quando um tipo de campo do construtor não está em `_TYPE_SAMPLES`, tenta resolver via enum e usa a primeira constante como sample value (`CategoryCodeName.FOOD`). Import do enum extraído dos imports da classe de produção. Safe-fail: sem dep_context ou enum não encontrado → retorna `None` (fallback LLM como antes). Desbloqueia data holders com campos enum (ex: `MerchantCategoryCodesDocument` com `CategoryCodeName`) — agora geram via caminho determinístico em vez de cair no LLM com alucinações de Mockito
- **Opção 9 — Hallucination Detection via test_code Scan**: `_is_irrecoverable_hallucination` ganhou parâmetros opcionais `test_code` e `project_imports`. Quando `repair_hint` contém `PACKAGE ERROR` E `test_code` é passado, scan por `[A-Z]\w+\.MEMBER` — qualquer classe referenciada que NÃO esteja em `{prod_imports, _JDK_IMPORT_MAP, project_imports, common JUnit/Mockito/Spring}` é alucinação irrecuperável → break do repair loop em 1 tentativa em vez de 3. Complementa Opção 6: se 6 não conseguiu injetar porque a classe não existe em mapa algum, 9 impede que o LLM invente variações por 3 tentativas

---

## Hierarquia de Modelos

| Papel | Modelo padrão | Tamanho | Responsabilidade |
|-------|--------------|---------|-----------------|
| Ultimate (SOLID) | `qwen2.5-coder:14b` | 9.0 GB | SOLID, arquitetura, revisão crítica |
| Advanced (Clean) | `qwen2.5-coder:14b` | (mesmo) | Clean code, lógica de negócio, **testes** (era `gemma4:latest`) |
| Recovery | `qwen2.5-coder:14b` | (mesmo) | Repair loop — code-aware, code-specialized |
| Standard (Struct) | `qwen2.5-coder:7b` | 4.7 GB | Estrutura, nomenclatura, revisão de diff, planner |
| Light (Doc) | `qwen2.5-coder:7b` | (mesmo) | **Javadoc** (era `neural-chat:7b` — code-aware previne mudança de estrutura) |

> Apenas **2 modelos físicos** ocupam RAM: `qwen2.5-coder:7b` (Standard/Light) e `qwen2.5-coder:14b` (Ultimate/Advanced/Recovery). Todos overridable via `.env`.

```bash
ollama pull qwen2.5-coder:14b   # Ultimate / Advanced / Recovery
ollama pull qwen2.5-coder:7b    # Standard / Light
```

---

## Requisitos

- **Ollama** rodando localmente
- **Python 3.12+**
- **Maven** + **Java 22** via SDKMAN

```bash
sdk use java 22-open   # obrigatório antes de qualquer Maven
```

## Instalação

```bash
git clone git@github.com:Emersondll/ai-refactor-agent.git
cd ai-refactor-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # configurar modelos e flags
sdk use java 22-open
python main.py
```

### Parâmetros principais do `.env`

#### Modelos Ollama

| Parâmetro | Padrão | Descrição |
|-----------|--------|-----------|
| `MODEL_DOC` | `qwen2.5-coder:7b` | Javadoc e `final` (code-aware: não muda estrutura) |
| `MODEL_STRUCT` | `qwen2.5-coder:7b` | Estrutura e nomenclatura |
| `MODEL_CLEAN` | `qwen2.5-coder:14b` | Clean code e testes (code-specialized; mesmo modelo de SOLID/RECOVERY → só 2 modelos físicos na RAM) |
| `MODEL_SOLID` | `qwen2.5-coder:14b` | SOLID e revisão crítica |
| `MODEL_RECOVERY` | `qwen2.5-coder:14b` | Repair loop — **diferente** de MODEL_CLEAN (segunda opinião real) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Endereço do Ollama |
| `OLLAMA_SEED` | `42` | **(P1)** Seed fixo nas options do Ollama — geração reproduzível run-a-run |

#### Flags de execução

| Parâmetro | Padrão | Descrição |
|-----------|--------|-----------|
| `USE_AGENT_MODE` | `false` | `true` = agent loop; `false` = pipeline fixo |
| `USE_CLAUDE_FALLBACK` | `false` | Permite Claude escrever Java (manter `false`) |
| `USE_LLMLINGUA` | `false` | Comprime `dep_context` (nunca o código-fonte) |
| `USE_RAG_CONTEXT` | `false` | LlamaIndex + ChromaDB |
| `USE_MEM0` | `false` | Memória semântica entre runs |
| `USE_CONTEXT7` | `false` | Docs ao vivo via Context7 MCP |

---

## Estrutura do Projeto

```
ai/                          # Prompts, modelos, compressão, roteamento
  prompt.py                  # _SOUL + BASE_CONSTRAINTS_TEST + build_prompt
  model.py                   # call_model (com OLLAMA_SEED P1), call_ai, repair loop
  agent_router.py            # select_agent_priority por file_type/complexity
  compressor.py              # LLMLingua (apenas em dep_context, nunca em código)
  sanitizer.py               # clean_output: limpa resposta LLM
  context7_client.py         # Docs ao vivo (opt-in)
java/
  refactor.py                # generate_tests, _build_active_rules (P3), _try_surgical_patch (P4),
                             #   _categorize_build_error, FailedFilesTracker
  data_holder_test_gen.py    # (P0) Gerador determinístico — sem LLM
  validator.py               # is_valid_java, validate_class_name/package
  context.py                 # get_dependency_context, // CONSTRUCTOR CALL: hints
  compiler.py                # maven_test, maven_test_with_coverage (JaCoCo)
  method_extractor.py        # MethodDef sem AST
  class_builder.py           # compress / merge / build_method_context
  method_runner.py           # Runner método a método e classe completa
  llm_runner.py              # Dispatch; _is_structural_type()
  flow_runner.py             # Refatoração por fluxo; DRY check
  flow_mapper.py             # Análise estática de endpoint chains
  community_runner.py        # OpenRewrite / GJF / PMD
  llm_reviewer.py            # APPROVE/REJECT/SKIP por diff
  sanitizer.py               # Sanitização final (remoção de métodos privados)
  javadoc_runner.py          # Javadoc em métodos públicos
  report_runner.py           # Relatório Markdown narrativo
phases/
  configs/                   # 14 arquivos .yml — um por fase
skills/                      # 10 skills LLM (snippets de prompt em Markdown)
  java-refactor-context/     # Base de toda chamada LLM em modo refator
  java-tdd-unit-test/        # Geração de testes + Repair Strategy
  java-repair-guide/         # Loop de correção do validator
  java-guard-clauses/        # Fase 09
  java-method-extraction/    # Fase 10
  java-solid-dip/            # Fase 11
  java-controller-lean/      # Fase 12
  java-flow-refactor/        # Fase 13
  java-dry-extraction/       # Fase 14
  java-javadoc/              # Fase JAVADOC
agent/                       # Loop agêntico (planner + executor; USE_AGENT_MODE)
core/                        # Logger, utilitários, ExecutionLogger, live_state
memory/                      # Cache de fases e métodos; SemanticMemory (opt-in)
dashboard/                   # data.py → dashboard_status.json (10s)
git_utils/
  repo.py                    # clone, branch, commit_and_push, commit_single_file (P2)
tests/                       # Suite pytest — java/, ai/, agent/, memory/
docs/
  superpowers/plans/         # Planos de implementação versionados
  images/                    # Screenshots do dashboard / relatório
logs/                        # execution.log, execution.jsonl, live_state.json (gitignored)
repos/                       # Repositórios alvo clonados (gitignored)
Claude Code agents/          # Material de referência (1.437 .md) — NÃO integrado ao pipeline
soul.md                      # Identidade do agente (EN) — injetada no topo de cada prompt
config.py                    # OLLAMA_SEED, TIMEOUT, modelos, flags via .env
main.py                      # Entry point — orquestra todas as fases
dashboard.html               # Dashboard em tempo real
report.html                  # Visualizador do relatório de refatoração
```

> **Nota:** A pasta `Claude Code agents/` contém o pacote `everything-claude-code` — agentes/skills do ecossistema Claude Code (modelo `sonnet`, tool-use). Não é carregada pelo pipeline (que só usa `skills/` na raiz). Serve como referência para extrair padrões e adaptá-los em código Python ou nas skills locais.

---

## Como Usar

```bash
sdk use java 22-open
source .venv/bin/activate
python main.py
# → informe a URL ou caminho local do repositório Java
# → acompanhe em http://localhost:8000/dashboard.html
# → relatório em  http://localhost:8000/report.html
```

O agente cria branch `refactor/ai-agent-automation`, executa todas as fases, gera `REFACTORING_REPORT.md` e faz commit ao final.

---

Desenvolvido para ser o braço direito do desenvolvedor Java que busca excelência e privacidade total.
