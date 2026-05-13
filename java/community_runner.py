import os
from core.logger import log
from core.utils import run_cmd
from java.compiler import ENV_WRAPPER
from config import GJF_PATH


def run_skill(skill_config: dict, repo_path: str) -> tuple[bool, str]:
    tool = skill_config.get("tool", "")
    if tool == "openrewrite":
        _run_openrewrite(
            repo_path,
            skill_config.get("artifact_coordinates", []),
            skill_config.get("recipes", []),
        )
    elif tool == "google-java-format":
        _run_google_java_format(repo_path)
    else:
        log(f"[CommunityRunner] Unknown tool: {tool}", "WARN")
        return False, ""
    diff = _get_diff(repo_path)
    return bool(diff.strip()), diff


def _run_openrewrite(repo_path: str, artifact_coordinates: list, recipes: list) -> None:
    active = ",".join(recipes)
    mvn_cmd = (
        f"mvn -U org.openrewrite.maven:rewrite-maven-plugin:run"
        f" -Drewrite.activeRecipes={active}"
    )
    if artifact_coordinates:
        coords = ",".join(artifact_coordinates)
        mvn_cmd += f" -Drewrite.recipeArtifactCoordinates={coords}"
    full_cmd = ENV_WRAPPER.format(mvn_cmd)
    code, out, err = run_cmd(full_cmd, cwd=repo_path)
    if code != 0:
        log(f"[CommunityRunner] OpenRewrite exited {code}: {err[:200]}", "WARN")


def _run_google_java_format(repo_path: str) -> None:
    java_dir = os.path.join(repo_path, "src", "main", "java")
    java_files = [
        os.path.join(root, f)
        for root, _, files in os.walk(java_dir)
        for f in files
        if f.endswith(".java")
    ]
    if not java_files:
        log("[CommunityRunner] No .java files found for GJF", "WARN")
        return
    files_arg = " ".join(f'"{p}"' for p in java_files)
    code, out, err = run_cmd(f"{GJF_PATH} --replace {files_arg}", cwd=repo_path)
    if code != 0:
        log(f"[CommunityRunner] GJF exited {code}: {err[:200]}", "WARN")


def _get_diff(repo_path: str) -> str:
    code, out, _ = run_cmd("git diff --unified=5", cwd=repo_path)
    return out if code == 0 else ""
