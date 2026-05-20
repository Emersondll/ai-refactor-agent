"""
refactor.py — Localização: java/refactor.py

CORRIGIDO:
  - Ao rejeitar por validator, reencaminha o código inválido + motivo
    de volta ao call_ai para que o modelo corrija especificamente o problema.
  - Máximo de MAX_VALIDATOR_RETRIES ciclos de correção antes de desistir.
"""

import os
import re
import json
import time
from datetime import datetime

from core.logger import log
from core.live_state import update as _live
from core.utils import read_file, write_file
from core.reporter import PhaseReporter
from core.execution_logger import ExecutionLogger
from ai.model import call_ai, call_ai_with_correction
from java.validator import is_valid_java, validate_package_matches_path
from java.compiler import maven_test, maven_test_with_coverage
from java.scope_reducer import (
    is_large_file,
    extract_class_header,
    get_processable_methods,
    build_method_context,
    extract_refactored_method,
    replace_method_in_file,
)


LARGE_FILE_THRESHOLD    = 100
MAX_FILE_LINES          = 500
MAX_VALIDATOR_RETRIES   = 3    # tentativas de correção após rejeição do validator
MAX_BUILD_FAILURES      = 3    # falhas de build acumuladas antes de pular o arquivo
MAX_TEST_FILE_TIMEOUT_S = 1200  # 20 min máximo por arquivo de teste — escala com TIMEOUT_TEST(300s) × (MAX_VALIDATOR_RETRIES+1)

_REASON_NO_CHANGE = "no_change"  # sinal: modelo confirmou que não há alterações

# S1/S2: mapa de tipos JDK que LLMs frequentemente usam sem importar
_JDK_IMPORT_MAP: dict[str, str] = {
    "BigDecimal":    "import java.math.BigDecimal;",
    "BigInteger":    "import java.math.BigInteger;",
    "LocalDate":     "import java.time.LocalDate;",
    "LocalDateTime": "import java.time.LocalDateTime;",
    "LocalTime":     "import java.time.LocalTime;",
    "ZonedDateTime": "import java.time.ZonedDateTime;",
    "OffsetDateTime":"import java.time.OffsetDateTime;",
    "Instant":       "import java.time.Instant;",
    "Duration":      "import java.time.Duration;",
    "Period":        "import java.time.Period;",
    "UUID":          "import java.util.UUID;",
    "ArrayList":     "import java.util.ArrayList;",
    "LinkedList":    "import java.util.LinkedList;",
    "HashMap":       "import java.util.HashMap;",
    "LinkedHashMap": "import java.util.LinkedHashMap;",
    "HashSet":       "import java.util.HashSet;",
    "LinkedHashSet": "import java.util.LinkedHashSet;",
    "Collections":   "import java.util.Collections;",
    "Arrays":        "import java.util.Arrays;",
    "Optional":      "import java.util.Optional;",
    "Objects":       "import java.util.Objects;",
    "Stream":        "import java.util.stream.Stream;",
    "Collectors":    "import java.util.stream.Collectors;",
    "AtomicInteger": "import java.util.concurrent.atomic.AtomicInteger;",
    "AtomicLong":    "import java.util.concurrent.atomic.AtomicLong;",
}


def _auto_inject_missing_imports(test_code: str, prod_imports: list[str]) -> str:
    """
    S1: Após geração LLM, injeta deterministicamente imports ausentes no teste.
    Cruza nomes de classe usados no código com prod_imports (do fonte de produção)
    e _JDK_IMPORT_MAP. Não envolve LLM — é uma correção estrutural pura.
    """
    # Monta mapa nome-curto → import completo a partir dos imports de produção
    prod_map: dict[str, str] = {}
    for imp in prod_imports:
        m = re.match(r'import\s+([\w.]+);', imp)
        if m:
            short = m.group(1).split(".")[-1]
            prod_map[short] = imp

    # Coleta imports que já existem no teste gerado
    existing_imports = set(re.findall(r'^import\s+[\w.*]+;', test_code, re.MULTILINE))
    existing_short: set[str] = set()
    for imp in existing_imports:
        m = re.match(r'import\s+([\w.]+(?:\.\*)?);', imp)
        if m:
            existing_short.add(m.group(1).split(".")[-1])

    # Detecta todos os nomes CamelCase usados no corpo do teste
    used_classes = set(re.findall(r'\b([A-Z][a-zA-Z0-9]+)\b', test_code))

    to_inject: list[str] = []
    for cls in sorted(used_classes):
        if cls in existing_short:
            continue
        if cls in prod_map:
            to_inject.append(prod_map[cls])
        elif cls in _JDK_IMPORT_MAP:
            to_inject.append(_JDK_IMPORT_MAP[cls])

    if not to_inject:
        return test_code

    # Injeta após o último import existente — ou após o package se não há imports
    last_import = None
    for m in re.finditer(r'^import\s+[\w.*]+;', test_code, re.MULTILINE):
        last_import = m
    if last_import:
        pos = last_import.end()
        return test_code[:pos] + "\n" + "\n".join(sorted(set(to_inject))) + test_code[pos:]
    pkg = re.search(r'^package\s+[\w.]+;', test_code, re.MULTILINE)
    if pkg:
        pos = pkg.end()
        return test_code[:pos] + "\n\n" + "\n".join(sorted(set(to_inject))) + test_code[pos:]
    return test_code


