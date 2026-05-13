import os
import xml.etree.ElementTree as ET
from core.utils import run_cmd
from core.logger import log

# Wrapper para garantir que o Maven use o Java 22 via SDKMAN no Linux
ENV_WRAPPER = 'bash -c "source $HOME/.sdkman/bin/sdkman-init.sh && sdk use java 22-open && {}"'


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
    cmd = ENV_WRAPPER.format("mvn clean test -q")
    code, out, err = run_cmd(cmd, cwd=path)
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

def maven_test_with_coverage(path: str, class_name: str) -> tuple[bool, str, float, list[int]]:
    """
    Executa testes injetando o JaCoCo dinamicamente.
    Retorna (sucesso, log_maven, porcentagem_cobertura, linhas_faltantes).
    """
    log("  Executando testes com análise de cobertura JaCoCo...")
    base_cmd = "mvn org.jacoco:jacoco-maven-plugin:prepare-agent test org.jacoco:jacoco-maven-plugin:report -q"
    cmd = ENV_WRAPPER.format(base_cmd)
    code, out, err = run_cmd(cmd, cwd=path)
    combined = out + err

    if code != 0:
        error_lines = [
            line for line in combined.splitlines()
            if any(k in line for k in ("[ERROR]", "BUILD FAILURE", "FAILED", "ERROR"))
        ]
        for line in error_lines[:15]:
            log(f"  {line.strip()}", "ERR")
        return False, combined, 0.0, []

    jacoco_xml_path = os.path.join(path, "target", "site", "jacoco", "jacoco.xml")
    if not os.path.exists(jacoco_xml_path):
        log("  [WARN] jacoco.xml não gerado. Verifique os plugins do Maven. Assumindo 100% para não travar.", "WARN")
        return True, combined, 100.0, []

    coverage = 100.0
    missed_lines = []
    
    try:
        tree = ET.parse(jacoco_xml_path)
        root = tree.getroot()
        
        for package in root.findall('package'):
            for sourcefile in package.findall('sourcefile'):
                if sourcefile.get('name') == class_name:
                    counter = sourcefile.find("counter[@type='INSTRUCTION']")
                    if counter is not None:
                        missed = int(counter.get('missed', '0'))
                        covered = int(counter.get('covered', '0'))
                        total = missed + covered
                        if total > 0:
                            coverage = (covered / total) * 100.0
                    
                    for line in sourcefile.findall('line'):
                        mi = int(line.get('mi', '0'))
                        mb = int(line.get('mb', '0'))
                        if mi > 0 or mb > 0:
                            missed_lines.append(int(line.get('nr')))
                    break
    except Exception as e:
        log(f"  [WARN] Erro ao parsear jacoco.xml: {e}", "WARN")
        
    return True, combined, coverage, missed_lines

def get_global_coverage(path: str) -> float:
    """Calcula a cobertura global (INSTRUCTION) do projeto usando o jacoco.xml existente."""
    jacoco_xml_path = os.path.join(path, "target", "site", "jacoco", "jacoco.xml")
    if not os.path.exists(jacoco_xml_path):
        return 0.0

    try:
        tree = ET.parse(jacoco_xml_path)
        root = tree.getroot()
        # O JaCoCo armazena o total global na tag root <report> como um <counter>
        counter = root.find("counter[@type='INSTRUCTION']")
        if counter is not None:
            missed = int(counter.get('missed', '0'))
            covered = int(counter.get('covered', '0'))
            total = missed + covered
            if total > 0:
                return (covered / total) * 100.0
    except Exception as e:
        log(f"  [WARN] Erro ao calcular cobertura global: {e}", "WARN")
    
    return 0.0
