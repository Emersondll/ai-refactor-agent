import os
import re
import subprocess


def load_skill(skill_name: str, section: str = "") -> str:
    """
    Carrega conteúdo de ~/.claude/skills/<skill_name>/SKILL.md.
    Remove frontmatter YAML. Se `section` for informado, retorna apenas
    o conteúdo daquela seção (## Section Name) até a próxima seção de mesmo nível.
    Retorna string vazia se a skill ou seção não existir.
    """
    skill_path = os.path.expanduser(f"~/.claude/skills/{skill_name}/SKILL.md")
    if not os.path.exists(skill_path):
        return ""
    with open(skill_path, "r", encoding="utf-8") as f:
        content = f.read()
    content = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)
    if not section:
        return content.strip()
    # Extrai conteúdo da seção ## <section> até a próxima seção ## ou fim do arquivo
    pattern = rf"^## {re.escape(section)}\s*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, content, flags=re.DOTALL | re.MULTILINE)
    if not match:
        return ""
    return match.group(1).strip()


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_file(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def force_safe_encoding(code: str) -> str:
    return code.encode("utf-8", "ignore").decode("utf-8")


def run_cmd(cmd: str, cwd: str | None = None) -> tuple[int, str, str]:
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr
