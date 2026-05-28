import re
from core.logger import log
from core.utils import run_cmd

def detect_signature_changes(old_code: str, new_code: str) -> list[tuple[str, str]]:
    """
    Detects whether public or protected methods had their names changed.
    Returns a list of (old_name, new_name) tuples.

    A full implementation would require a Java parser (e.g. javalang) for precision.
    Currently returns an empty list — a placeholder for future proactive repair.
    """
    method_regex = r'(public|protected)\s+[\w<>[\]]+\s+(\w+)\s*\('
    old_methods = set(re.findall(method_regex, old_code))
    new_methods = set(re.findall(method_regex, new_code))
    changes = []
    return changes

def propagate_rename(repo_path: str, old_name: str, new_name: str):
    """Scans the project and replaces the old name with the new one in all Java files."""
    log(f"  [Impact] Propagating rename: {old_name} -> {new_name}...", "WARN")
    
    # Use sed for a fast global substitution across the project
    # Limited to .java files
    cmd = f"find . -name '*.java' -exec sed -i 's/\\b{old_name}\\b/{new_name}/g' {{}} +"
    run_cmd(cmd, cwd=repo_path)
