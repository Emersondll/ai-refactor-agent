"""
scope_reducer.py — Localização: java/scope_reducer.py

Reduz o escopo de processamento para arquivos grandes.

Problema resolvido:
  Arquivos > MAX_FILE_LINES eram pulados completamente porque modelos 7b
  truncam o contexto — o código saía incompleto ou corrompido.

Solução:
  Em vez de pular o arquivo, processa método a método:
    1. Extrai o cabeçalho da classe (package, imports, fields, construtores)
    2. Extrai cada método individualmente
    3. Monta um contexto mínimo: cabeçalho + 1 método por vez
    4. Envia esse contexto reduzido para o modelo (< 50 linhas em geral)
    5. Extrai apenas o método refatorado da resposta
    6. Substitui o método no arquivo original
    7. Repete para todos os métodos

Benefícios:
  - Arquivos de 200+ linhas passam a ser processados
  - Modelos 7b recebem contexto pequeno (alta qualidade de saída)
  - Cada método é validado individualmente antes de ser aceito
"""

import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Estruturas de dados
# ---------------------------------------------------------------------------

@dataclass
class JavaMethod:
    """Representa um método extraído de uma classe Java."""
    name: str             # nome do método (ex: performTransaction)
    signature: str        # assinatura completa (ex: public void doX(String s))
    full_text: str        # texto completo do método incluindo anotações
    start_line: int       # linha de início (0-indexed)
    end_line: int         # linha de fim (0-indexed, inclusive)


@dataclass
class ClassHeader:
    """Cabeçalho da classe: tudo antes do primeiro método."""
    text: str             # texto completo do cabeçalho
    end_line: int         # última linha do cabeçalho (0-indexed)


# ---------------------------------------------------------------------------
# Regex de detecção
# ---------------------------------------------------------------------------

# Detecta início de método: modificadores + tipo de retorno + nome + parênteses
_METHOD_START = re.compile(
    r'^(\s*)'                                          # indentação
    r'(?:(?:\/\*\*[\s\S]*?\*\/\s*)?)?'               # javadoc opcional
    r'(?:@\w+(?:\([^)]*\))?\s*\n\s*)*'               # anotações
    r'(?:public|protected|private|static|final|'
    r'abstract|synchronized|native|\s)+'              # modificadores
    r'[\w<>\[\],\s?]+\s+'                             # tipo de retorno
    r'(\w+)\s*\(',                                    # nome do método
    re.MULTILINE,
)

# Detecta se uma linha é início de método (simples, linha a linha)
_METHOD_LINE = re.compile(
    r'^\s*(?:@\w+(?:\([^)]*\))?\s*)*'
    r'(?:(?:public|protected|private|static|final|abstract|synchronized)\s+)+'
    r'(?:[\w<>\[\],]+\s+)+'
    r'\w+\s*\([^)]*\)\s*(?:throws\s+[\w\s,]+)?\s*\{'
)

# Detecta se uma linha é apenas uma anotação
_ANNOTATION_LINE = re.compile(r'^\s*@\w+')


# ---------------------------------------------------------------------------
# Extração de cabeçalho
# ---------------------------------------------------------------------------

def extract_class_header(code: str) -> ClassHeader:
    """
    Extrai tudo antes do primeiro método: package, imports, anotações
    de classe, declaração de classe, campos e construtores simples.

    Heurística: o cabeçalho termina na linha anterior ao primeiro
    método que não seja o construtor.
    """
    lines = code.splitlines()
    
    # Encontra o primeiro método público/privado com corpo
    for i, line in enumerate(lines):
        if _METHOD_LINE.match(line):
            # Retorna tudo até essa linha como cabeçalho
            # (mantém a linha em branco antes do método)
            end = max(0, i - 1)
            return ClassHeader(
                text='\n'.join(lines[:i]),
                end_line=end,
            )
    
    # Nenhum método encontrado — retorna o arquivo inteiro como cabeçalho
    return ClassHeader(text=code, end_line=len(lines) - 1)


# ---------------------------------------------------------------------------
# Extração de métodos
# ---------------------------------------------------------------------------

def extract_methods(code: str) -> list[JavaMethod]:
    """
    Extrai todos os métodos de uma classe Java usando balanceamento de chaves.

    Cada método inclui suas anotações e javadoc imediatamente acima dele.
    """
    lines = code.splitlines()
    methods: list[JavaMethod] = []
    i = 0

    while i < len(lines):
        # Verifica se a linha (e possíveis linhas de anotação acima) marca início de método
        if _is_method_start(lines, i):
            # Retrocede para incluir anotações e javadoc acima do método
            method_start = _find_annotation_start(lines, i)

            # Avança até encontrar a chave de abertura
            brace_line = i
            while brace_line < len(lines) and '{' not in lines[brace_line]:
                brace_line += 1

            if brace_line >= len(lines):
                i += 1
                continue

            # Balanceia chaves para encontrar o fim do método
            depth = 0
            j = brace_line
            while j < len(lines):
                depth += lines[j].count('{') - lines[j].count('}')
                if depth == 0:
                    # Fim do método encontrado
                    full_text = '\n'.join(lines[method_start:j + 1])
                    name = _extract_method_name(lines[i])
                    signature = lines[i].strip()

                    methods.append(JavaMethod(
                        name=name,
                        signature=signature,
                        full_text=full_text,
                        start_line=method_start,
                        end_line=j,
                    ))
                    i = j + 1
                    break
                j += 1
            else:
                i += 1
        else:
            i += 1

    return methods


