"""
prompt.py — Localização: ai/prompt.py

CORRIGIDO:
  - Import instruction: antes dizia "PRESERVE existing imports" sem exceção.
    O modelo adicionava tipos como Optional<X> no código mas não adicionava
    o import, quebrando o build com "cannot find symbol: class Optional".
  - Agora: preserva imports existentes E adiciona imports obrigatórios para
    qualquer tipo novo introduzido pelo refactoring.
"""


def build_prompt(code: str, rules: str, mode: str, file_name: str) -> str:
    """
    Prompt GENÉRICO — sem conflitos com as fases.

    As FASES definem O QUE fazer (via `rules`).
    O PROMPT define COMO fazer (formato técnico).
    """

    if mode == "test":
        task = (
            f"Write comprehensive JUnit 5 + Mockito unit tests for {file_name}.\n"
            "Include happy path, edge cases, and exception scenarios."
        )
    else:
        task = (
            f"Refactor {file_name} applying the rules below.\n"
            "Preserve existing behavior. Apply only the rules relevant to this file."
        )

    return (
        "You are a senior Java engineer.\n\n"

        "### RULES FROM PHASE\n"
        f"{rules.strip()}\n\n"

        "### TASK\n"
        f"{task}\n\n"

        "### TECHNICAL CONSTRAINTS (MANDATORY)\n"
        "PRESERVE the package declaration exactly as-is.\n"
        "PRESERVE all existing import statements.\n"
        "ADD import statements for any NEW type you introduce in the code.\n"
        "  Example: if you use Optional<X>, add 'import java.util.Optional;'\n"
        "  Example: if you use List<X>, add 'import java.util.List;'\n"
        "PRESERVE method signatures (name, parameters, return type).\n"
        "PRESERVE class-level annotations.\n"
        "DO NOT introduce external dependencies not already in the project.\n"
        "DO NOT modify Spring Boot main class structure.\n\n"

        "### OUTPUT FORMAT (MANDATORY)\n"
        "Return ONLY the complete Java source file.\n"
        "Return exactly ONE code block in ```java format.\n"
        "NO explanations, comments outside code, or multiple blocks.\n"
        "NO markdown before or after the code block.\n"
        "NO ANSI or invisible characters.\n\n"

        "### EXAMPLE OUTPUT FORMAT\n"
        "```java\n"
        "package com.example;\n"
        "\n"
        "import java.util.List;\n"
        "import java.util.Optional;\n"
        "\n"
        "public class Example {\n"
        "    public Optional<String> getItem(String id) {\n"
        "        return Optional.ofNullable(id);\n"
        "    }\n"
        "}\n"
        "```\n\n"

        "### SOURCE FILE TO PROCESS\n"
        "```java\n"
        f"{code}\n"
        "```"
    )