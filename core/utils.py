import subprocess


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
