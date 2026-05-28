"""
agent_router.py — Location: ai/agent_router.py

Routes each file to the appropriate model priority list based on file type,
complexity, and phase intent (documentation, architecture, test generation).
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
    SIMPLE = 1   # < 50 lines
    MEDIUM = 2   # 50-150 lines
    LARGE  = 3   # > 150 lines


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
    """Returns agent route in priority order, optimized by phase intent."""
    phase_lower = phase.lower()

    # 1. Phase-intent override
    if "javadoc" in phase_lower or "documentation" in phase_lower:
        # Documentation: light first, then standard — avoids loading the heaviest model.
        return ["light", "standard", "advanced", "claude"]

    if "solid" in phase_lower or "architecture" in phase_lower or "patterns" in phase_lower:
        # Architecture: Ultimate/Advanced first.
        return ["ultimate", "advanced", "standard", "claude"]

    if mode == "test" or "test" in phase_lower:
        # advanced (14b) primary — ultimate fallback — standard last resort.
        # 14b reintroduced: produces better code than 7b; OOM was in refactor mode,
        # not in test mode where files are smaller and context is more constrained.
        if complexity == FileComplexity.SIMPLE:
            return ["advanced", "standard", "claude"]
        return ["advanced", "ultimate", "standard", "claude"]

    # 2. Critical cases by size
    if complexity == FileComplexity.LARGE:
        return ["ultimate", "advanced", "standard", "claude"]

    # 3. Default routing by file type
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
    # Note: USE_CLAUDE_FALLBACK=false is a hard block in _run_pipeline — this function
    # is only consulted when the flag is true or all local models failed.
    if complexity == FileComplexity.LARGE:
        return True
    if file_type == FileType.SERVICE and complexity in (FileComplexity.MEDIUM, FileComplexity.LARGE):
        return True
    if attempts_failed >= 2:
        return True
    return False