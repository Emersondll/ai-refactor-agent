import json
import os
import re
from datetime import datetime

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False


def _cpu_percent() -> float:
    if not _PSUTIL:
        return -1.0
    return psutil.cpu_percent(interval=0.5)

JSONL_FILE  = "logs/execution.jsonl"
LOG_FILE    = "logs/execution.log"
OUTPUT_JSON = "dashboard_status.json"


def parse_logs():
    if os.path.exists(JSONL_FILE) and os.path.getsize(JSONL_FILE) > 0:
        _parse_jsonl()
    elif os.path.exists(LOG_FILE):
        _parse_text()


# ---------------------------------------------------------------------------
# Fonte primária: execution.jsonl (tem campo "file" por evento)
# ---------------------------------------------------------------------------

def _base_file(raw: str) -> str:
    """S1: descarta ::metodo_assinatura — eventos de método sobem para a classe pai."""
    return raw.split("::")[0] if raw else raw


def _parse_jsonl():
    with open(JSONL_FILE, "r") as f:
        entries = []
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not entries:
        return

    # Isola a sessão atual: a partir do último GIT_BRANCH_CREATED
    session_start = 0
    for i, e in enumerate(entries):
        if e.get("event") == "GIT_BRANCH_CREATED":
            session_start = i
    session = entries[session_start:]

    stats = {
        "start_time": None,
        "last_update": None,
        "files_total": 0,
        "files_completed": 0,
        "current_coverage": 0.0,
        "phase": "Iniciando",
        "avg_seconds_per_file": 0,
    }

    steps = []
    seen_files = set()
    accepted_files = set()  # deduplica: conta cada classe uma única vez
    accepted_refactor_files = set()  # subset: arquivos de PRODUÇÃO aceitos (exclui testes)
    file_start_times = {}   # filename → datetime
    durations = []          # segundos por arquivo aceito
    last_file_seen = "Aguardando..."
    is_complete = False     # S2: True quando PIPELINE_COMPLETE detectado

    for entry in session:
        ts_str = entry.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            continue

        if not stats["start_time"]:
            stats["start_time"] = ts_str
        stats["last_update"] = ts_str

        event       = entry.get("event", "")
        raw_file    = entry.get("file", "")
        filename    = _base_file(raw_file)   # S1: normalizado sem ::método
        message     = entry.get("message", "")
        # S5: detalhe completo para tooltip (inclui assinatura do método se houver)
        detail      = raw_file if raw_file else message

        if event == "FILES_TOTAL":
            total = entry.get("count", 0)
            if total > stats["files_total"]:
                stats["files_total"] = total

        elif event == "FILES_QUEUE":
            for fname in entry.get("files", []):
                if fname not in seen_files:
                    seen_files.add(fname)
                    steps.append({"name": fname, "status": "pending",
                                  "time": ts_str, "detail": fname})

        elif event == "COVERAGE":
            m = re.search(r"(\d+\.\d+)%", message)
            if m:
                cov = float(m.group(1))
                if cov > stats["current_coverage"]:
                    stats["current_coverage"] = cov

        elif event == "PHASE_START":
            stats["phase"] = entry.get("phase", message)
            phase_id = entry.get("phase", "")
            # S2: detecta encerramento do pipeline
            if phase_id == "PIPELINE_COMPLETE":
                is_complete = True
            # C2: pipeline encerrado — limpa qualquer "processing" restante
            if phase_id in ("PIPELINE_COMPLETE", "COMMIT_PUSH_FAILED"):
                for s in steps:
                    if s["status"] == "processing":
                        s["status"] = "pending"

        elif event == "FILE_START":
            last_file_seen = filename
            file_start_times[filename] = ts
            if filename not in seen_files:
                seen_files.add(filename)
                stats["files_total"] += 1
                steps.append({"name": filename, "status": "processing",
                               "time": ts_str, "detail": detail})
            else:
                for s in steps:
                    if s["name"] == filename:
                        s["status"] = "processing"
                        s["time"] = ts_str
                        s["detail"] = detail   # S5: atualiza com método atual
                        break

        elif event == "FILE_ACCEPTED":
            if filename not in accepted_files:
                accepted_files.add(filename)
                stats["files_completed"] += 1
            # Refator de PRODUÇÃO: exclui arquivos de teste (convenção *Test.java).
            # Files de teste podem ser tocados por fases de community (dead-code,
            # naming, etc.), mas não contam como "refatoração do projeto".
            if filename and not filename.endswith("Test.java") and not filename.endswith("Tests.java"):
                accepted_refactor_files.add(filename)
            for s in steps:
                if s["name"] == filename and s["status"] == "processing":
                    s["status"] = "completed"
                    s["time"] = ts_str
                    s["detail"] = detail
                    if filename in file_start_times:
                        delta = (ts - file_start_times[filename]).total_seconds()
                        if delta > 0:
                            durations.append(delta)
                    break

        elif event == "FILE_REVERTED":
            for s in steps:
                if s["name"] == filename and s["status"] == "processing":
                    s["status"] = "failed"
                    s["time"] = ts_str
                    s["detail"] = detail
                    if filename in file_start_times:
                        delta = (ts - file_start_times[filename]).total_seconds()
                        if delta > 0:
                            durations.append(delta)
                    break

        elif event == "FILE_SKIPPED":
            found = False
            for s in steps:
                if s["name"] == filename and s["status"] in ("pending", "processing"):
                    s["status"] = "skipped"
                    s["time"] = ts_str
                    s["detail"] = detail
                    found = True
                    break
            if not found and filename and filename not in seen_files:
                seen_files.add(filename)
                steps.append({"name": filename, "status": "skipped",
                               "time": ts_str, "detail": detail})

    if durations:
        stats["avg_seconds_per_file"] = sum(durations) / len(durations)

    stats["files_total"] = max(stats["files_total"], stats["files_completed"])
    stats["accepted_refactor_count"] = len(accepted_refactor_files)

    jsonl_active = next(
        (s["name"] for s in reversed(steps) if s["status"] == "processing"),
        None,
    )
    active = jsonl_active or last_file_seen

    active_elapsed = 0.0
    if active in file_start_times:
        active_elapsed = (datetime.now() - file_start_times[active]).total_seconds()

    _write_output(stats, steps, active, active_elapsed, is_complete)


