# Local AI Code Refactor Agent

Um agente de refatoração Java autônomo e meticuloso, projetado para rodar 100% localmente utilizando Ollama. O agente utiliza uma hierarquia de modelos e "Skills de Elite" para transformar código legado em código limpo, documentado e seguindo princípios SOLID.

## 🚀 Diferenciais e Skills de Elite

Diferente de refatoradores simples, este agente utiliza técnicas avançadas de IA Agentica:

- **Reviewer Pattern (O Crítico Sênior)**: Todo código refatorado por modelos menores passa por uma revisão obrigatória do modelo mais forte (ex: Qwen 2.5 14B), garantindo qualidade sênior.
- **Enforced 90% Coverage (JaCoCo Guardrail)**: O agente exige e valida matematicamente uma cobertura mínima de 90% em testes unitários para o núcleo do sistema antes e depois da refatoração.
- **Vertical Flow Slicing (End-to-End)**: O agente pode operar em modo de fluxo, refatorando fatias completas da aplicação (Controller -> Service -> Repository) para garantir integridade de negócio.
- **Behavioral Context Sync**: Injeta os arquivos de teste unitário no prompt da IA como restrições comportamentais, impedindo que a refatoração quebre regras de negócio existentes.
- **Java 17+ Modernization**: Identificação automática de DTOs e conversão para `record`, aproveitando recursos modernos da linguagem.
- **Post-Refactor Sanitization**: Etapa final que remove métodos órfãos e consolida códigos duplicados (DRY) após a refatoração.
- **Self-Healing Build**: Em caso de falha no Maven, o agente captura o erro de compilação e tenta se "auto-curar" em um novo ciclo de correção.
- **Dependency Context Injection**: O agente analisa os `imports` do projeto e injeta as assinaturas das classes dependentes no prompt, evitando alucinações.

## 🏗️ Estratégia de Modelos (Hierarquia)

O agente otimiza o uso da sua RAM distribuindo tarefas por "Papéis":

- **Ultimate (14B+)**: SOLID, Arquitetura e Revisão Crítica.
- **Advanced (9B)**: Clean Code e Lógica de Negócios.
- **Standard (7B)**: Estrutura e Nomenclatura.
- **Light (4B)**: Javadoc, Imutabilidade (`final`) e Documentação.

## 🛠️ Como Configurar os Modelos Locais

Para que o agente funcione com performance máxima, você deve baixar os modelos correspondentes via [Ollama](https://ollama.com/). Execute os seguintes comandos no seu terminal:

### 1. Modelo Principal de Refatoração (Ultimate)
Este será o responsável pelas revisões críticas e mudanças estruturais pesadas.
```bash
ollama pull qwen2.5-coder:14b
```

### 2. Modelo de Lógica e Clean Code (Advanced)
```bash
ollama pull gemma4:latest
```

### 3. Modelo de Estrutura e Padrões (Standard)
```bash
ollama pull qwen3.5:latest
```

### 4. Modelo de Documentação e Javadoc (Light)
Modelo otimizado para tarefas de texto e imutabilidade.
```bash
ollama pull neural-chat:7b
```

> **Dica:** Se você tiver menos de 16GB de RAM, recomendamos substituir o `14b` pelo `7b` em todas as categorias para garantir estabilidade.

## 🛠️ Requisitos

- **Ollama** (rodando localmente)
- **Python 3.10+**
- **Maven** (para validação de build)
- Modelos recomendados: `qwen2.5-coder:14b`, `gemma2:9b`, `qwen2.5-coder:7b`, `neural-chat`.

## ⚙️ Configuração

1. Clone o repositório.
2. Crie um ambiente virtual: `python -m venv .venv && source .venv/bin/activate`
3. Instale as dependências: `pip install -r requirements.txt`
4. Configure o arquivo `config.py` ou seu arquivo `.env`:
   - `FLOW_MODE=true`: Ativa a refatoração end-to-end por fluxos.
   - `USE_CLAUDE_FALLBACK=true`: Ativa o Claude como modelo de segurança.

## 🏃 Como Usar

Para evitar conflitos com os pacotes do sistema (especialmente no Linux), é recomendável executar o projeto dentro do ambiente virtual que você criou.

1. Ative o ambiente virtual:
2. Execute o orquestrador principal:

```bash
source .venv/bin/activate
python main.py
```

Você verá uma saída similar a esta, aguardando que você informe o repositório a ser trabalhado:

```text
[17:13:09] RUN  ============================================================
[17:13:09] RUN  AI Refactor Agent — Orquestrador Principal
[17:13:09] RUN  ============================================================
Repo URL ou caminho local: {Insira aqui o diretorio do repositório ou url git}
```

Ao inserir a URL do repositório Git ou o caminho local, o agente criará uma branch específica para realizar as alterações.

## 📂 Estrutura do Projeto

- `ai/`: Cérebro do agente (roteamento, prompts e skills).
- `java/`: Especialista em Java (análise de contexto, validação e build).
- `phases/`: Definições das regras de refatoração divididas por tiers.
- `core/`: Utilitários de sistema, logs e execução de processos.

---
Desenvolvido para ser o braço direito do desenvolvedor Java que busca excelência e privacidade total.