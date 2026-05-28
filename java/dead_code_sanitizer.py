import os
import re
from core.logger import log
from core.utils import read_file, write_file
from java.maven_build import maven_test_with_coverage

# Methods that must never be removed by name
_PROTECTED_NAMES = {
    "main", "toString", "equals", "hashCode", "compareTo",
    "getId", "setId", "getName", "setName", "getValue", "setValue",
    "build", "create", "of", "from", "get", "set", "is",
    "run", "execute", "handle", "process", "apply", "accept",
    "call", "invoke", "init", "close", "destroy", "start", "stop",
}

# Annotations indicating the method is called externally (not by Java code)
_EXTERNAL_ANNOTATIONS = {
    # Spring MVC / REST
    "@GetMapping", "@PostMapping", "@PutMapping", "@DeleteMapping",
    "@PatchMapping", "@RequestMapping",
    # Spring lifecycle / DI
    "@Bean", "@Override", "@PostConstruct", "@PreDestroy",
    # Spring events / scheduling
    "@EventListener", "@Scheduled", "@Async",
    # Messaging
    "@KafkaListener", "@RabbitListener", "@SqsListener",
    # Persistence / validation
    "@Transactional", "@Cacheable", "@CacheEvict",
    # Tests
    "@Test", "@BeforeEach", "@AfterEach", "@BeforeAll", "@AfterAll",
    "@ParameterizedTest",
}


def run_sanitization(repo_path: str):
    log("Starting final project sanitization...", "PHASE")

    main_files = []
    all_files  = []  # main + test — for usage search
    for root, _, files in os.walk(repo_path):
        is_main = "src/main/java" in root
        is_test = "src/test/java" in root
        for f in files:
            if f.endswith(".java"):
                path = os.path.join(root, f)
                all_files.append(path)
                if is_main:
                    main_files.append(path)

    for file in main_files:
        _sanitize_file(file, all_files, repo_path)

    log("Sanitization complete.", "OK")


def _sanitize_file(file_path: str, all_files: list, repo_path: str):
    content = read_file(file_path)
    file_name = os.path.basename(file_path)

    method_pattern = re.compile(
        r'(?:public|private|protected)\s+[\w<>\[\]]+\s+(\w+)\s*\('
    )
    methods = method_pattern.findall(content)

    modified = False
    new_content = content

    for method in methods:
        if method in _PROTECTED_NAMES:
            continue

        if _has_external_annotation(new_content, method):
            continue

        if _is_used_in_project(method, file_path, all_files):
            continue

        log(f"  [Sanitizer] Removing unused method: {file_name} -> {method}()", "WARN")
        pattern_remove = re.compile(
            rf'(?:public|private|protected)[^{{]*?\b{method}\s*\([^)]*\)\s*(?:throws[^{{]*)?\{{[^{{}}]*\}}',
            re.DOTALL,
        )
        candidate = pattern_remove.sub("", new_content)
        if candidate != new_content:
            new_content = candidate
            modified = True

    if modified:
        original = read_file(file_path)
        write_file(file_path, new_content)

        success, _, coverage, _ = maven_test_with_coverage(repo_path, file_name)
        if not success or coverage < 90.0:
            log(f"  [Sanitizer] Sanitization of {file_name} REVERTED (build break or coverage drop)", "ERR")
            write_file(file_path, original)
        else:
            log(f"  [Sanitizer] {file_name} sanitized successfully ✓", "OK")


def _has_external_annotation(content: str, method_name: str) -> bool:
    """Returns True if the method declaration is preceded by an external annotation."""
    decl_pattern = re.compile(
        rf'(?:public|private|protected)\s+[\w<>\[\]]+\s+{re.escape(method_name)}\s*\('
    )
    for match in decl_pattern.finditer(content):
        prefix = content[max(0, match.start() - 300): match.start()]
        for annotation in _EXTERNAL_ANNOTATIONS:
            if annotation in prefix:
                return True
    return False


def _is_used_in_project(method: str, file_path: str, all_files: list) -> bool:
    """Returns True if the method is called or referenced in any project file."""
    call_pattern = re.compile(rf'\b{re.escape(method)}\s*\(')
    ref_pattern  = re.compile(rf'::{re.escape(method)}\b')  # method references (Class::method)
    for other_file in all_files:
        other_content = read_file(other_file)
        if other_file == file_path:
            # In the same file: must appear more than once (declaration does not count)
            if len(call_pattern.findall(other_content)) > 1:
                return True
            if ref_pattern.search(other_content):
                return True
        else:
            if call_pattern.search(other_content) or ref_pattern.search(other_content):
                return True
    return False