# ---------------------------------------------------------------------------
# Fonte secundária: execution.log (texto — sem campo file em FILE_ACCEPTED)
# ---------------------------------------------------------------------------


def _parse_text():
    with open(LOG_FILE, "r") as f:
        lines = f.readlines()

    stats = {
        "start_time": None,
        "last_update": None,
        "files_total": 0,
        "files_completed": 0,
        "current_coverage": 0.0,
        "phase": "Iniciando",
        "avg_seconds_per_file": 0,
    }

    re_ts = re.compile(r"\[(\d{4}-\d{2}-\d{2}T[\d:.]+)\]")
    steps = []
    seen_files = set()
    accepted_files = set()
    file_start_times = {}
    durations = []
    last_file_seen = "Aguardando..."

    for line in lines:
        if "Cobertura Global Atual" in line or "Cobertura Final Atingida" in line:
            m = re.search(r"(\d+\.\d+)%", line)
            if m:
                cov = float(m.group(1))
                if cov > stats["current_coverage"]:
                    stats["current_coverage"] = cov

        ts_match = re_ts.search(line)
        if not ts_match:
            continue
        ts_str = ts_match.group(1)
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            continue

        if not stats["start_time"]:
            stats["start_time"] = ts_str
        stats["last_update"] = ts_str

        if "PHASE_START" in line:
            stats["phase"] = line.split("|")[-1].strip()

        if "FILE_START" in line:
            filename = line.split("|")[-1].strip().replace("Processando ", "").strip()
            last_file_seen = filename
            file_start_times[filename] = ts
            if filename not in seen_files:
                seen_files.add(filename)
                stats["files_total"] += 1
                steps.append({"name": filename, "status": "processing", "time": ts_str})

        if "FILE_ACCEPTED" in line:
            # extrai filename do log de texto: última parte após "|"
            accepted_name = line.split("|")[-1].strip()
            if accepted_name not in accepted_files:
                accepted_files.add(accepted_name)
                stats["files_completed"] += 1
            for s in reversed(steps):
                if s["status"] == "processing":
                    s["status"] = "completed"
                    s["time"] = ts_str
                    if s["name"] in file_start_times:
                        delta = (ts - file_start_times[s["name"]]).total_seconds()
                        if delta > 0:
                            durations.append(delta)
                    break

        if "FILE_REVERTED" in line:
            for s in reversed(steps):
                if s["status"] == "processing":
                    s["status"] = "failed"
                    s["time"] = ts_str
                    if s["name"] in file_start_times:
                        delta = (ts - file_start_times[s["name"]]).total_seconds()
                        if delta > 0:
                            durations.append(delta)
                    break

    if durations:
        stats["avg_seconds_per_file"] = sum(durations) / len(durations)

    stats["files_total"] = max(stats["files_total"], stats["files_completed"])

    active = next(
        (s["name"] for s in reversed(steps) if s["status"] == "processing"),
        last_file_seen,
    )

    active_elapsed = 0.0
    if active in file_start_times:
        active_elapsed = (datetime.now() - file_start_times[active]).total_seconds()

    _write_output(stats, steps, active, active_elapsed)


def _write_output(stats: dict, steps: list, active_file: str, active_elapsed: float = 0.0, is_complete: bool = False) -> None:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from core.live_state import read as _read_live
        live = _read_live()
    except Exception:
        live = {}

    # live_state.current_file é preenchido por llm_runner e flow_runner
    # quando o JSONL não tem FILE_START ativo (fases LLM não emitem esse evento)
    display_file = active_file or live.get("current_file", "") or "Aguardando..."

    # % de código refatorado — inclui testes gerados E refatorações de produção.
    # files_completed conta FILE_ACCEPTED deduplicado por nome de arquivo (uma classe
    # aceita em N fases = 1). files_total é o tamanho da fila inicial.
    _total = stats.get("files_total", 0) or 0
    _done  = stats.get("files_completed", 0) or 0
    stats["percent_refactored"] = round((_done / _total) * 100.0, 1) if _total > 0 else 0.0

    # % SOMENTE de refatoração de produção — denominador = files_total (universo
    # completo: testes + produção). Numerador = arquivos de produção aceitos
    # (qualquer fase). Excluímos testes por nome (convenção *Test.java).
    _refactor_only = stats.get("accepted_refactor_count", 0) or 0
    stats["percent_refactor_only"] = round((_refactor_only / _total) * 100.0, 1) if _total > 0 else 0.0

    data = {
        "heartbeat": datetime.now().isoformat(),
        "is_complete": is_complete,
        "stats": stats,
        "current_file": display_file,
        "current_file_elapsed": round(active_elapsed),
        "cpu_percent": _cpu_percent(),
        "current_model": live.get("current_model", ""),
        "active_skill": live.get("active_skill", ""),
        "steps": steps,
    }
    with open(OUTPUT_JSON, "w") as f:
        json.dump(data, f, indent=4)


if __name__ == "__main__":
    parse_logs()
