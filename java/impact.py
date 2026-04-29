import re
from core.logger import log
from core.executor import run_cmd

def detect_signature_changes(old_code: str, new_code: str) -> list[tuple[str, str]]:
    """
    Detecta se métodos públicos ou protegidos tiveram seus nomes alterados.
    Retorna uma lista de tuplas (nome_antigo, nome_novo).
    """
    # Regex para capturar declarações de métodos simples
    # (Visibilidade) (Tipo) (Nome)(Argumentos)
    method_regex = r'(public|protected)\s+[\w<>[\]]+\s+(\w+)\s*\('
    
    old_methods = set(re.findall(method_regex, old_code))
    new_methods = set(re.findall(method_regex, new_code))
    
    # Se a visibilidade e o nome mudaram, mas os argumentos parecem iguais, 
    # podemos inferir um rename em alguns casos, mas a forma mais segura 
    # por agora é detectar o que sumiu do "old" e o que apareceu no "new" 
    # que tenha a mesma posição ou contexto (esta é uma heurística complexa).
    
    # Simplificação: Vamos focar em assinaturas que sumiram mas o build quebrou.
    # Mas para uma Skill Proativa:
    changes = []
    # (Isso precisaria de um parser tipo javalang para ser 100% preciso)
    # Por enquanto, se o modelo mudou o nome de um método público, vamos logar.
    
    return changes

def propagate_rename(repo_path: str, old_name: str, new_name: str):
    """
    Varre o projeto e substitui o nome antigo pelo novo em todos os arquivos Java.
    """
    log(f"  [Skill: Propagação] Sincronizando rename: {old_name} -> {new_name}...", "WARN")
    
    # Usa sed para uma substituição rápida e global no projeto
    # Limitando a arquivos .java
    cmd = f"find . -name '*.java' -exec sed -i 's/\\b{old_name}\\b/{new_name}/g' {{}} +"
    run_cmd(cmd, cwd=repo_path)
