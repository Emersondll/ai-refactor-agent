import re
from core.utils import force_safe_encoding


# ---------------------------------------------------------------------------
# Limpeza de caracteres inválidos
# ---------------------------------------------------------------------------

def sanitize_java_code(code: str) -> str:
    code = re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', '', code)
    code = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', code)
    code = code.replace('\ufeff', '').replace('\u200b', '')
    return code.strip()


# ---------------------------------------------------------------------------
# HTML entities → caracteres reais
# ---------------------------------------------------------------------------

def unescape_html_entities(code: str) -> str:
    """
    Modelos às vezes codificam < e > como entidades HTML dentro de generics.
    Ex: JpaRepository&lt;Balance, Long&gt;  →  JpaRepository<Balance, Long>
    """
    code = code.replace('&lt;',  '<')
    code = code.replace('&gt;',  '>')
    code = code.replace('&amp;', '&')
    code = code.replace('&apos;', "'")
    code = code.replace('&quot;', '"')
    return code


# ---------------------------------------------------------------------------
# Reconstitui linhas package/import truncadas
# ---------------------------------------------------------------------------

def fix_package_import_lines(code: str) -> str:
    """
    Corrige quebras de linha indevidas em declarações package/import.

    Padrões detectados:
      1. import sem ; no final seguido de continuação com .
         import com.example.service    →  import com.example.service.impl;
         .impl;

      2. import sem ; seguido de ; sozinho
         import com.example.Foo        →  import com.example.Foo;
         ;

      3. NOVO — import truncado seguido de linha de pacote "órfã" (sem import):
         import ...MerchantCategoryCodesDocumen;     ← truncado pelo modelo
         com...MerchantCategoryCodesDocument;        ← continuação sem "import"

         Solução: substitui o import truncado pelo completo da linha órfã.
    """
    # Detecta linha que parece um pacote Java mas não tem "import" na frente
    _ORPHAN_PKG = re.compile(r'^[a-z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+;?$')

    lines  = code.splitlines()
    result = []
    i      = 0

    while i < len(lines):
        line     = lines[i]
        stripped = line.strip()

        is_pkg_or_import = (
            stripped.startswith("package ")
            or stripped.startswith("import ")
        )

        if is_pkg_or_import and not stripped.endswith(";"):
            # Caso 1 e 2: une com próximas linhas
            combined = stripped
            while i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if nxt in (";", "") or nxt.startswith("."):
                    i += 1
                    if nxt == ";":
                        combined += ";"
                        break
                    elif nxt.startswith("."):
                        combined += nxt
                        if combined.endswith(";"):
                            break
                else:
                    break

            if not combined.endswith(";"):
                combined += ";"
            result.append(combined)

        elif not is_pkg_or_import and _ORPHAN_PKG.match(stripped) and stripped:
            # Caso 3: linha de pacote órfã após um import
            if result and result[-1].startswith("import "):
                # Substitui o import anterior (possivelmente truncado) por este
                # que é o mais completo
                fixed = "import " + stripped
                if not fixed.endswith(";"):
                    fixed += ";"
                result[-1] = fixed
                # Não adiciona a linha órfã — ela substitui a anterior
            else:
                # Linha solta sem contexto de import — adiciona import na frente
                fixed = "import " + stripped
                if not fixed.endswith(";"):
                    fixed += ";"
                result.append(fixed)

        else:
            result.append(line)

        i += 1

    return "\n".join(result)


# ---------------------------------------------------------------------------
# Reconstitui generics quebrados entre linhas
# ---------------------------------------------------------------------------

