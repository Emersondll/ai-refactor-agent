"""
agent_router.py — Localização: ai/agent_router.py

ATUALIZADO:
  - Adicionado "gemma" como 4º agente local na rota
  - dolphin agora aponta para qwen3.5 via config (transparente aqui)
  - Rota padrão: neural-chat → mistral → dolphin → gemma → claude
"""

import re
from enum import Enum


class FileType(Enum):
    REPOSITORY = "repository"
    SERVICE    = "service"
    CONTROLLER = "controller"
    DOCUMENT   = "document"
    MODEL      = "model"
    TEST       = "test"
    OTHER      = "other"


class FileComplexity(Enum):
    SIMPLE = 1   # < 50 linhas
    MEDIUM = 2   # 50-150 linhas
    LARGE  = 3   # > 150 linhas


def analyze_file(code: str, file_path: str) -> tuple[FileType, FileComplexity]:
    normalized = file_path.replace("\\", "/").lower()
    file_name  = normalized.split("/")[-1]
    line_count = len(code.splitlines())

    if line_count < 50:    complexity = FileComplexity.SIMPLE
    elif line_count < 150: complexity = FileComplexity.MEDIUM
    else:                  complexity = FileComplexity.LARGE

    if "repository" in file_name:
        return (FileType.REPOSITORY if ("extends" in code and "Repository" in code)
                else FileType.SERVICE), complexity
    if "controller" in file_name:
        return FileType.CONTROLLER, complexity
    if "document" in file_name or "entity" in file_name:
        return FileType.DOCUMENT, complexity
    if "model" in file_name or "dto" in file_name or "record" in file_name:
        return FileType.MODEL, complexity
    if "test" in file_name:
        return FileType.TEST, complexity
    if re.search(r'@RestController|@Controller', code):
        return FileType.CONTROLLER, complexity
    if re.search(r'@Service|implements.*Service|ServiceImpl', code):
        return FileType.SERVICE, complexity
    if re.search(r'@Document|@Entity', code):
        return FileType.DOCUMENT, complexity
    if re.search(r'@Test|extends.*TestCase', code):
        return FileType.TEST, complexity
    return FileType.OTHER, complexity


def select_agent_priority(file_type: FileType, complexity: FileComplexity,
                          mode: str, phase: str = "") -> list[str]:
    """
    Retorna rota de agentes em ordem de prioridade.
    Otimiza o uso de modelos baseando-se na INTENÇÃO da fase.
    """
    phase_lower = phase.lower()
    
    # 1. Prioridade por intenção da fase (Override)
    if "javadoc" in phase_lower or "documentation" in phase_lower:
        # Documentação: light primeiro, depois standard. Evita usar o modelo mais pesado.
        return ["light", "standard", "advanced", "claude"]
    
    if "solid" in phase_lower or "architecture" in phase_lower or "patterns" in phase_lower:
        # Arquitetura: Ultimate/Advanced primeiro.
        return ["ultimate", "advanced", "standard", "claude"]

    if mode == "test" or "test" in phase_lower:
        return ["ultimate", "advanced", "standard", "claude"]

    # 2. Casos críticos por tamanho
    if complexity == FileComplexity.LARGE:
        return ["ultimate", "advanced", "standard", "claude"]

    # 3. Mapeamento padrão por tipo de arquivo
    routing_map = {
        FileType.REPOSITORY: ["ultimate", "advanced", "standard", "claude"],
        FileType.SERVICE:    ["ultimate", "advanced", "standard", "claude"],
        FileType.CONTROLLER: ["ultimate", "advanced", "standard", "claude"],
        FileType.DOCUMENT:   ["advanced", "standard", "light", "claude"],
        FileType.MODEL:      ["standard", "light", "claude"],
        FileType.OTHER:      ["standard", "light", "ultimate", "claude"],
    }
    return routing_map.get(file_type, routing_map[FileType.OTHER])


def should_use_claude(file_type: FileType, complexity: FileComplexity,
                      mode: str, attempts_failed: int) -> bool:
    if mode == "test":
        return True
    if complexity == FileComplexity.LARGE:
        return True
    if file_type == FileType.SERVICE and complexity in (FileComplexity.MEDIUM, FileComplexity.LARGE):
        return True
    if attempts_failed >= 2:
        return True
    return False