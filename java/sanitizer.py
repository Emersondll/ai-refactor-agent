import os
import re
from core.logger import log
from core.utils import read_file, write_file
from java.compiler import maven_test_with_coverage

def run_sanitization(repo_path: str):
    """
    Executa a etapa final de sanitização:
    1. Remove métodos não utilizados.
    2. Identifica blocos duplicados (TODO: Implementar lógica de similaridade profunda).
    """
    log("Iniciando sanitização final do projeto...", "PHASE")
    
    java_files = []
    for root, _, files in os.walk(repo_path):
        if "src/main/java" not in root: continue
        for f in files:
            if f.endswith(".java"):
                java_files.append(os.path.join(root, f))

    for file in java_files:
        _sanitize_file(file, java_files, repo_path)

    log("Sanitização concluída.", "OK")

def _sanitize_file(file_path: str, all_files: list, repo_path: str):
    content = read_file(file_path)
    file_name = os.path.basename(file_path)
    
    # Extrai nomes de métodos públicos e privados (heurística simples)
    methods = re.findall(r'(?:public|private|protected)\s+[\w<>]+\s+(\w+)\s*\(', content)
    
    modified = False
    new_content = content
    
    for method in methods:
        if method in ["main", "toString", "equals", "hashCode", "getId", "setId"]: continue
        
        # Verifica se o método é usado em QUALQUER arquivo do projeto
        is_used = False
        pattern = re.compile(rf'\b{method}\s*\(')
        
        for other_file in all_files:
            other_content = read_file(other_file)
            # Se for o próprio arquivo, tem que aparecer mais de uma vez (a declaração não conta)
            if other_file == file_path:
                if len(pattern.findall(other_content)) > 1:
                    is_used = True
                    break
            else:
                if pattern.search(other_content):
                    is_used = True
                    break
        
        if not is_used:
            log(f"  [Sanitizer] Removendo método não utilizado: {file_name} -> {method}()", "WARN")
            # Remove o método (heurística: da declaração até a próxima chave fechada balanceada)
            # Nota: Implementação simplificada para o MVP.
            pattern_remove = re.compile(rf'(?:public|private|protected).*?\b{method}\s*\(.*?\)\s*\{{.*?\}}', re.DOTALL)
            new_content = pattern_remove.sub("", new_content)
            modified = True

    if modified:
        original = read_file(file_path)
        write_file(file_path, new_content)
        
        # Regra de Ouro: Validação de Cobertura e Build
        success, _, coverage, _ = maven_test_with_coverage(repo_path, file_name)
        if not success or coverage < 90.0:
            log(f"  [Sanitizer] Sanitização de {file_name} REVERTIDA (quebra ou queda de cobertura)", "ERR")
            write_file(file_path, original)
        else:
            log(f"  [Sanitizer] {file_name} sanitizado com sucesso ✓", "OK")
