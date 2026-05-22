"""
data_holder_test_gen.py — Localização: java/data_holder_test_gen.py

Gerador determinístico de testes JUnit 5 para classes data-holder puras
(@Document / @Entity / POJOs com apenas campos + construtor + getters/setters).

Não envolve LLM — produz testes perfeitos e reproduzíveis sem repair loop.
"""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Tabela de tipos suportados: tipo → (import_stmt | None, sample_A, sample_B)
# ---------------------------------------------------------------------------
_SUPPORTED_TYPES: dict[str, tuple[Optional[str], str, str]] = {
    "String":        (None,                              '"sampleA"',                                  '"sampleB"'),
    "BigDecimal":    ("import java.math.BigDecimal;",    'new BigDecimal("100.00")',                   'new BigDecimal("250.50")'),
    "BigInteger":    ("import java.math.BigInteger;",    'BigInteger.valueOf(100)',                    'BigInteger.valueOf(250)'),
    "Timestamp":     ("import java.sql.Timestamp;",      'Timestamp.valueOf("2023-01-15 10:00:00")',   'Timestamp.valueOf("2024-06-20 14:30:00")'),
    "long":          (None,                              '1L',                                         '2L'),
    "Long":          (None,                              '1L',                                         '2L'),
    "int":           (None,                              '1',                                          '2'),
    "Integer":       (None,                              '1',                                          '2'),
    "double":        (None,                              '1.0',                                        '2.0'),
    "Double":        (None,                              '1.0',                                        '2.0'),
    "boolean":       (None,                              'true',                                       'false'),
    "Boolean":       (None,                              'true',                                       'false'),
    "LocalDate":     ("import java.time.LocalDate;",     'LocalDate.of(2023, 1, 15)',                  'LocalDate.of(2024, 6, 20)'),
    "LocalDateTime": ("import java.time.LocalDateTime;", 'LocalDateTime.of(2023, 1, 15, 10, 0)',       'LocalDateTime.of(2024, 6, 20, 14, 30)'),
}


# ---------------------------------------------------------------------------
# Regexes auxiliares
# ---------------------------------------------------------------------------

# Captura declaração de classe (não interface, enum, record)
_CLASS_DECL_RE = re.compile(
    r'(?:public\s+)?(?:final\s+)?(?:abstract\s+)?class\s+(\w+)',
    re.MULTILINE,
)

# Rejeita se contém interface/enum/record declaration
_NOT_CLASS_RE = re.compile(
    r'\b(?:interface|enum|record)\s+\w+',
    re.MULTILINE,
)

# Getter: public T getX() { return field; }  ou  public boolean isX() { return field; }
# Body MUST be exactly: return <one_identifier>;  — no ternary, operators, or calls.
_GETTER_RE = re.compile(
    r'public\s+\S+\s+(?:get|is)(\w+)\s*\(\s*\)\s*\{\s*return\s+\w+\s*;\s*\}',
    re.MULTILINE | re.DOTALL,
)

# Setter: public void setX(T v) { this.field = v; }
# Body MUST be exactly: this.<field> = <param>;  — both sides bare identifiers.
_SETTER_RE = re.compile(
    r'public\s+void\s+set(\w+)\s*\(\s*\S+\s+\w+\s*\)\s*\{\s*this\.\w+\s*=\s*\w+\s*;\s*\}',
    re.MULTILINE | re.DOTALL,
)

# Construtor: public ClassName(...)
_CTOR_RE = re.compile(
    r'public\s+(\w+)\s*\(([^)]*)\)\s*\{([^}]*)\}',
    re.MULTILINE | re.DOTALL,
)

# Método genérico (para detectar métodos não-getter/setter/ctor/eq/hc/ts)
_METHOD_RE = re.compile(
    r'(?:public|protected|private)\s+(?:static\s+)?(?:final\s+)?\S+\s+(\w+)\s*\([^)]*\)\s*\{',
    re.MULTILINE,
)

# Field declaration: private T name;
_FIELD_RE = re.compile(
    r'private\s+(\w+)\s+(\w+)\s*;',
    re.MULTILINE,
)

# Package declaration
_PACKAGE_RE = re.compile(r'^\s*package\s+([\w.]+)\s*;', re.MULTILINE)


# ---------------------------------------------------------------------------
# is_pure_data_holder
# ---------------------------------------------------------------------------

