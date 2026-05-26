"""
java/report_runner.py — Gera relatório Markdown de refatoração por classe.

Fluxo:
  1. Lê execution.jsonl e agrupa eventos por arquivo
  2. Constrói sumário estruturado (o que foi aplicado, o que foi pulado e por quê)
  3. Envia o sumário ao LLM para gerar narrativa legível em Markdown
  4. Salva em logs/refactoring_report.md e REFACTORING_REPORT.md na raiz do repo
"""

import json
import os
import re
from datetime import datetime

from core.logger import log
from core.live_state import update as _live

# ---------------------------------------------------------------------------
# Mapeamentos legíveis
# ---------------------------------------------------------------------------

_PHASE_LABELS = {
    "clean-imports":        "Remoção de imports não utilizados (OpenRewrite)",
    "format":               "Formatação de código (Google Java Format)",
    "final-keywords":       "Adição de modificadores `final`",
    "naming-conventions":   "Correção de convenções de nomenclatura",
    "dead-code":            "Remoção de código morto",
    "simplify-code":        "Simplificação de código (expressões, ternários)",
    "modernize-syntax":     "Modernização de sintaxe Java (streams, lambdas, var)",
    "static-analysis":      "Análise estática e correções (Spotbugs/PMD patterns)",
    "guard-clauses":        "Refatoração de guard clauses (early return)",
    "method-extraction":    "Extração de métodos longos",
    "solid-dip":            "Aplicação de DIP — injeção de dependência via construtor",
    "controller-lean":      "Remoção de lógica de negócio do Controller",
    "flow-refactor":        "Refatoração de fluxo de controle",
    "dry-check":            "Verificação e eliminação de duplicação (DRY)",
    "javadoc":              "Inserção de Javadoc em métodos públicos",
    "initial_coverage_fix": "Geração automática de testes de cobertura",
    "flow-dry":             "Verificação DRY de fluxos (dry-run)",
}

_SKIP_LABELS = {
    "no_business_logic":        "Tipo estrutural sem lógica de negócio (interface, @Document, @Entity, repository, DTO) — fase não aplicável",
    "not_a_controller":         "Não é um @RestController — fase controller-lean não se aplica",
    "no_change":                "Código já em conformidade com os critérios da fase — nenhuma alteração necessária",
    "no_pattern_match":         "Nenhum método da classe apresentou o padrão alvo da fase — fase não aplicável",
    "compile_failed":           "Geração falhou após múltiplas tentativas de reparo — alteração revertida para preservar build estável",
    "already_documented":       "Todos os métodos públicos já possuem Javadoc",
    "deferred_field_injection": "Classe usa @Autowired em campo sem construtor explícito — aguarda conversão para constructor injection (solid-dip)",
    "repair_no_change":         "Reparo automático não produziu alteração válida — operação cancelada",
    "no_new_instantiation":     "Classe não contém instanciações concretas (new ConcreteClass()) — injeção de dependência não aplicável",
    "bootstrap_class":          "Classe de configuração/bootstrap (@SpringBootApplication, @Configuration) — DIP não aplicável",
    "deferred_flow_refactor":   "Classe já foi processada por flow-refactor — solid-dip deferido para evitar conflito estrutural",
    "deferred_repeat_failure":  "Classe falhou nesta fase em ciclo anterior — deferida para revisão manual",
    "timeout":                  "Processamento excedeu o tempo limite por arquivo — operação cancelada para não bloquear o pipeline",
    "permanent_skip":           "Classe atingiu o limite de falhas consecutivas nesta fase — marcada para revisão manual",
    "code_structure_changed":   "LLM alterou estrutura do código além dos comentários Javadoc — alteração rejeitada para preservar integridade",
}


# ---------------------------------------------------------------------------
# M11: Fix Candidates section
# ---------------------------------------------------------------------------

def _build_fix_candidates_section(entries: list[dict], fixes: list[dict] | None = None) -> str:
    """Return a Markdown section listing permanent_skip entries whose stack/reason
    is covered by a fix in fix_metadata.json that was applied AFTER the entry's
    timestamp. These files are likely to compile/pass on the next run if forced
    to retry. Returns empty string if no candidates.

    `entries`: contents of logs/failed_files.json
    `fixes`:   contents of logs/fix_metadata.json (or get_fixes() if None)
    """
    import datetime as _dt
    if fixes is None:
        try:
            from java.fix_metadata import get_fixes
            fixes = get_fixes()
        except Exception:
            fixes = []
    if not fixes:
        return ""

    candidates: list[tuple[str, list[str]]] = []  # (basename, [fix_ids])
    for e in entries or []:
        if not e.get("permanent_skip"):
            continue
        ts_raw = e.get("timestamp")
        if not ts_raw:
            continue
        try:
            entry_ts = _dt.datetime.fromisoformat(ts_raw)
        except Exception:
            continue
        haystack = (e.get("stack_trace") or "") + " " + (e.get("reason") or "")
        matching: list[str] = []
        for f in fixes:
            try:
                f_ts = _dt.datetime.fromisoformat(f.get("applied_at", ""))
            except Exception:
                continue
            if entry_ts >= f_ts:
                continue
            if any(p in haystack for p in f.get("patterns", [])):
                matching.append(f.get("id", "?"))
        if matching:
            basename = e["file"].split("/")[-1]
            candidates.append((basename, sorted(set(matching))))

    if not candidates:
        return ""

    lines = [
        "## Fix Candidates",
        "",
        "Os seguintes arquivos estão em `permanent_skip` mas fixes recentes "
        "em `logs/fix_metadata.json` cobrem o padrão de erro deles. "
        "Considere re-rodar com `FORCE_RETRY=<basename>` no `.env` "
        "ou `python main.py --clear-skip <basename>` antes do próximo run.",
        "",
        "| Arquivo | Fixes candidatos |",
        "|---------|------------------|",
    ]
    for basename, fix_ids in candidates:
        lines.append(f"| `{basename}` | {', '.join(fix_ids)} |")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Extração de dados do JSONL
# ---------------------------------------------------------------------------

def _load_session(jsonl_path: str) -> list[dict]:
    with open(jsonl_path) as f:
        entries = [json.loads(l) for l in f if l.strip()]
    start = 0
    for i, e in enumerate(entries):
        if e.get("event") == "GIT_BRANCH_CREATED":
            start = i
    return entries[start:]


def _build_class_summaries(session: list[dict]) -> dict:
    """Retorna dict {filename: {accepted:[phases], skipped:{phase:reason}, reverted:[phases]}}."""
    summaries = {}
    coverages = []

    for e in session:
        ev  = e.get("event", "")
        ph  = e.get("phase", "") or ""
        fi  = (e.get("file", "") or "").split("::")[0]
        msg = e.get("message", "")

        if ev == "COVERAGE":
            m = re.search(r"(\d+\.\d+)%", msg)
            if m:
                coverages.append((e["timestamp"], float(m.group(1)), msg))
            continue

        if not fi:
            continue

        if fi not in summaries:
            summaries[fi] = {"accepted": [], "skipped": {}, "reverted": []}

        if ev == "FILE_ACCEPTED":
            if ph not in summaries[fi]["accepted"]:
                summaries[fi]["accepted"].append(ph)

        elif ev == "FILE_SKIPPED":
            raw_reason = msg.replace("Pulado: ", "").strip()
            summaries[fi]["skipped"][ph] = raw_reason

        elif ev == "FILE_REVERTED":
            if ph not in summaries[fi]["reverted"]:
                summaries[fi]["reverted"].append(ph)

    return summaries, coverages


