import os
import re
from core.utils import read_file

def get_dependency_context(file_code: str, repo_path: str) -> str:
    """
    Busca no repositório os arquivos importados no código atual
    e extrai suas assinaturas de classe e métodos para dar contexto à IA.
    """
    imports = re.findall(r'^import\s+([\w.]+);', file_code, re.MULTILINE)
    context_parts = []
    
    # Limita a busca para evitar contexto gigante
    for imp in imports[:10]: 
        if not imp.startswith("com.caju"): # Foca no código interno do projeto
             continue
             
        # Converte pacote em caminho de arquivo aproximado
        parts = imp.split('.')
        # Tenta encontrar o arquivo no repo
        potential_path = os.path.join(repo_path, "src", "main", "java", *parts) + ".java"
        
        if os.path.exists(potential_path):
            dep_code = read_file(potential_path)
            header = _extract_simplified_header(dep_code, imp)
            context_parts.append(header)
            
    if not context_parts:
        return ""
        
    return "\n--- CONTEXTO DE DEPENDÊNCIAS (SIGNATURES) ---\n" + "\n".join(context_parts)

def _extract_simplified_header(code: str, full_name: str) -> str:
    """Extrai apenas a declaração de classe e métodos (sem corpos)."""
    lines = code.splitlines()
    header_lines = []
    
    class_def_found = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(('import ', 'package ', '//', '/*')):
            continue
            
        if any(x in stripped for x in ('class ', 'interface ', 'enum ')):
            class_def_found = True
            header_lines.append(stripped + " {")
            continue
            
        if class_def_found and ('public ' in stripped or 'protected ' in stripped) and '(' in stripped:
            # Pega apenas a assinatura do método
            signature = stripped.split('{')[0].strip()
            if not signature.endswith(';'):
                signature += ";"
            header_lines.append("    " + signature)
            
    header_lines.append("}")
    return f"// Class: {full_name}\n" + "\n".join(header_lines)
