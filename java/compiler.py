from core.executor import run_cmd
from core.logger import log


def maven_test(path: str) -> tuple[bool, str]:
    """
    Executa mvn clean test no diretório do projeto.
    Retorna (sucesso, saída_combinada).

    BUG CORRIGIDO: javac_check foi removido.
    Rodar `javac Arquivo.java` isolado, sem o classpath do Maven, falha em 100%
    dos arquivos que têm qualquer dependência (Spring, Lombok, etc.) — então
    revertia o código sempre, mesmo quando estava correto.
    O Maven já compila + testa de forma correta e completa.
    """
    log("  Executando mvn clean test...")
    code, out, err = run_cmd("mvn clean test -q", cwd=path)
    combined = out + err

    if code != 0:
        # Exibe apenas linhas de erro relevantes para não poluir o log
        error_lines = [
            line for line in combined.splitlines()
            if any(k in line for k in ("[ERROR]", "BUILD FAILURE", "FAILED", "ERROR"))
        ]
        for line in error_lines[:25]:
            log(f"  {line.strip()}", "ERR")

    return code == 0, combined
