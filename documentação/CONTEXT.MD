# 🧠 CONTEXTO DO PROJETO — AI REFACTOR AGENT (JAVA)

## 🎯 OBJETIVO

Criar um agente automatizado que:

* acessa repositórios no GitHub
* identifica projetos Java
* aplica refatorações baseadas em um padrão central (`CLAUDE.md`)
* valida build
* sobe alterações automaticamente

---

## ⚙️ COMPORTAMENTO DO AGENTE

A cada execução:

```text
1. Busca repositórios do usuário no GitHub
2. Filtra candidatos (linguagem Java ou nome)
3. Clona o repositório em diretório temporário (/tmp)
4. Valida se é projeto Java (pom.xml ou gradle)
5. Injeta/atualiza CLAUDE.md (sempre sobrescreve)
6. Seleciona 1 arquivo .java
7. Envia para IA (Claude) para refatoração
8. Salva backup (.bak)
9. Executa build (Maven/Gradle)
10. Se sucesso:
    - commit controlado
    - push para branch ai/refactor
11. Se falha:
    - rollback do arquivo
12. Marca repo como processado
13. Executa apenas 1 repo por dia
```

---

## 🧠 PADRÃO CENTRAL

Arquivo:

```text
CLAUDE.md
```

Função:

* define regras de refatoração
* guia a IA
* é injetado em todos os repositórios processados

---

## 🔐 CONTROLE DE EXECUÇÃO

### Arquivos locais:

* `processed_repos.txt` → evita reprocessar repos
* `last_run.txt` → limita execução a 1 vez por dia

---

## 🛡️ CONTROLE DE SEGURANÇA

### Evita:

* reprocessamento
* loop infinito
* excesso de uso de API
* commits desnecessários
* inclusão de arquivos indevidos

### Estratégias:

* diretório isolado (`/tmp`)
* limite de tamanho de arquivo (~50KB)
* delay entre execuções
* commit controlado:

```bash
git add -u
git add CLAUDE.md
```

---

## ⚠️ PONTOS CRÍTICOS RESOLVIDOS

### 1. Problema de quota (OpenAI)

* substituído por Claude (Anthropic)

---

### 2. Risco de subir arquivos indesejados

* removido `git add .`
* uso de `git add -u`

---

### 3. Reprocessamento infinito

* resolvido com controle de estado (`processed_repos.txt`)

---

### 4. Execução excessiva

* limitado para **1 repositório por dia**

---

### 5. Falta de visibilidade

* adicionados logs:

  * repos encontrados
  * linguagem detectada
  * decisões de filtro

---

## 🔧 STACK UTILIZADA

* Python 3
* Git
* Maven / Gradle
* API da Anthropic (Claude)
* API do GitHub

---

## 🔑 CONFIGURAÇÃO (.env)

```env
ANTHROPIC_API_KEY=...
GITHUB_TOKEN=...
GITHUB_USERNAME=...
```

---

## 🚀 EXECUÇÃO

```bash
source venv/bin/activate
python agent.py
```

---

## 📂 ESTRATÉGIA DE ISOLAMENTO

* repos são clonados em `/tmp`
* removidos ao final (ou mantidos para debug)
* evita interferência com projeto local

---

## 🧠 LIMITAÇÕES ATUAIS

* processa apenas 1 arquivo por repo
* depende de crédito na API Claude
* depende da detecção de linguagem do GitHub
* não cria Pull Request (push direto em branch)

---

## 🚀 POSSÍVEIS EVOLUÇÕES

* criação automática de PR
* refatoração de múltiplos arquivos
* análise de diff antes de commit
* fallback entre provedores de IA
* execução automática via cron
* controle de custo por execução

---

## 🎯 RESUMO FINAL

Este projeto é um:

```text
Agente autônomo de refatoração Java guiado por padrão central (CLAUDE.md),
com controle de execução, segurança e integração com IA.
```

