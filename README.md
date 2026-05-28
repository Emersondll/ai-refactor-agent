# AI Refactor Agent

Agente autônomo de refatoração Java que executa **100% localmente** via Ollama.

Ele analisa o repositório Java alvo, garante cobertura de testes ≥ 90%, aplica 21 etapas de qualidade (ferramentas determinísticas + LLM método a método) e nunca quebra o build Maven — tudo sem enviar código para a nuvem.

---

## Screenshots do Dashboard

### Visão Geral — Pipeline e Métricas
![Dashboard — Pipeline e métricas](docs/images/dashboard_overview.png)

> Pipeline de 21 etapas com status ao vivo, cobertura de testes, ETC e modelo LLM ativo.

### Mapa de Classes (Honeycomb)
![Dashboard — Honeycomb de arquivos](docs/images/dashboard_full.png)

> Cada hexágono representa uma classe Java. Cores: verde = refatorado, laranja = pulado (estrutural/conforme), vermelho = revertido, dourado = processando.

### Visualizador de Relatório
![Relatório de Refatoração](docs/images/report_viewer.png)

> Relatório narrativo gerado pela LLM ao final de cada ciclo — acessível em `http://localhost:8000/report.html`.

---

## O que a aplicação faz

O AI Refactor Agent recebe a URL ou caminho local de um repositório Java e executa automaticamente:

1. **Cria uma branch isolada** `refactor/ai-agent-automation` — o `main` nunca é alterado.
2. **Verifica a saúde do projeto** — garante que os testes existentes passam antes de qualquer mudança.
3. **Audita a cobertura** com JaCoCo e, se estiver abaixo de 90%, **gera testes JUnit 5 + Mockito autonomamente** usando LLM local.
4. **Aplica 14 fases de qualidade** (8 ferramentas determinísticas + 6 fases LLM) — sempre validando com `mvn test` após cada mudança.
5. **Insere Javadoc** nos métodos públicos sem alterar a lógica.
6. **Valida o resultado final** com build + JaCoCo.
7. **Gera um relatório narrativo** por classe e faz commit + push na branch.

---

## Etapas de Refatoração no Dashboard

O dashboard exibe 21 etapas organizadas em 5 grupos:

### ⚙️ Infraestrutura

| # | Etapa | O que faz |
|---|-------|-----------|
| 1 | **Branch** | Cria a branch `refactor/ai-agent-automation` isolada. Nunca altera o main. |
| 2 | **Health Check** | Executa `mvn test` no estado original para garantir que os testes já passam antes de qualquer mudança — pré-condição obrigatória. |
| 3 | **Auditoria** | Mede a cobertura atual com JaCoCo. Determina se a geração de testes é necessária antes de iniciar a refatoração. |
| 4 | **Cobertura 90%** | Se cobertura < 90%: gera testes JUnit 5 + Mockito com LLM por classe. Gate: só avança para refatoração com ≥ 90%. |

### 🔧 Community 01–08 (Ferramentas Determinísticas)

| # | Etapa | O que faz |
|---|-------|-----------|
| 5 | **clean-imports** | OpenRewrite: remove imports não utilizados e reorganiza a ordem de imports. |
| 6 | **format** | Google Java Format: aplica formatação padrão (Google Java Style). |
| 7 | **final-keywords** | OpenRewrite: adiciona `final` em variáveis locais e parâmetros que nunca são reatribuídos. |
| 8 | **naming** | OpenRewrite: corrige nomes fora do padrão Java — camelCase, UPPER_SNAKE_CASE para constantes. |
| 9 | **dead-code** | OpenRewrite: detecta e remove métodos privados e variáveis nunca utilizados. |
| 10 | **simplify** | OpenRewrite: simplifica expressões booleanas, null checks verbosos e condicionais redundantes. |
| 11 | **modernize** | OpenRewrite: migra para sintaxe moderna — switch expressions, var, text blocks (Java 14–21). |
| 12 | **static-analysis** | OpenRewrite: aplica regras de PMD e SpotBugs — detecta bugs e code smells estáticos. |

### 🧠 LLM por Classe 09–12

| # | Etapa | O que faz |
|---|-------|-----------|
| 13 | **guard-clauses** | LLM 7B: converte `if`s aninhados (profundidade ≥ 3) em early return. |
| 14 | **method-extract** | LLM 7B: extrai métodos com mais de 30 linhas em helpers privados descritivos. |
| 15 | **solid-dip** | LLM 7B: substitui `new ConcreteService()` por injeção via construtor (DIP do SOLID). |
| 16 | **ctrl-lean** | LLM 7B: remove lógica de negócio de `@RestController`, delegando ao Service (SRP). |

### 🔀 LLM por Fluxo 13–14

| # | Etapa | O que faz |
|---|-------|-----------|
| 17 | **flow-refactor** | LLM por endpoint: mapeia controller→service→repository e refatora cada arquivo com contexto do fluxo completo. |
| 18 | **dry-check** | LLM por grupo: detecta métodos repetidos em 2+ arquivos e extrai para classe utilitária static (princípio DRY). |