def _categorize_build_error(output: str, prod_imports: list[str] | None = None) -> str:
    """Analisa o erro Maven e retorna instrução de reparo direcionada."""
    out = output.lower()

    # Erro de construtor de record (detectar ANTES de cannot find symbol)
    if "constructor" in out and "in record" in out and "cannot be applied" in out:
        for line in output.splitlines():
            if "required:" in line:
                args = line.split("required:")[-1].strip()
                return (
                    f"RECORD CONSTRUCTOR ERROR: Constructor called without required arguments.\n"
                    f"Required arguments: {args}\n"
                    "ALWAYS use the canonical constructor with ALL declared arguments. "
                    "NEVER use an empty constructor for records — records have no default constructor."
                )
        return (
            "RECORD CONSTRUCTOR ERROR: The record constructor was called incorrectly.\n"
            "Check the required arguments in the record declaration inside the DEPENDENCY CONTEXT."
        )

    # D: Construtor sem argumentos em classe que exige parâmetros (não-record)
    if "constructor" in out and "cannot be applied" in out and "found:" in out:
        required, found = "", ""
        for line in output.splitlines():
            if "required:" in line and not required:
                required = line.split("required:")[-1].strip()
            if "found:" in line and not found:
                found = line.split("found:")[-1].strip()
        if required:
            return (
                f"CONSTRUCTOR ERROR: You called the constructor with wrong arguments.\n"
                f"  Required: {required}\n"
                f"  Found:    {found or 'no arguments'}\n"
                "Check the DEPENDENCY CONTEXT for the EXACT constructor signature.\n"
                "Pass ALL required arguments — NEVER use an empty constructor if the class has none.\n"
                "Copy each argument type verbatim from the 'Required' line above."
            )
        return (
            "CONSTRUCTOR ERROR: Constructor called with wrong argument count or types.\n"
            "Check the DEPENDENCY CONTEXT for the exact constructor signature and pass all required arguments."
        )

    # Erro de enum/variável inventada
    if "cannot find symbol" in out:
        for line in output.splitlines():
            if "symbol:" in line:
                sym = line.split("symbol:")[-1].strip()
                if "variable" in sym:
                    return (
                        f"ENUM/VARIABLE ERROR: You used '{sym}' which DOES NOT EXIST in the class.\n"
                        "Use ONLY the values declared in the DEPENDENCY CONTEXT section of the prompt.\n"
                        "Replace it with the correct value listed under 'ALLOWED ENUM VALUES'."
                    )
                if "method" in sym:
                    return (
                        f"METHOD ERROR: You called '{sym}' which DOES NOT EXIST in the class.\n"
                        "Check the exact signatures of the source class and use only real methods."
                    )
                if "class" in sym:
                    cls_name = sym.replace("class", "").strip()
                    # S2: busca import exato no mapa de imports de produção ou JDK
                    if prod_imports:
                        for imp in prod_imports:
                            m = re.match(r'import\s+([\w.]+);', imp)
                            if m and m.group(1).split(".")[-1] == cls_name:
                                return (
                                    f"IMPORT ERROR: Class `{cls_name}` is missing its import.\n"
                                    f"ADD THIS EXACT LINE to your import block (copy verbatim):\n"
                                    f"  {imp}\n"
                                    "Do NOT modify this import in any way."
                                )
                    if cls_name in _JDK_IMPORT_MAP:
                        jdk_imp = _JDK_IMPORT_MAP[cls_name]
                        return (
                            f"IMPORT ERROR: Class `{cls_name}` is missing its import.\n"
                            f"ADD THIS EXACT LINE to your import block (copy verbatim):\n"
                            f"  {jdk_imp}\n"
                            "Do NOT modify this import in any way."
                        )
                    return (
                        f"IMPORT ERROR: Class '{sym}' not found.\n"
                        "Add the correct import. Use only classes that exist in the project."
                    )
        return (
            "ERROR 'cannot find symbol': A referenced symbol does not exist.\n"
            "Check enum values, methods and imports — use only what is declared in the source class."
        )

    # Package inexistente
    if "package" in out and "does not exist" in out:
        return (
            "PACKAGE ERROR: An import points to a package that does not exist.\n"
            "Use only classes from the project — check the DEPENDENCY CONTEXT for the correct imports."
        )

    # Erro de asserção (valor esperado errado)
    if "assertionerror" in out or "expected:" in out:
        for line in output.splitlines():
            if "expected:" in line or "but was:" in line:
                detail = line.strip()

                # G1: extrai expected/actual direto do erro Maven — instrução cirúrgica
                # Cobre tanto BigDecimal (50.00 vs 5.00) quanto qualquer outro mismatch
                _m_vals = re.search(
                    r'expected:\s*<([^>]*)>\s*but was:\s*<([^>]*)>', detail
                )
                if _m_vals:
                    _expected_in_test = _m_vals.group(1)
                    _actual_from_code = _m_vals.group(2)

                    # F4: null vs empty string — caso especial com instrução de substituição de método
                    if _expected_in_test == "null" and _actual_from_code == "":
                        return (
                            "ASSERTION WRONG EXPECTED VALUE:\n"
                            "  Your test expects: <null>\n"
                            "  Actual return value: <\"\"> (empty string)\n\n"
                            "SURGICAL FIX — change ONLY the assertion:\n"
                            "  REPLACE assertNull(...) with assertEquals(\"\", result) "
                            "or assertTrue(result.isEmpty()).\n"
                            "  Do NOT change inputs, method calls, imports, or any other code.\n"
                            "  ONE change only."
                        )

                    # Caso geral: substitui apenas o valor esperado
                    return (
                        f"ASSERTION WRONG EXPECTED VALUE:\n"
                        f"  Your test expects: <{_expected_in_test}>\n"
                        f"  Actual return value: <{_actual_from_code}>\n\n"
                        f"SURGICAL FIX — change ONLY the expected value in the assertion:\n"
                        f"  Find the assertion containing '{_expected_in_test}' "
                        f"and replace it with '{_actual_from_code}'.\n"
                        f"  Do NOT modify inputs, method calls, imports, or any other code.\n"
                        f"  ONE LINE CHANGE — nothing else."
                    )

                # Sem padrão extraível — fallback genérico
                return (
                    f"ASSERTION ERROR: The expected value in the test is wrong.\n"
                    f"Detail: {detail}\n"
                    "Fix assertEquals/assertThat to match what the method ACTUALLY returns.\n"
                    "Do NOT guess what 'should' happen — test current behavior, not desired behavior."
                )
        return (
            "ASSERTION ERROR: Expected value in the test differs from the actual method return.\n"
            "Run the method mentally step by step with the test input.\n"
            "Use the actual computed result as the expected value."
        )

    # Spring context (SpringBootTest/WebMvcTest proibidos)
    if "springboottest" in out or "applicationcontext" in out or "webmvctest" in out:
        return (
            "SPRING CONTEXT ERROR: You used @SpringBootTest or @WebMvcTest — this is FORBIDDEN.\n"
            "Use ONLY @ExtendWith(MockitoExtension.class) with new ClassName() and @Mock/@InjectMocks."
        )

    # NullPointerException sem mock configurado
    if "nullpointerexception" in out:
        return (
            "NULLPOINTEREXCEPTION ERROR: A dependency was not mocked correctly.\n"
            "Make sure all @Mock fields are configured with Mockito.when(...) before the method call."
        )

    # Tipo incompatível no retorno do mock ou assertion
    if "incompatible types" in out:
        # A: String literal passado onde BigDecimal é esperado
        if "string" in out and "bigdecimal" in out:
            return (
                "TYPE MISMATCH — BigDecimal: You passed a String literal where BigDecimal is required.\n"
                "REPLACE every string literal with new BigDecimal(\"value\").\n"
                "  WRONG:   someMethod(\"100.00\")  /  new Foo(\"50.00\")\n"
                "  CORRECT: someMethod(new BigDecimal(\"100.00\"))  /  new Foo(new BigDecimal(\"50.00\"))\n"
                "Apply this fix to ALL BigDecimal parameters in constructors and method calls."
            )
        for line in output.splitlines():
            if "incompatible types" in line.lower():
                return (
                    f"TYPE MISMATCH ERROR: {line.strip()}\n"
                    "Check that mock return values match the exact return type of the method.\n"
                    "For ResponseEntity<X>, mock the service to return X (not ResponseEntity)."
                )
        return (
            "TYPE MISMATCH ERROR: A value or mock return has an incompatible type.\n"
            "Check exact return types in DEPENDENCY CONTEXT and align assertions/mocks."
        )

    # Método não pode ser aplicado (argumentos errados)
    if "method" in out and ("cannot be applied" in out or "not applicable" in out):
        for line in output.splitlines():
            if "cannot be applied" in line.lower() or "not applicable" in line.lower():
                return (
                    f"METHOD CALL ERROR: {line.strip()}\n"
                    "Check the exact method signature in DEPENDENCY CONTEXT — wrong argument count or type."
                )
        return (
            "METHOD CALL ERROR: A method was called with wrong arguments.\n"
            "Check the method signatures in DEPENDENCY CONTEXT and fix argument types/count."
        )

    # MockMvc sem contexto Spring (proibido sem @WebMvcTest)
    if "mockmvc" in out:
        return (
            "MOCKMVC ERROR: MockMvc requires Spring context (@WebMvcTest) which is FORBIDDEN.\n"
            "Instead: instantiate the controller directly with new ControllerClass().\n"
            "Use @Mock for the service and @InjectMocks for the controller."
        )

    # Construtor não encontrado (não-record)
    if "constructor" in out and ("no suitable" in out or "cannot find" in out):
        return (
            "CONSTRUCTOR ERROR: No suitable constructor found.\n"
            "Check the class declaration in DEPENDENCY CONTEXT — use the exact constructor args declared.\n"
            "For records, use the CONSTRUCTOR CALL hint in the DEPENDENCY CONTEXT section."
        )

    # Mockito — stub desnecessário (strict stubbing)
    if "unnecessarystubbingexception" in out:
        return (
            "MOCKITO STRICT ERROR: You declared a mock stub (when/thenReturn) that was never called.\n"
            "Remove all Mockito.when(...) stubs that are not used by any @Test method.\n"
            "Only stub what each test actually invokes."
        )

    # Mockito — verificação falhou (método não foi chamado)
    if "wantedbutnotinvoked" in out or "wanted but not invoked" in out:
        return (
            "MOCKITO VERIFY ERROR: verify() expected a method call that never happened.\n"
            "Either remove the verify() or fix the test so the method is actually called."
        )

    # Mockito — when() sem chamada de método real dentro
    if "missingmethodinvocationexception" in out or "missing method invocation" in out:
        return (
            "MOCKITO WHEN ERROR: when() must wrap a real method call on a mock.\n"
            "Pattern: when(mockObj.realMethod(args)).thenReturn(value).\n"
            "Do NOT call when() on a concrete object or a spy without a method."
        )

    # Mockito — cannot mock final/sealed class
    if "cannot mock" in out or "cannot spy" in out:
        return (
            "MOCKITO MOCK TYPE ERROR: This class cannot be mocked (final, sealed, or primitive).\n"
            "Use the real object instead of a mock, or wrap it in an interface."
        )

    # Mockito — argument matchers mixed with raw values
    if "invaliduseofmatchersexception" in out or "invalid use of argument matchers" in out:
        return (
            "MOCKITO MATCHER ERROR: Cannot mix argument matchers (any(), eq()) with raw values.\n"
            "Either use matchers for ALL arguments or raw values for ALL arguments.\n"
            "Example: when(mock.method(any(), eq(\"value\"))).thenReturn(x)  — ALL matchers."
        )

    # Classe pública com nome diferente do arquivo (class Foo in Bar.java)
    if "should be declared in a file named" in out:
        m = re.search(
            r'class (\w+) is public, should be declared in a file named (\w+\.java)',
            output,
        )
        if m:
            wrong_cls, correct_file = m.group(1), m.group(2)
            correct_cls = correct_file.replace(".java", "")
            return (
                f"CLASS NAME CRITICAL ERROR: You declared `public class {wrong_cls}` "
                f"but the file is `{correct_file}`.\n"
                f"RENAME the class to EXACTLY: `public class {correct_cls} {{`\n"
                "Java law: the public class name MUST equal the filename. No exceptions.\n"
                "Do NOT abbreviate, shorten, or change it in any way."
            )

    # Output truncado pelo limite de tokens (reached end of file / try without catch)
    if "reached end of file while parsing" in out or (
        "'try' without 'catch'" in out and "reached end of file" in out
    ):
        return (
            "TRUNCATED OUTPUT: Your previous code was cut off before completion.\n"
            "DO NOT rewrite the entire file.\n"
            "Count the open `{` braces vs closed `}` braces in your previous output "
            "and add ONLY the missing closing braces `}`, catch/finally blocks, "
            "and semicolons needed to complete the file.\n"
            "Start your output from the last complete line of the previous attempt."
        )

    return (
        "COMPILATION/EXECUTION ERROR: Analyze the stack trace below and fix the code.\n"
        "Do NOT change business logic — fix only what the error points to."
    )


