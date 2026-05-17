"""
java/method_extractor.py — Extrai métodos individuais de código Java.

Usa contagem de chaves (sem parser AST). Suporta:
- Métodos de instância e estáticos
- Construtores
- Anotações multi-linha
- Assinaturas com parâmetros em múltiplas linhas
- Herança de interfaces (default methods)
"""

import re
from dataclasses import dataclass, field


@dataclass
class MethodDef:
    signature: str          # "public Result process(Transaction t)"
    annotations: list[str]  # ["@Override", "@Transactional"]
    full_text: str          # anotações + assinatura + corpo completo
    body: str               # conteúdo entre { } (sem os próprios delimitadores)
    start_line: int         # 1-indexed, inclusive (primeira anotação ou assinatura)
    end_line: int           # 1-indexed, inclusive (linha do } final)
    is_constructor: bool = False

    @property
    def cache_key(self) -> str:
        """Chave única para cache — normaliza espaços da assinatura."""
        return re.sub(r'\s+', ' ', self.signature.strip())


# Padrão que identifica o início de uma declaração de método
_METHOD_START = re.compile(
    r'^\s*'
    r'(?:(?:public|private|protected)\s+)?'
    r'(?:(?:static|final|synchronized|abstract|default|native)\s+)*'
    r'(?:[\w<>\[\],\s?]+\s+)'   # tipo de retorno (inclui genéricos)
    r'(\w+)\s*\('               # nome do método + (
)

# Padrão de anotação
_ANNOTATION = re.compile(r'^\s*@\w+')

# Padrão de declaração de classe interna, interface, enum
_INNER_TYPE = re.compile(
    r'^\s*(?:public|private|protected|static)?\s*'
    r'(?:static\s+)?(?:final\s+)?'
    r'(?:class|interface|enum|record)\s+\w+'
)

# Padrão de campo (declaração de variável de instância)
_FIELD = re.compile(
    r'^\s*(?:private|protected|public)?\s*'
    r'(?:static\s+)?(?:final\s+)?'
    r'[\w<>\[\],]+\s+\w+\s*(?:=|;)'
)


def extract_methods(code: str) -> list[MethodDef]:
    """
    Extrai todos os métodos (incluindo construtores) de um arquivo Java.
    Ignora campos, declarações de tipo internas e blocos estáticos.
    """
    lines = code.splitlines()
    methods: list[MethodDef] = []

    i = 0
    class_brace_depth = 0  # profundidade após o { da classe externa
    class_opened = False

    while i < len(lines):
        line = lines[i]

        # Detecta abertura da classe principal (primeira { de classe/record)
        if not class_opened:
            if re.search(r'(?:class|record|interface|enum)\s+\w+', line) and '{' in line:
                class_opened = True
                class_brace_depth = 1
            i += 1
            continue

        # Rastreia profundidade dentro da classe
        # (para evitar métodos de classes internas serem confundidos com top-level)
        stripped = line.strip()

        # Pula linhas em branco e comentários simples
        if not stripped or stripped.startswith('//'):
            i += 1
            continue

        # Coleta anotações antes de um possível método
        annotations: list[str] = []
        ann_start = i
        while i < len(lines) and _ANNOTATION.match(lines[i]):
            annotations.append(lines[i].strip())
            i += 1
        if i >= len(lines):
            break

        line = lines[i]

        # Ignora declarações de tipo interno
        if _INNER_TYPE.match(line):
            # Avança até o { para ajustar profundidade depois
            while i < len(lines) and '{' not in lines[i]:
                i += 1
            i += 1
            continue

        # Ignora campos
        if _FIELD.match(line) and '{' not in line:
            i += 1
            continue

        # Tenta encontrar início de método
        # A assinatura pode se estender por múltiplas linhas até o )
        sig_start = i
        sig_lines = []
        found_open_paren = False

        # Lê até encontrar ) { ou ; (abstrato/interface sem corpo)
        temp_i = i
        paren_depth = 0
        sig_complete = False

        while temp_i < len(lines):
            sig_line = lines[temp_i]
            sig_lines.append(sig_line)

            for ch in sig_line:
                if ch == '(':
                    paren_depth += 1
                    found_open_paren = True
                elif ch == ')':
                    paren_depth -= 1
                    if paren_depth == 0 and found_open_paren:
                        sig_complete = True

            if sig_complete:
                break
            temp_i += 1

        if not sig_complete or not found_open_paren:
            i += 1
            continue

        # Verifica se é realmente uma assinatura de método (não um if/while/for/catch)
        first_sig_line = sig_lines[0].strip()
        if re.match(r'^(?:if|while|for|catch|switch|else)\s*\(', first_sig_line):
            i += 1
            continue

        # Verifica se tem modificador ou tipo de retorno válido
        if not _METHOD_START.match(sig_lines[0]) and not re.match(
            r'^\s*(?:public|private|protected)?\s*\w+\s*\(', sig_lines[0]
        ):
            i = max(i + 1, ann_start + 1)
            continue

        # Monta assinatura normalizada — remove { e throws
        raw_sig = ' '.join(l.strip() for l in sig_lines)
        signature = re.sub(r'\s+', ' ', raw_sig).strip()
        signature = re.sub(r'\s+throws\s+[\w,\s]+', '', signature)
        signature = re.sub(r'\s*\{.*$', '', signature).strip()  # remove { e o que vier depois

        # Avança para a linha que contém o { de abertura do corpo
        i = temp_i + 1
        # Método abstrato ou de interface sem corpo (termina em ;)
        after_paren = ' '.join(sig_lines).split(')')[-1].strip()
        if after_paren.lstrip().startswith(';') or re.search(r'\)\s*;', ' '.join(sig_lines)):
            continue  # método sem corpo — ignora

        # Encontra o { de abertura do corpo
        body_open_line = i - 1
        while body_open_line < len(lines) and '{' not in lines[body_open_line]:
            body_open_line += 1
        if body_open_line >= len(lines):
            continue

        # Coleta o corpo inteiro usando contagem de chaves
        brace_depth = 0
        body_lines: list[str] = []
        body_start_line = body_open_line
        j = body_open_line

        while j < len(lines):
            body_lines.append(lines[j])
            for ch in lines[j]:
                if ch == '{':
                    brace_depth += 1
                elif ch == '}':
                    brace_depth -= 1
                    if brace_depth == 0:
                        break
            if brace_depth == 0:
                break
            j += 1

        if brace_depth != 0:
            i = j + 1
            continue  # chaves desbalanceadas — pula

        end_line = j
        full_text_lines = lines[ann_start:end_line + 1]
        full_text = '\n'.join(full_text_lines)

        # Extrai apenas o corpo (entre o primeiro { e o último })
        body_text = '\n'.join(body_lines)
        body_inner = re.sub(r'^[^{]*\{', '', body_text, count=1)
        body_inner = re.sub(r'\}[^}]*$', '', body_inner)

        # Detecta se é construtor (nome da classe, sem tipo de retorno)
        is_ctor = bool(re.match(r'^\s*(?:public|private|protected)?\s*[A-Z]\w*\s*\(', sig_lines[0]))

        methods.append(MethodDef(
            signature=signature,
            annotations=annotations,
            full_text=full_text,
            body=body_inner,
            start_line=ann_start + 1,   # 1-indexed
            end_line=end_line + 1,       # 1-indexed
            is_constructor=is_ctor,
        ))

        i = end_line + 1

    return methods


def method_signature_normalized(sig: str) -> str:
    """Normaliza assinatura para usar como chave de cache."""
    return re.sub(r'\s+', ' ', sig.strip())