### ✅ Finalização

| # | Etapa | O que faz |
|---|-------|-----------|
| 19 | **Sanitização** | Remove imports soltos e código morto residual gerado pelas fases anteriores. |
| 20 | **Validação** | `mvn test` + JaCoCo: confirma build OK e cobertura ≥ 90% mantida após todas as refatorações. |
| 21 | **Commit + Push** | `git commit` + push para a branch. Retry automático com rebase em caso de non-fast-forward. |

---

## Variáveis de Ambiente (`.env`)

Copie `.env.example` para `.env` e configure conforme necessário.

### Modelos Ollama

| Variável | Padrão | Valores aceitos | O que faz |
|----------|--------|-----------------|-----------|
| `MODEL_DOC` | `qwen2.5-coder:7b` | qualquer modelo Ollama | Modelo para Javadoc e `final` — code-aware: não altera estrutura, só documenta |
| `MODEL_STRUCT` | `qwen2.5-coder:7b` | qualquer modelo Ollama | Modelo para estrutura e nomenclatura Java |
| `MODEL_CLEAN` | `gemma4:latest` | qualquer modelo Ollama | Modelo para Clean Code e geração de testes |
| `MODEL_SOLID` | `qwen2.5-coder:14b` | qualquer modelo Ollama | Modelo para SOLID, arquitetura — o mais crítico |
| `MODEL_RECOVERY` | `qwen2.5-coder:14b` | qualquer modelo Ollama | Modelo para autocura (repair loop) — deve ser diferente de MODEL_CLEAN para segundo ponto de vista real |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | URL do servidor Ollama | Endereço do Ollama local |
| `OLLAMA_SEED` | `42` | número inteiro | Semente fixa no Ollama — torna a geração reproduzível entre execuções |

### Flags de Execução

| Variável | Padrão | Valores aceitos | O que faz |
|----------|--------|-----------------|-----------|
| `USE_CLAUDE_FALLBACK` | `false` | `true` / `false` | Permite usar Claude (API Anthropic) como fallback quando os modelos locais falham. Requer `ANTHROPIC_API_KEY`. |
| `USE_AGENT_MODE` | `false` | `true` / `false` | `true` = loop agêntico (Claude planeja, Ollama executa). `false` = pipeline fixo de 14 fases. |
| `AGENT_MAX_CYCLES` | `20` | número inteiro | Número máximo de ciclos no modo agente antes de parar. |
| `PLANNER_MODE` | `local` | `local` / `claude` | `local` = planejador local (totalmente offline). `claude` = Claude API planeja, Ollama executa. |

### Features Opcionais

| Variável | Padrão | Valores aceitos | O que faz |
|----------|--------|-----------------|-----------|
| `USE_LLMLINGUA` | `false` | `true` / `false` | Comprime o `dep_context` (contexto de dependências) antes de enviar ao LLM. Nunca comprime o código fonte. Reduz tokens sem perder semântica. |
| `USE_RAG_CONTEXT` | `false` | `true` / `false` | Ativa LlamaIndex + ChromaDB para recuperação semântica de contexto. Requer dependências extras. |
| `USE_MEM0` | `false` | `true` / `false` | Memória semântica entre execuções via Mem0. Permite ao agente lembrar de padrões de runs anteriores. |
| `USE_CONTEXT7` | `false` | `true` / `false` | Busca documentação ao vivo via Context7 MCP e injeta no prompt. Útil para bibliotecas recentes. |

### Credenciais

| Variável | Obrigatório | O que faz |
|----------|-------------|-----------|
| `ANTHROPIC_API_KEY` | Não (só se `USE_CLAUDE_FALLBACK=true`) | Chave da API Anthropic para usar Claude como fallback ou planejador. |
| `GITHUB_TOKEN` | Não (só para push em repos privados) | Token GitHub com permissão de escrita para o repositório alvo. |
| `GITHUB_USERNAME` | Não | Usuário GitHub associado ao token. |

---

## Instalação

```bash
git clone git@github.com:Emersondll/ai-refactor-agent.git
cd ai-refactor-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # configure os modelos e flags
sdk use java 22-open
python main.py
```

### Dependências necessárias

- **Ollama** em execução local (`ollama serve`)
- **Python 3.12+**
- **Maven** + **Java 22** via SDKMAN

```bash
sdk use java 22-open   # necessário antes de qualquer comando Maven

# Modelos recomendados (apenas 2 físicos em RAM):
ollama pull qwen2.5-coder:14b   # Ultimate / Advanced / Recovery
ollama pull qwen2.5-coder:7b    # Standard / Light
```

---

## Como usar

```bash
sdk use java 22-open
source .venv/bin/activate
python main.py
# → informe a URL ou caminho local do repositório Java
# → acompanhe em http://localhost:8000/dashboard.html
# → relatório em  http://localhost:8000/report.html
```