_SKIP_PATTERNS = [
    (re.compile(r'extends\s+\w*Repository\w*\s*<'),
     "Interface JPA pura (generics complexos)"),
    (re.compile(r'@SpringBootApplication'),
     "Classe main Spring Boot"),
    (re.compile(r'public\s+interface\b'),
     "Interface pura (sem lógica)"),
    (re.compile(r'(?m)^\s*[A-Z][A-Z_0-9]+\s*\([^)]+\)\s*[,;]'),
     "Enum com construtor parametrizado"),
]

# Padrões que só se aplicam em fases estruturais (SOLID, arquitetura, etc.)
_STRUCTURAL_PHASE_KEYWORDS = {
    "solid", "architecture", "patterns", "clean_code",
    "tracking", "nomenclature", "structure", "final_keywords",
    # community skills — @Document/@Entity não devem ser convertidas/reestruturadas
    "community", "record_migration", "builder_pattern", "dead_code",
    "introduce_parameter", "strategy_pattern", "encapsulate_field",
}
_SKIP_FOR_STRUCTURAL = [
    (re.compile(r'@Document\b'), "@Document — holder de dados MongoDB"),
    (re.compile(r'@Entity\b'),   "@Entity — holder de dados JPA"),
    (re.compile(r'@Table\b'),    "@Table — holder de dados JPA"),
]


# ---------------------------------------------------------------------------
# Solução 5 — Registro de falhas
# ---------------------------------------------------------------------------

_PERMANENT_SKIP_THRESHOLD = 3  # runs consecutivos com falha → skip permanente


class FailedFilesTracker:
    def __init__(self, logs_dir: str = "logs"):
        self._path   = os.path.join(logs_dir, "failed_files.json")
        self._entries: list[dict] = []
        os.makedirs(logs_dir, exist_ok=True)
        if os.path.exists(self._path):
            try:
                with open(self._path) as f:
                    self._entries = json.load(f)
            except Exception:
                self._entries = []

    def record(self, file_path: str, phase: str, reason: str,
               stack_trace: str = "") -> None:
        key = (file_path, phase)
        # Não duplicar dentro do mesmo run
        if any(e["file"] == file_path and e["phase"] == phase and not e.get("prev_run")
               for e in self._entries):
            return
        # Herdar fail_count acumulado de runs anteriores (prev_run ou permanent_skip)
        prior_count = self._get_prior_fail_count(file_path, phase)
        entry = {
            "file": file_path, "phase": phase, "reason": reason,
            "timestamp": datetime.now().isoformat(), "retried": False,
            "fail_count": prior_count + 1,
        }
        if stack_trace:
            entry["stack_trace"] = stack_trace[-800:]
        # Promover a permanent_skip se atingiu o threshold
        if entry["fail_count"] >= _PERMANENT_SKIP_THRESHOLD:
            entry["permanent_skip"] = True
            # Remove entradas prev_run anteriores — permanent_skip é o único registro necessário
            self._entries = [
                e for e in self._entries
                if not (e["file"] == file_path and e["phase"] == phase and e.get("prev_run"))
            ]
            log(
                f"  → {os.path.basename(file_path)}: SKIP PERMANENTE "
                f"({entry['fail_count']} falhas consecutivas)",
                "WARN",
            )
        self._entries.append(entry)
        self._save()
        log(f"  → failed_files.json: {os.path.basename(file_path)}", "WARN")

    def _get_prior_fail_count(self, file_path: str, phase: str) -> int:
        """Soma fail_count de todas as entradas anteriores (prev_run + permanent_skip)."""
        return sum(
            e.get("fail_count", 1)
            for e in self._entries
            if e["file"] == file_path and e["phase"] == phase
            and (e.get("prev_run") or e.get("permanent_skip"))
        )

    def is_permanent_skip(self, file_path: str, phase: str) -> bool:
        """Retorna True se este arquivo deve ser pulado permanentemente."""
        return any(
            e.get("permanent_skip")
            for e in self._entries
            if e["file"] == file_path and e["phase"] == phase
        )

    def _save(self):
        with open(self._path, "w") as f:
            json.dump(self._entries, f, indent=2, ensure_ascii=False)

    def get_pending(self) -> list[dict]:
        return [e for e in self._entries if not e["retried"]]

    def mark_retried(self, file_path: str, phase: str):
        for e in self._entries:
            if e["file"] == file_path and e["phase"] == phase:
                e["retried"] = True
        self._save()

    def get_build_failure_count(self, file_path: str) -> int:
        """Conta falhas de build reais (exclui 'código idêntico' e skips semânticos)."""
        return sum(
            1 for e in self._entries
            if e["file"] == file_path and "build quebrou" in e.get("reason", "")
        )

    def __len__(self) -> int:
        return len(self._entries)

    def reset(self) -> None:
        """Marca entradas atuais como prev_run (acumulam fail_count). Remove permanentes antigas."""
        kept = []
        for e in self._entries:
            if e.get("permanent_skip"):
                kept.append(e)  # permanentes sobrevivem sem alteração
            elif not e.get("prev_run"):
                e["prev_run"] = True  # entrada atual vira histórico para o próximo run
                kept.append(e)
            # entradas já marcadas como prev_run são descartadas (já foram contadas no fail_count)
        self._entries = kept
        self._save()


_failed_tracker: FailedFilesTracker | None = None


def get_failed_tracker(logs_dir: str = "logs") -> FailedFilesTracker:
    global _failed_tracker
    if _failed_tracker is None:
        _failed_tracker = FailedFilesTracker(logs_dir)
    return _failed_tracker


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def should_skip(file_path: str, code: str, phase: str = "") -> tuple[bool, str]:
    if len(code.splitlines()) > MAX_FILE_LINES:
        return True, f"Arquivo muito grande ({len(code.splitlines())} linhas)"
    for pattern, reason in _SKIP_PATTERNS:
        if pattern.search(code):
            return True, reason
    phase_lower = phase.lower() if phase else ""
    if any(kw in phase_lower for kw in _STRUCTURAL_PHASE_KEYWORDS):
        for pattern, reason in _SKIP_FOR_STRUCTURAL:
            if pattern.search(code):
                return True, reason
    return False, ""


def _mode_for(file_path: str) -> str:
    return "test" if "/test/" in file_path.replace("\\", "/") else "refactor"


def get_java_files(repo_path: str, tests: bool = False) -> list[str]:
    files = []
    for root, _, fs in os.walk(repo_path):
        if "target" in root.replace("\\", "/").split("/"):
            continue
        for f in fs:
            if not f.endswith(".java"):
                continue
            full       = os.path.join(root, f)
            normalized = full.replace("\\", "/")
            in_test    = "/test/" in normalized
            if tests and in_test:
                files.append(full)
            elif not tests and not in_test:
                files.append(full)
    return files


def _test_path_for(main_file: str, repo_path: str) -> str | None:
    normalized = main_file.replace("\\", "/")
    if "/main/" not in normalized:
        return None
    test_path = normalized.replace("/main/", "/test/")
    base, _   = os.path.splitext(test_path)
    return base + "Test.java"


# ---------------------------------------------------------------------------
# Ciclo de geração + validação com correção
# ---------------------------------------------------------------------------

