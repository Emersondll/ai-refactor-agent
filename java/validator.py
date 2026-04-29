"""
validator.py — Localização: java/validator.py

SOLUÇÕES APLICADAS:
  1. Ampliar is_modern_java — cobre mais padrões Java 14+ para eliminar
     falsos positivos do javalang 0.13.0
  3. Logar trecho do erro — ao rejeitar por sintaxe, loga as linhas
     ao redor do erro para facilitar diagnóstico
"""

import os
import re
import javalang
from core.logger import log


_JAVA_DECL = re.compile(r'\b(class|interface|enum|record)\s+\w+', re.MULTILINE)
_DECL_NAME = re.compile(r'\b(?:class|interface|enum|record)\s+(\w+)', re.MULTILINE)

# ---------------------------------------------------------------------------
# Solução 1 — Ampliar is_modern_java
#
# Antes cobria: record, case ->, """, sealed
# Agora cobre também:
#   - var (Java 10+)
#   - yield (switch expression Java 13+)
#   - instanceof com pattern matching (Java 16+): instanceof String s
#   - @interface (anotações personalizadas — javalang rejeita às vezes)
#   - text block com indentação variável
#   - non-sealed (Java 17+)
#   - permits (Java 17+)
# ---------------------------------------------------------------------------

_MODERN_JAVA_HINTS = [
    # Java 16+ — record class
    re.compile(r'\brecord\s+\w+\s*[(<]'),

    # Java 14+ — switch expression com arrow
    re.compile(r'\bcase\b[^:]*->'),

    # Java 15+ — text block
    re.compile(r'"""'),

    # Java 17+ — sealed e non-sealed
    re.compile(r'\b(?:sealed|non-sealed)\s+(?:class|interface)'),
    re.compile(r'\bpermits\s+\w'),

    # Java 10+ — var local variable
    re.compile(r'\bvar\s+\w+\s*='),

    # Java 16+ — pattern matching instanceof
    re.compile(r'\binstanceof\s+\w+\s+\w+'),

    # Java 13+ — yield em switch
    re.compile(r'\byield\s+'),

    # Annotation declarations (javalang às vezes rejeita @interface)
    re.compile(r'public\s+@interface\s+\w+'),
]


def is_modern_java(code: str) -> bool:
    """Detecta features de Java 10+ que javalang 0.13.0 não suporta."""
    for pattern in _MODERN_JAVA_HINTS:
        if pattern.search(code):
            return True
    return False


def extract_type_name(code: str) -> str | None:
    m = _DECL_NAME.search(code)
    return m.group(1) if m else None


def has_invalid_imports(code: str) -> bool:
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith("import "):
            if any(x in stripped for x in ["..", "springforg", "utijava"]):
                return True
    return False


# ---------------------------------------------------------------------------
# Solução 3 — Logar trecho do erro
#
# javalang retorna JavaSyntaxError com position (line, column).
# Ao rejeitar, extraímos e logamos as 3 linhas ao redor do erro
# para diagnóstico imediato sem precisar abrir o arquivo.
# ---------------------------------------------------------------------------

def _log_syntax_context(code: str, error: Exception) -> None:
    """Loga as linhas ao redor do erro de sintaxe para diagnóstico."""
    lines = code.splitlines()
    error_line = None

    # javalang expõe a posição via .position ou parseando a mensagem
    if hasattr(error, 'position') and error.position:
        try:
            error_line = int(error.position[0]) - 1  # 0-indexed
        except (TypeError, IndexError):
            pass

    if error_line is None:
        # Tenta extrair linha da string do erro
        m = re.search(r'line\s+(\d+)', str(error), re.IGNORECASE)
        if m:
            error_line = int(m.group(1)) - 1

    if error_line is not None and 0 <= error_line < len(lines):
        start = max(0, error_line - 2)
        end   = min(len(lines), error_line + 3)
        log("  Contexto do erro:", "WARN")
        for i in range(start, end):
            marker = ">>>" if i == error_line else "   "
            log(f"  {marker} L{i+1:3}: {lines[i]}", "WARN")
    else:
        # Sem posição — loga as primeiras linhas do trecho problemático
        log("  Trecho inicial do código rejeitado:", "WARN")
        for i, line in enumerate(lines[:8]):
            log(f"    L{i+1:3}: {line}", "WARN")


def check_syntax(code: str) -> tuple[bool, str]:
    """
    Tenta validar sintaxe com javalang, mas o resultado é apenas indicativo.

    javalang 0.13.0 é não confiável:
      - Rejeita Java 14+ (record, switch expression, var, yield, etc.)
      - Retorna JavaSyntaxError com mensagem VAZIA tanto para erros reais
        quanto para construtos que não conhece
      - Não distingue falso positivo de erro real

    Por isso:
      - Parse OK → sinal positivo, aceita
      - Parse falha com mensagem vazia → aceita (não confiável)
      - Parse falha com mensagem + Java moderno → aceita
      - Parse falha com mensagem real + Java clássico → rejeita + loga contexto

    O Maven (mvn clean test) é o validador definitivo de sintaxe.
    O javalang serve apenas como filtro rápido para erros grosseiros.
    """
    try:
        javalang.parse.parse(code)
        return True, ""
    except javalang.parser.JavaSyntaxError as e:
        error_msg = str(e).strip()

        # Mensagem vazia = javalang não sabe descrever o problema →
        # não é confiável, deixa o Maven decidir
        if not error_msg:
            return True, ""

        # Java moderno que javalang não suporta
        if is_modern_java(code):
            return True, ""

        # Único caso que rejeita: mensagem descritiva + Java clássico
        _log_syntax_context(code, e)
        return False, f"Erro de sintaxe: {error_msg[:120]}"

    except Exception as e:
        # Qualquer outra exceção sem mensagem → aceita
        if not str(e).strip() or is_modern_java(code):
            return True, ""
        return False, f"Parse falhou: {type(e).__name__}: {str(e)[:80]}"


def is_valid_java(original: str, new: str) -> tuple[bool, str]:
    """Pipeline de validação — apenas estrutura técnica."""

    if not new or not new.strip():
        return False, "Código vazio"

    if '\x1b' in new or '\u001b' in new:
        return False, "ANSI detectado"

    if new.strip() == original.strip():
        return False, "Código idêntico ao original"

    if not _JAVA_DECL.search(new):
        return False, "Sem declaração Java reconhecível"

    if has_invalid_imports(new):
        return False, "Import com typo"

    if new.count("{") != new.count("}"):
        return False, (
            f"Chaves desbalanceadas: "
            f"{new.count('{')}x'{{' vs {new.count('}')}x'}}'"
        )

    ok, reason = check_syntax(new)
    if not ok:
        return False, reason

    return True, ""
def validate_class_name_matches_file(code: str, file_path: str) -> tuple[bool, str]:
    """
    Verifica se o código gerado contém uma classe/interface/enum 
    que corresponde ao nome do arquivo físico.
    """
    file_name = os.path.basename(file_path).replace(".java", "")
    pattern = rf'public\s+(class|interface|enum|record)\s+({file_name})\b'
    
    if re.search(pattern, code):
        return True, ""
    
    any_public = re.search(r'public\s+(class|interface|enum|record)\s+(\w+)', code)
    if any_public:
        found_name = any_public.group(2)
        return False, f"O arquivo se chama '{file_name}.java' mas você gerou a classe '{found_name}'."
    
    return False, f"Não foi encontrada uma classe pública '{file_name}' no código gerado."
