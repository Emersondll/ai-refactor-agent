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

> Cada hexágono representa uma classe Java. Cores: verde = refatorado, laranja = pulado (estrutural/conforme), vermelho = falhou, dourado pulsante = processando agora.

### Visualizador de Relatório
![Relatório de Refatoração](docs/images/report_viewer.png)

> Relatório narrativo gerado pela LLM ao final de cada ciclo — acessível em `http://localhost:8000/report.html`.

---

## O que a aplicação faz

O AI Refactor Agent recebe a URL ou caminho local de um repositório Java e executa automaticamente:

1. **Cria uma branch isolada** `refactor/ai-agent-automation` — o `main` nunca é alterado.
2. **Verifica a saúde do projeto** — garante que os testes existentes passam antes de qualquer mudança.
3. **Audita a cobertura** com JaCoCo e, se estiver abaixo de 90%, **gera testes JUnit 5 + Mockito autonomamente** usando LLM local.
4. **Aplica 21 etapas de qualidade** — 8 ferramentas determinísticas (OpenRewrite + GJF) seguidas de 6 fases LLM (método a método, classe completa e por fluxo de endpoint).
5. **Insere Javadoc** nos métodos públicos sem alterar a lógica.
6. **Valida o resultado final** com build completo + JaCoCo.
7. **Gera um relatório narrativo** por classe e faz commit + push na branch isolada.

Cada etapa LLM valida o código gerado com `mvn compile` antes de aceitar — qualquer falha reverte o arquivo e registra o motivo no dashboard.

---

## Instalação rápida com setup.sh

O `setup.sh` é o **ponto de entrada único** para qualquer máquina nova. Ele verifica e instala automaticamente todas as dependências, configura o ambiente e inicia o agente:

```bash
git clone git@github.com:Emersondll/ai-refactor-agent.git
cd ai-refactor-agent
chmod +x setup.sh
./setup.sh
```

### O que o setup.sh faz, passo a passo

| Etapa | O que verifica / instala |
|-------|--------------------------|
| **1. Python 3.12+** | Detecta `python3.12`, `python3.13` ou `python3` compatível. Aborta se não encontrar. |
| **2. SDKMAN** | Instala SDKMAN se ausente (`curl get.sdkman.io`). |
| **3. Java 22-open** | Instala via `sdk install java 22-open` e ativa com `sdk use java 22-open`. Obrigatório para Maven. |
| **4. Ollama (binário)** | Instala Ollama se ausente. Inicia `ollama serve` em background se o serviço não estiver respondendo. |
| **5. Modelos Ollama** | Faz `ollama pull` dos 5 modelos necessários apenas se ainda não estiverem locais. |
| **6. Skills LLM** | Copia os prompts Markdown de `skills/` para `~/.claude/skills/` — cada skill é um fragmento de instrução injetado nos prompts. |
| **7. Virtualenv Python** | Cria `.venv/` se ausente e instala todas as dependências via `pip install -r requirements.txt`. |
| **8. Arquivo .env** | Copia `.env.example` para `.env` se não existir. Pausa para o usuário editar as credenciais antes de continuar. |
| **9. Inicia o agente** | Executa `python3 main.py` com o ambiente totalmente configurado. |

### Relação do setup.sh com os demais arquivos

```
setup.sh
├── lê  requirements.txt        → instala dependências Python no .venv
├── lê  skills/*/SKILL.md       → copia para ~/.claude/skills/ (prompts dos LLMs)
├── copia .env.example → .env   → base de configuração do agente
├── inicia ollama serve         → backend de LLM local consumido por ai/model.py
└── executa python3 main.py     → orquestra todo o pipeline
```

O `setup.sh` não é necessário em máquinas onde tudo já está instalado — basta `source .venv/bin/activate && python main.py`. Ele existe para garantir que um desenvolvedor com uma máquina zerada consiga executar o agente com **um único comando**.

---

## Etapas de Refatoração no Dashboard

O dashboard exibe 21 etapas organizadas em 5 grupos:

### ⚙️ Infraestrutura