def _generate_and_validate(original: str, rules: str, mode: str,
                             file_name: str, file_path: str,
                             phase: str = "",
                             cache=None,
                             semantic_mem=None) -> tuple[str | None, str]:
    """
    Chama a IA e valida o resultado com injeção de contexto de dependências.
    dep_context é obtido do cache ou gerado, e passado separado para build_prompt.
    """
    from java.context import get_dependency_context

    dep_context = ""
    root = file_path
    try:
        while root != "/" and not os.path.exists(os.path.join(root, "pom.xml")):
            root = os.path.dirname(root)
        if os.path.exists(os.path.join(root, "pom.xml")):
            dep_context = get_dependency_context(original, root, cache=cache)
    except Exception:
        pass

    test_context = ""
    try:
        test_file = _test_path_for(file_path, root)
        if test_file and os.path.exists(test_file):
            from core.utils import read_file as _read
            test_code = _read(test_file)
            test_context = (
                "\n\n[CONTEXTO DE TESTE] O teste abaixo valida esta classe. "
                "Sua refatoração DEVE garantir que ele continue passando:\n\n"
                f"```java\n{test_code}\n```"
            )
            log("  [Contexto] Teste unitário injetado.", "OK")
    except Exception:
        pass

    phase_delta = rules + test_context

    if semantic_mem is not None:
        mem_context = semantic_mem.search(f"{phase} {file_name}")
        if mem_context:
            phase_delta = phase_delta + f"\n\n[APRENDIZADOS ANTERIORES]:\n{mem_context}"

    new_code = call_ai(original, phase_delta, mode, file_name,
                       file_path=file_path, phase=phase,
                       dep_context=dep_context)

    if not new_code:
        return None, "IA não gerou código"

    # Melhoria 1: código idêntico = modelo confirmou que não há mudanças necessárias
    if new_code.strip() == original.strip():
        return None, _REASON_NO_CHANGE

    valid, reason = is_valid_java(original, new_code)
    if valid:
        # Skill: Validador de Integridade de Nome
        from java.validator import validate_class_name_matches_file
        is_name_ok, name_error = validate_class_name_matches_file(new_code, file_path)
        if not is_name_ok:
            reason = f"INTEGRITY ERROR: {name_error}"
        else:
            # Melhoria 2: Validação de package
            is_pkg_ok, pkg_error = validate_package_matches_path(new_code, file_path)
            if not is_pkg_ok:
                reason = f"PACKAGE ERROR: {pkg_error}"
            else:
                return new_code, ""

    log(f"  Validator rejeitou: {reason} — tentando correção", "WARN")

    from core.utils import load_skill as _ls
    _refactor_repair = _ls("java-repair-guide", section="LLM INSTRUCTIONS") or ""
    _live(active_skill="java-repair-guide")

    # Ciclos de correção
    rejected_code = new_code
    for attempt in range(1, MAX_VALIDATOR_RETRIES + 1):
        log(f"  Correção validator {attempt}/{MAX_VALIDATOR_RETRIES}: {reason[:60]}")
        repair_reason = f"{_refactor_repair}\n\n{reason}".strip() if _refactor_repair else reason

        corrected = call_ai_with_correction(
            original      = original,
            rules         = phase_delta,
            mode          = mode,
            file_name     = file_name,
            file_path     = file_path,
            bad_output    = rejected_code,
            error_reason  = repair_reason,
            phase         = phase,
            dep_context   = dep_context,
        )

        if not corrected:
            log(f"  Correção {attempt}: sem resposta", "WARN")
            break

        if corrected and corrected.strip() == original.strip():
            return None, _REASON_NO_CHANGE

        valid, reason = is_valid_java(original, corrected)
        if valid:
            from java.validator import validate_class_name_matches_file
            is_name_ok, name_error = validate_class_name_matches_file(corrected, file_path)
            if not is_name_ok:
                reason = f"INTEGRITY ERROR: {name_error}. The class name must be '{file_name.replace('.java','')}'."
            else:
                is_pkg_ok, pkg_error = validate_package_matches_path(corrected, file_path)
                if not is_pkg_ok:
                    reason = f"PACKAGE ERROR: {pkg_error}"
                else:
                    log(f"  Correção {attempt}: aceita ✓", "OK")
                    return corrected, ""

        log(f"  Correção {attempt}: ainda rejeitado — {reason}", "WARN")
        rejected_code = corrected

    return None, reason


# ---------------------------------------------------------------------------
# Refatoração — arquivo inteiro
# ---------------------------------------------------------------------------

def _refactor_whole_file(file: str, original: str, rules: str,
                          repo_path: str, phase: str,
                          reporter: PhaseReporter,
                          exec_logger: ExecutionLogger | None,
                          cache=None,
                          semantic_mem=None) -> bool:
    file_name = os.path.basename(file)
    mode      = _mode_for(file)

    new_code, reason = _generate_and_validate(
        original, rules, mode, file_name, file, phase=phase, cache=cache,
        semantic_mem=semantic_mem,
    )

    if not new_code:
        if reason == _REASON_NO_CHANGE:
            log(f"  {file_name}: modelo confirmou que não há alterações necessárias", "OK")
            if exec_logger:
                exec_logger.log_file_skipped(phase, file_name, "Não necessita alterações")
            reporter.record_skipped(phase, file_name, "Não necessita alterações")
            return False
        log(f"  {file_name}: falhou — {reason}", "WARN")
        get_failed_tracker().record(file, phase, reason)
        if exec_logger:
            exec_logger.log_ai_failure(phase, file_name, "all-agents", reason)
        if "não gerou" in reason:
            reporter.record_skipped(phase, file_name, reason)
        else:
            reporter.record_rejected(phase, file_name, reason)
        return False

    write_file(file, new_code)
    success, build_output = maven_test(repo_path)

    if not success:
        log(f"  {file_name}: Build falhou. Analisando impacto global...", "WARN")
        
        # Skill: Detecção de Impacto em Cascata
        if "cannot find symbol" in build_output or "does not override" in build_output:
            _live(active_skill="Sincronia Contextual")
            log("  [Impacto Detectado] Mudança de contrato detectada. Tentando sincronização contextual...", "PHASE")
            _attempt_global_sync(build_output, repo_path, rules, phase, new_code)
            success, build_output = maven_test(repo_path)
            if success:
                log(f"  {file_name}: Sincronização global restaurou o build! ✓", "OK")

    if not success:
        log(f"  {file_name}: Build persiste com erro. Ativando Diagnóstico de Precisão...", "WARN")
        
        # Skill: Identificação de Culpado Transversal
        # Se o erro for em OUTRO arquivo (ex: interface que sumiu), tentamos restaurar/corrigir o outro arquivo.
        culprit_match = re.search(r'([/\\].*\.java):\[\d+', build_output)
        if culprit_match:
            culprit_path = culprit_match.group(1)
            culprit_name = os.path.basename(culprit_path)
            if culprit_name != file_name:
                log(f"  [Auto-Cura] O culpado parece ser {culprit_name}. Tentando reparo de emergência...", "PHASE")
                # Se o erro for "does not contain class" ou "should be declared in file", é erro estrutural
                if "should be declared in a file" in build_output or "does not contain class" in build_output:
                    # Tenta restaurar o arquivo da interface/culpado para o estado estável
                    run_command(f"git checkout -- \"{culprit_path}\"", repo_path)
                    log(f"  [Auto-Cura] {culprit_name} restaurado para estado estável do Git.", "OK")
                    success, build_output = maven_test(repo_path)
                    if success: return True # Resolvido restaurando o culpado
        
        # Skill: Raio-X de Erros (Continua para o arquivo atual)
        _live(active_skill="Raio-X de Erros")
        error_diagnostics = []
        raw_error_lines = [l for l in build_output.splitlines() if "[ERROR]" in l and ".java:[" in l][:5]
        
        for err_line in raw_error_lines:
            # Regex melhorado para suportar espaços no caminho: /caminho/com espaço/Arquivo.java:[linha,coluna]
            m = re.search(r'([/\\].*\.java):\[(\d+)', err_line)
            if m:
                fpath, lnum = m.group(1), int(m.group(2))
                try:
                    code_snippet = _get_line_from_file(fpath, lnum)
                    diag = f"Erro em {os.path.basename(fpath)} L{lnum}: {code_snippet.strip()}\n      -> {err_line.split('] ', 1)[-1]}"
                    error_diagnostics.append(diag)
                    log(f"  [Raio-X] {diag}", "ERR")
                except: pass

        error_summary = "\n".join(error_diagnostics) or "\n".join(build_output.splitlines()[:5])
        
        # Skill: Registro de Diagnóstico para análise posterior
        exec_logger.log_detailed_diagnostic(phase, file_name, build_output, error_diagnostics)

        # Skill: Reforço de Import com Dicionário Global
        _live(active_skill="Project Dictionary")
        if "cannot find symbol" in error_summary:
            from java.dictionary import build_project_dictionary
            proj_map = None
            if cache is not None:
                proj_map = cache.get_project_dict()
            if proj_map is None:
                proj_map = build_project_dictionary(repo_path)
                if cache is not None:
                    cache.set_project_dict(proj_map)
            error_summary += f"\n\n{proj_map}\n\nDICA: Use o mapa acima para adicionar o IMPORT correto."
        
        corrected_code = call_ai_with_correction(
            original     = original,
            rules        = rules,
            mode         = mode,
            file_name    = file_name,
            file_path    = file,
            bad_output   = new_code,
            error_reason = f"Falha de Compilação Maven:\n{error_summary}",
            phase        = phase
        )

        _live(active_skill="Auto-Cura")
        if corrected_code:
            write_file(file, corrected_code)
            success, _ = maven_test(repo_path)
            if success:
                log(f"  {file_name}: Auto-Cura bem sucedida! ✓", "OK")
                new_code = corrected_code
            else:
                log(f"  {file_name}: Auto-Cura falhou.", "ERR")
                write_file(file, original)
                get_failed_tracker().record(file, phase, "build quebrou (auto-cura falhou)")
                return False
        else:
            write_file(file, original)
            log(f"  {file_name} REVERTIDO: build quebrou e IA não corrigiu", "WARN")
            get_failed_tracker().record(file, phase, "build quebrou")
            return False

    reporter.record_changed(phase, file_name, file, original, new_code)
    if exec_logger:
        exec_logger.log_file_accepted(phase, file_name, "+refactor")
    log(f"  {file_name} REFATORADO ✓", "OK")
    return True


