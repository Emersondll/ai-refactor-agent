import os
import re
from core.logger import log
from core.utils import read_file, write_file
from java.compiler import maven_test_with_coverage

# Métodos que nunca devem ser removidos por nome
_PROTECTED_NAMES = {
    "main", "toString", "equals", "hashCode", "compareTo",
    "getId", "setId", "getName", "setName", "getValue", "setValue",
    "build", "create", "of", "from", "get", "set", "is",
    "run", "execute", "handle", "process", "apply", "accept",
    "call", "invoke", "init", "close", "destroy", "start", "stop",
}

# Anotações que indicam que o método é chamado externamente (não por código Java)
_EXTERNAL_ANNOTATIONS = {
    # Spring MVC / REST
    "@GetMapping", "@PostMapping", "@PutMapping", "@DeleteMapping",
    "@PatchMapping", "@RequestMapping",
    # Spring lifecycle / DI
    "@Bean", "@Override", "@PostConstruct", "@PreDestroy",
    # Spring eventos / agendamento
    "@EventListener", "@Scheduled", "@Async",
    # Mensageria
    "@KafkaListener", "@RabbitListener", "@SqsListener",
    # Persistência / validação
    "@Transactional", "@Cacheable", "@CacheEvict",
    # Testes
    "@Test", "@BeforeEach", "@AfterEach", "@BeforeAll", "@AfterAll",
    "@ParameterizedTest",
}


def run_sanitization(repo_path: str):
    log("Iniciando sanitização final do projeto...", "PHASE")

    java_files = []
    for root, _, files in os.walk(repo_path):
        if "src/main/java" not in root:
            continue
        for f in files:
            if f.endswith(".java"):
                java_files.append(os.path.join(root, f))

    for file in java_files:
        _sanitize_file(file, java_files, repo_path)

    log("Sanitização concluída.", "OK")


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

        log(f"  [Sanitizer] Removendo método não utilizado: {file_name} -> {method}()", "WARN")
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
            log(f"  [Sanitizer] Sanitização de {file_name} REVERTIDA (quebra ou queda de cobertura)", "ERR")
            write_file(file_path, original)
        else:
            log(f"  [Sanitizer] {file_name} sanitizado com sucesso ✓", "OK")


def _has_external_annotation(content: str, method_name: str) -> bool:
    """Retorna True se a declaração do método for precedida por uma anotação externa."""
    # Encontra todas as ocorrências da declaração do método
    decl_pattern = re.compile(
        rf'(?:public|private|protected)\s+[\w<>\[\]]+\s+{re.escape(method_name)}\s*\('
    )
    for match in decl_pattern.finditer(content):
        # Pega os 300 caracteres antes da declaração para checar anotações
        prefix = content[max(0, match.start() - 300): match.start()]
        for annotation in _EXTERNAL_ANNOTATIONS:
            if annotation in prefix:
                return True
    return False


def _is_used_in_project(method: str, file_path: str, all_files: list) -> bool:
    """Retorna True se o método for chamado em qualquer arquivo do projeto."""
    call_pattern = re.compile(rf'\b{re.escape(method)}\s*\(')
    for other_file in all_files:
        other_content = read_file(other_file)
        if other_file == file_path:
            # No próprio arquivo: precisa aparecer mais de uma vez (declaração não conta)
            if len(call_pattern.findall(other_content)) > 1:
                return True
        else:
            if call_pattern.search(other_content):
                return True
    return False