| # | Etapa | O que faz |
|---|-------|-----------|
| 1 | **Branch** | Cria a branch `refactor/ai-agent-automation` isolada. Nunca altera o main. |
| 2 | **Health Check** | Executa `mvn test` no estado original. Pré-condição obrigatória — se algum teste já está quebrado, o agente para aqui e reporta antes de fazer qualquer mudança. |
| 3 | **Auditoria** | Mede a cobertura atual com JaCoCo. Determina quantas classes precisam de testes antes de iniciar a refatoração. |
| 4 | **Cobertura 90%** | Gera testes JUnit 5 + Mockito por LLM para cada classe abaixo de 90%. Classes com apenas campos + getters/setters recebem testes determinísticos (sem LLM). Gate: só avança com ≥ 90% garantida. |

### 🔧 Community 01–08 (Ferramentas Determinísticas)

| # | Etapa | O que faz |
|---|-------|-----------|
| 5 | **clean-imports** | OpenRewrite: remove imports não utilizados e reorganiza a ordem de imports segundo o padrão Java. |
| 6 | **format** | Google Java Format: formata todo o código segundo o Google Java Style — indentação, espaços, quebras de linha. |
| 7 | **final-keywords** | OpenRewrite: adiciona `final` em variáveis locais e parâmetros que nunca são reatribuídos. Melhora legibilidade e previne mutação acidental. |
| 8 | **naming** | OpenRewrite: corrige nomes fora do padrão Java — camelCase para variáveis/métodos, UPPER_SNAKE_CASE para constantes. |
| 9 | **dead-code** | OpenRewrite: detecta e remove métodos privados, variáveis e imports nunca utilizados. |
| 10 | **simplify** | OpenRewrite: simplifica expressões booleanas redundantes, null checks verbosos e condicionais desnecessários. |
| 11 | **modernize** | OpenRewrite: migra para sintaxe moderna — switch expressions, `var`, text blocks (Java 14–21). |
| 12 | **static-analysis** | OpenRewrite: aplica regras PMD e SpotBugs — detecta bugs potenciais e code smells estáticos. |

### 🧠 LLM por Classe 09–12

| # | Etapa | O que faz |
|---|-------|-----------|
| 13 | **guard-clauses** | LLM: converte `if`s aninhados com profundidade ≥ 3 em early return. Processa método a método para reduzir o contexto enviado. |
| 14 | **method-extract** | LLM: extrai métodos com mais de 30 linhas em helpers privados com nomes descritivos. Processa método a método. |
| 15 | **solid-dip** | LLM: substitui `new ConcreteService()` por injeção via construtor (Dependency Inversion Principle). Envia a classe completa para manter contexto das dependências internas. |
| 16 | **ctrl-lean** | LLM: remove lógica de negócio de `@RestController`, delegando ao Service (Single Responsibility Principle). Processa método a método. |

### 🔀 LLM por Fluxo 13–14

| # | Etapa | O que faz |
|---|-------|-----------|
| 17 | **flow-refactor** | LLM por endpoint: mapeia a cadeia controller→service→repository de cada endpoint e refatora cada arquivo com o contexto completo do fluxo. Arquivos compartilhados entre fluxos são processados com teste completo imediatamente. |
| 18 | **dry-check** | LLM por grupo: detecta métodos com lógica idêntica ou muito similar em 2+ arquivos e extrai para uma classe utilitária estática (`XyzUtils`). |

### ✅ Finalização

| # | Etapa | O que faz |
|---|-------|-----------|
| 19 | **Sanitização** | Remove imports soltos, código morto e métodos privados não utilizados gerados pelas fases LLM anteriores. |
| 20 | **Validação** | `mvn test` + JaCoCo: confirma build OK e cobertura ≥ 90% mantida após todas as refatorações. |
| 21 | **Commit + Push** | `git commit` + push para a branch `refactor/ai-agent-automation`. Retry automático com rebase em caso de non-fast-forward. |

---

## Variáveis de Ambiente (`.env`)

Copie `.env.example` para `.env` e configure conforme necessário. O `setup.sh` faz isso automaticamente na primeira execução.

### Credenciais