# ---------------------------------------------------------------------------
# Refatoração — método a método
# ---------------------------------------------------------------------------

def _refactor_by_method(file: str, original: str, rules: str,
                         repo_path: str, phase: str,
                         reporter: PhaseReporter,
                         exec_logger: ExecutionLogger | None,
                         cache=None,
                         semantic_mem=None) -> bool:
    file_name = os.path.basename(file)
    mode      = _mode_for(file)

    header  = extract_class_header(original)
    methods = get_processable_methods(original)

    if not methods:
        log(f"  {file_name}: nenhum método extraível — tentando arquivo inteiro")
        return _refactor_whole_file(file, original, rules, repo_path, phase,
                                    reporter, exec_logger, cache=cache,
                                    semantic_mem=semantic_mem)

    log(f"  {file_name}: {len(methods)} métodos a processar")

    current_code    = original
    methods_changed = 0
    methods_failed  = 0

    for method in methods:
        log(f"    → {method.name}() [{len(method.full_text.splitlines())}L]")

        context = build_method_context(header, method)

        ai_response, reason = _generate_and_validate(
            original     = context,
            rules        = rules,
            mode         = mode,
            file_name    = file_name,
            file_path    = file,
            phase        = phase,
            cache        = cache,
            semantic_mem = semantic_mem,
        )

        if not ai_response:
            log(f"      {method.name}: {reason}", "WARN")
            methods_failed += 1
            continue

        new_method_text = extract_refactored_method(ai_response, method)

        if not new_method_text:
            log(f"      {method.name}: método não encontrado na resposta", "WARN")
            methods_failed += 1
            continue

        if new_method_text.strip() == method.full_text.strip():
            log(f"      {method.name}: sem alteração")
            continue

        updated_code = replace_method_in_file(current_code, method, new_method_text)
        valid_full, reason_full = is_valid_java(current_code, updated_code)
        if not valid_full:
            log(f"      {method.name}: inválido após substituição: {reason_full}", "WARN")
            methods_failed += 1
            continue

        current_code = updated_code
        methods_changed += 1
        log(f"      {method.name}: OK ✓")

    if methods_changed == 0:
        if methods_failed > 0:
            get_failed_tracker().record(
                file, phase, f"todos os {methods_failed} métodos falharam"
            )
        log(f"  {file_name}: nenhum método alterado", "WARN")
        reporter.record_skipped(phase, file_name, "nenhum método alterado")
        return False

    write_file(file, current_code)
    success, build_out = maven_test(repo_path)

    if not success:
        write_file(file, original)
        log(f"  {file_name} REVERTIDO após {methods_changed} métodos", "WARN")
        get_failed_tracker().record(file, phase, "build quebrou após refatoração")
        if exec_logger:
            exec_logger.log_file_reverted(phase, file_name, error_type=_categorize_build_error(build_out)[:80])
        reporter.record_build_failed(phase, file_name)
        return False

    reporter.record_changed(phase, file_name, file, original, current_code)
    if exec_logger:
        exec_logger.log_file_accepted(phase, file_name, f"+{methods_changed}methods")
    log(f"  {file_name} REFATORADO ✓ ({methods_changed} métodos)", "OK")
    return True


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

def refactor_file(file: str, rules: str, repo_path: str,
                  phase: str, reporter: PhaseReporter,
                  exec_logger: ExecutionLogger | None = None,
                  cache=None,
                  semantic_mem=None) -> bool:
    file_name = os.path.basename(file)

    # Phase skip: se já processamos este arquivo nesta fase neste run, pula
    if cache is not None:
        phase_name = phase.split("/")[-1].replace(".md", "")
        if cache.is_phase_done(file, phase_name):
            log(f"  {file_name}: cache hit — {phase_name} já aplicada neste run", "OK")
            reporter.record_skipped(phase, file_name, f"cache: {phase_name} já aplicada")
            return False

    # Melhoria 4: pular arquivos com histórico de falhas de build repetidas
    build_fails = get_failed_tracker().get_build_failure_count(file)
    if build_fails >= MAX_BUILD_FAILURES:
        log(f"  {file_name}: {build_fails}x build quebrou em fases anteriores — pulando", "WARN")
        if exec_logger:
            exec_logger.log_file_skipped(phase, file_name,
                                         f"Histórico: {build_fails}x build quebrou")
        reporter.record_skipped(phase, file_name,
                                f"Histórico de falhas ({build_fails}x build quebrou)")
        return False

    log(f"Processando [{_mode_for(file)}]: {file_name}")

    if exec_logger:
        exec_logger.log_file_processing(phase, file_name, "unknown", "unknown")

    original = read_file(file)

    # Melhoria 3: passa phase para considerar padrões de skip por fase
    skip, reason = should_skip(file, original, phase)
    if skip:
        log(f"  {file_name} PULADO: {reason}", "WARN")
        if exec_logger:
            exec_logger.log_file_skipped(phase, file_name, reason)
        reporter.record_skipped(phase, file_name, reason)
        return False

    if is_large_file(original, LARGE_FILE_THRESHOLD):
        log(f"  {file_name}: arquivo grande → processamento por método")
        success = _refactor_by_method(file, original, rules, repo_path, phase,
                                      reporter, exec_logger, cache=cache,
                                      semantic_mem=semantic_mem)
    else:
        success = _refactor_whole_file(file, original, rules, repo_path, phase,
                                       reporter, exec_logger, cache=cache,
                                       semantic_mem=semantic_mem)

    if semantic_mem is not None:
        phase_label = phase.split("/")[-1].replace(".md", "")
        file_type   = "test" if "/test/" in file.replace("\\", "/") else "src"
        if success:
            semantic_mem.store(
                f"SUCCESS: phase={phase_label} file={file_name} type={file_type} — refactoring accepted and build passed"
            )
        else:
            semantic_mem.store(
                f"FAILURE: phase={phase_label} file={file_name} type={file_type} — refactoring rejected or build failed"
            )

    if cache is not None:
        phase_name = phase.split("/")[-1].replace(".md", "")
        cache.mark_phase_done(file, phase_name)

    return success


# ---------------------------------------------------------------------------
# M7 — Detecção de field injection sem construtor (deferred skip)
# ---------------------------------------------------------------------------

_RE_AUTOWIRED_FIELD = re.compile(
    r'@Autowired\s+(?:private\s+)?(?:final\s+)?(?:\w+)\s+\w+\s*;',
    re.MULTILINE,
)
_RE_EXPLICIT_CONSTRUCTOR = re.compile(
    r'(?:public|protected)\s+\w+\s*\([^)]+\)\s*\{',
    re.MULTILINE,
)


def _has_field_injection_without_constructor(code: str) -> bool:
    """Detecta classes com @Autowired em campo mas sem construtor explícito.
    Essas classes não podem ser testadas unitariamente sem Spring context
    até que a fase 11 (SOLID DIP) converta para constructor injection."""
    has_field_injection = bool(_RE_AUTOWIRED_FIELD.search(code))
    has_constructor = bool(_RE_EXPLICIT_CONSTRUCTOR.search(code))
    return has_field_injection and not has_constructor


# ---------------------------------------------------------------------------
# M8 — Extração de setup de teste existente para reuso no complement
# ---------------------------------------------------------------------------

_RE_MOCK_FIELD   = re.compile(r'@Mock\b.*?\n\s+\w[\w<>, ]*\s+\w+\s*;', re.DOTALL)
_RE_INJECT_FIELD = re.compile(r'@InjectMocks\b.*?\n\s+\w[\w<>, ]*\s+\w+\s*;', re.DOTALL)
_RE_SPY_FIELD    = re.compile(r'@Spy\b.*?\n\s+\w[\w<>, ]*\s+\w+\s*;', re.DOTALL)
_RE_FIELD_DECL   = re.compile(r'(?:private|protected)\s+(?:final\s+)?[\w<>, ]+\s+(\w+)\s*(?:=|;)', re.MULTILINE)

# Todas as anotações de ciclo de vida JUnit 4 e JUnit 5
_LIFECYCLE_ANNOTATIONS = [
    "@BeforeAll",   # JUnit 5 — estático, executa uma vez antes de todos os testes
    "@BeforeEach",  # JUnit 5 — executa antes de cada @Test
    "@AfterEach",   # JUnit 5 — executa após cada @Test
    "@AfterAll",    # JUnit 5 — estático, executa uma vez após todos os testes
    "@Before",      # JUnit 4 — equivalente a @BeforeEach
    "@After",       # JUnit 4 — equivalente a @AfterEach
    "@BeforeClass", # JUnit 4 — equivalente a @BeforeAll
    "@AfterClass",  # JUnit 4 — equivalente a @AfterAll
]

def _build_lifecycle_pattern(annotation: str) -> re.Pattern:
    """Regex que captura método anotado com qualquer anotação de ciclo de vida."""
    ann = re.escape(annotation)
    return re.compile(
        ann + r'\s+(?:(?:public|protected|static|void|\s)+\w+\s*\([^)]*\)\s*\{)'
        r'(?:[^{}]|\{[^{}]*\})*\}',
        re.DOTALL,
    )

_LIFECYCLE_RE: dict[str, re.Pattern] = {
    ann: _build_lifecycle_pattern(ann) for ann in _LIFECYCLE_ANNOTATIONS
}


def _extract_test_setup(existing_test: str) -> str:
    """Extrai mocks, injects, spies, métodos de ciclo de vida e campos do teste existente.

    Retorna um bloco estruturado para injetar no prompt de complementação (M8),
    indicando ao LLM exatamente o que já existe e o que é READ-ONLY."""
    sections: list[str] = []

    # --- Campos de mock / injeção ---
    mocks   = _RE_MOCK_FIELD.findall(existing_test)
    injects = _RE_INJECT_FIELD.findall(existing_test)
    spies   = _RE_SPY_FIELD.findall(existing_test)
    fields  = _RE_FIELD_DECL.findall(existing_test)

    if mocks or injects or spies:
        decls = "\n".join(f"    {d.strip()}" for d in mocks + injects + spies)
        sections.append(f"ALREADY DECLARED FIELDS (DO NOT redeclare these):\n{decls}")

    if fields:
        sections.append(
            f"ALL FIELD NAMES IN THE CLASS: {', '.join(fields)}\n"
            "  → Use these exact names in new tests — never create new field declarations."
        )

    # --- Métodos de ciclo de vida existentes ---
    found_lifecycle: list[tuple[str, str]] = []
    for ann in _LIFECYCLE_ANNOTATIONS:
        matches = _LIFECYCLE_RE[ann].findall(existing_test)
        for m in matches:
            found_lifecycle.append((ann, m.strip()))

    if found_lifecycle:
        lifecycle_lines: list[str] = []
        present_annotations = {ann for ann, _ in found_lifecycle}

        for ann, body in found_lifecycle:
            lifecycle_lines.append(
                f"{ann} (READ-ONLY — already present, DO NOT add another {ann}):\n"
                f"  {body[:300]}{'...' if len(body) > 300 else ''}"
            )

        # Regra dinâmica: lista só as anotações AUSENTES como permitidas
        absent = [a for a in _LIFECYCLE_ANNOTATIONS if a not in present_annotations]
        absent_note = (
            f"  → Lifecycle annotations NOT YET present (allowed to create if truly needed): "
            f"{', '.join(absent)}"
        ) if absent else "  → All common lifecycle annotations are already present."

        sections.append(
            "EXISTING LIFECYCLE METHODS (READ-ONLY — see rules below):\n"
            + "\n\n".join(lifecycle_lines)
            + f"\n\n{absent_note}"
        )

    if not sections:
        return ""

    return (
        "\n### EXISTING TEST SETUP — MUST REUSE, NEVER REDECLARE\n"
        + "\n\n".join(sections)
        + "\n"
    )


# ---------------------------------------------------------------------------
# Geração de testes
# ---------------------------------------------------------------------------