def _is_method_start(lines: list[str], i: int) -> bool:
    """Verifica se a linha i é o início de uma declaração de método."""
    line = lines[i]
    # Ignora anotações puras
    if _ANNOTATION_LINE.match(line) and '(' not in line:
        return False
    return bool(_METHOD_LINE.match(line))


def _find_annotation_start(lines: list[str], i: int) -> int:
    """Retrocede a partir da linha i para incluir anotações e javadoc."""
    start = i
    j = i - 1
    while j >= 0:
        stripped = lines[j].strip()
        if stripped.startswith('@') or stripped.startswith('*') or stripped.startswith('/*'):
            start = j
            j -= 1
        elif stripped == '':
            j -= 1
        else:
            break
    return start


def _extract_method_name(signature_line: str) -> str:
    """Extrai o nome do método de uma linha de assinatura."""
    m = re.search(r'(\w+)\s*\(', signature_line)
    return m.group(1) if m else 'unknown'


# ---------------------------------------------------------------------------
# Construção de contexto reduzido
# ---------------------------------------------------------------------------

def build_method_context(header: ClassHeader, method: JavaMethod,
                          close_class: bool = True) -> str:
    """
    Monta um contexto mínimo para o modelo processar um único método.

    Estrutura:
        [cabeçalho da classe — package, imports, declaração, fields]
        [apenas o método alvo]
        [fechamento da classe: }]

    Isso garante que o modelo veja um arquivo Java sintaticamente completo
    mas com apenas 1 método para refatorar — contexto muito menor.
    """
    parts = [header.text.rstrip()]
    parts.append('')
    parts.append(method.full_text)
    if close_class:
        parts.append('}')
    return '\n'.join(parts)


# ---------------------------------------------------------------------------
# Extração do método refatorado da resposta da IA
# ---------------------------------------------------------------------------

def extract_refactored_method(ai_response: str, original_method: JavaMethod) -> str | None:
    """
    Extrai apenas o método refatorado da resposta da IA.

    A IA recebe um arquivo completo (header + 1 método) e devolve
    um arquivo completo. Precisamos extrair apenas o método de volta.

    Estratégia:
        1. Busca pelo nome do método na resposta
        2. Balanceia chaves a partir daí
        3. Retorna apenas o bloco do método
    """
    if not ai_response:
        return None

    lines = ai_response.splitlines()
    method_name = original_method.name

    # Encontra a linha que declara o método pelo nome
    method_line = None
    for i, line in enumerate(lines):
        if method_name + '(' in line and _METHOD_LINE.match(line):
            method_line = i
            break

    if method_line is None:
        # Tenta encontrar sem o regex estrito
        for i, line in enumerate(lines):
            if method_name + '(' in line and '{' in line:
                method_line = i
                break

    if method_line is None:
        return None

    # Retrocede para incluir anotações e javadoc
    start = _find_annotation_start(lines, method_line)

    # Balanceia chaves para extrair o bloco completo
    depth = 0
    found_open = False
    for j in range(method_line, len(lines)):
        depth += lines[j].count('{') - lines[j].count('}')
        if '{' in lines[j]:
            found_open = True
        if found_open and depth == 0:
            return '\n'.join(lines[start:j + 1])

    return None


# ---------------------------------------------------------------------------
# Substituição no arquivo original
# ---------------------------------------------------------------------------

def replace_method_in_file(original_code: str, method: JavaMethod,
                            new_method_text: str) -> str:
    """
    Substitui o método original pelo método refatorado no arquivo completo.

    Preserva todas as outras linhas do arquivo intactas.
    """
    lines = original_code.splitlines()
    new_lines = (
        lines[:method.start_line]
        + new_method_text.splitlines()
        + lines[method.end_line + 1:]
    )
    return '\n'.join(new_lines)


# ---------------------------------------------------------------------------
# API principal
# ---------------------------------------------------------------------------

def is_large_file(code: str, threshold: int = 100) -> bool:
    """
    Retorna True se o arquivo deve ser processado por método.

    Threshold menor que MAX_FILE_LINES do refactor.py — processa
    arquivos que antes eram pulados (200 linhas) e também os médios
    que o 7b trata mal (100+ linhas).
    """
    return len(code.splitlines()) >= threshold


def get_processable_methods(code: str) -> list[JavaMethod]:
    """
    Retorna apenas os métodos que valem a pena processar individualmente.
    Exclui: getters/setters triviais (< 5 linhas), métodos sem corpo.
    """
    all_methods = extract_methods(code)
    return [
        m for m in all_methods
        if len(m.full_text.splitlines()) >= 4   # exclui triviais de 1-3 linhas
    ]
