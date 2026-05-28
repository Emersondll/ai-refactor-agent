import os
import re
import subprocess


def load_skill(skill_name: str, section: str = "") -> str:
    """Load content from ~/.claude/skills/<skill_name>/SKILL.md.

    Strips YAML frontmatter. If `section` is given, returns only the content
    of that section (## Section Name) up to the next same-level section.
    Returns empty string if the skill or section does not exist.
    """
    skill_path = os.path.expanduser(f"~/.claude/skills/{skill_name}/SKILL.md")
    if not os.path.exists(skill_path):
        return ""
    with open(skill_path, "r", encoding="utf-8") as f:
        content = f.read()
    content = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)
    if not section:
        return content.strip()
    # Extract section ## <section> up to the next ## or end of file
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