def generate_tests(repo_path: str, phase: str, rules: str,
                   reporter: PhaseReporter,
                   exec_logger: ExecutionLogger | None = None) -> bool:
    from core.utils import load_skill as _load_skill
    _repair_strategy = _load_skill("java-tdd-unit-test", section="Repair Strategy") or (
        "Fix ONLY the error reported. Do NOT rewrite the test class. "
        "Preserve passing tests. Use only symbols from DEPENDENCY CONTEXT."
    )
    _live(active_skill="java-tdd-unit-test")

    any_changed = False
    main_files  = get_java_files(repo_path, tests=False)

    for main_file in main_files:
        original  = read_file(main_file)
        file_name = os.path.basename(main_file)

        skip, _ = should_skip(main_file, original)
        if skip:
            continue

        # S2 (corrigido): pula apenas interfaces puras — @Document/@Entity ainda têm
        # getters/setters/construtores que precisam de cobertura de testes.
        # should_skip() já filtra interfaces JPA repositories e @SpringBootApplication.
        # Filtro adicional: interfaces não-repository (sem herança de Repository).
        if re.search(r'(?:public\s+)?interface\s+\w+', original) and \
                not re.search(r'extends\s+\w*Repository\w*\s*<', original):
            # Interface pura sem implementação — should_skip pode não ter capturado
            # (ex: service interfaces sem "Repository" no nome)
            continue

        test_path = _test_path_for(main_file, repo_path)
        if not test_path:
            continue

        test_name = os.path.basename(test_path)

        # M6: skip permanente — arquivo falhou em 3+ runs consecutivos
        if get_failed_tracker().is_permanent_skip(test_path, phase):
            log(f"  {test_name}: SKIP PERMANENTE (falhas recorrentes em runs anteriores)", "WARN")
            if exec_logger:
                exec_logger.log_file_skipped(phase, test_name, "permanent_skip")
            continue

        # M7: deferred skip — class de produção com field injection (@Autowired sem construtor)
        if _has_field_injection_without_constructor(original):
            # S5 (corrigido): desbloqueia se solid-dip nunca vai processar este arquivo.
            # Dois casos em que solid-dip não vai agir:
            #   a) permanent_skip: já tentou 3x e falhou
            #   b) no_new_instantiation: pré-filtro elimina antes do LLM (nunca acumula falhas)
            _dip_permanent   = get_failed_tracker().is_permanent_skip(main_file, "solid-dip")
            _dip_prefiltered = not bool(re.search(r'\bnew\s+[A-Z]\w+\s*\(', original))
            if _dip_permanent or _dip_prefiltered:
                log(
                    f"  {test_name}: solid-dip não aplicável "
                    f"({'permanent_skip' if _dip_permanent else 'no_new_instantiation'}) "
                    f"— gerando teste com @InjectMocks",
                    "WARN"
                )
                # Não dá continue — Mockito suporta field injection via @InjectMocks
            else:
                log(
                    f"  {test_name}: DEFERRED — field injection detectada "
                    f"(testar após fase 11 SOLID DIP)", "WARN"
                )
                if exec_logger:
                    exec_logger.log_file_skipped(phase, test_name, "deferred_field_injection")
                reporter.record_skipped(phase, test_name, "deferred: field injection sem construtor")
                continue

        # M8: complementação de testes existentes com cobertura parcial
        complement_mode   = False
        existing_test_code = ""
        existing_coverage  = 0.0

        if os.path.exists(test_path):
            _, _, existing_coverage, missed_existing = maven_test_with_coverage(repo_path, file_name)
            if existing_coverage >= 90.0 or not missed_existing:
                continue  # cobertura já adequada — nada a fazer
            complement_mode    = True
            existing_test_code = read_file(test_path)
            log(
                f"  Complementando: {test_name} "
                f"(cobertura atual {existing_coverage:.1f}% — linhas: {missed_existing})"
            )
        else:
            log(f"  Gerando teste: {test_name}")

        # Limpa modelos marcados como OOM entre arquivos para evitar cascade de falhas
        # Se Ollama estava fisicamente OOM, aguarda recuperação antes de continuar
        from ai.model import _OOM_MODELS, wait_for_ollama_recovery
        if _OOM_MODELS:
            _OOM_MODELS.clear()
            if not wait_for_ollama_recovery():
                log(f"  {test_name}: Ollama não recuperou — pulando", "WARN")
                get_failed_tracker().record(test_path, phase, "Ollama OOM — serviço não recuperou")
                if exec_logger:
                    exec_logger.log_ai_failure(phase, test_name, "ollama-oom", "Serviço não recuperou após cascade de OOM")
                reporter.record_skipped(phase, test_name, "Ollama OOM")
                continue
        else:
            _OOM_MODELS.clear()

        file_mode = "complement" if complement_mode else "new"
        if exec_logger:
            exec_logger.log_file_processing(phase, test_name, "test", file_mode)

        from java.context import get_dependency_context
        try:
            test_dep_context = get_dependency_context(original, repo_path)
        except Exception:
            test_dep_context = ""

        # C3: calcula restrição de nome/package ANTES de construir active_rules — inserida no INÍCIO
        _test_cls_name = test_name.replace(".java", "")
        _test_pkg = ""
        try:
            _norm_tp = test_path.replace("\\", "/")
            _java_idx = _norm_tp.find("/test/java/")
            if _java_idx >= 0:
                _pkg_path = _norm_tp[_java_idx + len("/test/java/"):]
                _pkg_path = "/".join(_pkg_path.split("/")[:-1])
                _test_pkg = _pkg_path.replace("/", ".")
        except Exception:
            pass

        _mandatory_prefix = (
            f"### TEST CLASS — MANDATORY NAME AND PACKAGE (HIGHEST PRIORITY — APPLY BEFORE ANYTHING ELSE)\n"
            f"- The test class declaration MUST be EXACTLY: `public class {_test_cls_name} {{`\n"
            f"- NEVER rename, shorten, or alter this class name in any way.\n"
        )
        if _test_pkg:
            _mandatory_prefix += (
                f"- The package declaration MUST be EXACTLY: `package {_test_pkg};`\n"
                f"- NEVER abbreviate `{_test_pkg}` — copy the FULL package path verbatim.\n"
                f"  (Common mistake: writing `{'.'.join(_test_pkg.split('.')[:3])}.*` instead of the full path)\n"
                f"- NEVER use com.example.*, com.test.*, com.demo.*, or any invented package.\n"
            )
        _mandatory_prefix += "\n\n"

        # M8: regras de complementação — LLM recebe teste existente + setup explícito + lacunas
        if complement_mode:
            setup_block = _extract_test_setup(existing_test_code)
            active_rules = (
                f"{_mandatory_prefix}{rules}\n\n"
                "### EXISTING TEST FILE (DO NOT MODIFY OR REMOVE ANY EXISTING TEST)\n"
                f"```java\n{existing_test_code}\n```\n"
                f"{setup_block}\n"
                "### TASK: COMPLEMENT — DO NOT REWRITE\n"
                f"Current coverage: {existing_coverage:.1f}% (target: 90%)\n"
                f"Uncovered lines: {missed_existing}\n\n"
                "ADD new @Test methods to cover the uncovered lines above.\n"
                "RULES for new tests (MANDATORY — violation causes compilation failure):\n"
                "  1. NEVER redeclare @Mock, @InjectMocks, @Spy, or any private field — they already exist.\n"
                "  2. Lifecycle methods (@BeforeEach, @AfterEach, @BeforeAll, @AfterAll, @Before, @After, etc.):\n"
                "     → If one ALREADY EXISTS (shown in EXISTING TEST SETUP): DO NOT add another of the same type.\n"
                "       The existing one already runs automatically — rely on it as-is.\n"
                "     → If extra per-test setup is needed beyond what already exists:\n"
                "         a) Initialize extra objects as LOCAL VARIABLES inside the @Test method.\n"
                "         b) OR create a private helper method called from the tests that need it.\n"
                "         c) NEVER modify or extend the body of an existing lifecycle method.\n"
                "     → If a lifecycle annotation is NOT YET present (shown as 'allowed to create'):\n"
                "         you MAY create it, but only if genuinely needed by multiple new tests.\n"
                "  3. Use ONLY the field names listed in EXISTING TEST SETUP — never declare new fields.\n"
                "  4. NEVER remove, rename, or modify any existing @Test method or its assertions.\n"
                "Return the COMPLETE test file: all existing content unchanged + new @Test methods at the end."
            )
        else:
            active_rules = _mandatory_prefix + rules

        # C21: injetar semântica de record quando a classe-alvo é um record Java
        if re.search(r'\brecord\s+\w+', original):
            active_rules += (
                "\n\n### JAVA RECORD SEMANTICS (the class under test is a Java record)\n"
                "Records auto-generate:\n"
                "- equals/hashCode based on all component fields\n"
                "- toString() returning 'ClassName[field1=val1, field2=val2]' — NEVER just the raw field value\n"
                "- A canonical constructor requiring all declared fields — no default no-arg constructor exists\n"
                "MANDATORY rules:\n"
                "- NEVER assert toString() returns only the raw value (e.g. 'ABC') — always includes class name prefix\n"
                "- NEVER call new RecordName() without all required field arguments\n"
                "- Two records with the same field values are equal via assertEquals without extra setup\n"
            )

        _prod_imports = re.findall(r'^import\s+[\w.]+;', original, re.MULTILINE)

        # F1: self-import — a classe sob teste não importa a si mesma, mas o teste precisa importá-la.
        # Derivamos o import exato do package da classe de produção + nome do arquivo.
        _prod_pkg_m = re.search(r'^package\s+([\w.]+);', original, re.MULTILINE)
        _prod_cls_name = file_name.replace(".java", "")
        _self_import: str | None = (
            f"import {_prod_pkg_m.group(1)}.{_prod_cls_name};" if _prod_pkg_m else None
        )
        # Lista ampliada para S1: prod_imports + self-import (garante que MerchantDocument,
        # TransactionController etc. sejam sempre injetados mesmo após reparos do LLM)
        _s1_imports = list(_prod_imports)
        if _self_import:
            _s1_imports.append(_self_import)

        if _prod_imports:
            active_rules += (
                "\n\n### IMPORTS PRESENT IN PRODUCTION CLASS (use as reference — do not hallucinate others)\n"
                + "\n".join(_prod_imports) + "\n"
            )
        if _self_import:
            active_rules += (
                f"\n### SELF-IMPORT (MANDATORY — always include this line in the test file)\n"
                f"  {_self_import}\n"
            )

        # C: regra preventiva — quando a classe de produção declara campos BigDecimal
        if re.search(r'\bBigDecimal\b', original):
            active_rules += (
                "\n\n### BIGDECIMAL CONSTRUCTION (MANDATORY — VIOLATION CAUSES COMPILE FAILURE)\n"
                "This class uses BigDecimal. For ALL test values involving BigDecimal:\n"
                "  CORRECT: new BigDecimal(\"100.00\")  or  BigDecimal.valueOf(100)\n"
                "  WRONG:   \"100.00\"  ← String literal, incompatible type, will NOT compile\n"
                "Apply this to constructors, setters, method calls, and mock return values.\n"
            )

        # C1: injetar campos @Autowired quando classe usa field injection (S5 path)
        _autowired_fields = re.findall(
            r'@Autowired\s+(?:private\s+)?(\w[\w<>, ]*?\s+\w+)\s*;',
            original,
        )
        if _autowired_fields:
            # S4: resolve import exato para cada @Mock — só para tipos simples (sem generics)
            _prod_import_map: dict[str, str] = {}
            for _imp in _prod_imports:
                _m = re.match(r'import\s+([\w.]+);', _imp)
                if _m:
                    _prod_import_map[_m.group(1).split(".")[-1]] = _imp

            _mock_lines: list[str] = []
            for _field in _autowired_fields:
                _type_name = _field.split()[0]
                _mock_lines.append(f"  @Mock  {_field};")
                if "<" not in _type_name:
                    _resolved = _prod_import_map.get(_type_name) or _JDK_IMPORT_MAP.get(_type_name)
                    if _resolved:
                        _mock_lines.append(f"  // Required import: {_resolved}")

            active_rules += (
                "\n\n### FIELD INJECTION — MOCK SETUP (MANDATORY)\n"
                "The class under test uses @Autowired field injection (no constructor).\n"
                "Use @ExtendWith(MockitoExtension.class) + @InjectMocks for the class under test.\n"
                "Declare one @Mock per injected dependency listed below "
                "(each line shows the @Mock and its required import):\n"
                + "\n".join(_mock_lines) + "\n"
                "Do NOT write a constructor or @BeforeEach that manually injects these — "
                "Mockito does it automatically via @InjectMocks.\n"
            )

        # M2: classe com @Document precisa do import MongoDB explícito no teste
        if re.search(r'@Document\b', original):
            active_rules += (
                "\n\n### MONGODB @Document IMPORT (MANDATORY)\n"
                "The class under test uses @Document from Spring Data MongoDB.\n"
                "You MUST add this import to the test file:\n"
                "  import org.springframework.data.mongodb.core.mapping.Document;\n"
                "Do NOT omit it — the class will not compile without it.\n"
            )

        # P3: IMPORT PROHIBITION simplificado — "Do NOT use com.example.*" já está no _mandatory_prefix.
        # Este bloco cobre apenas a proibição de inventar paths de import para tipos do projeto.
        active_rules += (
            "\n\n### IMPORT PROHIBITION\n"
            "For project-specific types: derive import paths ONLY from ### IMPORTS PRESENT IN PRODUCTION CLASS.\n"
            "If a type is not listed there and is not a standard JDK or Mockito/JUnit type, do NOT import it.\n"
        )

        file_start_time = time.time()

        test_code, reason = _generate_and_validate(
            original  = original,
            rules     = active_rules,
            mode      = "test",
            file_name = test_name,
            file_path = test_path,
            phase     = phase,
        )

        if not test_code:
            log(f"  {test_name}: {reason}", "WARN")
            get_failed_tracker().record(test_path, phase, reason)
            if exec_logger:
                exec_logger.log_ai_failure(phase, test_name, "all-agents", reason)
            reporter.record_skipped(phase, test_name, reason)
            continue

        # S1: injeta imports ausentes antes de gravar no disco (inclui self-import via _s1_imports)
        test_code = _auto_inject_missing_imports(test_code, _s1_imports)

        os.makedirs(os.path.dirname(test_path), exist_ok=True)
        write_file(test_path, test_code)

        success, combined_out, coverage, missed_lines = maven_test_with_coverage(repo_path, file_name)

        # M8: no modo complement, também passar o active_rules com o teste existente para os reparos

        # Ciclo de reparo estruturado — timeout já iniciado antes da geração
        timed_out = False
        timed_out = False
        error_history: list[str] = []  # acumula erros entre tentativas

        for attempt in range(MAX_VALIDATOR_RETRIES):
            elapsed = time.time() - file_start_time
            if elapsed > MAX_TEST_FILE_TIMEOUT_S:
                log(f"  [{test_name}] timeout de {MAX_TEST_FILE_TIMEOUT_S // 60}min atingido — encerrando reparos", "WARN")
                timed_out = True
                break

            if success and coverage >= 90.0:
                log(f"  [{test_name}] Cobertura atingida: {coverage:.2f}% ✓", "OK")
                break

            if not success:
                repair_hint = _categorize_build_error(combined_out, _prod_imports)
                error_history.append(f"Attempt {attempt + 1}: {repair_hint}")
                log(f"  [{test_name}] Reparo {attempt + 1}/{MAX_VALIDATOR_RETRIES}: {repair_hint[:80]}...", "WARN")
                history_block = (
                    f"REPAIR HISTORY (do NOT repeat these mistakes):\n"
                    + "\n".join(error_history) + "\n\n"
                ) if len(error_history) > 1 else ""
                error_msg = (
                    f"{_repair_strategy}\n\n"
                    f"{history_block}"
                    f"CURRENT ERROR: {repair_hint}\n\n"
                    f"MAVEN ERROR:\n{combined_out[-2000:]}"
                )
            else:
                log(f"  [{test_name}] Cobertura baixa: {coverage:.2f}%. Expandindo cobertura...", "WARN")
                error_msg = (
                    f"Tests passed but coverage is {coverage:.2f}% (minimum required: 90%).\n"
                    f"Add test methods to cover the following lines: {missed_lines}.\n"
                    "Do NOT remove existing tests — only add new @Test methods."
                )

            corrected_test = call_ai_with_correction(
                original=original, rules=active_rules, mode="test",
                file_name=test_name, file_path=test_path,
                bad_output=test_code, error_reason=error_msg, phase=phase,
                dep_context=test_dep_context,
            )

            if not corrected_test:
                log(f"  [{test_name}] LLM não gerou correção — encerrando reparos", "WARN")
                break

            # C2: valida nome da classe ANTES de escrever no disco
            _expected_cls = test_name.replace(".java", "")
            if f"class {_expected_cls}" not in corrected_test:
                _cls_found = re.search(r'(?:public\s+)?class\s+(\w+)', corrected_test)
                _found_name = _cls_found.group(1) if _cls_found else "UNKNOWN"
                combined_out = (
                    f"CLASS NAME CRITICAL ERROR: You generated `public class {_found_name}` "
                    f"but the file MUST be named `{_expected_cls}`.\n"
                    f"RENAME the class declaration to EXACTLY: `public class {_expected_cls} {{`\n"
                    "Java law: the public class name MUST equal the filename. No exceptions.\n"
                    "Do NOT abbreviate, shorten, or change the class name in any way.\n\n"
                ) + combined_out[-1000:]
                success = False
                continue  # não escreve o arquivo — força novo reparo com erro de classe

            # F2: valida package declaration ANTES de escrever no disco
            # O LLM pode preservar o nome da classe mas trocar o package (com.example.model etc.)
            if _test_pkg and f"package {_test_pkg};" not in corrected_test:
                _pkg_found = re.search(r'^package\s+([\w.]+);', corrected_test, re.MULTILINE)
                _found_pkg = _pkg_found.group(1) if _pkg_found else "UNKNOWN"
                combined_out = (
                    f"PACKAGE CRITICAL ERROR: You declared `package {_found_pkg};` "
                    f"but the file MUST use `package {_test_pkg};`.\n"
                    f"REPLACE the package declaration to EXACTLY: `package {_test_pkg};`\n"
                    f"NEVER abbreviate or invent a package — copy `{_test_pkg}` verbatim.\n"
                    f"Common mistake: writing `com.example.*` or shortened path instead of the full package.\n\n"
                ) + combined_out[-1000:]
                success = False
                continue  # não escreve o arquivo — força novo reparo com erro de package

            # S1: injeta imports ausentes no código corrigido antes de gravar (inclui self-import)
            corrected_test = _auto_inject_missing_imports(corrected_test, _s1_imports)
            write_file(test_path, corrected_test)
            test_code = corrected_test
            success, combined_out, coverage, missed_lines = maven_test_with_coverage(repo_path, file_name)

        # Após todos os reparos: aceita se compilou, reverte se não
        if not success:
            timeout_note = " (timeout)" if timed_out else ""
            err_reason = f"build quebrou após {MAX_VALIDATOR_RETRIES} reparos{timeout_note}"
            final_error_type = _categorize_build_error(combined_out)[:150]
            if complement_mode:
                # M8: restaura teste original em vez de apagar
                write_file(test_path, existing_test_code)
                log(f"  {test_name}: {err_reason} — complementação revertida", "WARN")
            else:
                os.remove(test_path)
                log(f"  {test_name}: {err_reason} — arquivo removido", "WARN")
            get_failed_tracker().record(test_path, phase, err_reason,
                                        stack_trace=combined_out)
            if exec_logger:
                exec_logger.log_file_reverted(phase, test_name, error_type=final_error_type)
            reporter.record_build_failed(phase, test_name)
            continue

        from ai.model import get_last_model as _get_model
        change_type = "+complement" if complement_mode else "+test"
        action_label = "COMPLEMENTADO" if complement_mode else "CRIADO"
        reporter.record_changed(phase, test_name, test_path,
                                existing_test_code if complement_mode else "", test_code)
        if exec_logger:
            exec_logger.log_file_accepted(phase, test_name, change_type)
            exec_logger.log_model_used(phase, test_name, _get_model(), "ACCEPTED")
        log(f"  {test_name} {action_label} ✓", "OK")
        any_changed = True

    return any_changed