def is_pure_data_holder(code: str) -> bool:
    """
    Retorna True somente se ``code`` declara uma classe (não interface/enum/record)
    cujos TODOS os métodos são: getter, setter, construtor ou equals/hashCode/toString.
    Qualquer outra lógica → False.  Ambiguidade de parsing → False (conservador).
    """
    # Deve ter declaração de classe
    if not _CLASS_DECL_RE.search(code):
        return False

    # Não pode ser interface, enum ou record
    if _NOT_CLASS_RE.search(code):
        return False

    # Determina o nome da classe
    cls_match = _CLASS_DECL_RE.search(code)
    if not cls_match:
        return False
    class_name = cls_match.group(1)

    # Extrai o corpo da classe (tudo entre o { de abertura da declaração de classe e o } final)
    try:
        class_body = _extract_class_body(code, class_name)
    except Exception:
        return False

    if class_body is None:
        return False

    # Encontra todos os métodos declarados no corpo
    # Um "método" é qualquer bloco com modificador de acesso + tipo + nome + parênteses + chaves
    # Constrói lista de métodos encontrados
    methods = _METHOD_RE.findall(class_body)

    # Nomes permitidos
    allowed_names = {"equals", "hashCode", "toString"}

    # Constrói sets de getter e setter names
    getter_names = {m.group(1).lower() for m in _GETTER_RE.finditer(class_body)}
    setter_names = {m.group(1).lower() for m in _SETTER_RE.finditer(class_body)}
    ctor_names   = {class_name}

    for method_name in methods:
        name_lower = method_name.lower()
        if method_name in ctor_names:
            continue
        if method_name in allowed_names:
            continue
        # Getter: getXxx ou isXxx → suffix lowercase in getter_names
        if method_name.startswith("get") and name_lower[3:] in getter_names:
            continue
        if method_name.startswith("is") and name_lower[2:] in getter_names:
            continue
        # Setter
        if method_name.startswith("set") and name_lower[3:] in setter_names:
            continue
        # Nenhuma regra cobriu — método com outra lógica
        return False

    # Se não encontrou nenhum método, pode ser apenas campos → ainda é um data holder
    # mas só se tiver pelo menos um construtor (para ser testável)
    ctor_matches = [m for m in _CTOR_RE.finditer(class_body) if m.group(1) == class_name]
    if not ctor_matches:
        return False

    return True