| Variável | Obrigatório | O que faz |
|----------|-------------|-----------|
| `ANTHROPIC_API_KEY` | Não — só se `USE_CLAUDE_FALLBACK=true` | Chave da API Anthropic. Usada como fallback quando os modelos locais esgotam todas as tentativas de repair. Sem essa chave, o fallback é simplesmente desativado. |
| `GITHUB_TOKEN` | Sim para push em repos privados | Token GitHub com permissão de escrita (`repo` scope) no repositório alvo. Sem ele, o push final da etapa 21 falha em repos privados. |
| `GITHUB_USERNAME` | Sim se `GITHUB_TOKEN` definido | Usuário GitHub associado ao token. Usado para montar a URL autenticada de push. |
| `REPO_GITHUB_URL` | Não | URL pública do repositório sendo refatorado (ex: `https://github.com/org/repo`). Aparece no cabeçalho do `REFACTORING_REPORT.md` commitado dentro do repo alvo — apenas cosmético. |

### Modelos Ollama

Todos os modelos são opcionais — se não configurados, os padrões de `config.py` são usados. Os 5 modelos foram separados por responsabilidade para permitir trocar um sem afetar os outros.

| Variável | Padrão | O que faz |
|----------|--------|-----------|
| `MODEL_DOC` | `qwen2.5-coder:7b` | Modelo para inserção de Javadoc e adição de `final`. Deve ser code-aware e conservador — apenas documenta e anota, nunca altera lógica. Modelos menores (7b) funcionam bem aqui. |
| `MODEL_STRUCT` | `qwen2.5-coder:7b` | Modelo para tarefas estruturais: geração de esqueletos de classe, extração de assinaturas de métodos, helpers de contexto. Não precisa de criatividade — consistência é mais importante. |
| `MODEL_CLEAN` | `gemma4:latest` | Modelo para Clean Code e geração de testes JUnit 5. É o modelo com maior volume de trabalho: processa cada classe gerando testes completos com Mockito, repair loop incluído. Modelos mais capazes produzem testes que passam na primeira tentativa. |
| `MODEL_SOLID` | `qwen2.5-coder:14b` | Modelo para fases SOLID e arquitetura (guard-clauses, method-extract, solid-dip, ctrl-lean). Precisa entender padrões de design e refatorar sem quebrar comportamento. Recomendado: modelos 14b+ code-aware. |
| `MODEL_RECOVERY` | `qwen2.5-coder:14b` | Modelo do repair loop — entra em ação quando o código gerado não compila ou os testes falham. Idealmente diferente de `MODEL_CLEAN` para oferecer uma segunda perspectiva real sobre o problema. Se for o mesmo modelo, o repair ainda funciona mas com menos diversidade. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Endereço do servidor Ollama. Altere se o Ollama estiver em outro host ou porta (ex: container Docker em `http://192.168.1.10:11434`). |
| `OLLAMA_SEED` | `42` | Semente de aleatoriedade fixa no Ollama. Torna a geração reproduzível entre execuções do mesmo arquivo com o mesmo prompt — os "fixes" ficam estáveis em vez de variar a cada run. Troque para `0` para comportamento não-determinístico. |

### Flags de Execução

| Variável | Padrão | O que faz |
|----------|--------|-----------|
| `USE_CLAUDE_FALLBACK` | `false` | Quando `true`, usa Claude (API Anthropic) como último recurso no repair loop, após `MODEL_RECOVERY` esgotar suas tentativas. Exige `ANTHROPIC_API_KEY`. O código gerado pelo Claude nunca é aceito diretamente — passa pelo mesmo ciclo de validação Maven. |
| `USE_AGENT_MODE` | `false` | Quando `true`, ativa o loop agêntico: Claude planeja dinamicamente quais fases executar com base no estado atual do projeto, em vez de seguir o pipeline fixo de 21 etapas. Mais flexível, menos previsível. `false` é o modo recomendado para uso em produção. |
| `AGENT_MAX_CYCLES` | `20` | Número máximo de ciclos de planejamento no modo agente (`USE_AGENT_MODE=true`) antes de parar. Evita loops infinitos em projetos complexos. |
| `PLANNER_MODE` | `local` | `local` = planejador roda inteiramente offline com modelo Ollama. `claude` = Claude API planeja as fases, Ollama executa. Só relevante quando `USE_AGENT_MODE=true`. |

### Features Opcionais

Todas desabilitadas por padrão. Cada uma adiciona dependências externas — instale-as antes de ativar.