def _attempt_global_sync(build_output: str, repo_path: str, rules: str, phase: str, trigger_file_content: str):
    """
    Skill de Sincronia Contextual 2.0: Usa o código recém-refatorado como
    referência para consertar as dependências em outros arquivos.
    """
    error_lines = [l for l in build_output.splitlines() if "cannot find symbol" in l or "does not override" in l]
    
    for line in error_lines[:3]:
        symbol, failing_file_abs = _extract_missing_symbol_and_target(line)
        if not failing_file_abs: continue
        
        if not os.path.exists(failing_file_abs): continue
        
        failing_file_name = os.path.basename(failing_file_abs)
        failing_file_rel = os.path.relpath(failing_file_abs, repo_path)
        log(f"  [Sincronia] Corrigindo impacto em {failing_file_name} usando contrato atualizado...", "WARN")
        
        old_content = read_file(failing_file_abs)
        sync_prompt = (
            f"The file {failing_file_rel} broke after refactoring the original file.\n"
            f"REFERENCE CONTRACT (Updated code):\n{trigger_file_content}\n\n"
            f"INSTRUCTION: Update {failing_file_rel} to be COMPATIBLE with the Reference Contract above.\n"
            f"- If a method signature changed, update the call or implementation accordingly.\n"
            f"- NEVER convert Interfaces into Classes.\n"
            f"- Keep the original business logic.\n\n"
            f"CODE THAT NEEDS TO BE FIXED:\n{old_content}"
        )
        
        new_content = call_ai(old_content, sync_prompt, "sync_fix", failing_file_rel, phase=phase)
        if new_content and new_content != old_content:
            write_file(failing_file_abs, new_content)

def _extract_missing_symbol_and_target(maven_line: str) -> tuple[str | None, str | None]:
    """Extrai o nome do símbolo e o caminho absoluto da classe desfalcada do log do Maven."""
    # O maven_line geralmente vem no formato: [ERROR] /caminho/completo/Arquivo.java:[linha,coluna] erro...
    m = re.search(r'(/.*?\.java):', maven_line)
    file_path = m.group(1) if m else None
    
    symbol = None
    if "method" in maven_line:
        m_sym = re.search(r'method (\w+)\(', maven_line)
        symbol = m_sym.group(1) if m_sym else None
        
    return symbol, file_path

def _get_line_from_file(file_path: str, line_number: int) -> str:
    """Retorna uma linha específica de um arquivo."""
    with open(file_path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f, 1):
            if i == line_number:
                return line
    return ""
