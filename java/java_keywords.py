import os
import re

def build_project_dictionary(repo_path: str) -> str:
    """
    Builds a list of all Java classes in the project and their packages
    to help the LLM resolve missing imports.
    """
    dictionary = []
    
    for root, _, files in os.walk(repo_path):
        for file in files:
            if file.endswith(".java"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        package_match = re.search(r'package\s+([\w.]+);', content)
                        if package_match:
                            package = package_match.group(1)
                            class_name = file.replace(".java", "")
                            dictionary.append(f"- {class_name} ({package}.{class_name})")
                except:
                    continue
    
    if not dictionary:
        return "No class dictionary available."

    return "PROJECT CLASS MAP (for import resolution):\n" + "\n".join(sorted(dictionary))