O agente cria a branch `refactor/ai-agent-automation`, executa todas as fases, gera `REFACTORING_REPORT.md` e faz commit ao final.

---

## Dashboard — Observabilidade em Tempo Real

O `dashboard.html` é atualizado a cada 5 segundos com dados de `logs/execution.jsonl`.

| Cor do hexágono | Significado |
|-----------------|-------------|
| Cinza | Pendente (ainda não processado) |
| Dourado pulsante | Processando no momento |
| Laranja neon | Pulado (record/interface/DTO/entity — sem lógica de negócio, ou código já conforme) |
| Verde | Concluído com sucesso |
| Vermelho | Falhou / autocurado (compile falhou, arquivo revertido) |

**Recursos do dashboard:**
- **ETC ao vivo**: contador regressivo; após `PIPELINE_COMPLETE` mostra duração real (`✓ 3h 44m`) e muda o rótulo para "Duração Total"
- **Card de classe ativa**: exibe o arquivo em processamento com cronômetro; ao concluir mostra `✓ Pipeline concluído`
- **Tooltips nos hexágonos**: ao passar o mouse exibe `Arquivo.java::assinaturaDoMétodo` para fases método a método
- **Fase COMMIT_PUSH**: marcada automaticamente como `done` ao final
- **Link do relatório**: botão "Ver Relatório de Refatoração" no topo abre `report.html`

```bash
# Servidor do dashboard (main.py inicia automaticamente)
python3 -m http.server 8000
# Dashboard:  http://localhost:8000/dashboard.html
# Relatório:  http://localhost:8000/report.html
```

---

## Estrutura do Projeto

```
ai/                          # Prompts, modelos, compressão, roteamento
  prompt.py                  # _SOUL + BASE_CONSTRAINTS + build_prompt
  model.py                   # call_model (OLLAMA_SEED P1), call_ai, repair loop
  agent_router.py            # Roteamento por tipo/complexidade de arquivo
  compressor.py              # LLMLingua (apenas dep_context, nunca o código)
  sanitizer.py               # clean_output: limpa resposta LLM
  context7_client.py         # Docs ao vivo (opt-in)
java/
  refactor.py                # generate_tests, _build_active_rules, _try_surgical_patch
  data_holder_test_gen.py    # Gerador determinístico — sem LLM (P0)
  validator.py               # is_valid_java, validate_class_name/package
  context.py                 # get_dependency_context, hints // CONSTRUCTOR CALL:
  compiler.py                # maven_test, maven_test_with_coverage (JaCoCo)
  method_extractor.py        # MethodDef sem AST parser
  class_builder.py           # compress / merge / build_method_context
  method_runner.py           # Runner método a método e classe completa
  llm_runner.py              # Dispatch; _is_structural_type()
  flow_runner.py             # Refatoração por fluxo de endpoint; DRY check
  flow_mapper.py             # Análise estática de cadeias de endpoint
  community_runner.py        # OpenRewrite / GJF / PMD
  llm_reviewer.py            # APPROVE/REJECT/SKIP por diff
  sanitizer.py               # Sanitização final (remoção de métodos privados)
  javadoc_runner.py          # Javadoc em métodos públicos
  report_runner.py           # Relatório narrativo Markdown por classe
phases/
  configs/                   # 14 arquivos .yml — um por fase
skills/                      # 10 skills LLM (trechos de prompt Markdown)
  java-refactor-context/     # Base para toda chamada LLM em modo refactor
  java-tdd-unit-test/        # Geração de testes + estratégia de repair
  java-repair-guide/         # Loop de correção do validator
  java-guard-clauses/        # Fase 09
  java-method-extraction/    # Fase 10
  java-solid-dip/            # Fase 11
  java-controller-lean/      # Fase 12
  java-flow-refactor/        # Fase 13
  java-dry-extraction/       # Fase 14
  java-javadoc/              # Fase JAVADOC
agent/                       # Loop agêntico (planejador + executor; USE_AGENT_MODE)
core/                        # Logger, utilitários, ExecutionLogger, live_state
memory/                      # Cache de fase e método; SemanticMemory (opt-in)
dashboard/                   # data.py → dashboard_status.json (10s)
git_utils/
  repo.py                    # clone, branch, commit_and_push, commit_single_file
tests/                       # Suite pytest — java/, ai/, agent/, memory/
docs/
  images/                    # Screenshots do dashboard e relatório
logs/                        # execution.log, execution.jsonl (gitignored)
repos/                       # Repositórios clonados (gitignored)
soul.md                      # Identidade do agente (EN) — injetado no topo de cada prompt
config.py                    # OLLAMA_SEED, TIMEOUT, modelos, flags via .env
main.py                      # Entry point — orquestra todas as fases
dashboard.html               # Dashboard em tempo real
report.html                  # Visualizador do relatório de refatoração
```

---

Desenvolvido para ser o braço direito do desenvolvedor Java que busca excelência e total privacidade.