| Variável | Padrão | O que faz |
|----------|--------|-----------|
| `USE_LLMLINGUA` | `false` | Comprime o `dep_context` (contexto de dependências da classe) antes de enviar ao LLM usando o modelo BERT multilingual da Microsoft. Reduz tokens em até 50% sem perda semântica significativa. **Nunca comprime o código-fonte** — só o contexto auxiliar. Requer `pip install llmlingua`. |
| `USE_RAG_CONTEXT` | `false` | Ativa recuperação semântica de contexto com LlamaIndex + ChromaDB. Em vez de incluir todos os imports como contexto, busca apenas os mais semanticamente relevantes para a classe atual. Requer `pip install llama-index chromadb`. |
| `USE_MEM0` | `false` | Memória semântica persistente entre execuções via Mem0 + Ollama. O agente lembra de padrões que funcionaram ou falharam em runs anteriores do mesmo repositório. Requer `pip install mem0ai`. |
| `USE_CONTEXT7` | `false` | Busca documentação técnica ao vivo via Context7 MCP e injeta no prompt antes da chamada LLM. Útil para bibliotecas recentes cujo conhecimento pode estar desatualizado nos modelos locais. Requer conexão com internet. |

---

## Instalação manual

Se preferir configurar manualmente ao invés de usar o `setup.sh`:

```bash
git clone git@github.com:Emersondll/ai-refactor-agent.git
cd ai-refactor-agent

# Ambiente Python
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Java 22 via SDKMAN (obrigatório para Maven)
sdk install java 22-open
sdk use java 22-open

# Configuração
cp .env.example .env   # edite GITHUB_TOKEN e GITHUB_USERNAME

# Modelos Ollama (apenas 2 físicos em RAM simultaneamente)
ollama pull qwen2.5-coder:14b   # MODEL_SOLID + MODEL_RECOVERY
ollama pull qwen2.5-coder:7b    # MODEL_DOC + MODEL_STRUCT

# Executar
python main.py
```

### Dependências necessárias

- **Ollama** em execução local (`ollama serve`)
- **Python 3.12+**
- **Maven** + **Java 22** via SDKMAN (`sdk use java 22-open` antes de qualquer Maven)

---

## Como usar

```bash
# Executar (ambiente já configurado)
sdk use java 22-open
source .venv/bin/activate
python main.py
# → informe a URL ou caminho local do repositório Java quando solicitado
# → acompanhe o progresso em http://localhost:8000/dashboard.html
# → relatório narrativo em    http://localhost:8000/report.html
```

O agente cria a branch `refactor/ai-agent-automation`, executa todas as 21 etapas, gera `REFACTORING_REPORT.md` dentro do repositório alvo e faz commit + push ao final.

### Opções avançadas de linha de comando

```bash
python main.py --list-skips                    # lista arquivos em permanent_skip com motivo
python main.py --clear-skip TransactionControllerTest  # reabilita um arquivo específico
python main.py --clear-all-skips               # limpa todos os permanent_skips
# FORCE_RETRY via .env:
# FORCE_RETRY=TransactionControllerTest,MerchantService   # força retry desses arquivos
```

---

## Dashboard — Observabilidade em Tempo Real

O `dashboard.html` é atualizado a cada 5 segundos lendo `logs/execution.jsonl`.

| Cor do hexágono | Significado |
|-----------------|-------------|
| Cinza | Pendente — ainda não processado nesta execução |
| Dourado pulsante | Processando no momento — LLM ativo |
| Laranja neon | Pulado — record, interface, DTO, @Entity ou código já conforme |
| Verde | Concluído com sucesso |
| Vermelho | Falhou — compile falhou, LLM não gerou código, ou arquivo revertido |

**Recursos do dashboard:**
- **ETC ao vivo**: contador regressivo calculado pela média de tempo por arquivo aceito; após `PIPELINE_COMPLETE` exibe a duração total real (ex: `✓ 3h 44m`)
- **Card de classe ativa**: exibe o arquivo em processamento com cronômetro ao vivo; ao final mostra `✓ Pipeline concluído`
- **Tooltips nos hexágonos**: ao passar o mouse exibe `Arquivo.java::assinaturaDoMétodo` para fases método a método
- **Métricas ao vivo**: cobertura global JaCoCo, % de conteúdo novo inserido, classes modernizadas, % de refatoração de produção e uso de CPU
- **Link do relatório**: botão "Ver Relatório de Refatoração" no topo abre `report.html`

---

## Estrutura do Projeto