def _build_text_summary(summaries: dict, coverages: list, session: list[dict]) -> str:
    """Serializa o sumário estruturado como texto compacto para o LLM."""
    start_ts = session[0]["timestamp"]
    end_ts   = session[-1]["timestamp"]
    dur_sec  = int((datetime.fromisoformat(end_ts) - datetime.fromisoformat(start_ts)).total_seconds())
    h, r = divmod(dur_sec, 3600)
    m, _ = divmod(r, 60)

    lines = [
        f"CICLO: {start_ts[:10]}  DURAÇÃO: {h}h {m}m",
        "",
    ]
    if coverages:
        for ts, val, msg in coverages:
            lines.append(f"COBERTURA [{ts[11:16]}]: {val:.2f}% — {msg}")
    lines.append("")

    for fname in sorted(summaries):
        s = summaries[fname]
        acc_labels = [_PHASE_LABELS.get(p, p) for p in s["accepted"]]
        rev_labels = [_PHASE_LABELS.get(p, p) for p in s["reverted"]]
        skip_items = {
            ph: _SKIP_LABELS.get(r, r)
            for ph, r in s["skipped"].items()
            if ph not in s["accepted"]  # ignora skips em fases onde depois foi aceito
        }

        lines.append(f"ARQUIVO: {fname}")
        if acc_labels:
            lines.append(f"  MELHORIAS APLICADAS: {' | '.join(acc_labels)}")
        if rev_labels:
            lines.append(f"  REVERTIDO EM: {' | '.join(rev_labels)}")
        if skip_items:
            for ph, reason in skip_items.items():
                ph_label = _PHASE_LABELS.get(ph, ph)
                lines.append(f"  PULADO [{ph_label}]: {reason}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Chamada LLM
# ---------------------------------------------------------------------------

_REPORT_PROMPT = """Você é um engenheiro de software senior revisando um ciclo de refatoração automática de um projeto Java Spring Boot.

Abaixo estão os dados estruturados de execução do pipeline de refatoração:

{summary}

Com base nesses dados, gere um RELATÓRIO TÉCNICO em Markdown com a seguinte estrutura:

# Relatório de Refatoração — {date}

## Visão Geral
[Parágrafo de 3-4 frases descrevendo o ciclo: duração, cobertura inicial e final, quantas classes foram modificadas, quantas puladas e quantas revertidas.]

## Cobertura de Testes
[Tabela ou lista com a trajetória de cobertura: inicial → pós-geração de testes → final.]

## Classes Modificadas
[Para cada arquivo que teve MELHORIAS APLICADAS, um item com: nome da classe em negrito, lista das melhorias aplicadas com descrição do impacto no código.]

## Classes Puladas
[Para cada arquivo que foi PULADO em TODAS as fases de refatoração, um item com: nome da classe em negrito, motivo claro e objetivo (por que a classe não precisava de alteração).]

## Classes Revertidas
[Para cada arquivo que teve REVERTIDO EM, um item com: nome da classe em negrito, fase que reverteu, motivo técnico provável e recomendação de ação manual.]

## Observações e Próximos Passos
[2-3 observações sobre padrões identificados no ciclo e sugestões de melhoria.]

Regras:
- Escreva em Português do Brasil
- Seja objetivo e técnico, mas legível para desenvolvedores sem contexto do pipeline
- Use linguagem afirmativa: "foram aplicadas X melhorias", não "o agente tentou"
- Não mencione detalhes internos do agente (model names, fase IDs, etc.)
"""


def _call_llm_for_report(summary_text: str, date: str) -> str | None:
    try:
        from ai.model import call_claude, _try_local_agent
        from config import MODEL_REVIEWER
    except Exception:
        return None

    prompt = _REPORT_PROMPT.format(summary=summary_text, date=date)

    # Tenta Claude primeiro (melhor qualidade para relatório narrativo)
    try:
        result = call_claude(prompt)
        if result and len(result) > 200:
            log("[Report] Relatório gerado via Claude ✓", "OK")
            return result
    except Exception:
        pass

    # Fallback: modelo local — chama call_model diretamente (output é Markdown, não Java)
    try:
        from ai.model import call_model
        raw, is_oom = call_model(MODEL_REVIEWER, prompt, temperature=0.3,
                                 num_predict=4096, timeout=600)
        if raw and not is_oom and len(raw.strip()) > 200:
            log("[Report] Relatório gerado via modelo local ✓", "OK")
            return raw.strip()
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Gerador de fallback (sem LLM)
# ---------------------------------------------------------------------------

def _build_fallback_report(summaries: dict, coverages: list, session: list[dict]) -> str:
    """Relatório estruturado puro, sem narrativa LLM."""
    start_ts = session[0]["timestamp"]
    end_ts   = session[-1]["timestamp"]
    dur_sec  = int((datetime.fromisoformat(end_ts) - datetime.fromisoformat(start_ts)).total_seconds())
    h, r = divmod(dur_sec, 3600)
    m, _ = divmod(r, 60)
    date = start_ts[:10]

    accepted_files = [f for f, s in summaries.items() if s["accepted"]]
    reverted_files = [f for f, s in summaries.items() if s["reverted"]]
    skipped_only   = [
        f for f, s in summaries.items()
        if not s["accepted"] and not s["reverted"] and s["skipped"]
    ]

    lines = [
        f"# Relatório de Refatoração — {date}",
        "",
        f"**Duração:** {h}h {m}m  |  **Classes modificadas:** {len(accepted_files)}  |  "
        f"**Puladas:** {len(skipped_only)}  |  **Revertidas:** {len(reverted_files)}",
        "",
    ]

    if coverages:
        lines += ["## Cobertura de Testes", ""]
        for _, val, msg in coverages:
            lines.append(f"- {msg}")
        lines.append("")

    if accepted_files:
        lines += ["## Classes Modificadas", ""]
        for fname in sorted(accepted_files):
            s = summaries[fname]
            lines.append(f"### {fname}")
            for ph in s["accepted"]:
                lines.append(f"- {_PHASE_LABELS.get(ph, ph)}")
            if s["reverted"]:
                lines.append(f"- ⚠ Revertido em: {', '.join(_PHASE_LABELS.get(p,p) for p in s['reverted'])}")
            lines.append("")

    if skipped_only:
        lines += ["## Classes Puladas", ""]
        for fname in sorted(skipped_only):
            s = summaries[fname]
            lines.append(f"### {fname}")
            seen = set()
            for ph, reason in s["skipped"].items():
                label = _SKIP_LABELS.get(reason, reason)
                if label not in seen:
                    lines.append(f"- {label}")
                    seen.add(label)
            lines.append("")

    if reverted_files:
        lines += ["## Classes Revertidas", ""]
        for fname in sorted(reverted_files):
            s = summaries[fname]
            lines.append(f"### {fname}")
            for ph in s["reverted"]:
                lines.append(f"- Fase: {_PHASE_LABELS.get(ph, ph)}")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def run_report(repo_path: str, jsonl_path: str, logs_dir: str, exec_logger=None) -> None:
    """Gera o relatório de refatoração e salva nos diretórios de log e no repo."""
    _live(active_skill="report", current_file="")
    log("[Report] Carregando eventos do ciclo...")

    if not os.path.exists(jsonl_path) or os.path.getsize(jsonl_path) == 0:
        log("[Report] execution.jsonl vazio — relatório não gerado", "WARN")
        return

    session = _load_session(jsonl_path)
    summaries, coverages = _build_class_summaries(session)
    if not summaries:
        log("[Report] Nenhum evento de arquivo encontrado — relatório não gerado", "WARN")
        return

    date = session[0]["timestamp"][:10]
    summary_text = _build_text_summary(summaries, coverages, session)

    log("[Report] Solicitando narrativa ao LLM...")
    report_md = _call_llm_for_report(summary_text, date)

    if not report_md:
        log("[Report] LLM indisponível — gerando relatório estruturado", "WARN")
        report_md = _build_fallback_report(summaries, coverages, session)

    # M11: Fix Candidates section
    try:
        import json as _json
        from java.fix_metadata import get_fixes as _get_fixes
        _failed_path = os.path.join(logs_dir, "failed_files.json")
        _failed_entries = []
        if os.path.exists(_failed_path):
            with open(_failed_path) as _f:
                _failed_entries = _json.load(_f)
        _section = _build_fix_candidates_section(_failed_entries, fixes=_get_fixes())
        if _section:
            report_md = report_md.rstrip() + "\n\n" + _section + "\n"
    except Exception as _exc:
        log(f"M11 fix-candidates section skipped: {_exc}", "WARN")

    # Salva no diretório de logs
    log_report_path = os.path.join(logs_dir, "refactoring_report.md")
    with open(log_report_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    log(f"[Report] Salvo em {log_report_path}", "OK")

    # Salva na raiz do repositório alvo (será commitado)
    repo_report_path = os.path.join(repo_path, "REFACTORING_REPORT.md")
    with open(repo_report_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    log(f"[Report] Salvo em {repo_report_path}", "OK")

    if exec_logger:
        exec_logger.log_phase_start("REPORT_DONE", "Relatório de refatoração gerado")

    _live(active_skill="", current_file="")
