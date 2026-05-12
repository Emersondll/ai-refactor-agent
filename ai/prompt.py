"""
prompt.py — ai/prompt.py

BASE_CONSTRAINTS: constante global com regras técnicas e formato de output.
  Enviada em toda chamada — não modifique para não quebrar o output format.

build_prompt(): compõe BASE_CONSTRAINTS + phase delta + dep_context separado.
  dep_context é colocado em sua própria seção para ser facilmente identificável.
"""


BASE_CONSTRAINTS = """\
You are a senior Java engineer.

### TECHNICAL CONSTRAINTS (MANDATORY)
PRESERVE the package declaration exactly as-is.
PRESERVE all existing import statements.
ADD import statements for any NEW type you introduce in the code.
  Check the dependency section below for '// SUGGESTED IMPORT' hints.
PRESERVE method signatures (name, parameters, return type).
PRESERVE class-level annotations.
DO NOT create new classes — work within the existing file only.
DO NOT introduce external dependencies not already in the project.
DO NOT modify Spring Boot main class structure.
DO NOT change public API or method signatures.
DO NOT modify existing test code.

### OUTPUT FORMAT (MANDATORY)
Return ONLY the complete Java source file.
Return exactly ONE java code block (triple-backtick java).
NO explanations, NO markdown outside the code block.
NO ANSI or invisible characters.\
"""


def _build_task(mode: str, file_name: str) -> str:
    if mode == "test":
        return (
            f"Escreva testes unitários abrangentes com JUnit 5 + Mockito para a classe '{file_name}'.\n"
            "DIRETRIZES TÉCNICAS:\n"
            "1. PACOTE: Use exatamente o mesmo pacote da classe original.\n"
            "2. IMPORTS: Importe explicitamente Mockito (@Mock, @InjectMocks, Mockito.when), "
            "JUnit 5 (@Test, @BeforeEach, Assertions) e TODAS as dependências.\n"
            "3. MOCKS: Use @InjectMocks na classe sendo testada e @Mock em suas dependências.\n"
            "4. INTEGRIDADE: Verifique as assinaturas da classe original. "
            "Não chame métodos inexistentes.\n"
            "5. COBERTURA: Inclua 'happy path', casos de borda e cenários de erro/exceção.\n"
            "6. JAVA RECORDS: Se encontrar 'record', use o construtor canônico (com todos os argumentos).\n"
            "7. FIDELIDADE: Teste apenas o que o código faz atualmente."
        )
    return (
        f"Refactor {file_name} applying the rules below.\n"
        "Preserve existing behavior. Apply only the rules relevant to this file."
    )


def build_prompt(code: str, phase_delta: str, mode: str, file_name: str,
                 dep_context: str = "") -> str:
    """
    Monta o prompt completo para o modelo.

    Args:
        code: Código Java do arquivo a processar.
        phase_delta: Regras específicas da fase (apenas o que é exclusivo).
        mode: 'refactor' ou 'test'.
        file_name: Nome do arquivo Java (ex: CustomerService.java).
        dep_context: Contexto de dependências compacto (opcional).
    """
    parts = [
        BASE_CONSTRAINTS,
        f"\n### PHASE RULES\n{phase_delta.strip()}",
        f"\n### TASK\n{_build_task(mode, file_name)}",
    ]
    if dep_context and dep_context.strip():
        parts.append(f"\n### DEPENDENCY CONTEXT\n{dep_context.strip()}")
    parts.append(f"\n### SOURCE FILE TO PROCESS\n```java\n{code}\n```")
    return "\n".join(parts)
