import os
import re

def build_project_dictionary(repo_path: str) -> str:
    """
    Cria uma lista de todas as classes Java do projeto e seus pacotes
    para ajudar a IA a resolver imports faltantes.
    """
    dictionary = []
    
    for root, _, files in os.walk(repo_path):
        for file in files:
            if file.endswith(".java"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # Extrai o package
                        package_match = re.search(r'package\s+([\w.]+);', content)
                        if package_match:
                            package = package_match.group(1)
                            class_name = file.replace(".java", "")
                            dictionary.append(f"- {class_name} ({package}.{class_name})")
                except:
                    continue
    
    if not dictionary:
        return "Nenhum dicionário de classes disponível."
        
    return "MAPA DE CLASSES DO PROJETO (Para auxílio em IMPORTS):\n" + "\n".join(sorted(dictionary))