def fix_broken_generics(code: str) -> str:
    """
    Reconstitui declarações de tipo genérico quebradas pelo modelo.

    O modelo frequentemente quebra a linha dentro de um bloco <...>:
      public interface Foo extends JpaRepository<Balance,
                                                 Long> {

    ou sem o espaço:
      JpaRepository<Balance,\nLong>

    Este passo une as linhas sempre que uma linha termina com vírgula
    dentro de um contexto de generics (< aberto sem > fechado).
    """
    lines  = code.splitlines()
    result = []
    i      = 0

    while i < len(lines):
        line = lines[i]

        # Conta < e > na linha atual — se não fechou, une com a próxima
        open_generics = line.count('<') - line.count('>')

        while open_generics > 0 and i + 1 < len(lines):
            i   += 1
            nxt  = lines[i].strip()
            line = line.rstrip() + ' ' + nxt
            open_generics += nxt.count('<') - nxt.count('>')

        result.append(line)
        i += 1

    return "\n".join(result)


# ---------------------------------------------------------------------------
# Correções menores de tokens colados
# ---------------------------------------------------------------------------

def fix_common_syntax_issues(code: str) -> str:
    code = re.sub(r'(\w)(public\s|class\s|interface\s|enum\s)', r'\1\n\2', code)
    return code


# ---------------------------------------------------------------------------
# Extração principal
# ---------------------------------------------------------------------------

def clean_output(text: str) -> str | None:
    if not text:
        return None

    text = force_safe_encoding(text)

    m = re.search(r"```java\s*([\s\S]*?)```", text)
    if m:
        return _finalize(m.group(1))

    m = re.search(r"```[\w]*\s*([\s\S]*?)```", text)
    if m:
        return _finalize(m.group(1))

    m = re.search(
        r"^(package\s+[\w.]+|import\s+[\w.]+|/\*\*?"
        r"|public\s+(?:class|interface|enum|record|@interface)"
        r"|class\s+\w|interface\s+\w|enum\s+\w)",
        text, re.MULTILINE,
    )
    if m:
        return _finalize(text[m.start():])

    return None


def _is_brace_balanced(code: str) -> bool:
    """Rejeita output truncado antes do Maven — conta { vs } fora de strings/comentários."""
    depth = 0
    in_string = False
    in_char = False
    in_line_comment = False
    in_block_comment = False
    i = 0
    while i < len(code):
        c = code[i]
        if in_line_comment:
            if c == '\n':
                in_line_comment = False
        elif in_block_comment:
            if c == '*' and i + 1 < len(code) and code[i + 1] == '/':
                in_block_comment = False
                i += 1
        elif in_string:
            if c == '\\':
                i += 1
            elif c == '"':
                in_string = False
        elif in_char:
            if c == '\\':
                i += 1
            elif c == "'":
                in_char = False
        else:
            if c == '/' and i + 1 < len(code) and code[i + 1] == '/':
                in_line_comment = True
                i += 1
            elif c == '/' and i + 1 < len(code) and code[i + 1] == '*':
                in_block_comment = True
                i += 1
            elif c == '"':
                in_string = True
            elif c == "'":
                in_char = True
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
        i += 1
    return depth == 0


def _finalize(code: str) -> str | None:
    code = sanitize_java_code(code)
    code = unescape_html_entities(code)
    code = fix_package_import_lines(code)
    code = fix_broken_generics(code)
    code = fix_common_syntax_issues(code)
    code = _fix_missing_semicolons(code)
    if not code.strip():
        return None
    if not _is_brace_balanced(code):
        return None  # output truncado — rejeita antes do Maven
    return code.strip()


def _fix_missing_semicolons(code: str) -> str:
    lines = code.splitlines()
    refined = []
    # Skill para corrigir falta de ponto e vírgula em locais óbvios
    needs_semicolon = re.compile(r'^\s*(return|throw|import|package|int|String|boolean|long|float|double)\b(?!.*;\s*$).*[^;{}]\s*$')
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.endswith((";", "{", "}", ",", "(", ")", ":")):
            refined.append(line)
        elif needs_semicolon.match(line):
            refined.append(line + ";")
        else:
            refined.append(line)
    return "\n".join(refined)