```
ai/                          # Prompts, modelos, compressão, roteamento
  prompt.py                  # soul.md + restrições base + build_prompt
  model.py                   # call_model (OLLAMA_SEED), call_ai, repair loop, N9 timeout guard
  agent_router.py            # Roteamento por tipo e complexidade de arquivo
  compressor.py              # LLMLingua — comprime dep_context (nunca o código-fonte)
  sanitizer.py               # clean_output: limpa resposta LLM antes de validar
  context7_client.py         # Docs ao vivo via Context7 MCP (opt-in)
java/
  refactor.py                # generate_tests, _build_active_rules, repair loop, surgical patch
  data_holder_test_gen.py    # Gerador determinístico de testes para data holders (sem LLM)
  output_validator.py        # is_valid_java, validate_class_name, validate_package
  dep_context.py             # get_dependency_context — hints // CONSTRUCTOR CALL:
  maven_build.py             # maven_test, maven_test_with_coverage (JaCoCo), ENV_WRAPPER
  method_extractor.py        # MethodDef — extração sem AST parser
  class_context_builder.py   # compress_done_methods / merge / build_method_context
  method_runner.py           # Runner método a método e classe completa (solid-dip)
  llm_runner.py              # Dispatch para method_runner; _is_structural_type()
  flow_runner.py             # Refatoração por fluxo de endpoint; DRY check
  endpoint_mapper.py         # Análise estática de cadeias controller→service→repository
  community_runner.py        # OpenRewrite / GJF / PMD
  diff_reviewer.py           # APPROVE/REJECT/SKIP por diff do arquivo gerado
  dead_code_sanitizer.py     # Sanitização final — métodos privados, imports soltos
  javadoc_runner.py          # Javadoc em métodos públicos (fase 20)
  report_runner.py           # Relatório narrativo Markdown por classe (fase REPORT)
  large_file_processor.py    # Extração de métodos em arquivos grandes para reduzir contexto
  java_keywords.py           # Dicionário de palavras reservadas e tipos Java
phases/
  configs/                   # 14 arquivos .yml — um por fase LLM
skills/                      # 10 skills LLM — fragmentos de prompt Markdown injetados
  java-refactor-context/     # Base para toda chamada LLM em modo refactor
  java-tdd-unit-test/        # Geração de testes + estratégia de repair
  java-repair-guide/         # Loop de correção pós-falha de build
  java-guard-clauses/        # Fase 13 — early return
  java-method-extraction/    # Fase 14 — extração de métodos longos
  java-solid-dip/            # Fase 15 — injeção de dependência
  java-controller-lean/      # Fase 16 — controller sem lógica de negócio
  java-flow-refactor/        # Fase 17 — refatoração por fluxo de endpoint
  java-dry-extraction/       # Fase 18 — extração de código duplicado
  java-javadoc/              # Fase Javadoc
agent/                       # Loop agêntico (planejador + executor; USE_AGENT_MODE=true)
core/                        # Logger, utilitários, ExecutionLogger, live_state
memory/                      # Cache de fase e método; SemanticMemory (opt-in com Mem0)
dashboard/                   # data.py → dashboard_status.json (lido pelo dashboard.html)
git_utils/
  repo.py                    # clone, branch, commit_and_push, commit_single_file
tests/                       # Suite pytest — java/, ai/, agent/, memory/
docs/
  images/                    # Screenshots do dashboard e relatório
logs/                        # execution.log, execution.jsonl (gitignored)
repos/                       # Repositórios clonados (gitignored)
templates/
  refactoring_report_header.md  # Cabeçalho Markdown do relatório final
soul.md                      # Identidade e regras do agente (EN) — injetado em cada prompt
config.py                    # Centraliza todas as flags, timeouts e modelos lidos do .env
main.py                      # Entry point — orquestra todas as 21 etapas
setup.sh                     # Instalação completa em um comando (SDKMAN, Ollama, venv, skills)
dashboard.html               # Dashboard em tempo real (lê dashboard_status.json)
report.html                  # Visualizador do relatório Markdown de refatoração
```

---

Desenvolvido para ser o braço direito do desenvolvedor Java que busca excelência e total privacidade dos dados.

---

## Desenvolvedor

**Emerson Lima**
Engenheiro de Software — especialista em arquitetura Java, automação e IA aplicada ao desenvolvimento.

- GitHub: [@Emersondll](https://github.com/Emersondll)
- E-mail: emerson.elima@gmail.com