def _extract_class_body(code: str, class_name: str) -> Optional[str]:
    """Extrai o conteúdo entre chaves da declaração da classe."""
    # Encontra a posição do `class ClassName` e caminha até a chave de abertura
    pattern = re.compile(
        r'(?:public\s+)?(?:final\s+)?(?:abstract\s+)?class\s+' + re.escape(class_name) + r'\b[^{]*\{',
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(code)
    if not m:
        return None

    start = m.end()  # posição logo após o '{'
    depth = 1
    i = start
    while i < len(code) and depth > 0:
        if code[i] == '{':
            depth += 1
        elif code[i] == '}':
            depth -= 1
        i += 1

    if depth != 0:
        return None  # chaves desbalanceadas

    return code[start:i - 1]


# ---------------------------------------------------------------------------
# generate_data_holder_test
# ---------------------------------------------------------------------------

def generate_data_holder_test(
    code: str,
    test_class_name: str,
    test_package: str,
) -> Optional[str]:
    """
    Gera o código-fonte Java completo de um teste JUnit 5 para a classe data-holder
    descrita em ``code``.

    Retorna None se:
    - ``code`` não é um data holder puro;
    - algum tipo de campo/parâmetro do construtor não está na tabela de tipos suportados;
    - o único construtor é no-arg;
    - os parâmetros do construtor não mapeiam 1:1 por nome para campos com getters.
    """
    if not is_pure_data_holder(code):
        return None

    # --- Extrai package e nome da classe de produção
    pkg_match = _PACKAGE_RE.search(code)
    prod_package = pkg_match.group(1) if pkg_match else ""

    cls_match = _CLASS_DECL_RE.search(code)
    if not cls_match:
        return None
    class_name = cls_match.group(1)

    # --- Extrai corpo da classe
    class_body = _extract_class_body(code, class_name)
    if class_body is None:
        return None

    # --- Extrai fields: name → type
    fields: dict[str, str] = {}
    for m in _FIELD_RE.finditer(class_body):
        ftype, fname = m.group(1), m.group(2)
        fields[fname] = ftype

    # --- Localiza construtor com argumentos
    ctor_params: list[tuple[str, str]] = []  # [(type, name), ...]
    for m in _CTOR_RE.finditer(class_body):
        if m.group(1) != class_name:
            continue
        params_str = m.group(2).strip()
        if not params_str:
            continue  # no-arg — ignora
        # Analisa parâmetros: "Type name, Type name, ..."
        params = [p.strip() for p in params_str.split(",") if p.strip()]
        parsed = []
        for p in params:
            parts = p.split()
            if len(parts) < 2:
                return None  # parsing ambíguo
            ptype = parts[-2]
            pname = parts[-1]
            parsed.append((ptype, pname))
        if parsed:
            ctor_params = parsed
            break

    if not ctor_params:
        return None  # somente construtor no-arg → não testável de forma útil

    # --- Valida que todos os tipos são suportados
    for ptype, _ in ctor_params:
        if ptype not in _SUPPORTED_TYPES:
            return None

    # --- Monta mapa de getters: field_name_lower → getter_method_name
    getter_map: dict[str, str] = {}
    for m in _GETTER_RE.finditer(class_body):
        suffix = m.group(1)  # "Id", "Name", etc.
        # Recupera o tipo de retorno para distinguir is/get
        full_match = m.group(0)
        if re.match(r'public\s+boolean\s+is', full_match):
            getter_method = "is" + suffix
        else:
            getter_method = "get" + suffix
        getter_map[suffix.lower()] = getter_method

    # --- Monta mapa de setters: field_name_lower → setter_method_name
    setter_map: dict[str, str] = {}
    for m in _SETTER_RE.finditer(class_body):
        suffix = m.group(1)
        setter_map[suffix.lower()] = "set" + suffix

    # --- Valida mapeamento 1:1 construtor → getter
    for ptype, pname in ctor_params:
        if pname.lower() not in getter_map:
            return None

    # --- Coleta imports necessários
    needed_imports: set[str] = set()
    for ptype, _ in ctor_params:
        imp, _, _ = _SUPPORTED_TYPES[ptype]
        if imp:
            needed_imports.add(imp)

    # Imports dos tipos dos setters (round-trip tests)
    for ptype, pname in ctor_params:
        pname_lower = pname.lower()
        if pname_lower in setter_map:
            imp, _, _ = _SUPPORTED_TYPES[ptype]
            if imp:
                needed_imports.add(imp)

    # Import da classe de produção
    if prod_package:
        prod_import = f"import {prod_package}.{class_name};"
    else:
        prod_import = None

    # --- Monta amostras
    sample_a: dict[str, str] = {}
    sample_b: dict[str, str] = {}
    for ptype, pname in ctor_params:
        _, sa, sb = _SUPPORTED_TYPES[ptype]
        sample_a[pname] = sa
        sample_b[pname] = sb

    # --- Gera lista de argumentos do construtor (sample A)
    ctor_args_a = ", ".join(sample_a[pname] for _, pname in ctor_params)

    # --- Gera bloco constructor_shouldInitializeAllFields
    assertions_lines = []
    for ptype, pname in ctor_params:
        getter_method = getter_map[pname.lower()]
        assertions_lines.append(
            f"        assertEquals({sample_a[pname]}, obj.{getter_method}());"
        )
    assertions_block = "\n".join(assertions_lines)

    constructor_test = (
        f"    @Test\n"
        f"    void constructor_shouldInitializeAllFields() {{\n"
        f"        {class_name} obj = new {class_name}({ctor_args_a});\n"
        f"{assertions_block}\n"
        f"    }}"
    )

    # --- Gera testes de round-trip setter/getter (um por setter que tem getter correspondente)
    round_trip_tests = []
    for ptype, pname in ctor_params:
        pname_lower = pname.lower()
        if pname_lower not in setter_map:
            continue
        setter_method = setter_map[pname_lower]
        getter_method = getter_map[pname_lower]
        # Capitaliza para o nome do teste: setId_getId_roundTrip
        cap = pname[0].upper() + pname[1:]
        test_method_name = f"set{cap}_get{cap}_roundTrip"
        sb = sample_b[pname]
        test_body = (
            f"    @Test\n"
            f"    void {test_method_name}() {{\n"
            f"        {class_name} obj = new {class_name}({ctor_args_a});\n"
            f"        obj.{setter_method}({sb});\n"
            f"        assertEquals({sb}, obj.{getter_method}());\n"
            f"    }}"
        )
        round_trip_tests.append(test_body)

    # --- Monta o arquivo completo
    lines: list[str] = []

    # package
    lines.append(f"package {test_package};")
    lines.append("")

    # imports
    lines.append("import org.junit.jupiter.api.Test;")
    lines.append("import static org.junit.jupiter.api.Assertions.*;")

    # type imports (sorted)
    for imp in sorted(needed_imports):
        lines.append(imp)

    # prod class import
    if prod_import:
        lines.append(prod_import)

    lines.append("")
    lines.append(f"class {test_class_name} {{")
    lines.append("")

    # constructor test
    lines.append(constructor_test)

    # round-trip tests
    for t in round_trip_tests:
        lines.append("")
        lines.append(t)

    lines.append("")
    lines.append("}")

    return "\n".join(lines) + "\n"
